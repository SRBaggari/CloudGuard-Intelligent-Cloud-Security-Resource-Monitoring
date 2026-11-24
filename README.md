# CloudGuard — Intelligent Cloud Security & Resource Monitoring System

CloudGuard is a full-stack platform that monitors local cloud infrastructure — the host machine,
Docker containers and VirtualBox virtual machines — detects suspicious activity and abnormal
resource usage with transparent rules and an optional machine-learning model, and raises real-time
security alerts.

![Dashboard](documentation/screenshots/03-dashboard.png)

| | |
|---|---|
| **Backend** | Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · Pydantic · WebSockets · psutil · Docker SDK · scikit-learn · ReportLab · prometheus-client |
| **Frontend** | React 19 · TypeScript · Vite · Tailwind CSS 4 · Recharts · Lucide |
| **Database** | PostgreSQL (SQLite supported for quick local runs and tests) |
| **Ops** | Docker Compose · Prometheus · Grafana |
| **Tests** | Pytest (145) · Vitest + Testing Library (17) · Playwright E2E (19) |

Everything is free and open source. No paid APIs, cloud credits or API keys are required.

---

## Features

* **Live dashboard** — monitored devices, active VMs, running containers, CPU/RAM/disk utilisation,
  network throughput, active alerts by severity, threat summary, infrastructure health score and
  recent activity, streamed over WebSockets.
* **Infrastructure monitoring** — real psutil metrics (CPU, memory, disk, network rates,
  processes, connections, uptime, OS info), historical charts (15 min – 7 days), configurable
  collection interval and retention, Prometheus exporter.
* **Docker containers** — discovery, running/stopped state, health, CPU/memory/network stats,
  inspect, logs, start/stop/restart with authorisation and audit.
* **VirtualBox VMs (optional)** — discovery, state, configuration, start/ACPI shutdown/power-off
  through a whitelisted `VBoxManage` wrapper. If VirtualBox is missing, a setup message is shown and
  no VM is reported as monitored.
* **Security engine** — 19 transparent, tunable rules: brute force (with lockout), password
  spraying, new login IP, repeated logins, CPU/memory/disk thresholds, process spikes, process
  watchlist, connection volume, network throughput, file changes, container crash / unhealthy /
  restart / resource abuse, unexpected VM shutdown, repeated service failures, ML anomalies.
* **Alert Center** — Critical/High/Medium/Low, categories, affected resource, de-duplication with
  occurrence counts, search & filters, acknowledge/resolve with notes, remediation guidance,
  real-time toasts.
* **File integrity monitoring** — SHA-256 baselines for admin-selected directories, detection of
  modified/new/deleted files, change history, re-baselining; sensitive system paths are blocked.
* **Anomaly detection (ML)** — Isolation Forest trained on this host's own history with
  chronological hold-out evaluation, configurable contamination and a z-score guard, per-feature
  explanations; refuses to predict until enough real data exists.
* **Reports** — PDF (with charts) and CSV for any date range: health, utilisation, incidents,
  containers, VMs, anomalies, alert history.
* **Users & security** — registration (first user = admin), JWT access/refresh with rotation,
  Argon2id, RBAC, object-level ownership, login history, failed-login tracking, audit log,
  rate limiting, profile and password management, light/dark/system themes saved per user.

### Added in v1.1

* **Incident response** — create incidents from alerts, stages *detected → acknowledged →
  investigating → resolved*, assignee, root cause, investigation notes, an immutable timeline, and
  response actions that are either executed through the authorised integrations (stop/restart a
  container, shut down a VM, disable an account / revoke sessions / unlock, re-baseline FIM) or
  recorded manually. MTTA/MTTR statistics.
* **Notification Center** — real-time per-user notifications over a personal WebSocket, severity
  categories, mark read / mark all read, history, minimum-severity preference, and de-duplication
  (one notification per alert; only escalations re-surface it).
* **Infrastructure topology** — interactive map of hosts, Docker Engine, containers, networks,
  VirtualBox and VMs with health colours + labels, alert badges, details panel, zoom/pan, live refresh.
* **Security audit & compliance** — 27-item configurable checklist (23 automated, read-only checks
  *inspired by* CIS Controls v8 / CIS Benchmarks + manual and custom items), weighted posture score
  and history, posture PDF/CSV report, audit-log filters and CSV export. No certification is claimed.
* **Capacity planning** — utilisation trends from measured history, linear-trend estimates with a
  ~95% band, days until warning/critical thresholds, memory/disk requirement estimates, containers
  near their limits — estimates are always labelled as such.
* **System settings** — security thresholds panel, live **system health diagnostics** (database,
  migrations, background loops, collector, storage, integrations), saved theme preference.
