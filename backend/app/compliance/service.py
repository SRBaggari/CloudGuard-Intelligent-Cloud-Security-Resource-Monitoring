"""Checklist seeding, evaluation and posture scoring."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.checks import AUTOMATED, DEFAULT_CHECKS
from app.core.database import utcnow
from app.models import ComplianceCheck, ComplianceRun, User

log = logging.getLogger("cloudguard.compliance")

WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}
CREDIT = {"pass": 1.0, "warning": 0.5, "fail": 0.0}  # other statuses are excluded from the score


def seed_checks(db: Session) -> None:
    existing = {c.key for c in db.scalars(select(ComplianceCheck)).all()}
    for d in DEFAULT_CHECKS:
        if d["key"] not in existing:
            db.add(ComplianceCheck(check_type=d.get("check_type", "automated"),
                                   **{k: v for k, v in d.items() if k != "check_type"}))
    db.commit()


def grade(score: float) -> str:
    return "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"


def evaluate(db: Session, check: ComplianceCheck) -> tuple[str, str]:
    if check.check_type == "manual":
        if not check.manual_status:
            return "not_assessed", "Awaiting manual assessment."
        return check.manual_status, check.manual_evidence or "Assessed manually."
    fn = AUTOMATED.get(check.key)
    if fn is None:
        return "unknown", "No implementation for this check."
    try:
        return fn(db)
    except Exception as e:  # a broken check must not abort the run; report it honestly
        log.exception("compliance check %s failed", check.key)
        db.rollback()
        return "unknown", f"Check could not be completed: {e.__class__.__name__}"


def score_results(results: list[dict]) -> tuple[float, dict[str, int]]:
    counts: dict[str, int] = {}
    num = den = 0.0
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if r["status"] in CREDIT:
            num += WEIGHT[r["severity"]] * CREDIT[r["status"]]
            den += WEIGHT[r["severity"]]
    return (round(num / den * 100, 1) if den else 0.0), counts


def run_checks(db: Session, user: User | None) -> ComplianceRun:
    now = utcnow()
    results = []
    for c in db.scalars(select(ComplianceCheck).where(ComplianceCheck.enabled.is_(True)).order_by(ComplianceCheck.category, ComplianceCheck.id)).all():
        status, evidence = evaluate(db, c)
        c.last_status, c.last_evidence, c.last_checked_at = status, evidence[:2000], now
        results.append({"key": c.key, "title": c.title, "category": c.category, "severity": c.severity,
                        "type": c.check_type, "status": status, "evidence": evidence[:2000], "reference": c.reference,
                        "remediation": c.remediation})
    score, counts = score_results(results)
    run = ComplianceRun(score=score, grade=grade(score), counts=counts, results=results,
                        run_by_id=user.id if user else None, created_at=now)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def latest_run(db: Session) -> ComplianceRun | None:
    return db.scalar(select(ComplianceRun).order_by(ComplianceRun.created_at.desc(), ComplianceRun.id.desc()).limit(1))
