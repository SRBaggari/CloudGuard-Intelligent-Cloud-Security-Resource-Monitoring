# CloudGuard — Demonstration Guide (≈15 minutes)

A step-by-step script for presenting CloudGuard. Every effect shown is produced by real activity on
the presenting machine. All demo actions target **only this computer**.

## Before the presentation (10+ minutes earlier)

1. Start the stack (README → *Run locally*). Open **http://localhost:5173**.
2. Register the first account — it becomes the **administrator**.
3. Leave CloudGuard running so it collects a baseline. With a 5 s interval, the ML model needs
   200 samples ≈ 17 minutes (set *Settings → Metric collection interval* to 2–3 s to go faster).
4. Optional: start Docker Desktop and run two containers so the Containers page has content:
   ```bash
   docker run -d --name demo-web --health-cmd "wget -qO- localhost || exit 1" nginx:alpine
   docker run -d --name demo-api python:3.12-slim python -m http.server 8000
   ```
5. Prepare a folder for file-integrity monitoring:
   ```bash
   cd backend
   python scripts/demo_scenarios.py fim --dir C:\CloudGuardDemo\site --step create
   ```
6. In a second browser (or private window), register a regular user, e.g. `analyst`.

## Live script

| # | Show | What to say / do |
|---|---|---|
| 1 | **Login page** | Argon2id hashing, JWT access + rotating refresh tokens, rate limiting. |
| 2 | **Dashboard** | Live CPU/RAM/disk/network from psutil, streamed over WebSockets (point at *Live stream connected*). Device counts, health score, threat summary. If Docker/VirtualBox is absent, show the honest “not connected” state. |
| 3 | **Infrastructure** | Host details, historical ranges (15m → 7d), process table and connection summary (admin-only). |
| 4 | **Trigger: CPU** | In a terminal: `python scripts/demo_scenarios.py cpu --seconds 40`. Watch the CPU line climb; after 3 consecutive samples ≥ 85% a **High/Critical** alert appears as a toast and on the bell. |
| 5 | **Alert Center** | Filter by severity/category, search, open the alert: evidence, *Recommended response*, occurrence count (dedupe). **Acknowledge**, then **Resolve** with a note. |
| 6 | **Trigger: brute force** | `python scripts/demo_scenarios.py bruteforce --user analyst --attempts 6`. A **High** “Multiple failed login attempts” alert appears; the `analyst` account is locked (`423`). Show *Detection & Events → Login attempts*, then *Settings → Users → Unlock*. |
| 7 | **Trigger: password spraying** | `python scripts/demo_scenarios.py spray`. Alert: “Login failures across N accounts from 127.0.0.1”. |
| 8 | **Detection rules** | Every rule shows its exact condition (`IF …`). Tune one (e.g. CPU warning 85 → 70) and disable/enable another. |
| 9 | **File integrity** | Add `C:\CloudGuardDemo\site` (baseline of SHA-256 hashes). Run `python scripts/demo_scenarios.py fim --dir C:\CloudGuardDemo\site --step tamper`, click **Scan**: 1 modified, 1 new, 1 deleted, old/new hashes, high-severity alert. Try adding `C:\Windows` → rejected. **Accept changes** re-baselines. |
| 10 | **Containers** (if Docker) | Stats, logs, inspect (env values hidden). Stop a container from the UI → no alert (expected). Then `docker kill demo-api` in a terminal → **“Unexpected container termination”** alert. |
| 11 | **RBAC** | As admin, assign `demo-web` to `analyst`. In the analyst's browser only that container is visible and admin pages show “Administrator access required”. |
| 12 | **Analytics & ML** | Overview charts (alerts per day by severity, MTTR). *Anomaly detection*: if below 200 samples, show the “more data is needed” state; otherwise **Train model**, show hold-out evaluation, score chart with flagged points and explanations such as “CPU 46.6% is 3.2σ above normal”. |
| 13 | **Reports** | Generate a PDF for the last 24 h (health, utilisation chart, incidents, containers, VMs, anomalies, alert history); also a CSV. |
| 14 | **Audit log & API docs** | Show every action recorded; open **http://127.0.0.1:8000/docs** (Swagger). |
| 15 | **Tests** | `pytest` (80 backend tests), `npm test` (16 component tests), `npx playwright test` (10 E2E tests). |

## Reset after the demo

* Resolve remaining alerts in the Alert Center; remove the FIM demo directory.
* Delete `C:\CloudGuardDemo` and demo containers (`docker rm -f demo-web demo-api`).
* For a completely fresh database with SQLite, stop the backend and delete `backend/data/`.
