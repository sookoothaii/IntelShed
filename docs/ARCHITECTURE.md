# WorldBase Architecture

Comprehensive guide to the enhanced WorldBase backend architecture.

## Overview

WorldBase uses a layered architecture with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────┐
│ Presentation Layer (React + CesiumJS)                       │
│ Globe · Map · Data Panel · AI Chat · OSINT Views            │
│ (Modularized: App.tsx, ChatPanel.tsx, DataPanel.tsx, etc.)  │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│ API Layer (FastAPI + Pydantic v2)                             │
│ • Request validation                                          │
│ • Response serialization                                      │
│ • OpenAPI schema generation                                   │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│ Business Logic Layer                                          │
│ • node_sync.py (Pi↔PC sync)                                   │
│ • Feed bridges (18x data sources)                            │
│ • AI chat tools                                               │
│ • Anomaly detection (River ML)                                │
│ • Context budget manager (token budget + provenance truncation)│
│ • News feeds background ingest (ReliefWeb + RSS)              │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│ Data Access Layer                                           │
│ • SQLAlchemy 2.0 async ORM                                  │
│ • Auto-detect: SQLite (dev) / PostgreSQL (prod)             │
│ • Feed registry with dual-backend support                     │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│ Cross-Cutting Concerns                                      │
│ • Authentication (HMAC + replay protection)                   │
│ • Rate limiting (slowapi)                                    │
│ • Middleware (CORS, security headers)                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
backend/
├── main.py                    # FastAPI application entry point
├── node_sync.py               # Pi↔PC synchronization (refactored with Pydantic)
├── feed_registry.py           # Unified cache: SQLite or PostgreSQL
├── context_budget.py          # Token budget manager (provenance truncation + refuse path)
├── news_feeds.py              # Background ReliefWeb + RSS ingest (no live HTTP in chat path)
│
├── models/                    # 🆕 Pydantic v2 validation schemas
│   ├── __init__.py           # Central exports
│   └── node.py               # Node telemetry, health, mesh, GPS models
│
├── auth/                      # 🆕 Security layer
│   └── security.py           # HMAC signing, replay protection, API Key Auth
│
├── middleware/                # 🆕 FastAPI middleware
│   └── rate_limit.py         # slowapi integration, Redis/memory backend
│
├── db/                        # 🆕 SQLAlchemy 2.0 ORM
│   ├── __init__.py           # Model & utility exports
│   ├── models.py             # Database entities (NodeState, Briefing, etc.)
│   └── database.py           # Async engine, session factory, health checks
│
└── scripts/                   # 🆕 Automation & migration
    ├── migrate_to_postgres.py # SQLite → PostgreSQL data migration
    └── setup-postgres.ps1     # One-command PostgreSQL setup

frontend/src/
├── App.tsx                    # Main layout and routing
├── components/                # Modularized UI components
│   ├── ChatPanel.tsx          # AI Chat interface
│   ├── DataPanel.tsx          # Data tables and lists
│   ├── OsintPanel.tsx         # OSINT tools interface
│   ├── FirewallMonitor.tsx    # Firewall status display
│   └── WebcamSection.tsx      # Webcam grid and viewer
└── lib/
    └── networkFetch.ts        # Centralized fetchApi wrapper with API Key injection
```

---

## Pydantic Models (`models/`)

### NodeIngestPayload
Main model for Pi → PC telemetry ingestion.

```python
class NodeIngestPayload(BaseModel):
    node_id: str                    # Unique identifier
    name: Optional[str]             # Human-readable name
    lat, lon: Optional[float]       # Top-level coordinates
    sensors: Optional[SensorData]   # Environmental readings
    health: Optional[HealthData]   # System metrics
    mesh: Optional[list[MeshNode]] # Visible mesh peers
    pihole: Optional[PiholeStats]   # DNS filter stats
    gps: Optional[GPSData]          # GPS fix data
```

### Key Features
- **Field validators**: Latitude -90..90, longitude -180..180
- **Computed fields**: `heat_index_c`, `health_score`, `mesh_peer_count`
- **Model validators**: Ensure at least one location source
- **JSON Schema**: Auto-generated for API documentation

### Usage in Endpoints
```python
@router.post("/node/ingest")
async def node_ingest(payload: NodeIngestPayload, ...):
    # payload is validated and typed
    node_id = payload.node_id
    temp = payload.sensors.temp_c if payload.sensors else None
