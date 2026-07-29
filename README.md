# STP Trading Platform
**Nomura Tech Graduate Program 2026**

Straight-Through Processing trading platform — cash equities and ETFs.

## Quick start (one command)
```bash
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
docker compose up
```

The platform will be available at:
- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000
- **API docs:** http://localhost:8000/docs

## Default credentials
| Username | Password | Role |
|---|---|---|
| admin | Password123! | Administrator |
| trader1 | Password123! | Trader |
| ops1 | Password123! | Operations |
| risk1 | Password123! | Risk |
| compliance1 | Password123! | Compliance |
| tom | Password123! | Client (persona P-01) |
| secretary1 | Password123! | Authorised Rep |

## What `docker compose up` does
1. Starts TimescaleDB (Postgres + time-series extension)
2. Runs Alembic migrations — creates all 15 tables
3. Ingests all 16 simulation data files (prices, news → sentiment)
4. Derives market calendar from the actual data dates
5. Seeds instruments, users, accounts, risk limits
6. Starts FastAPI backend on port 8000
7. Starts React frontend on port 3000

## Running tests
```bash
cd backend
pytest tests/unit/ -v
```

## Project structure
```
backend/app/
├── core/          # State machine, WebSocket manager
├── models/        # SQLAlchemy ORM entities
├── api/v1/        # FastAPI endpoints
├── services/      # Business logic (Stage 2)
└── scripts/       # Data ingestion, seeding
```

## Build stages
- **Stage 1 (this):** Foundation — schema, migrations, data ingestion, state machine ✅
- **Stage 2:** Order execution engine, risk checks, portfolio engine
- **Stage 3:** Reporting, analytics, paper trading
- **Stage 4:** React frontend, WebSocket streaming
- **Stage 5:** GenAI layer (NL order entry, query, narration)
- **Stage 6:** Security hardening, CI/CD, test coverage