* **Demo & Learning** — a separate, labelled demonstration environment with scenarios that run
  through the real rule engine, an incident walkthrough, demo topology and forecast; plus a
  **Project information** page on cloud computing, virtualisation, containerisation and security
  monitoring.

## Screenshots

| | |
|---|---|
| ![Login](documentation/screenshots/01-login.png) | ![Monitoring](documentation/screenshots/04-monitoring.png) |
| ![Alert detail](documentation/screenshots/07b-alert-detail.png) | ![File integrity](documentation/screenshots/09-integrity.png) |
| ![Anomaly detection](documentation/screenshots/11-anomaly-detection.png) | ![Detection rules](documentation/screenshots/08-detection-rules.png) |
| ![Analytics](documentation/screenshots/10-analytics.png) | ![Light theme](documentation/screenshots/15-dashboard-light.png) |
| ![Incident detail](documentation/screenshots/16-incident-detail.png) | ![Compliance](documentation/screenshots/20-compliance.png) |
| ![Demo & Learning](documentation/screenshots/23-demo-center.png) | ![Capacity forecast](documentation/screenshots/24-capacity-demo-forecast.png) |
| ![Topology](documentation/screenshots/19-topology.png) | ![Diagnostics](documentation/screenshots/22-settings-diagnostics.png) |

More in [`documentation/screenshots`](documentation/screenshots).

---

## Quick start

### Prerequisites

| Tool | Version | Required? |
|---|---|---|
| Python | 3.11 – 3.13 (3.12 recommended) | yes |
| Node.js | 20+ | yes |
| PostgreSQL | 14+ | recommended (SQLite fallback available) |
| Docker Desktop / Engine | any recent | optional – enables container monitoring |
| Oracle VirtualBox | 7.x | optional – enables VM monitoring |

### 1. Database (PostgreSQL)

```bash
psql -U postgres -v app_password="'choose-a-strong-password'" -f database/setup_postgres.sql
```

### 2. Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example .env                 # Windows: copy ..\.env.example .env
```

Edit `backend/.env`:

```ini
DATABASE_URL=postgresql+psycopg://cloudguard:choose-a-strong-password@localhost:5432/cloudguard
JWT_SECRET_KEY=<output of: python -c "import secrets; print(secrets.token_urlsafe(64))">
```

> No PostgreSQL? Use `DATABASE_URL=sqlite:///./data/cloudguard.db` for a quick local run.

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Migrations run automatically at start-up (`AUTO_MIGRATE=true`). API docs: **http://127.0.0.1:8000/docs**.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** and **register — the first account becomes the administrator.**

On Windows you can start both with `deployment\scripts\start-windows.ps1`; on Linux/macOS with
`deployment/scripts/start-linux.sh`.

### Docker Compose (PostgreSQL + backend + frontend + Prometheus + Grafana)

```bash
cp .env.example .env    # set POSTGRES_PASSWORD, JWT_SECRET_KEY, GRAFANA_ADMIN_PASSWORD
docker compose up -d --build
```

CloudGuard: http://localhost:8080 · Grafana: http://localhost:3000 · Prometheus: http://localhost:9090.
Inside a container psutil reports the container's view of the host; for full host telemetry on
Windows/macOS run the backend natively. *(The Compose stack was written for this project but could
not be executed in the development environment, which had no Docker installed.)*

---

## Configuration