```

---

## Authentication (`auth/`)

### API Key Authentication
Sensitive endpoints (Chat, Briefing generation, OSINT tools) are protected by a simple API key mechanism.
- Set `WORLDBASE_API_KEY` in `.env`
- The frontend automatically injects this key into the `X-API-Key` header via the `fetchApi` wrapper in `networkFetch.ts`.

### HMAC-SHA256 Signing (Node Sync)

```python
from auth.security import (
    verify_hmac_signature,
    generate_hmac_signature,
    check_replay_attack,
    INGEST_TOKEN, ADMIN_TOKEN
)
```

### Request Flow
```
Pi                              PC
│                               │
│ POST /api/node/ingest         │
│ Headers:                      │
│   X-Node-Token: <hmac>        │
│   X-Request-Nonce: <uuid>     │
│   X-Request-Timestamp: <ts>   │
│ Body: {...}                   │
│ ─────────────────────────────>│
│                               │
│         Verify HMAC           │
│         Check replay          │
│         Check timestamp       │
│                               │
│   200 OK / 403 Forbidden      │
│ <─────────────────────────────│
```

### Security Features

| Feature | Implementation | Default |
|---------|---------------|---------|
| HMAC Algorithm | SHA-256 | - |
| Comparison | `hmac.compare_digest()` (constant-time) | - |
| Nonce Storage | Thread-safe in-memory cache | - |
| Replay Window | `WORLDBASE_REPLAY_WINDOW` | 300 sec |
| Token TTL | `WORLDBASE_AUTH_TTL` | 300 sec |
| Nonce Max Age | `WORLDBASE_NONCE_MAX_AGE` | 600 sec |

---

## Rate Limiting (`middleware/`)

### slowapi Integration

```python
from middleware.rate_limit import (
    rate_limit_node_ingest,
    rate_limit_node_pull,
    rate_limit_node_command,
    setup_rate_limiting
)

# Apply to endpoint
@router.post("/node/ingest")
@rate_limit_node_ingest()  # 100 req/min per node
async def node_ingest(...):
    ...
```

### Limits

| Endpoint | Limit | Key Function |
|----------|-------|--------------|
| `/api/node/ingest` | 100/min | Extract node_id from payload |
| `/api/node/pull` | 20/min | IP + node token |
| `/api/node/command` | 10/min | Admin token + IP |
| General API | 1000/hour | IP with X-Forwarded-For support |

### Backends
- **Memory** (default): In-process, single-instance
- **Redis**: Shared across multiple backend instances

---

## Database (`db/`)

### SQLAlchemy 2.0 Async

```python
from db import get_db, NodeState, Briefing

@router.get("/nodes")
async def list_nodes(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NodeState))
    nodes = result.scalars().all()
    return {"count": len(nodes), "nodes": nodes}
```

### Models

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `NodeState` | Pi node telemetry | node_id (PK), lat, lon, last_seen |
| `Briefing` | AI-generated briefings | id, content, generated_at, expires_at |
| `SensorAlert` | Threshold alerts | node_id, severity, message, acknowledged |
| `NodeCommand` | Command queue | node_id, command, status, created_at |
| `SensorHistory` | Time-series data | node_id, sensor, value, recorded_at |
| `FeedCache` | Feed snapshots | key (PK), value_json, cached_at |

### Dual Backend Support

```python
# feed_registry.py automatically selects backend

if feed_registry.is_postgres_mode():
    # Uses SQLAlchemy async session
    await feed_registry.async_write(db, "pegel", payload)
else:
    # Uses direct SQLite
    feed_registry.write("pegel", payload)

# Unified convenience function
feed_registry.write_auto("pegel", payload)  # Auto-detects
```

---

## Migration to PostgreSQL

### When to Migrate
- Multiple concurrent writers (18 feed bridges)
- High-frequency sensor ingestion
- Analytics queries on historical data
- Multi-instance deployment

### Migration Steps

```powershell
# 1. Setup PostgreSQL + migrate data
.\backend\scripts\setup-postgres.ps1 -Migrate

# 2. Set environment variable
# Add to backend/.env:
# DATABASE_URL=postgresql+asyncpg://worldbase:worldbase@localhost:5432/worldbase

# 3. Start server (automatically uses PostgreSQL)
.\start.ps1
```

### Rollback
Simply remove `DATABASE_URL` from `.env` — code falls back to SQLite.

---

## SSE Streaming

### Endpoint: `GET /api/node/stream`

Real-time node telemetry without polling.

### Events

| Event | Data | Frequency |
|-------|------|-----------|
| `connected` | `{client_id, timestamp}` | Once on connect |
| `node-update` | Node telemetry payload | On each ingest |
| `heartbeat` | `{timestamp}` | Every 30 seconds |

### JavaScript Client

```javascript
const es = new EventSource('/api/node/stream');

// Connection opened
es.addEventListener('connected', (e) => {
    console.log('SSE connected:', JSON.parse(e.data));
});

// Node update received
es.addEventListener('node-update', (e) => {
    const update = JSON.parse(e.data);
    console.log(`Node ${update.node_id}:`, update.sensors);
    // Update UI, refresh globe markers, etc.
});

