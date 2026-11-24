export type Severity = "critical" | "high" | "medium" | "low";
export type AlertStatus = "open" | "acknowledged" | "resolved";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface User {
  id: number;
  email: string;
  username: string;
  full_name: string;
  role_name: "admin" | "user";
  is_active: boolean;
  theme_preference?: "dark" | "light" | "system";
  last_login_at: string | null;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: User;
}

export interface Metric {
  id: number;
  timestamp: string;
  cpu_percent: number;
  memory_percent: number;
  memory_used: number;
  memory_total: number;
  disk_percent: number;
  disk_used: number;
  disk_total: number;
  net_bytes_sent: number;
  net_bytes_recv: number;
  net_send_rate: number;
  net_recv_rate: number;
  process_count: number;
  connection_count: number;
}

export interface Health {
  status: "healthy" | "degraded" | "critical" | "unknown";
  score: number | null;
  issues: string[];
}

export interface Alert {
  id: number;
  title: string;
  description: string;
  severity: Severity;
  category: string;
  status: AlertStatus;
  resource_type: string;
  resource_name: string;
  occurrences: number;
  last_seen_at: string;
  recommended_action: string;
  details: Record<string, unknown>;
  rule_id: number | null;
  acknowledged_by_id: number | null;
  acknowledged_at: string | null;
  resolved_by_id: number | null;
  resolved_at: string | null;
  resolution_note: string;
  is_demo?: boolean;
  created_at: string;
}

export interface IntegrationStatus {
  available: boolean;
  mode?: "real" | "mock";
  message?: string;
  version?: string;
}

export interface DashboardSummary {
  devices: { total: number; hosts: number };
  vms: IntegrationStatus & { total: number; running: number };
  containers: IntegrationStatus & { total: number; running: number; unhealthy: number };
  metric: Metric | null;
  health: Health;
  alerts: { active: number; by_severity: Record<Severity, number>; recent: Alert[] };
  threats: {
    events_24h: number;
    failed_logins_24h: number;
    anomalies_24h: number;
    alerts_by_category_24h: Record<string, number>;
    ml_model_ready: boolean;
  };
  activity: { id: number; action: string; resource_type: string; resource_id: string; user_id: number | null; created_at: string }[];
}

export interface Container {
  id: number;
  container_id: string;
  name: string;
  image: string;
  status: string;
  health: string;
  restart_count: number;
  exit_code: number | null;
  cpu_percent: number;
  memory_percent: number;
  memory_usage: number;
  net_rx_bytes: number;
  net_tx_bytes: number;
  owner_id: number | null;
  last_seen_at: string | null;
}

export interface VM {
  id: number;
  uuid: string;
  name: string;
  state: string;
  os_type: string;
  memory_mb: number;
  cpus: number;
  owner_id: number | null;
  last_seen_at: string | null;
}

export interface Rule {
  id: number;
  key: string;
  name: string;
  description: string;
  category: string;
  severity: Severity;
  enabled: boolean;
  condition: string;
  params: Record<string, number | string>;
  recommended_response: string;
  updated_at: string;
}

export interface SecurityEvent {
  id: number;
  event_type: string;
  category: string;
  severity: Severity;
  message: string;
  source: string;
  resource: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface Process {
  pid: number;
  name: string;
  username: string;
  status: string;
  cpu_percent: number;
  memory_percent: number;
  memory_rss: number;
  started_at: string | null;
}

export interface Report {
  id: number;
  title: string;
  format: "pdf" | "csv";
  start_date: string;
  end_date: string;
  sections: string[];
  file_name: string;
  file_size: number;
  summary: Record<string, unknown>;
  created_by_id: number | null;
  created_at: string;
}

export interface Settings {
  monitoring: {
    interval_seconds: number;
    container_poll_interval_seconds: number;
    retention_days: number;
    process_watchlist: string[];
  };
  ml: { enabled: boolean; contamination: number; min_training_samples: number; z_threshold: number; auto_alert: boolean };
}

export interface LoginAttempt {
  id: number;
  identifier: string;
  ip_address: string;
  user_agent: string;
  success: boolean;
  reason: string;
  created_at: string;
}

export type NotificationSeverity = Severity | "info";

export interface AppNotification {
  id: number;
  category: "alert" | "incident" | "system";
  severity: NotificationSeverity;
  title: string;
  message: string;
  link: string;
  alert_id: number | null;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotificationPage extends Page<AppNotification> {
  unread: number;
}

export type IncidentStatus = "detected" | "acknowledged" | "investigating" | "resolved";

export interface IncidentSummary {
  id: number;
  reference: string;
  title: string;
  severity: Severity;
  status: IncidentStatus;
  category: string;
  assignee_id: number | null;
  created_by_id: number | null;
  detected_at: string;
  acknowledged_at: string | null;
  investigation_started_at: string | null;
  resolved_at: string | null;
  is_demo: boolean;
  created_at: string;
  updated_at: string;
}

export interface IncidentEvent {
  id: number;
  event_type: string;
  message: string;
  details: Record<string, unknown>;
  user_id: number | null;
  created_at: string;
}

export interface IncidentAction {
  id: number;
  action_type: string;
  target: string;
  mode: "executed" | "recorded";
  status: "completed" | "failed" | "recorded";
  result: string;
  performed_by_id: number | null;
  created_at: string;
}

export interface Incident extends IncidentSummary {
  description: string;
  root_cause: string;
  resolution_summary: string;
  alerts: Alert[];
  timeline: IncidentEvent[];
  actions: IncidentAction[];
}