All configuration is via environment variables (`backend/.env` or the project root `.env`); see
[`.env.example`](.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | SQLite file in `backend/data` | SQLAlchemy URL (`postgresql+psycopg://…`) |
| `JWT_SECRET_KEY` | — (required in production) | signing key; an ephemeral key is generated in development with a warning |
| `APP_ENV` | `development` | `production` enforces a JWT secret |
| `INTEGRATION_MODE` | `real` | `mock` = labelled demo containers/VMs (testing/offline demo) |
| `DOCKER_ENABLED` / `VIRTUALBOX_ENABLED` | `true` | turn integrations off |
| `VBOXMANAGE_PATH` | auto-detect | explicit path to `VBoxManage` |
| `METRICS_INTERVAL_SECONDS` | `5` | initial collection interval (admins can change at runtime) |
| `CORS_ORIGINS` | `http://localhost:5173,…` | allowed browser origins |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `20` | login/register limit per IP |
| `PROMETHEUS_ENABLED` / `PROMETHEUS_TOKEN` | `true` / empty | `/metrics` exporter and optional bearer token |

Runtime settings (collection intervals, retention, process watchlist, ML parameters) and every
detection-rule threshold are editable by administrators in the UI.

---

## Testing

```bash
# Backend: 145 tests (auth, RBAC, API, monitoring, rules, Docker/VM via mock adapters, FIM, ML, reports, WebSockets,
#          notifications, incidents, topology, compliance, capacity, diagnostics, demo-data separation)
cd backend && pytest
# …against PostgreSQL instead of SQLite:
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/cloudguard_test pytest

# Frontend component/unit tests: 17 (Vitest + Testing Library)
cd frontend && npm test

# End-to-end: 19 (Playwright) — requires backend on :8000 and `npm run dev` on :5173
npx playwright install chromium   # first time only
npm run e2e
```

The E2E suite also regenerates the screenshots in `documentation/screenshots`.

---

## Project structure

```
backend/
  app/
    api/routes/          REST + WebSocket endpoints
    core/                config, database, security (JWT/Argon2), RBAC deps, rate limit, audit
    models/              SQLAlchemy models
    schemas/             Pydantic schemas
    monitoring/          psutil collector, process-scan worker, monitoring service
    docker_integration/  Docker adapter (real + mock) and sync/detections
    virtualization/      VBoxManage wrapper (real + mock) and sync/detections
    security_engine/     detection rules and evaluation engine
    compliance/          CIS-inspired checklist, automated checks, posture scoring
    integrity/           file integrity monitoring
    ml_engine/           Isolation Forest anomaly detector
    reports/             PDF/CSV report generator
    services/            alerts, notifications, incidents, topology, capacity, diagnostics, demo, settings, scheduler
    realtime/            WebSocket hub
  alembic/               database migrations
  scripts/               demo scenarios, API doc generator
  tests/                 pytest suite
frontend/
  src/{components,lib,pages,test}   React app and component tests
  e2e/                   Playwright tests
database/                PostgreSQL setup script
deployment/              Prometheus, Grafana provisioning, start scripts
documentation/           architecture, ER diagram, API, security, demo guide, academic report, screenshots
docker-compose.yml
```

## Documentation

* [Architecture](documentation/ARCHITECTURE.md) — components, data flows, design decisions
* [Database design & ER diagram](documentation/DATABASE.md)
* [REST API reference](documentation/API.md) (generated; also Swagger at `/docs`)
* [Security controls](documentation/SECURITY.md)
* [Demonstration guide](documentation/DEMO_GUIDE.md)
* [Academic project report](documentation/ACADEMIC_REPORT.md)

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| “Cannot reach the CloudGuard API” in the browser | Start the backend on port 8000; the Vite dev server proxies `/api` and `/ws` to it (`VITE_BACKEND_URL` to change). |
| `JWT_SECRET_KEY not set` warning; logged out after restart | Set `JWT_SECRET_KEY` in `backend/.env`. |
| `password authentication failed` / connection refused | Check `DATABASE_URL`, that PostgreSQL is running and that the database exists (`database/setup_postgres.sql`). |
| Containers page: “Docker Engine is not connected” | Install/start Docker Desktop (Windows/macOS) or the Docker daemon (Linux); on Linux add your user to the `docker` group. |
| VMs page: “VirtualBox is not connected” | Install VirtualBox; ensure `VBoxManage` is on PATH or set `VBOXMANAGE_PATH`. |
| Account locked (`423`) | Wait 15 minutes or have an admin click *Unlock* in Settings → Users. |
| `429 Too Many Requests` | Rate limit reached; wait a minute (limits are configurable). |
| ML shows “More monitoring data is needed” | Expected until `min_training_samples` (default 200) real samples are collected. |
| Integrity scan reports “unreadable (locked)” | Another program (often antivirus) held the file open; it is retried and never reported as deleted — scan again later. |
| Adding a directory to FIM is rejected | System locations, drive roots and folders containing `AppData`/`.ssh` are blocked by design; choose a specific folder. |
| `npm test` fails with “Vitest failed to find the runner” on Windows | Open the terminal in the path with an upper-case drive letter (`C:\…`, not `c:\…`); this is a Vitest path-casing issue. |
| Process table slow on first load | The first scan of all processes takes ~1–2 s on Windows; results are cached for 5 s. |
| Capacity Planning says “Not enough history yet” | Estimates need at least 3 hours of samples across 12 time buckets; use the Demo & Learning forecast meanwhile. |
| Demo alerts do not appear in the Alert Center | By design — tick **Show demonstration data** or use the Demo & Learning page. |
| E2E tests fail with “Too many requests” | The auth rate limit (20/min per IP) is working; wait a minute between full runs. |

## Responsible use

CloudGuard is intended for monitoring **your own** machines and systems you are explicitly
authorised to manage. The demo scenarios in `backend/scripts/demo_scenarios.py` only target
`localhost`.
