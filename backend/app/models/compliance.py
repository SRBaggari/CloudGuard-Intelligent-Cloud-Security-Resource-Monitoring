"""Security checklists (automated, CIS-inspired checks plus manual items) and posture history."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, utcnow

CHECK_STATUSES = ("pass", "fail", "warning", "not_applicable", "unknown", "not_assessed")


class ComplianceCheck(TimestampMixin, Base):
    __tablename__ = "compliance_checks"
    __table_args__ = (
        CheckConstraint("severity IN ('critical','high','medium','low')", name="ck_compliance_severity"),
        CheckConstraint("check_type IN ('automated','manual')", name="ck_compliance_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    check_type: Mapped[str] = mapped_column(String(16), nullable=False)
    reference: Mapped[str] = mapped_column(String(255), default="")  # e.g. "Inspired by CIS Controls v8 5.3"
    remediation: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    # manual assessment
    manual_status: Mapped[str | None] = mapped_column(String(16))
    manual_evidence: Mapped[str] = mapped_column(Text, default="")
    assessed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # latest result (automated run or manual assessment)
    last_status: Mapped[str] = mapped_column(String(16), default="not_assessed")
    last_evidence: Mapped[str] = mapped_column(Text, default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ComplianceRun(Base):
    """Snapshot of a full checklist evaluation (posture history)."""

    __tablename__ = "compliance_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    grade: Mapped[str] = mapped_column(String(2), nullable=False)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[list] = mapped_column(JSON, default=list)
    run_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)
