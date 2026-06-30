/**
 * Browser-side ML — Transformers.js ONNX for headline scoring + NER.
 *
 * V4-48 — Provides client-side ML inference for OSINT headline scoring
 * and named entity recognition using Transformers.js (ONNX Runtime Web).
 * Zero network calls after model download — all inference runs in browser.
 *
 * Models (downloaded from HuggingFace Hub on first use, cached in IndexedDB):
 *   - NER: Xenova/bert-base-NER-uncased (~110MB)
 *   - Scoring: Xenova/distilbert-base-uncased-finetuned-sst-2-english (~65MB)
 *     (used for sentiment-based headline relevance scoring)
 *
 * Features:
 *   - Headline scoring: 0–1 relevance score based on sentiment + keyword overlap
 *   - NER: Extract person, organization, location entities from text
 *   - Batch processing: Score multiple headlines in one call
 *   - Lazy loading: Models load on first use, cached thereafter
 *   - Fail-soft: Returns null scores if models unavailable
 */

// Lazy-loaded model instances
let _nerPipeline: any = null;
let _sentimentPipeline: any = null;
let _initPromise: Promise<void> | null = null;
let _initError: string | null = null;

// Mutable loader — tests can override via _setLoader()
let _loader: () => Promise<any> = _defaultLoader;

/** Override the Transformers.js loader (for testing). */
export function _setLoader(fn: () => Promise<any>): void {
  _loader = fn;
  _initPromise = null;
  _nerPipeline = null;
  _sentimentPipeline = null;
  _initError = null;
}

// Configuration
const NER_MODEL = 'Xenova/bert-base-NER-uncased';
const SENTIMENT_MODEL = 'Xenova/distilbert-base-uncased-finetuned-sst-2-english';
const MAX_HEADLINE_LEN = 512;
const BATCH_SIZE = 8;

// Entity type mapping from BERT NER labels to readable types
const ENTITY_TYPE_MAP: Record<string, string> = {
  PER: 'Person',
  ORG: 'Organization',
  LOC: 'Location',
  MISC: 'Miscellaneous',
};

export interface NerEntity {
  text: string;
  type: string;
  start: number;
  end: number;
  score: number;
}

export interface HeadlineScore {
  score: number; // 0–1 relevance/intensity score
  sentiment: 'positive' | 'negative' | 'neutral';
  sentimentScore: number; // raw model output
  entities: NerEntity[];
  text: string;
}

export interface BrowserMlStatus {
  ready: boolean;
  nerLoaded: boolean;
  sentimentLoaded: boolean;
  error: string | null;
}

/**
 * Check if Transformers.js is available (dynamic import).
 * The library is loaded on demand to avoid bundling if unused.
 */
async function _defaultLoader(): Promise<any> {
  // Use variable to hide import from Vite's static analysis
  // (the package is optional and may not be installed)
  const hfModule = '@huggingface/transformers';
  const xenovaModule = '@xenova/transformers';
  try {
    const mod = await import(/* @vite-ignore */ hfModule);
    return mod;
  } catch {
    try {
      const mod = await import(/* @vite-ignore */ xenovaModule);
      return mod;
    } catch {
      throw new Error(
        'Transformers.js not installed. Run: npm install @huggingface/transformers'
      );
    }
  }
}

/** Exposed for testing — returns the real loader. */
export const _loadTransformers = _defaultLoader;

/**
 * Initialize browser ML models. Safe to call multiple times.
 * Loads both NER and sentiment pipelines.
 */
export async function initBrowserMl(): Promise<void> {
  if (_initPromise) {
    return _initPromise;
  }

  _initPromise = (async () => {
    try {
      _initError = null;
      const { pipeline } = await _loader();

      // Load NER pipeline (token-classification)
      try {
        _nerPipeline = await pipeline('token-classification', NER_MODEL, {
          quantized: true,
        });
      } catch (err) {
        console.warn('[browser_ml] NER model load failed:', err);
      }

      // Load sentiment pipeline (text-classification)
      try {
        _sentimentPipeline = await pipeline('text-classification', SENTIMENT_MODEL, {
          quantized: true,
        });
      } catch (err) {
        console.warn('[browser_ml] sentiment model load failed:', err);
      }

      if (!_nerPipeline && !_sentimentPipeline) {
        throw new Error('Both NER and sentiment models failed to load');
      }
    } catch (err: any) {
      _initError = err?.message || String(err);
      _initPromise = null; // allow retry
      throw err;
    }
  })();

  return _initPromise;
}

/**
 * Get current browser ML status.
 */
export function getBrowserMlStatus(): BrowserMlStatus {
  return {
    ready: _nerPipeline !== null || _sentimentPipeline !== null,
    nerLoaded: _nerPipeline !== null,
    sentimentLoaded: _sentimentPipeline !== null,
    error: _initError,
  };
}

/**
 * Extract named entities from text using the NER pipeline.
 * Returns empty array if model is not loaded.
 */
