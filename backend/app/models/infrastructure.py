from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin, utcnow


class Device(TimestampMixin, Base):
    """A monitored host (the local machine is registered automatically)."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    device_type: Mapped[str] = mapped_column(String(32), default="host")
    os_info: Mapped[str] = mapped_column(String(255), default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="online", index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    metrics: Mapped[list[SystemMetric]] = relationship(back_populates="device", cascade="all, delete-orphan", passive_deletes=True)


class VirtualMachine(TimestampMixin, Base):
    __tablename__ = "virtual_machines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    os_type: Mapped[str] = mapped_column(String(128), default="")
    memory_mb: Mapped[int] = mapped_column(Integer, default=0)
    cpus: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Container(TimestampMixin, Base):
    __tablename__ = "containers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    container_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    image: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    health: Mapped[str] = mapped_column(String(32), default="none")
    restart_count: Mapped[int] = mapped_column(Integer, default=0)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    cpu_percent: Mapped[float] = mapped_column(Float, default=0.0)
    memory_percent: Mapped[float] = mapped_column(Float, default=0.0)
    memory_usage: Mapped[int] = mapped_column(BigInteger, default=0)
    net_rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    net_tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    networks: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")  # Docker network names
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when CloudGuard itself stops a container, so it is not flagged as unexpected
    expected_stop_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SystemMetric(Base):
    __tablename__ = "system_metrics"
    __table_args__ = (Index("ix_system_metrics_device_time", "device_id", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)
    cpu_percent: Mapped[float] = mapped_column(Float, nullable=False)
    memory_percent: Mapped[float] = mapped_column(Float, nullable=False)
    memory_used: Mapped[int] = mapped_column(BigInteger, default=0)
    memory_total: Mapped[int] = mapped_column(BigInteger, default=0)
    disk_percent: Mapped[float] = mapped_column(Float, nullable=False)
    disk_used: Mapped[int] = mapped_column(BigInteger, default=0)
    disk_total: Mapped[int] = mapped_column(BigInteger, default=0)
    net_bytes_sent: Mapped[int] = mapped_column(BigInteger, default=0)
    net_bytes_recv: Mapped[int] = mapped_column(BigInteger, default=0)
    net_send_rate: Mapped[float] = mapped_column(Float, default=0.0)  # bytes/sec
    net_recv_rate: Mapped[float] = mapped_column(Float, default=0.0)  # bytes/sec
    process_count: Mapped[int] = mapped_column(Integer, default=0)
    connection_count: Mapped[int] = mapped_column(Integer, default=0)

    device: Mapped[Device] = relationship(back_populates="metrics")
