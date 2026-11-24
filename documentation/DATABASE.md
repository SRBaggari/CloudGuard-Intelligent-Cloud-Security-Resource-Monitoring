# CloudGuard — Database Design

PostgreSQL is the primary database (SQLite is supported for local runs/tests). The schema is created
and versioned with **Alembic** (`backend/alembic/versions/0001_initial_schema.py`). All tables with
mutable rows have `created_at` / `updated_at` timestamps (UTC). Integrity is enforced with primary
keys, foreign keys (with explicit `ON DELETE` behaviour), unique constraints, `CHECK` constraints on
enumerations and indexes on every column used for filtering or time-range queries.

## Entity–relationship diagram

```mermaid
erDiagram
    ROLES ||--o{ USERS : "has"
    USERS ||--o{ LOGIN_ATTEMPTS : "attempts"
    USERS ||--o{ REFRESH_TOKENS : "sessions"
    USERS ||--o{ ACTIVITY_LOGS : "performs"
    USERS ||--o{ REPORTS : "generates"
    USERS |o--o{ CONTAINERS : "owns"
    USERS |o--o{ VIRTUAL_MACHINES : "owns"
    USERS |o--o{ ALERTS : "acknowledges / resolves"
    USERS |o--o{ MONITORED_DIRECTORIES : "configures"
    DEVICES ||--o{ SYSTEM_METRICS : "produces"
    DEVICES |o--o{ CONTAINERS : "hosts"
    DEVICES |o--o{ VIRTUAL_MACHINES : "hosts"
    DEVICES ||--o{ ANOMALY_RECORDS : "scored for"
    SYSTEM_METRICS |o--o{ ANOMALY_RECORDS : "explains"
    DETECTION_RULES |o--o{ SECURITY_EVENTS : "triggers"
    DETECTION_RULES |o--o{ ALERTS : "raises"
    SECURITY_EVENTS |o--o{ ALERTS : "evidence for"
    MONITORED_DIRECTORIES ||--o{ FILE_INTEGRITY_RECORDS : "baseline"
    MONITORED_DIRECTORIES ||--o{ FILE_INTEGRITY_CHANGES : "history"

    ROLES {
        int id PK
        string name UK
        string description
    }
    USERS {
        int id PK
        string email UK
        string username UK
        string hashed_password
        int role_id FK
        bool is_active
        datetime last_login_at
        int failed_login_count
        datetime locked_until
    }
    LOGIN_ATTEMPTS {
        int id PK
        int user_id FK
        string identifier
        string ip_address
        string user_agent
        bool success
        string reason
        datetime created_at
    }
    REFRESH_TOKENS {
        int id PK
        string jti UK
        int user_id FK
        datetime expires_at
        bool revoked
    }
    DEVICES {
        int id PK
        string name
        string hostname UK
        string device_type
        string os_info
        string ip_address
        string status
        datetime last_seen_at
    }
    SYSTEM_METRICS {
        int id PK
        int device_id FK
        datetime timestamp
        float cpu_percent
        float memory_percent
        float disk_percent
        float net_send_rate
        float net_recv_rate
        int process_count
        int connection_count
    }
    CONTAINERS {
        int id PK
        string container_id UK
        string name
        string image
        string status
        string health
        int restart_count
        float cpu_percent
        float memory_percent
        int owner_id FK
        int device_id FK
        datetime expected_stop_at
    }
    VIRTUAL_MACHINES {
        int id PK
        string uuid UK
        string name
        string state
        string os_type
        int memory_mb
        int cpus
        json config
        int owner_id FK
        int device_id FK
    }
    DETECTION_RULES {
        int id PK
        string key UK
        string name
        string category
        string severity
        bool enabled
        string condition
        json params
        text recommended_response
    }
    SECURITY_EVENTS {
        int id PK
        string event_type
        string category
        string severity
        text message
        string resource
        json details
        int rule_id FK
        datetime created_at
    }
    ALERTS {
        int id PK
        string title
        string severity
        string category
        string status
        string resource_type
        string resource_name
        string fingerprint
        int occurrences
        json details
        int rule_id FK
        int event_id FK
        int acknowledged_by_id FK
        int resolved_by_id FK
    }
    MONITORED_DIRECTORIES {
        int id PK
        string path UK
        bool recursive
        bool enabled
        datetime baseline_at
        datetime last_scan_at
        int created_by_id FK
    }
    FILE_INTEGRITY_RECORDS {
        int id PK
        int directory_id FK
        string file_path
        string sha256
        bigint size
        string status
    }
    FILE_INTEGRITY_CHANGES {
        int id PK
        int directory_id FK
        string file_path
        string change_type
        string old_hash
        string new_hash
        datetime detected_at
    }
    ANOMALY_RECORDS {
        int id PK
        int device_id FK
        int metric_id FK
        datetime timestamp
        float score
        bool is_anomaly
        json features
        text explanation
        string model_version
    }
    ACTIVITY_LOGS {
        int id PK
        int user_id FK
        string action
        string resource_type
        string resource_id
        json details
        string ip_address
        datetime created_at
    }
    REPORTS {
        int id PK
        string title
        string format
        datetime start_date
        datetime end_date
        json sections
        string file_name
        json summary
        int created_by_id FK
    }
    SYSTEM_SETTINGS {
        string key PK
        json value
    }
```

