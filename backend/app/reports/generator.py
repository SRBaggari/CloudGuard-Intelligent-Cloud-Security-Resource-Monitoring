"""Report generation: gathers data for a date range and renders PDF (ReportLab) or CSV."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Alert, AnomalyRecord, Container, SecurityEvent, SystemMetric, VirtualMachine

SEV = ["critical", "high", "medium", "low"]


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def gather(db: Session, start: datetime, end: datetime) -> dict[str, Any]:
    mq = select(SystemMetric).where(SystemMetric.timestamp >= start, SystemMetric.timestamp <= end)
    agg = db.execute(select(
        func.count(SystemMetric.id), func.avg(SystemMetric.cpu_percent), func.max(SystemMetric.cpu_percent),
        func.avg(SystemMetric.memory_percent), func.max(SystemMetric.memory_percent),
        func.avg(SystemMetric.disk_percent), func.max(SystemMetric.disk_percent),
        func.avg(SystemMetric.net_send_rate), func.avg(SystemMetric.net_recv_rate),
        func.max(SystemMetric.net_send_rate), func.max(SystemMetric.net_recv_rate),
    ).where(SystemMetric.timestamp >= start, SystemMetric.timestamp <= end)).one()
    n = agg[0] or 0
    # downsample series to <= 120 points for the chart
    total = n
    step = max(1, total // 120)
    series = []
    if total:
        rows = db.scalars(mq.order_by(SystemMetric.timestamp)).all()
        series = [{"t": r.timestamp, "cpu": r.cpu_percent, "mem": r.memory_percent, "disk": r.disk_percent}
                  for r in rows[::step]]

    alerts = db.scalars(select(Alert).where(Alert.created_at >= start, Alert.created_at <= end)
                        .order_by(Alert.created_at.desc())).all()
    by_sev = {s: sum(a.severity == s for a in alerts) for s in SEV}
    by_cat: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for a in alerts:
        by_cat[a.category] = by_cat.get(a.category, 0) + 1
        by_status[a.status] = by_status.get(a.status, 0) + 1

    events_total = db.scalar(select(func.count(SecurityEvent.id)).where(
        SecurityEvent.created_at >= start, SecurityEvent.created_at <= end)) or 0
    anomalies = db.scalars(select(AnomalyRecord).where(
        AnomalyRecord.timestamp >= start, AnomalyRecord.timestamp <= end, AnomalyRecord.is_anomaly.is_(True))
        .order_by(AnomalyRecord.timestamp.desc())).all()
    containers = db.scalars(select(Container).order_by(Container.name)).all()
    vms = db.scalars(select(VirtualMachine).order_by(VirtualMachine.name)).all()

    def r(v):
        return round(float(v), 2) if v is not None else None

    resources = {
        "samples": n, "cpu_avg": r(agg[1]), "cpu_max": r(agg[2]), "mem_avg": r(agg[3]), "mem_max": r(agg[4]),
        "disk_avg": r(agg[5]), "disk_max": r(agg[6]), "tx_avg": r(agg[7]), "rx_avg": r(agg[8]),
        "tx_max": r(agg[9]), "rx_max": r(agg[10]),
    }
    open_crit = sum(1 for a in alerts if a.status != "resolved" and a.severity in ("critical", "high"))
    health = "healthy"
    if (resources["cpu_max"] or 0) >= 95 or (resources["mem_max"] or 0) >= 95 or by_sev["critical"]:
        health = "critical"
    elif (resources["cpu_avg"] or 0) >= 75 or (resources["mem_avg"] or 0) >= 85 or open_crit:
        health = "degraded"
    return {
        "start": start, "end": end, "health": health, "resources": resources, "series": series,
        "alerts": alerts, "alerts_by_severity": by_sev, "alerts_by_category": by_cat, "alerts_by_status": by_status,
        "events_total": events_total, "anomalies": anomalies, "containers": containers, "vms": vms,
        "open_high_or_critical": open_crit,
    }


POSTURE_DISCLAIMER = ("Checks are inspired by CIS Controls v8 and CIS Benchmarks. "
                      "This is not a formal CIS assessment or certification.")


def summary_of(data: dict[str, Any]) -> dict[str, Any]:
    posture = data.get("posture")
    return {
        **({"posture_score": posture.score, "posture_grade": posture.grade} if posture else {}),
        "health": data["health"], "samples": data["resources"]["samples"], "alerts": len(data["alerts"]),
        "alerts_by_severity": data["alerts_by_severity"], "events": data["events_total"],
        "anomalies": len(data["anomalies"]), "containers": len(data["containers"]), "vms": len(data["vms"]),
        "cpu_avg": data["resources"]["cpu_avg"], "mem_avg": data["resources"]["mem_avg"],
    }


# ------------------------------------------------------------------ CSV
def render_csv(data: dict[str, Any], sections: list[str], path: Path) -> None:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["CloudGuard Report", f"{data['start'].isoformat()} to {data['end'].isoformat()}"])
    w.writerow([])
    if "health" in sections:
        w.writerow(["# Infrastructure health"])
        w.writerow(["status", data["health"]])
        w.writerow(["open high/critical alerts", data["open_high_or_critical"]])
        w.writerow([])
    if "resources" in sections:
        w.writerow(["# Resource utilisation"])
        for k, v in data["resources"].items():
            w.writerow([k, v])
        w.writerow([])
    if "incidents" in sections:
        w.writerow(["# Security incidents summary"])
        w.writerow(["security events", data["events_total"]])
        for s, c in data["alerts_by_severity"].items():
            w.writerow([f"alerts_{s}", c])
        for cat, c in data["alerts_by_category"].items():
            w.writerow([f"category_{cat}", c])
        w.writerow([])
    if "containers" in sections:
        w.writerow(["# Containers"])
        w.writerow(["name", "image", "status", "health", "restarts", "cpu_percent", "memory_percent"])
        for c in data["containers"]:
            w.writerow([c.name, c.image, c.status, c.health, c.restart_count, c.cpu_percent, c.memory_percent])
        w.writerow([])
    if "vms" in sections:
        w.writerow(["# Virtual machines"])
        w.writerow(["name", "uuid", "state", "os_type", "memory_mb", "cpus"])
        for v in data["vms"]:
            w.writerow([v.name, v.uuid, v.state, v.os_type, v.memory_mb, v.cpus])
        w.writerow([])
    if "anomalies" in sections:
        w.writerow(["# Anomalies"])
        w.writerow(["timestamp", "score", "explanation"])
        for a in data["anomalies"]:
            w.writerow([a.timestamp.isoformat(), round(a.score, 4), a.explanation])
        w.writerow([])
    if "alerts" in sections:
        w.writerow(["# Alert history"])
        w.writerow(["id", "created_at", "severity", "category", "status", "title", "resource", "occurrences"])
        for a in data["alerts"]:
            w.writerow([a.id, a.created_at.isoformat(), a.severity, a.category, a.status, a.title,
                        a.resource_name, a.occurrences])
        w.writerow([])
    if "posture" in sections and data.get("posture"):
        p = data["posture"]
        w.writerow(["# Security posture"])
        w.writerow(["score", p.score])
        w.writerow(["grade", p.grade])
        w.writerow(["assessed_at", p.created_at.isoformat()])
        w.writerow(["note", POSTURE_DISCLAIMER])
        w.writerow(["category", "check", "severity", "type", "status", "evidence", "reference", "remediation"])
        for r in p.results:
            w.writerow([r["category"], r["title"], r["severity"], r["type"], r["status"], r["evidence"],
                        r["reference"], r["remediation"]])
    path.write_text(buf.getvalue(), encoding="utf-8", newline="")


# ------------------------------------------------------------------ PDF
def render_pdf(data: dict[str, Any], sections: list[str], title: str, path: Path) -> None:
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    navy = colors.HexColor("#0b1730")
    accent = colors.HexColor("#3b82f6")
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=navy, fontSize=20, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=navy, spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("b", parent=styles["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=9)

    def table(rows, widths=None, header=True):
        t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
        st = [("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
              ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")])]
        if header:
            st += [("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
        t.setStyle(TableStyle(st))
        return t

    el: list = [Paragraph(title, h1), Paragraph(
        f"Period: {data['start']:%Y-%m-%d %H:%M} to {data['end']:%Y-%m-%d %H:%M} UTC &nbsp;·&nbsp; "
        f"Generated by CloudGuard", body), Spacer(1, 6 * mm)]

    if "health" in sections:
        color = {"healthy": "#16a34a", "degraded": "#d97706", "critical": "#dc2626"}[data["health"]]
        el += [Paragraph("Infrastructure health", h2), Paragraph(
            f"Overall status: <font color='{color}'><b>{data['health'].upper()}</b></font> &nbsp; "
            f"Open high/critical alerts: <b>{data['open_high_or_critical']}</b> &nbsp; "
            f"Containers: <b>{len(data['containers'])}</b> &nbsp; VMs: <b>{len(data['vms'])}</b>", body)]

    if "resources" in sections:
        r = data["resources"]
        el += [Paragraph("Resource utilisation", h2)]
        if r["samples"]:
            el.append(table([
                ["Metric", "Average", "Peak"],
                ["CPU", f"{r['cpu_avg']}%", f"{r['cpu_max']}%"],
                ["Memory", f"{r['mem_avg']}%", f"{r['mem_max']}%"],
                ["Disk", f"{r['disk_avg']}%", f"{r['disk_max']}%"],
                ["Upload", f"{_fmt_bytes(r['tx_avg'] or 0)}/s", f"{_fmt_bytes(r['tx_max'] or 0)}/s"],
                ["Download", f"{_fmt_bytes(r['rx_avg'] or 0)}/s", f"{_fmt_bytes(r['rx_max'] or 0)}/s"],
            ], widths=[50 * mm, 40 * mm, 40 * mm]))
            el.append(Paragraph(f"{r['samples']} samples collected.", small))
            if len(data["series"]) > 1:
                d = Drawing(170 * mm, 60 * mm)
                lp = LinePlot()
                lp.x, lp.y, lp.width, lp.height = 30, 20, 160 * mm - 30, 50 * mm
                t0 = data["series"][0]["t"].timestamp()
                lp.data = [[((p["t"].timestamp() - t0) / 60.0, p[k]) for p in data["series"]] for k in ("cpu", "mem", "disk")]
                for i, c in enumerate((accent, colors.HexColor("#a855f7"), colors.HexColor("#f59e0b"))):
                    lp.lines[i].strokeColor = c
                    lp.lines[i].strokeWidth = 1.2
                lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = 0, 100
                lp.xValueAxis.labelTextFormat = "%d"
                d.add(lp)
                d.add(String(30, 5, "minutes since start  —  blue: CPU %, purple: memory %, amber: disk %", fontSize=7))
                el.append(d)
        else:
            el.append(Paragraph("No metric samples in this period.", body))

    if "incidents" in sections:
        el += [Paragraph("Security incidents summary", h2), Paragraph(
            f"{data['events_total']} security events and {len(data['alerts'])} alerts recorded.", body)]
        sev = data["alerts_by_severity"]
        if any(sev.values()):
            d = Drawing(170 * mm, 50 * mm)
            bc = VerticalBarChart()
            bc.x, bc.y, bc.width, bc.height = 30, 15, 90 * mm, 38 * mm
            bc.data = [[sev[s] for s in SEV]]
            bc.categoryAxis.categoryNames = [s.title() for s in SEV]
            bc.valueAxis.valueMin = 0
            bc.bars[0].fillColor = accent
            d.add(bc)
            el.append(d)
        if data["alerts_by_category"]:
            el.append(table([["Category", "Alerts"]] + [[k, v] for k, v in sorted(data["alerts_by_category"].items())],
                            widths=[60 * mm, 30 * mm]))

    if "containers" in sections:
        el += [Paragraph("Container activity", h2)]
        if data["containers"]:
            el.append(table([["Name", "Image", "Status", "Health", "Restarts", "CPU %", "Mem %"]] + [
                [c.name[:28], c.image[:30], c.status, c.health, c.restart_count, f"{c.cpu_percent:.1f}",
                 f"{c.memory_percent:.1f}"] for c in data["containers"]]))
        else:
            el.append(Paragraph("No containers discovered (Docker unavailable or no containers).", body))

    if "vms" in sections:
        el += [Paragraph("Virtual machine status", h2)]
        if data["vms"]:
            el.append(table([["Name", "State", "OS", "Memory (MB)", "vCPUs"]] + [
                [v.name[:30], v.state, v.os_type, v.memory_mb, v.cpus] for v in data["vms"]]))
        else:
            el.append(Paragraph("No virtual machines discovered (VirtualBox unavailable or no VMs).", body))

    if "anomalies" in sections:
        el += [Paragraph("Anomaly detection results", h2)]
        if data["anomalies"]:
            el.append(table([["Time", "Score", "Explanation"]] + [
                [f"{a.timestamp:%m-%d %H:%M:%S}", f"{a.score:.3f}", Paragraph(a.explanation[:300], small)]
                for a in data["anomalies"][:50]], widths=[28 * mm, 18 * mm, 124 * mm]))
        else:
            el.append(Paragraph("No anomalies detected in this period (or the ML model is not trained).", body))

    if "alerts" in sections:
        el += [Paragraph("Alert history", h2)]
        if data["alerts"]:
            el.append(table([["Time", "Severity", "Status", "Title", "Resource"]] + [
                [f"{a.created_at:%m-%d %H:%M}", a.severity, a.status, Paragraph(a.title[:120], small),
                 Paragraph(a.resource_name[:60], small)] for a in data["alerts"][:200]],
                widths=[22 * mm, 18 * mm, 24 * mm, 70 * mm, 36 * mm]))
        else:
            el.append(Paragraph("No alerts in this period.", body))

    if "posture" in sections and data.get("posture"):
        p = data["posture"]
        status_color = {"pass": "#16a34a", "fail": "#dc2626", "warning": "#d97706"}
        el += [Paragraph("Security posture", h2), Paragraph(
            f"Posture score <b>{p.score:.1f}/100</b> (grade <b>{p.grade}</b>) · assessed {p.created_at:%Y-%m-%d %H:%M} UTC · "
            + " · ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted(p.counts.items())), body),
            Paragraph(f"<i>{POSTURE_DISCLAIMER}</i>", small), Spacer(1, 3 * mm)]
        rows = [["Category", "Check", "Sev.", "Status", "Evidence / remediation"]]
        for r in p.results:
            col = status_color.get(r["status"], "#64748b")
            fix = f"<br/><font color='#64748b'>Fix: {r['remediation'][:160]}</font>" if r["status"] in ("fail", "warning") and r["remediation"] else ""
            rows.append([r["category"], Paragraph(r["title"][:90], small), r["severity"],
                         Paragraph(f"<font color='{col}'><b>{r['status'].replace('_', ' ')}</b></font>", small),
                         Paragraph(r["evidence"][:220].replace("<", "&lt;") + fix, small)])
        el.append(table(rows, widths=[22 * mm, 46 * mm, 14 * mm, 20 * mm, 72 * mm]))

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title=title, author="CloudGuard")
    doc.build(el)
