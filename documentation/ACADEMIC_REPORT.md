# CloudGuard: Intelligent Cloud Security & Resource Monitoring System

*Computer Science Engineering — Academic Project Report*

---

## Abstract

Organisations increasingly run workloads on virtualised and containerised infrastructure, where
resource exhaustion, crashing services and unauthorised changes must be noticed quickly. CloudGuard
is a centralised monitoring and security platform for local cloud infrastructure. It collects real
host telemetry with psutil, discovers and controls Docker containers through the Docker Engine API
and VirtualBox VMs through a validated command wrapper, and evaluates 19 transparent detection rules
covering authentication abuse, abnormal resource consumption, container and VM failures and file
tampering. An unsupervised Isolation Forest model, trained on the host's own history, adds anomaly
detection with per-feature explanations. Alerts are de-duplicated, pushed to a React dashboard over
WebSockets and managed through an acknowledge/resolve workflow; PDF and CSV reports summarise any
period. The system is implemented with FastAPI, SQLAlchemy, PostgreSQL, React and TypeScript, is
protected by JWT authentication, Argon2id hashing and role-based access control. Version 1.1 adds
incident response management, an interactive infrastructure topology, CIS-inspired compliance
checks with a posture score, per-user notifications, capacity planning and a separated
demonstration mode. The system is verified by 181 automated tests (145 backend, 17 component,
19 end-to-end).

## 1. Introduction

### 1.1 Problem statement
Small teams and students who run services on their own machines, virtual machines or containers
rarely have an integrated view of resource health and security events. Commercial observability
and SIEM products are expensive and opaque; ad-hoc tools (Task Manager, `docker ps`, log files) are
fragmented and give no alerting or history.

### 1.2 Objectives
1. Collect **real** infrastructure metrics (no simulated values) and keep a history.
2. Integrate **containerisation** (Docker) and **virtualisation** (VirtualBox) with safe control operations.
3. Detect security-relevant conditions with **transparent, configurable rules**.
4. Add **unsupervised anomaly detection** that is honest about data sufficiency.
5. Provide **real-time alerting**, an alert-management workflow, reporting and an audit trail.
6. Apply secure-engineering practice: authentication, authorisation, validation, safe subprocess use.
7. Deliver a maintainable, tested, documented system using only free and open-source software.

### 1.3 Scope
CloudGuard monitors the local host and systems the operator is authorised to manage. It does not
scan third-party networks and does not claim to detect malware.

## 2. Background concepts

| Concept | How CloudGuard applies it |
|---|---|
| **Cloud computing / IaaS** | Treats the host, its VMs and containers as an infrastructure pool with health, capacity and event monitoring — the core of cloud operations (cf. AWS CloudWatch, Azure Monitor). |
| **Virtualisation** | Type-2 hypervisor (VirtualBox) managed through its CLI: VM discovery, state, configuration, lifecycle. |
| **Containerisation** | Docker Engine API: container lifecycle, cgroup-based CPU/memory statistics, health checks, restart policies. |
| **Observability** | Time-series metrics, Prometheus exposition format, Grafana dashboards. |
| **Intrusion detection** | Host-based, rule-driven detection (brute force, password spraying, FIM) similar to OSSEC/Wazuh concepts. |
| **File integrity monitoring** | Cryptographic hashing (SHA-256) against a trusted baseline (cf. Tripwire, AIDE). |
| **Anomaly detection** | Isolation Forest (Liu, Ting & Zhou, 2008) isolates outliers with random partitioning; anomalies need fewer splits. |
| **Authentication & authorisation** | JWT (RFC 7519) with refresh-token rotation, Argon2id (RFC 9106, PHC winner), RBAC and object-level ownership. |

## 3. System requirements

**Functional:** user registration/login/logout, profile and password management; RBAC; live and
historical host metrics; container and VM discovery/inspection/control; configurable detection
rules; alert lifecycle with real-time notification; FIM; anomaly detection with training and
evaluation; reports (PDF/CSV, date range); audit log; REST API with OpenAPI docs; WebSockets.

**Non-functional:** security (OWASP-aligned controls), graceful degradation when Docker/VirtualBox
are absent, responsiveness (API latency in milliseconds under concurrent load), portability
(Windows/Linux; PostgreSQL and SQLite), testability (mock adapters for CI), maintainability
(modular packages, typed code, migrations).

## 4. System design

The architecture, sequence diagrams and module responsibilities are documented in
[ARCHITECTURE.md](ARCHITECTURE.md); the normalised schema and ER diagram in
[DATABASE.md](DATABASE.md); all 60 REST operations in [API.md](API.md).

Key design choices:

* **Adapter pattern for integrations.** `RealDockerAdapter`/`MockDockerAdapter` and
  `RealVBoxAdapter`/`MockVBoxAdapter` share one interface. Production uses real adapters; tests and
  explicitly labelled demo mode use mocks. Unavailable integrations return `available: false` with
  setup guidance rather than fake data.
* **Rule engine with explicit conditions.** Rules are rows in `detection_rules` with a human-readable
  condition template and JSON parameters (e.g. `{"warning": 85, "critical": 95, "consecutive": 3}`),
  tunable at runtime with type and range validation.