export async function extractEntities(text: string): Promise<NerEntity[]> {
  if (!_nerPipeline) {
    try {
      await initBrowserMl();
    } catch {
      return [];
    }
  }
  if (!_nerPipeline) return [];

  try {
    const truncated = text.slice(0, MAX_HEADLINE_LEN);
    const rawEntities = await _nerPipeline(truncated);

    // Transformers.js returns array of entity objects
    const entities: NerEntity[] = [];
    const seen = new Set<string>();

    for (const ent of Array.isArray(rawEntities) ? rawEntities : [rawEntities]) {
      const rawType = ent.entity || ent.entity_group || '';
      const baseType = rawType.replace(/^[BI]-/, '');
      const type = ENTITY_TYPE_MAP[baseType] || ENTITY_TYPE_MAP[rawType] || rawType || 'Unknown';
      const text_val = (ent.word || ent.text || '').replace(/^##/, '');
      const key = `${type}:${text_val.toLowerCase()}`;

      if (text_val.length < 2 || seen.has(key)) continue;
      seen.add(key);

      entities.push({
        text: text_val,
        type,
        start: ent.start || 0,
        end: ent.end || text_val.length,
        score: ent.score || 0,
      });
    }

    return entities;
  } catch (err) {
    console.warn('[browser_ml] NER extraction failed:', err);
    return [];
  }
}

/**
 * Score a single headline for relevance/intensity.
 * Combines sentiment model output with keyword heuristics.
 * Returns score 0–1 where higher = more relevant for intelligence.
 */
export async function scoreHeadline(text: string): Promise<HeadlineScore> {
  const entities = await extractEntities(text);
  const sentimentResult = await _getSentiment(text);

  // Combine sentiment + entity count + keyword signals
  let score = 0.0;

  // Sentiment contribution: negative news is often more relevant for OSINT
  if (sentimentResult) {
    if (sentimentResult.label === 'NEGATIVE') {
      score += 0.3 + sentimentResult.confidence * 0.2;
    } else if (sentimentResult.label === 'POSITIVE') {
      score += 0.1 + sentimentResult.confidence * 0.1;
    } else {
      score += 0.15;
    }
  } else {
    score += 0.2; // neutral fallback
  }

  // Entity contribution: more entities = more information density
  const entityBoost = Math.min(entities.length * 0.08, 0.3);
  score += entityBoost;

  // Keyword contribution: intelligence-relevant keywords
  const intelKeywords = [
    'attack', 'strike', 'explosion', 'fire', 'crash', 'collision',
    'sanction', 'arrest', 'raid', 'seizure', 'cyber', 'breach',
    'missile', 'drone', 'military', 'naval', 'border', 'conflict',
    'evacuate', 'emergency', 'casualt', 'death', 'kill', 'wound',
    'threat', 'alert', 'warning', 'critical', 'urgent',
  ];
  const lowerText = text.toLowerCase();
  const keywordHits = intelKeywords.filter((kw) => lowerText.includes(kw)).length;
  score += Math.min(keywordHits * 0.05, 0.2);

  // Clamp to 0–1
  score = Math.min(Math.max(score, 0), 1);

  return {
    score: round(score, 3),
    sentiment: sentimentResult?.label?.toLowerCase() as HeadlineScore['sentiment'] || 'neutral',
    sentimentScore: sentimentResult?.confidence || 0,
    entities,
    text,
  };
}

/**
 * Score multiple headlines in batch.
 * Processes in chunks of BATCH_SIZE to avoid blocking the UI.
 */
export async function scoreHeadlines(texts: string[]): Promise<HeadlineScore[]> {
  const results: HeadlineScore[] = [];
  for (let i = 0; i < texts.length; i += BATCH_SIZE) {
    const batch = texts.slice(i, i + BATCH_SIZE);
    const batchResults = await Promise.all(batch.map((t) => scoreHeadline(t)));
    results.push(...batchResults);
    // Yield to event loop between batches
    if (i + BATCH_SIZE < texts.length) {
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
  }
  return results;
}

/**
 * Get sentiment from the sentiment pipeline.
 * Returns null if model not available.
 */
async function _getSentiment(
  text: string
): Promise<{ label: string; confidence: number } | null> {
  if (!_sentimentPipeline) {
    try {
      await initBrowserMl();
    } catch {
      return null;
    }
  }
  if (!_sentimentPipeline) return null;

  try {
    const truncated = text.slice(0, MAX_HEADLINE_LEN);
    const result = await _sentimentPipeline(truncated);
    const item = Array.isArray(result) ? result[0] : result;
    if (!item) return null;
    return {
      label: item.label || 'NEUTRAL',
      confidence: round(item.score || 0, 4),
    };
  } catch (err) {
    console.warn('[browser_ml] sentiment inference failed:', err);
    return null;
  }
}

/**
 * Filter and rank headlines by score.
 * Returns headlines sorted by score descending, optionally filtered by threshold.
 */
export function rankHeadlines(
  scores: HeadlineScore[],
  minScore: number = 0
): HeadlineScore[] {
  return scores
    .filter((s) => s.score >= minScore)
    .sort((a, b) => b.score - a.score);
}

/**
 * Extract unique entities from multiple headlines.
 * Returns deduplicated entities with frequency count.
 */
export function aggregateEntities(
  scores: HeadlineScore[]
): Array<NerEntity & { frequency: number }> {
  const entityMap = new Map<string, NerEntity & { frequency: number }>();

  for (const s of scores) {
    for (const ent of s.entities) {
      const key = `${ent.type}:${ent.text.toLowerCase()}`;
      const existing = entityMap.get(key);
      if (existing) {
        existing.frequency++;
      } else {
        entityMap.set(key, { ...ent, frequency: 1 });
      }
    }
  }

  return Array.from(entityMap.values()).sort((a, b) => b.frequency - a.frequency);
}

/**
 * Helper: round to N decimal places.
 */
function round(val: number, decimals: number = 3): number {
  const factor = Math.pow(10, decimals);
  return Math.round(val * factor) / factor;
}

/**
 * Preload models (call on app startup if browser ML is desired).
 * Fail-soft: catches errors silently.
 */
export async function preloadBrowserMl(): Promise<void> {
  try {
    await initBrowserMl();
  } catch (err) {
    console.warn('[browser_ml] preload failed (will retry on first use):', err);
  }
}
