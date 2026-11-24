"""Unsupervised anomaly detection on historical host metrics using Isolation Forest.

- Training requires a minimum number of real samples (configurable). With insufficient data the
  API reports that more monitoring data is needed instead of producing misleading predictions.
- Evaluation uses a chronological hold-out split (last 20%) to report the outlier rate and score
  distribution on unseen data.
- Explanations are per-feature z-scores relative to the training distribution.
- Isolation Forest cannot extrapolate: a value far outside the training range falls into the same
  leaf as the most extreme training values. A transparent statistical guard therefore also flags a
  sample when any feature is >= `z_threshold` standard deviations from its learned mean.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import ensure_aware
from app.models import AnomalyRecord, SystemMetric

FEATURES = ["cpu_percent", "memory_percent", "disk_percent", "net_send_rate", "net_recv_rate",
            "process_count", "connection_count"]
LABELS = {
    "cpu_percent": ("CPU", "%"), "memory_percent": ("Memory", "%"), "disk_percent": ("Disk", "%"),
    "net_send_rate": ("Upload rate", " B/s"), "net_recv_rate": ("Download rate", " B/s"),
    "process_count": ("Process count", ""), "connection_count": ("Connections", ""),
}


class InsufficientData(Exception):
    def __init__(self, have: int, need: int):
        super().__init__(f"Insufficient monitoring data: {have} samples available, {need} required.")
        self.have, self.need = have, need


def _matrix(metrics: list[SystemMetric]) -> np.ndarray:
    return np.array([[float(getattr(m, f) or 0.0) for f in FEATURES] for m in metrics], dtype=float)


class AnomalyDetector:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.bundle: dict[str, Any] | None = None
        self._loaded = False

    @property
    def model_path(self) -> Path:
        return get_settings().data_dir / "models" / "isolation_forest.joblib"

    def _load(self) -> None:
        if not self._loaded:
            self._loaded = True
            if self.model_path.exists():
                try:
                    self.bundle = joblib.load(self.model_path)
                except Exception:
                    self.bundle = None

    def info(self) -> dict[str, Any] | None:
        with self._lock:
            self._load()
            if not self.bundle:
                return None
            return {k: v for k, v in self.bundle.items() if k not in ("model", "scaler")}

    def reset(self) -> None:
        with self._lock:
            self.bundle = None
            self._loaded = True
            if self.model_path.exists():
                self.model_path.unlink()

    # ------------------------------------------------------------ training
    def train(self, db: Session, device_id: int, contamination: float, min_samples: int,
              z_threshold: float = 4.0, max_samples: int = 20000) -> dict[str, Any]:
        metrics = db.scalars(
            select(SystemMetric).where(SystemMetric.device_id == device_id)
            .order_by(SystemMetric.timestamp.desc()).limit(max_samples)
        ).all()[::-1]
        if len(metrics) < min_samples:
            raise InsufficientData(len(metrics), min_samples)
        X = _matrix(metrics)

        # chronological hold-out evaluation
        split = int(len(X) * 0.8)
        X_train, X_test = X[:split], X[split:]
        sc_eval = StandardScaler().fit(X_train)
        m_eval = IsolationForest(n_estimators=200, contamination=contamination, random_state=42)
        m_eval.fit(sc_eval.transform(X_train))
        test_pred = m_eval.predict(sc_eval.transform(X_test))
        test_scores = m_eval.decision_function(sc_eval.transform(X_test))

        # final model on all data
        scaler = StandardScaler().fit(X)
        model = IsolationForest(n_estimators=200, contamination=contamination, random_state=42)
        model.fit(scaler.transform(X))
        train_scores = model.decision_function(scaler.transform(X))
        train_pred = model.predict(scaler.transform(X))

        bundle = {
            "model": model, "scaler": scaler,
            "version": uuid.uuid4().hex[:8],
            "algorithm": "IsolationForest(n_estimators=200)",
            "features": FEATURES,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "device_id": device_id,
            "n_samples": int(len(X)),
            "contamination": contamination,
            "z_threshold": z_threshold,
            "data_start": ensure_aware(metrics[0].timestamp).isoformat(),
            "data_end": ensure_aware(metrics[-1].timestamp).isoformat(),
            "feature_mean": dict(zip(FEATURES, map(float, X.mean(axis=0)))),
            "feature_std": dict(zip(FEATURES, map(float, X.std(axis=0)))),
            # std floor so features that were constant during training do not explode the z-score
            "feature_scale": dict(zip(FEATURES, map(float, np.maximum(X.std(axis=0), 0.05 * np.abs(X.mean(axis=0)) + 1e-6)))),
            "evaluation": {
                "holdout_samples": int(len(X_test)),
                "holdout_outlier_rate": float((test_pred == -1).mean()) if len(X_test) else 0.0,
                "training_outlier_rate": float((train_pred == -1).mean()),
                "expected_outlier_rate": contamination,
                "score_p5": float(np.percentile(train_scores, 5)),
                "score_median": float(np.median(train_scores)),
                "score_p95": float(np.percentile(train_scores, 95)),
                "holdout_score_median": float(np.median(test_scores)) if len(X_test) else None,
            },
        }
        with self._lock:
            joblib.dump(bundle, self.model_path)
            self.bundle = bundle
            self._loaded = True
        return {k: v for k, v in bundle.items() if k not in ("model", "scaler")}

    # ------------------------------------------------------------ scoring
    @staticmethod
    def zscores(bundle: dict[str, Any], row: np.ndarray) -> list[float]:
        scale = bundle.get("feature_scale") or bundle["feature_std"]
        return [float((row[i] - bundle["feature_mean"][f]) / max(scale[f], 1e-9)) for i, f in enumerate(FEATURES)]

    def explain(self, row: np.ndarray, bundle: dict[str, Any] | None = None) -> tuple[str, dict[str, float]]:
        bundle = bundle or self.bundle
        assert bundle
        z = {}
        parts = []
        for i, (f, zs) in enumerate(zip(FEATURES, self.zscores(bundle, row))):
            mean = bundle["feature_mean"][f]
            z[f] = round(zs, 2)
            if abs(zs) >= 2:
                label, unit = LABELS[f]
                direction = "above" if zs > 0 else "below"
                parts.append(f"{label} {row[i]:.1f}{unit} is {abs(zs):.1f}σ {direction} normal ({mean:.1f}{unit})")
        if not parts:
            parts = ["Unusual combination of metric values (no single metric beyond 2σ)"]
        return "; ".join(parts), z

    def score(self, metrics: list[SystemMetric]) -> list[dict[str, Any]]:
        with self._lock:
            self._load()
            if not self.bundle:
                return []
            bundle = self.bundle
        if not metrics:
            return []
        X = _matrix(metrics)
        Xs = bundle["scaler"].transform(X)
        scores = bundle["model"].decision_function(Xs)
        preds = bundle["model"].predict(Xs)
        z_thr = float(bundle.get("z_threshold", 4.0))
        out = []
        for m, row, s, p in zip(metrics, X, scores, preds):
            guard = any(abs(z) >= z_thr for z in self.zscores(bundle, row))
            anomalous = bool(p == -1) or guard
            item = {"metric_id": m.id, "timestamp": m.timestamp, "score": float(s), "is_anomaly": anomalous,
                    "detected_by": ("isolation_forest" if p == -1 else "") + ("+zscore" if guard else "") if anomalous else "",
                    "features": {f: float(v) for f, v in zip(FEATURES, row)}}
            if anomalous:
                item["explanation"], item["zscores"] = self.explain(row, bundle)
            out.append(item)
        return out

    def score_and_store(self, db: Session, metric: SystemMetric, store_all: bool = False) -> AnomalyRecord | None:
        """Score one sample; persist it when anomalous (or always with store_all)."""
        res = self.score([metric])
        if not res:
            return None
        r = res[0]
        if not r["is_anomaly"] and not store_all:
            return None
        rec = AnomalyRecord(
            device_id=metric.device_id, metric_id=metric.id, timestamp=metric.timestamp, score=r["score"],
            is_anomaly=r["is_anomaly"], features=r["features"], explanation=r.get("explanation", ""),
            model_version=self.bundle["version"] if self.bundle else "",
        )
        db.add(rec)
        db.commit()
        return rec


detector = AnomalyDetector()
