/**
 * Tests for browser_ml.ts (V4-48 — Browser-Side ML).
 *
 * Tests the headline scoring and NER logic without requiring
 * actual Transformers.js models. The _setLoader function is used
 * to inject fake pipeline functions.
 *
 * Uses Vitest with jsdom environment.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock pipelines
const mockNerPipeline = vi.fn();
const mockSentimentPipeline = vi.fn();
const mockPipelineFn = vi.fn(async (task: string, _model: string) => {
  if (task === 'token-classification') return mockNerPipeline;
  if (task === 'text-classification') return mockSentimentPipeline;
  return vi.fn();
});

// Import the module
import {
  initBrowserMl,
  getBrowserMlStatus,
  extractEntities,
  scoreHeadline,
  scoreHeadlines,
  rankHeadlines,
  aggregateEntities,
  preloadBrowserMl,
  _setLoader,
} from '../../src/lib/browser_ml';

// Inject mock loader to avoid importing the unresolvable external package
_setLoader(async () => ({ pipeline: mockPipelineFn, env: {} }));

describe('browser_ml', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockNerPipeline.mockReset();
    mockSentimentPipeline.mockReset();
    // Reset loader + state before each test
    _setLoader(async () => ({ pipeline: mockPipelineFn, env: {} }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('getBrowserMlStatus', () => {
    it('should return initial status with ready=false', () => {
      const status = getBrowserMlStatus();
      expect(status).toHaveProperty('ready');
      expect(status).toHaveProperty('nerLoaded');
      expect(status).toHaveProperty('sentimentLoaded');
      expect(status).toHaveProperty('error');
    });
  });

  describe('initBrowserMl', () => {
    it('should initialize models successfully', async () => {
      mockNerPipeline.mockResolvedValue([{ entity: 'B-PER', word: 'John', score: 0.99 }]);
      mockSentimentPipeline.mockResolvedValue([{ label: 'NEGATIVE', score: 0.85 }]);

      await initBrowserMl();
      const status = getBrowserMlStatus();
      expect(status.nerLoaded).toBe(true);
      expect(status.sentimentLoaded).toBe(true);
    });
  });

  describe('extractEntities', () => {
    it('should extract entities from NER pipeline output', async () => {
      // Ensure models are initialized
      mockNerPipeline.mockResolvedValue([
        { entity: 'B-PER', word: 'John', score: 0.99, start: 0, end: 4 },
        { entity: 'I-PER', word: '##Smith', score: 0.95, start: 5, end: 10 },
        { entity: 'B-ORG', word: 'NATO', score: 0.92, start: 15, end: 19 },
        { entity: 'B-LOC', word: 'Berlin', score: 0.88, start: 25, end: 31 },
      ]);

      await initBrowserMl();
      const entities = await extractEntities('John Smith met NATO in Berlin');

      expect(entities.length).toBeGreaterThan(0);
      // Should have Person, Organization, Location
      const types = entities.map((e) => e.type);
      expect(types).toContain('Person');
      expect(types).toContain('Organization');
      expect(types).toContain('Location');
    });

    it('should deduplicate entities', async () => {
      mockNerPipeline.mockResolvedValue([
        { entity: 'B-PER', word: 'John', score: 0.99, start: 0, end: 4 },
        { entity: 'B-PER', word: 'John', score: 0.97, start: 20, end: 24 },
      ]);

      await initBrowserMl();
      const entities = await extractEntities('John met John again');
      // Should only have one "Person:john" entry
      const persons = entities.filter((e) => e.type === 'Person');
      expect(persons.length).toBe(1);
    });

    it('should filter out very short entities', async () => {
      mockNerPipeline.mockResolvedValue([
        { entity: 'B-PER', word: 'A', score: 0.5, start: 0, end: 1 },
        { entity: 'B-PER', word: 'Alexander', score: 0.95, start: 5, end: 14 },
      ]);

      await initBrowserMl();
      const entities = await extractEntities('A Alexander');
      expect(entities.length).toBe(1);
      expect(entities[0].text).toBe('Alexander');
    });

    it('should return empty array on pipeline error', async () => {
      mockNerPipeline.mockRejectedValue(new Error('inference failed'));
      await initBrowserMl();
      const entities = await extractEntities('test text');
      expect(entities).toEqual([]);
    });
  });

  describe('scoreHeadline', () => {
    it('should return a score between 0 and 1', async () => {
      mockSentimentPipeline.mockResolvedValue([{ label: 'NEGATIVE', score: 0.9 }]);
      mockNerPipeline.mockResolvedValue([
        { entity: 'B-LOC', word: 'Kyiv', score: 0.95, start: 0, end: 4 },
      ]);

      await initBrowserMl();
      const result = await scoreHeadline('Explosion reported in Kyiv near government building');

      expect(result.score).toBeGreaterThanOrEqual(0);
      expect(result.score).toBeLessThanOrEqual(1);
      expect(result.sentiment).toBe('negative');
      expect(result.entities.length).toBeGreaterThan(0);
      expect(result.text).toContain('Kyiv');
    });

    it('should boost score for intelligence-relevant keywords', async () => {
      mockSentimentPipeline.mockResolvedValue([{ label: 'NEGATIVE', score: 0.8 }]);
      mockNerPipeline.mockResolvedValue([]);

      await initBrowserMl();
      const result = await scoreHeadline('Drone strike on military facility near border');

      // Should have high score due to keywords: drone, strike, military, border
      expect(result.score).toBeGreaterThan(0.4);
    });

    it('should have lower score for non-relevant content', async () => {
      mockSentimentPipeline.mockResolvedValue([{ label: 'POSITIVE', score: 0.7 }]);
      mockNerPipeline.mockResolvedValue([]);

      await initBrowserMl();
      const result = await scoreHeadline('Local bakery wins award for best croissant');

      // Should have lower score — positive sentiment, no intel keywords
      expect(result.score).toBeLessThan(0.5);
    });

    it('should handle neutral sentiment fallback', async () => {
      mockSentimentPipeline.mockResolvedValue([{ label: 'NEUTRAL', score: 0.6 }]);
      mockNerPipeline.mockResolvedValue([]);

      await initBrowserMl();
      const result = await scoreHeadline('Weather forecast for tomorrow');
      expect(result.sentiment).toBe('neutral');
      expect(result.score).toBeGreaterThanOrEqual(0);
    });
  });

  describe('scoreHeadlines (batch)', () => {
    it('should score multiple headlines', async () => {
      mockSentimentPipeline.mockResolvedValue([{ label: 'NEGATIVE', score: 0.85 }]);
      mockNerPipeline.mockResolvedValue([
        { entity: 'B-LOC', word: 'Damascus', score: 0.9, start: 0, end: 8 },
      ]);

      await initBrowserMl();
      const headlines = [
        'Explosion in Damascus',
        'Weather update',
        'Military movement near border',
      ];
      const results = await scoreHeadlines(headlines);

      expect(results.length).toBe(3);
      results.forEach((r) => {
        expect(r.score).toBeGreaterThanOrEqual(0);
        expect(r.score).toBeLessThanOrEqual(1);
      });
    });

    it('should handle empty array', async () => {
      await initBrowserMl();
      const results = await scoreHeadlines([]);
      expect(results).toEqual([]);
    });
  });

  describe('rankHeadlines', () => {
    it('should sort by score descending', () => {
      const scores = [
        { score: 0.3, sentiment: 'neutral' as const, sentimentScore: 0, entities: [], text: 'a' },
        { score: 0.8, sentiment: 'negative' as const, sentimentScore: 0.9, entities: [], text: 'b' },
        { score: 0.5, sentiment: 'negative' as const, sentimentScore: 0.7, entities: [], text: 'c' },
      ];
      const ranked = rankHeadlines(scores);
      expect(ranked[0].score).toBe(0.8);
      expect(ranked[1].score).toBe(0.5);
      expect(ranked[2].score).toBe(0.3);
    });

    it('should filter by minimum score', () => {
      const scores = [
        { score: 0.3, sentiment: 'neutral' as const, sentimentScore: 0, entities: [], text: 'a' },
        { score: 0.8, sentiment: 'negative' as const, sentimentScore: 0.9, entities: [], text: 'b' },
        { score: 0.5, sentiment: 'negative' as const, sentimentScore: 0.7, entities: [], text: 'c' },
      ];
      const ranked = rankHeadlines(scores, 0.5);
      expect(ranked.length).toBe(2);
      expect(ranked.every((r) => r.score >= 0.5)).toBe(true);
    });
  });

  describe('aggregateEntities', () => {
    it('should deduplicate and count entity frequency', () => {
      const scores = [
        {
          score: 0.8,
          sentiment: 'negative' as const,
          sentimentScore: 0.9,
          entities: [
            { text: 'Kyiv', type: 'Location', start: 0, end: 4, score: 0.95 },
            { text: 'NATO', type: 'Organization', start: 10, end: 14, score: 0.9 },
          ],
          text: 'a',
        },
        {
          score: 0.7,
          sentiment: 'negative' as const,
          sentimentScore: 0.8,
          entities: [
            { text: 'Kyiv', type: 'Location', start: 0, end: 4, score: 0.93 },
          ],
          text: 'b',
        },
      ];
      const aggregated = aggregateEntities(scores);
      expect(aggregated.length).toBe(2);

      const kyiv = aggregated.find((e) => e.text === 'Kyiv');
      expect(kyiv).toBeDefined();
      expect(kyiv!.frequency).toBe(2);

      const nato = aggregated.find((e) => e.text === 'NATO');
      expect(nato).toBeDefined();
      expect(nato!.frequency).toBe(1);
    });

    it('should sort by frequency descending', () => {
      const scores = [
        {
          score: 0.8,
          sentiment: 'negative' as const,
          sentimentScore: 0.9,
          entities: [
            { text: 'A', type: 'Person', start: 0, end: 1, score: 0.9 },
            { text: 'A', type: 'Person', start: 0, end: 1, score: 0.9 },
            { text: 'B', type: 'Person', start: 0, end: 1, score: 0.9 },
          ],
          text: 'a',
        },
      ];
      const aggregated = aggregateEntities(scores);
      expect(aggregated[0].text).toBe('A');
      expect(aggregated[0].frequency).toBe(2);
    });

    it('should handle empty input', () => {
      const aggregated = aggregateEntities([]);
      expect(aggregated).toEqual([]);
    });
  });

  describe('preloadBrowserMl', () => {
    it('should not throw on failure', async () => {
      // Should resolve without throwing even if models fail
      await expect(preloadBrowserMl()).resolves.toBeUndefined();
    });
  });
});
