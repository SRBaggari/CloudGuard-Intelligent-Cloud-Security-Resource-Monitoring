# CloudGuard — Security Controls & Review

This document lists the security controls implemented in CloudGuard, where they live in the code,
and the known limitations. Scope: CloudGuard monitors **the local machine and systems the operator
is authorised to manage**; it performs no scanning or testing of third-party systems.

## Controls

| Area | Control | Implementation |
|---|---|---|
| Passwords | Argon2id hashing (argon2-cffi defaults); minimum 8 chars with letters + digits | `core/security.py`, `schemas` validators |
| Login | Constant-time behaviour for unknown users (dummy hash verify); generic error message | `api/routes/auth.py` |
| Brute force | Per-account lockout after N failures in a window (default 5 / 10 min → 15 min lock); alert raised | `security_engine/engine.py` (`auth_bruteforce`) |
| Rate limiting | Sliding window per client IP: 20/min on login & register, 600/min on other API calls; `429` + `Retry-After` | `core/ratelimit.py` |
| Tokens | HS256 JWT; access 30 min, refresh 7 days; token *type* checked; refresh rotation with server-side `jti`; reuse of a rotated token revokes all sessions | `core/security.py`, `auth.py` |
| Logout / password change | Refresh tokens revoked; password change signs out other sessions; disabling a user revokes their sessions | `auth.py`, `users.py` |
| Secrets | No secrets in code; `JWT_SECRET_KEY` required in production (startup fails without it); `.env` git-ignored; `.env.example` contains no credentials | `core/config.py` |
| Authorisation | Role-based (`admin`, `user`) via FastAPI dependencies; admin-only endpoints for configuration, processes, events, FIM, ML training, user management | `core/deps.py` |
| Object-level access | Containers/VMs/reports visible and actionable only by admins or the assigned owner; unauthorised lookups return `404` (no existence leak) | `can_manage()`, routers |
| Sensitive data minimisation | Process lists and remote connection details admin-only; container env **values** never returned (names only) | `monitoring.py`, `docker_integration/adapter.py` |
| Input validation | Pydantic schemas on every body; regex validation of container IDs and VM UUIDs; enum patterns on query filters; rule-parameter type/range checks | `schemas/`, routers |
| SQL injection | SQLAlchemy ORM / bound parameters only; no string-built SQL | all data access |
| Command execution | VBoxManage via `subprocess.run([...], shell=False, timeout=…)`; only whitelisted sub-commands (`list vms/runningvms`, `showvminfo`, `startvm`, `controlvm`); arguments validated before execution | `virtualization/vbox.py` |
| Docker | Docker socket never exposed; only list / inspect / stats / logs (tail ≤ 5000) / start / stop / restart through the adapter | `docker_integration/adapter.py` |
| File integrity | Only admin-added absolute directories; drive roots and sensitive locations (Windows, Program Files, ProgramData, AppData, `/etc`, `/proc`, `/sys`, `~/.ssh`, …) and their parents rejected; symlinks not followed; file count capped | `integrity/fim.py` |
| Transport headers | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Cache-Control: no-store` on API; CSP in the nginx image | `main.py`, `frontend/nginx.conf` |
| CORS | Explicit origin allow-list from `CORS_ORIGINS`; limited methods and headers | `main.py` |
| Errors | Validation errors return field messages; unhandled errors return a generic 500 and are logged server-side | `main.py` |
| Audit | Logins, logouts, registration, profile/password changes, admin user changes, rule/settings changes, container/VM actions, log views, FIM changes, ML training, reports | `core/audit.py` → `activity_logs` |
| Demo tooling | `scripts/demo_scenarios.py` refuses non-loopback targets | `backend/scripts/` |

## Detection honesty

CloudGuard does **not** claim to detect malware or advanced attacks. Every alert comes from an
explicit rule whose condition is displayed in the UI (e.g. *“failed logins for one account ≥ 5 within
10 min”*), or from the optional anomaly model, whose output is explained per feature and is
withheld until enough real data exists.

## Known limitations / hardening for production

* Tokens are kept in `sessionStorage`; an XSS flaw would expose them. Moving to `HttpOnly` cookies
  with CSRF protection would be stronger.
* The rate limiter is in-memory (single process). Behind multiple workers use a shared store (Redis).
* The client IP is taken from the socket; behind a reverse proxy configure trusted `X-Forwarded-For`
  handling (e.g. uvicorn `--proxy-headers --forwarded-allow-ips`).
* Mounting `/var/run/docker.sock` in the Compose deployment grants the backend container
  root-equivalent control of Docker; keep the backend off public networks or use a socket proxy
  that allows only the required endpoints.
* No TLS termination is included; put the stack behind HTTPS in any shared environment.
* MFA is not implemented.