* **Event → alert separation.** Every detection is logged as an immutable `security_event`;
  actionable `alerts` are de-duplicated by fingerprint and carry status, owner and remediation advice.
* **Realtime bridge.** A thread-safe hub lets synchronous services publish to asynchronous
  WebSocket clients (`asyncio.run_coroutine_threadsafe`).

## 5. Implementation

### 5.1 Monitoring
The collector samples CPU, memory, system-disk usage, network byte counters (converted to rates
from deltas), process count and inet-connection count every *N* seconds (default 5, admin
configurable). The first sample after start-up uses a 0.5 s measurement window because a near-zero
window reads 0 % or 100 %. Samples are stored, broadcast and evaluated; data older than the
retention period is pruned hourly.

*Performance finding.* Enumerating all processes on Windows took 1–2 s. Run in a thread, it
degraded unrelated requests from ~6 ms to ~800 ms: each SQLite/socket call in other threads releases
the GIL and must wait a full switch interval to reacquire it (convoy effect). Moving the scan into a
persistent worker process (`ProcessPoolExecutor`) with a 5 s cache restored ~6 ms latency under
concurrency (measured before/after).

### 5.2 Security engine (selected rules)

| Rule | Condition (defaults) | Severity |
|---|---|---|
| Multiple failed login attempts | ≥ 5 failures for one account in 10 min → 15 min lockout | High |
| Password spraying | one IP failing on ≥ 3 accounts in 10 min | High |
| New source IP | successful login from an IP unseen for the user in 30 days | Low |
| CPU / memory threshold | ≥ 85 % for 3 consecutive samples (critical ≥ 95 %) | High → Critical |
| Disk space | ≥ 90 % (critical ≥ 97 %) | High → Critical |
| Process spike / watchlist | process count +60 between samples / watch-listed name running | Medium / High |
| Network | ≥ 800 open connections; ≥ 50 MB/s for 3 samples | Medium |
| File changed | SHA-256 differs, file added or removed (deletions escalate) | Medium / High |
| Container | running → exited without a CloudGuard stop; unhealthy; restart count increased; CPU/mem ≥ 90 % | High / Medium |
| VM | running → poweroff/aborted without a CloudGuard stop (aborted = critical) | High |
| Repeated service failures | ≥ 3 failures of one resource in 15 min | High |

Actions taken by CloudGuard itself (stopping a container or VM) are recorded so they are not
misreported as crashes.

### 5.3 File integrity monitoring
Directories must be absolute, existing, not a filesystem root and not inside (or containing)
sensitive locations. Files are hashed in 1 MiB chunks; symlinks are skipped; a scan compares the
current state with the baseline and records modified/new/deleted changes with old/new hashes.
During testing, Windows Defender briefly locked a newly created file, which the first version
silently skipped. The scanner now retries transient locks and tracks unreadable files separately,
so a locked file is never misreported as deleted.

### 5.4 Anomaly detection
Features: CPU %, memory %, disk %, upload and download rates, process count, connection count.
Training requires `min_training_samples` (default 200) real samples; otherwise the API and UI
explain that more data is needed. Evaluation fits a model on the first 80 % of samples
(chronologically) and reports the outlier rate on the last 20 % against the configured
contamination, plus score percentiles. The final model is trained on all samples and persisted.

Isolation Forest partitions only within the training range, so an extreme value (e.g. 99 % CPU when
training saw 20–29 %) lands in the same leaf as the edge values and is **not** isolated — our first
unit test exposed this. A transparent z-score guard therefore also flags samples where any feature
is ≥ 4 σ (configurable) from its learned mean. Each anomaly is explained, e.g. *“CPU 46.6% is 3.2σ
above normal (16.2%)”*. Two consecutive anomalous samples raise an alert.

### 5.5 Enhancement modules (v1.1)

* **Incident response.** Incidents aggregate alerts and follow the stages *detected →
  acknowledged → investigating → resolved*, mirroring the detection/analysis, containment and
  recovery phases of NIST SP 800-61. An append-only timeline records every status change, note,
  linked alert and response action. Response actions reuse the authorised integration code (Docker,
  VirtualBox, account controls, FIM) and are recorded with their outcome even when they fail.
* **Notifications.** A per-user table with a unique `(user, dedupe_key)` constraint guarantees one
  notification per alert; escalations re-surface it, repeated detections do not. Delivery uses a
  personal WebSocket channel.
* **Topology.** A graph derived from monitored resources; health is classified per node and active
  alerts are counted by resource. Disconnected integrations contribute no nodes.
* **Compliance.** 23 read-only automated checks and 4 organisational items, each with a reference
  to the CIS control or benchmark that inspired it, evidence and remediation; the posture score is a
  severity-weighted pass rate (warnings count half). The report states explicitly that this is not a
  CIS certification.
* **Capacity planning.** Ordinary least-squares trend over bucketed measured data with a ±1.96σ
  residual band, R²-based confidence and days-to-threshold; every projected value is tagged as an
  estimate. Tests verify the method on synthetic data with a known 1 %/day growth (estimated ETA
  within ±1.5 days of the analytical value).
