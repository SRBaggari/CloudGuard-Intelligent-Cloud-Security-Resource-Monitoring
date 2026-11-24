from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin, utcnow

SEVERITIES = ("critical", "high", "medium", "low")
ALERT_STATUSES = ("open", "acknowledged", "resolved")


class DetectionRule(TimestampMixin, Base):
    __tablename__ = "detection_rules"
    __table_args__ = (CheckConstraint("severity IN ('critical','high','medium','low')", name="ck_rule_severity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    condition: Mapped[str] = mapped_column(String(255), default="")  # human readable condition
    params: Mapped[dict] = mapped_column(JSON, default=dict)  # tunable thresholds
    recommended_response: Mapped[str] = mapped_column(Text, default="")


class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = (Index("ix_security_events_cat_time", "category", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="low", index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="cloudguard")
    resource: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("detection_rules.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False, index=True)


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("severity IN ('critical','high','medium','low')", name="ck_alert_severity"),
        CheckConstraint("status IN ('open','acknowledged','resolved')", name="ck_alert_status"),
        Index("ix_alerts_status_severity", "status", "severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), default="host")
    resource_name: Mapped[str] = mapped_column(String(255), default="")
    fingerprint: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("detection_rules.id", ondelete="SET NULL"), index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("security_events.id", ondelete="SET NULL"))
    acknowledged_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False, index=True)

    rule: Mapped[DetectionRule | None] = relationship(lazy="joined")


class MonitoredDirectory(TimestampMixin, Base):
    __tablename__ = "monitored_directories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    recursive: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    baseline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    records: Mapped[list[FileIntegrityRecord]] = relationship(back_populates="directory", cascade="all, delete-orphan", passive_deletes=True)


class FileIntegrityRecord(Base):
    """Current baseline entry for a single file."""

    __tablename__ = "file_integrity_records"
    __table_args__ = (UniqueConstraint("directory_id", "file_path", name="uq_fim_dir_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    directory_id: Mapped[int] = mapped_column(ForeignKey("monitored_directories.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="baseline")  # baseline|modified|new|deleted
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    directory: Mapped[MonitoredDirectory] = relationship(back_populates="records")


class FileIntegrityChange(Base):
    """Change history produced by integrity scans."""

    __tablename__ = "file_integrity_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    directory_id: Mapped[int] = mapped_column(ForeignKey("monitored_directories.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    change_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # modified|new|deleted
    old_hash: Mapped[str | None] = mapped_column(String(64))
    new_hash: Mapped[str | None] = mapped_column(String(64))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AnomalyRecord(Base):
    __tablename__ = "anomaly_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    metric_id: Mapped[int | None] = mapped_column(ForeignKey("system_metrics.id", ondelete="SET NULL"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    model_version: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
