"""Pydantic request/response schemas."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, field_validator
from typing import Annotated

from app.core.database import ensure_aware

T = TypeVar("T")
DT = Annotated[datetime, AfterValidator(ensure_aware)]
Severity = Literal["critical", "high", "medium", "low"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Message(BaseModel):
    detail: str


# ---------------------------------------------------------------- auth / users
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


def _check_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        raise ValueError("Password must contain letters and numbers")
    return v


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    full_name: str = Field(default="", max_length=128)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        if not USERNAME_RE.match(v):
            raise ValueError("Username may contain letters, numbers, '.', '_' and '-' only")
        return v

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return _check_password(v)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255, description="Username or email")
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UserOut(ORM):
    id: int
    email: str
    username: str
    full_name: str
    role_name: str
    is_active: bool
    last_login_at: DT | None
    created_at: DT


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=128)
    email: EmailStr | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return _check_password(v)


class AdminUserUpdate(BaseModel):
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None


class LoginAttemptOut(ORM):
    id: int
    identifier: str
    ip_address: str
    user_agent: str
    success: bool
    reason: str
    created_at: DT


# ---------------------------------------------------------------- monitoring
class MetricOut(ORM):
    id: int
    timestamp: DT
    cpu_percent: float
    memory_percent: float
    memory_used: int
    memory_total: int
    disk_percent: float
    disk_used: int
    disk_total: int
    net_bytes_sent: int
    net_bytes_recv: int
    net_send_rate: float
    net_recv_rate: float
    process_count: int
    connection_count: int


class DeviceOut(ORM):
    id: int
    name: str
    hostname: str
    device_type: str
    os_info: str
    ip_address: str
    status: str
    last_seen_at: DT | None


# ---------------------------------------------------------------- containers / vms
class ContainerOut(ORM):
    id: int
    container_id: str
    name: str
    image: str
    status: str
    health: str
    restart_count: int
    exit_code: int | None
    cpu_percent: float
    memory_percent: float
    memory_usage: int
    net_rx_bytes: int
    net_tx_bytes: int
    owner_id: int | None
    last_seen_at: DT | None


class VMOut(ORM):
    id: int
    uuid: str
    name: str
    state: str
    os_type: str
    memory_mb: int
    cpus: int
    owner_id: int | None
    last_seen_at: DT | None


class OwnerAssign(BaseModel):
    owner_id: int | None


# ---------------------------------------------------------------- security
class RuleOut(ORM):
    id: int
    key: str
    name: str
    description: str
    category: str
    severity: str
    enabled: bool
    condition: str
    params: dict[str, Any]
    recommended_response: str
    updated_at: DT


class RuleUpdate(BaseModel):
    enabled: bool | None = None
    severity: Severity | None = None
    params: dict[str, Any] | None = None


class EventOut(ORM):
    id: int
    event_type: str
    category: str
    severity: str
    message: str
    source: str
    resource: str
    details: dict[str, Any]
    rule_id: int | None
    created_at: DT


class AlertOut(ORM):
    id: int
    title: str
    description: str
    severity: str
    category: str
    status: str
    resource_type: str
    resource_name: str
    occurrences: int
    last_seen_at: DT
    recommended_action: str
    details: dict[str, Any]
    rule_id: int | None
    acknowledged_by_id: int | None
    acknowledged_at: DT | None
    resolved_by_id: int | None
    resolved_at: DT | None
    resolution_note: str
    created_at: DT


class AlertAction(BaseModel):
    note: str = Field(default="", max_length=2000)


# ---------------------------------------------------------------- integrity
class DirectoryCreate(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    recursive: bool = True


class DirectoryOut(ORM):
    id: int
    path: str
    recursive: bool
    enabled: bool
    baseline_at: DT | None
    last_scan_at: DT | None


class FileChangeOut(ORM):
    id: int
    directory_id: int
    file_path: str
    change_type: str
    old_hash: str | None
    new_hash: str | None
    detected_at: DT


class FileRecordOut(ORM):
    id: int
    directory_id: int
    file_path: str
    sha256: str
    size: int
    modified_at: DT | None
    status: str
    last_checked_at: DT


# ---------------------------------------------------------------- ml / reports / misc
class AnomalyOut(ORM):
    id: int
    timestamp: DT
    score: float
    is_anomaly: bool
    features: dict[str, Any]
    explanation: str
    model_version: str


class ReportRequest(BaseModel):
    title: str = Field(default="CloudGuard Security Report", max_length=255)
    format: Literal["pdf", "csv"] = "pdf"
    start_date: DT
    end_date: DT
    sections: list[Literal["health", "resources", "incidents", "containers", "vms", "anomalies", "alerts"]] = Field(
        default_factory=lambda: ["health", "resources", "incidents", "containers", "vms", "anomalies", "alerts"]
    )

    @field_validator("sections")
    @classmethod
    def _nonempty(cls, v):
        if not v:
            raise ValueError("Select at least one section")
        return list(dict.fromkeys(v))


class ReportOut(ORM):
    id: int
    title: str
    format: str
    start_date: DT
    end_date: DT
    sections: list[str]
    file_name: str
    file_size: int
    summary: dict[str, Any]
    created_by_id: int | None
    created_at: DT


class ActivityOut(ORM):
    id: int
    user_id: int | None
    action: str
    resource_type: str
    resource_id: str
    details: dict[str, Any]
    ip_address: str
    created_at: DT


class MonitoringSettings(BaseModel):
    interval_seconds: int = Field(ge=1, le=3600)
    container_poll_interval_seconds: int = Field(ge=5, le=3600)
    retention_days: int = Field(ge=1, le=365)
    process_watchlist: list[str] = Field(default_factory=list, max_length=200)


class MLSettings(BaseModel):
    enabled: bool
    contamination: float = Field(gt=0, le=0.5)
    min_training_samples: int = Field(ge=50, le=100000)
    z_threshold: float = Field(default=4.0, ge=2, le=20)
    auto_alert: bool


class SettingsOut(BaseModel):
    monitoring: MonitoringSettings
    ml: MLSettings


class SettingsUpdate(BaseModel):
    monitoring: MonitoringSettings | None = None
    ml: MLSettings | None = None


TokenPair.model_rebuild()


# ---------------------------------------------------------------- notifications
class NotificationOut(ORM):
    id: int
    category: str
    severity: str
    title: str
    message: str
    link: str
    alert_id: int | None
    is_read: bool
    read_at: DT | None
    created_at: DT
    updated_at: DT


class NotificationPage(Page[NotificationOut]):
    unread: int


class NotificationPreferences(BaseModel):
    min_severity: Severity
