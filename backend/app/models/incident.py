"""Incident response: incidents group related alerts and record investigation and response."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Table, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin, utcnow
from app.models.security import Alert

INCIDENT_STATUSES = ("detected", "acknowledged", "investigating", "resolved")

incident_alerts = Table(
    "incident_alerts",
    Base.metadata,
    Column("incident_id", ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True),
    Column("alert_id", ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class Incident(TimestampMixin, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint("severity IN ('critical','high','medium','low')", name="ck_incident_severity"),
        CheckConstraint("status IN ('detected','acknowledged','investigating','resolved')", name="ck_incident_status"),
        Index("ix_incidents_status_severity", "status", "severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="detected", nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="general")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    investigation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    root_cause: Mapped[str] = mapped_column(Text, default="")
    resolution_summary: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False, index=True)

    alerts: Mapped[list[Alert]] = relationship(secondary=incident_alerts, lazy="selectin")
    timeline: Mapped[list[IncidentEvent]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", passive_deletes=True,
        order_by="IncidentEvent.created_at", lazy="selectin")
    actions: Mapped[list[IncidentAction]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", passive_deletes=True,
        order_by="IncidentAction.created_at", lazy="selectin")

    @property
    def reference(self) -> str:
        return f"INC-{self.id:05d}"


class IncidentEvent(Base):
    """Immutable timeline entry (status changes, notes, linked alerts, assignments, actions)."""

    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident_time", "incident_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    incident: Mapped[Incident] = relationship(back_populates="timeline")


class IncidentAction(Base):
    """A response action: either executed through CloudGuard's authorised adapters or recorded manually."""

    __tablename__ = "incident_actions"
    __table_args__ = (
        CheckConstraint("mode IN ('executed','recorded')", name="ck_action_mode"),
        CheckConstraint("status IN ('completed','failed','recorded')", name="ck_action_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    target: Mapped[str] = mapped_column(String(255), default="")
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[str] = mapped_column(Text, default="")
    performed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    incident: Mapped[Incident] = relationship(back_populates="actions")