// Handle errors
es.onerror = (err) => {
    console.error('SSE error:', err);
    // Auto-reconnect is automatic
};

// Close when done
es.close();
```

### Filter by Node

```javascript
const es = new EventSource('/api/node/stream?node_id=offgrid-pi');
```

---

## Configuration

### Environment Variables

```bash
# --- Security ---
NODE_INGEST_TOKEN=your-secret-here        # Required for production
NODE_ADMIN_TOKEN=separate-admin-token     # Optional
WORLDBASE_REQUIRE_NODE_TOKEN=1            # Fail startup without token

# --- Rate Limiting ---
RATE_LIMIT_STORAGE=memory                 # or "redis"
RATE_LIMIT_REDIS_URL=redis://localhost:6379/0

# --- Database ---
# Uncomment to enable PostgreSQL:
# DATABASE_URL=postgresql+asyncpg://user:pass@localhost/worldbase

# --- HMAC Settings ---
WORLDBASE_AUTH_TTL=300                    # Token validity (seconds)
WORLDBASE_REPLAY_WINDOW=300               # Nonce window (seconds)
WORLDBASE_NONCE_MAX_AGE=600               # Max nonce age (seconds)

# --- SSE ---
SSE_HEARTBEAT_INTERVAL=30                 # Keepalive seconds
```

---

## API Changes Summary

### Node Sync Endpoints

| Endpoint | Method | Auth | Request | Response |
|----------|--------|------|---------|----------|
| `/api/node/ingest` | POST | HMAC + nonce | `NodeIngestPayload` | `{status, node_id, alerts}` |
| `/api/node/pull` | GET | Token | Query: `?mesh=1` | `NodeBriefing` |
| `/api/node/stream` | GET | Token | Query: `?node_id=x` | SSE stream |
| `/api/node/{id}/command` | POST | Admin token | `CommandPayload` | `{status, command_id}` |

### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `X-Node-Token` | Yes (if INGEST_TOKEN set) | HMAC signature |
| `X-Request-Nonce` | Recommended | UUID for replay protection |
| `X-Request-Timestamp` | Recommended | Unix timestamp |
| `X-Admin-Token` | For commands | Admin authorization |

---

## Performance Considerations

### SQLite (Default)
- ✅ Zero configuration
- ✅ Single-file portability
- ⚠️ Single-writer bottleneck (WAL helps)
- ⚠️ Limited concurrency

### PostgreSQL (Optional)
- ✅ Connection pooling
- ✅ Better concurrent writes
- ✅ Advanced indexing
- ✅ Read replicas possible
- ⚠️ Requires setup

### Recommendations

| Scenario | Backend | Notes |
|----------|---------|-------|
| Development | SQLite | Fast iteration |
| Single Pi + PC | SQLite | Simple, sufficient |
| Multiple Pis | PostgreSQL | Concurrent ingest |
| Production | PostgreSQL | Monitoring, backups |

---

## Spatial Reasoning (P6)

Rule-based natural-language → spatial operation layer (0 VRAM, zero external dependencies).

| Component | File | Role |
|-----------|------|------|
| NL parser | `backend/spatial_reasoning.py` | Regex patterns extract `within`, `near`, `border`, `river_direction`, `visible_from`, `contains` |
| Composition | `backend/spatial_relations.py` | SpaRAGraph-style matrix for AND/OR/THEN composition of operations |
| Execution | `backend/spatial_reasoning.py` | Resolves place names against static geography, queries FtM entities in computed bbox |
| API | `backend/intel_proximity.py` | `GET /api/intel/spatial/query?q=...`, `GET /api/intel/spatial/reasoning/stats`, `GET /api/intel/spatial/composition` |
| Chat tool | `backend/chat_tools.py` | `spatial_query` tool exposes the pipeline to Ollama / OpenAI function calling |

Opt-in via `WORLDBASE_SPATIAL_REASONING=1` (default off).

## Testing

### Quick Validation

```powershell
# Import check
python -c "from main import app; print('✓ Imports OK')"

# Database health
curl http://localhost:8002/api/health

# Spatial reasoning
curl "http://localhost:8002/api/intel/spatial/query?q=within%2050km%20of%20Bangkok"

# Node ingest (with token)
curl -X POST http://localhost:8002/api/node/ingest `
  -H "Content-Type: application/json" `
  -H "X-Node-Token: <hmac>" `
  -d '{"node_id":"test","lat":52.5,"lon":13.4}'

# SSE stream
curl http://localhost:8002/api/node/stream
```

---

## Further Reading

- [`SECURITY.md`](SECURITY.md) — HMAC implementation details
- [`POSTGRESQL.md`](POSTGRESQL.md) — Migration guide
- [`../LLM_HANDOFF.md`](../LLM_HANDOFF.md) — AI agent context