## Tables

| Table | Purpose | Notable constraints / indexes |
|---|---|---|
| `roles` | `admin`, `user` | `name` unique |
| `users` | accounts, Argon2id hashes, lockout state | `email`, `username` unique; FK `role_id` `ON DELETE RESTRICT` |
| `login_attempts` | login history & failed-login tracking | indexes on `identifier`, `success`, `created_at`, `(ip_address, created_at)` |
| `refresh_tokens` | refresh-token rotation and revocation | `jti` unique; cascade on user delete |
| `devices` | monitored hosts (local host registered automatically) | `hostname` unique |
| `system_metrics` | time series of host telemetry | index `(device_id, timestamp)`; cascade on device delete; pruned after `retention_days` |
| `containers`, `virtual_machines` | discovered workloads, ownership for RBAC | `container_id` / `uuid` unique; owner FK `SET NULL` |
| `detection_rules` | transparent, tunable rules | `key` unique; `CHECK severity IN (…)` |
| `security_events` | every detection & auth failure (immutable log) | index `(category, created_at)` |
| `alerts` | actionable, de-duplicated alerts with workflow | `CHECK status`, `CHECK severity`; index `(status, severity)`, `fingerprint` |
| `monitored_directories` | FIM configuration | `path` unique |
| `file_integrity_records` | current SHA-256 baseline per file | unique `(directory_id, file_path)` |
| `file_integrity_changes` | modified / new / deleted history | indexes on `change_type`, `detected_at` |
| `anomaly_records` | ML anomalies with explanations | index on `timestamp`, `is_anomaly` |
| `activity_logs` | audit trail | index `(user_id, created_at)`, `action` |
| `reports` | generated report metadata (files stored in `data/reports`) | FK `created_by_id` |
| `system_settings` | runtime-tunable settings (intervals, ML) | key/value JSON |

## Normalisation notes

* Reference data (roles, rules) is stored once and referenced by foreign key.
* Alerts reference their rule and originating event instead of copying rule metadata (the
  recommended action is copied deliberately so the alert keeps the guidance that applied at
  detection time even if the rule is later edited).
* FIM separates current state (`file_integrity_records`) from history (`file_integrity_changes`).
* Report files live on disk; the table stores metadata and a small summary for listing.

## Migrations

```bash
cd backend
alembic upgrade head          # create / update schema
alembic downgrade base        # drop everything
alembic revision --autogenerate -m "describe change"   # after editing models
alembic check                 # verify models and migrations agree
```