* **Demonstration mode.** Sample infrastructure and scenarios are flagged `is_demo`; a context
  variable makes the *same* detection code label its output as demo data. Tests prove the
  separation (real views, syncs and actions never see demo rows) and that engine-backed scenarios
  stop producing alerts when the corresponding rule is disabled — i.e. nothing is hard-coded.

### 5.6 Frontend
A React/TypeScript SPA with a navy dark theme (and light theme), sidebar navigation, live
notification bell, lazy-loaded pages and consistent loading, empty, error and success states.
Chart colours were validated for colour-vision-deficiency separation and contrast; charts always
use a single y-axis, legends and tooltips, and severity is never conveyed by colour alone.

## 6. Security implementation
See [SECURITY.md](SECURITY.md). Highlights: Argon2id; JWT with refresh rotation and reuse
detection; lockout and rate limiting; RBAC plus object-level ownership with non-leaking `404`s;
Pydantic validation and regex-validated identifiers; ORM-only SQL; `shell=False` whitelisted
subprocess calls; Docker socket never exposed; secrets only from the environment; audit log.

## 7. Testing and results

| Suite | Tool | Tests | Coverage of |
|---|---|---|---|
| Backend | Pytest | 145 | auth (hashing, login, lockout, refresh rotation & reuse, logout, profile), RBAC (12 admin-only endpoints, unauthenticated access, ownership), monitoring (real psutil values, worker-process scan, history, thresholds, dedupe, rule toggling), Docker & VM integration (mock adapters, validation, crash/restart/unhealthy detection, graceful degradation, command whitelist), alerts lifecycle & filters, WebSockets, FIM (baseline, all change types, unsafe paths, locked files), ML (insufficient data, training, explanation), reports (PDF/CSV, isolation), rate limiting, Prometheus |
| Frontend | Vitest + Testing Library | 17 | formatting, form validation, UI components, API client (errors, token refresh, offline), routing guards, dashboard rendering from API data, admin gating, error/retry state |
| End-to-end | Playwright (Chromium) | 19 | redirect to login, login/registration validation, live dashboard, navigation of every module, integration setup messages, **real file tampering → scan → alert → resolve**, PDF report download, theme toggle, logout |

All 181 tests pass. The v1.1 additions are covered by tests for notification de-duplication and
ownership, the incident lifecycle and RBAC, executed response actions, topology health and RBAC,
compliance scoring and manual assessments, capacity estimates, diagnostics and demo-data
separation, plus E2E flows for each new screen. The backend suite passes on both SQLite and
**PostgreSQL 18**; the seven Alembic migrations upgrade a populated database, downgrade and
re-upgrade cleanly, and `alembic check` reports no drift.

Defects found and fixed through testing (v1.1): boolean server defaults rendered as SQLite
integers that PostgreSQL rejects; a NOT NULL column migration that would fail on existing rows;
demo CPU samples skewing the forecast; a stale unread badge after marking notifications read;
E2E races and the suite tripping CloudGuard's own login rate limit. Earlier defects: Isolation Forest extrapolation gap (§5.4); GIL convoy
latency (§5.1); antivirus file locks in FIM (§5.3); stale titles on de-duplicated alerts; navigation
landmark mislabelled for assistive technology; filter controls ignoring width; first-sample CPU
artefact.

## 8. Limitations and future work

* Docker Compose deployment and the Docker/VirtualBox real adapters could not be exercised in the
  development environment (neither was installed); they are covered by unit tests with mock
  adapters and by graceful-degradation tests against the real adapters.
* Single-host collection; a lightweight agent pushing to the API would enable multi-host monitoring.
* In-memory rate limiting (single process) — use Redis for horizontal scaling.
* Tokens in `sessionStorage`; HttpOnly cookies + CSRF and MFA would harden authentication.
* Further ML work: per-hour seasonality features, model drift monitoring, analyst feedback labels.
* Notification channels (email/Slack/webhooks) and cloud-provider APIs (AWS/Azure) as further adapters.

## 9. Conclusion
CloudGuard demonstrates, end to end, the operational and security concerns of cloud
infrastructure: real telemetry, virtualisation and container management, transparent detection,
explainable machine learning, real-time alerting and secure engineering practice — implemented as a
tested, documented, free and open-source application that runs on a single laptop.

## References
1. F. T. Liu, K. M. Ting, Z.-H. Zhou, “Isolation Forest,” *IEEE ICDM*, 2008.
2. A. Biryukov, D. Dinu, D. Khovratovich, S. Josefsson, “Argon2 Memory-Hard Function,” RFC 9106, 2021.
3. M. Jones, J. Bradley, N. Sakimura, “JSON Web Token (JWT),” RFC 7519, 2015.
4. OWASP Foundation, *Application Security Verification Standard 4.0* and *Authentication Cheat Sheet*.
5. NIST SP 800-63B, *Digital Identity Guidelines: Authentication and Lifecycle Management*.
6. Documentation: FastAPI, SQLAlchemy, Alembic, psutil, Docker Engine API, VirtualBox `VBoxManage`, scikit-learn, Prometheus.
