"""
Adversarial Fairness Pipeline
-------------------------------
Fairlearn ExponentiatedGradient debiasing with pre/post comparison.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.preprocessing import LabelEncoder

logger = logging.getLogger(__name__)


def adversarial_fairness_pipeline(
    data: pd.DataFrame,
    feature_cols: list[str],
    outcome_col: str,
    sensitive_col: str,
    favorable_value: Any,
    constraint: str = "demographic_parity",
    test_size: float = 0.3,
    random_state: int = 42,
) -> dict:
    try:
        from fairlearn.reductions import ExponentiatedGradient, DemographicParity
    except ImportError as exc:
        raise ImportError("fairlearn is required for adversarial debiasing.") from exc

    missing = [c for c in feature_cols + [outcome_col, sensitive_col] if c not in data.columns]
    if missing:
        raise ValueError(f"Columns not found: {missing}")
    if sensitive_col in feature_cols:
        raise ValueError("sensitive_col must not be in feature_cols.")
    if len(data) < 50:
        raise ValueError("Dataset too small (minimum 50 rows).")

    X_raw = data[feature_cols].copy()
    cat_cols = X_raw.select_dtypes(include=["object", "category"]).columns.tolist()
    if cat_cols:
        X_raw = pd.get_dummies(X_raw, columns=cat_cols, drop_first=True)
    X_raw = X_raw.fillna(X_raw.median(numeric_only=True))
    feature_names = X_raw.columns.tolist()

    y = (data[outcome_col] == favorable_value).astype(int)
    s_raw = data[sensitive_col].astype(str)
    le = LabelEncoder()
    s = pd.Series(le.fit_transform(s_raw), index=data.index, name=sensitive_col)

    X_train, X_test, y_train, y_test, s_train, s_test, s_raw_train, s_raw_test = train_test_split(
        X_raw, y, s, s_raw, test_size=test_size, random_state=random_state, stratify=y,
    )

    baseline = LogisticRegression(solver="liblinear", random_state=random_state, max_iter=500)
    baseline.fit(X_train, y_train)
    y_pred_baseline = baseline.predict(X_test)

    baseline_report = classification_report(y_test, y_pred_baseline, output_dict=True, zero_division=0)
    baseline_group_rates = _group_positive_rates(y_pred_baseline, s_raw_test)
    baseline_di = _disparate_impact_from_rates(baseline_group_rates)

    if constraint == "demographic_parity":
        fairness_constraint = DemographicParity()
    else:
        raise ValueError(f"Unsupported constraint: {constraint}")

    estimator = LogisticRegression(solver="liblinear", random_state=random_state, max_iter=500)
    mitigator = ExponentiatedGradient(estimator, constraints=fairness_constraint)
    mitigator.fit(X_train, y_train, sensitive_features=s_train)
    y_pred_mitigated = mitigator.predict(X_test)

    mitigated_report = classification_report(y_test, y_pred_mitigated, output_dict=True, zero_division=0)
    mitigated_group_rates = _group_positive_rates(y_pred_mitigated, s_raw_test)
    mitigated_di = _disparate_impact_from_rates(mitigated_group_rates)

    delta_accuracy = mitigated_report.get("accuracy", 0) - baseline_report.get("accuracy", 0)

    return {
        "status": "success",
        "constraint": constraint,
        "dataset_summary": {
            "total_records": len(data),
            "train_records": len(X_train),
            "test_records": len(X_test),
            "feature_cols": feature_names,
            "sensitive_col": sensitive_col,
            "outcome_col": outcome_col,
            "favorable_value": str(favorable_value),
        },
        "baseline": {
            "accuracy": round(baseline_report.get("accuracy", 0), 4),
            "classification_report": _round_report(baseline_report),
            "group_positive_rates": baseline_group_rates,
            "disparate_impact": baseline_di,
        },
        "mitigated": {
            "accuracy": round(mitigated_report.get("accuracy", 0), 4),
            "classification_report": _round_report(mitigated_report),
            "group_positive_rates": mitigated_group_rates,
            "disparate_impact": mitigated_di,
        },
        "delta": {
            "accuracy_change": round(delta_accuracy, 4),
            "fairness_improvement": {
                group: round(mitigated_di.get(group, 0) - baseline_di.get(group, 0), 4)
                for group in set(list(baseline_di.keys()) + list(mitigated_di.keys()))
            },
        },
        "interpretation": _interpret(baseline_di, mitigated_di, delta_accuracy),
    }


def _group_positive_rates(y_pred: np.ndarray, s: pd.Series) -> dict[str, float]:
    df = pd.DataFrame({"pred": y_pred, "group": s.values})
    rates = df.groupby("group")["pred"].mean().round(4)
    return {str(k): float(v) for k, v in rates.items()}


def _disparate_impact_from_rates(rates: dict[str, float]) -> dict[str, float]:
    if not rates:
        return {}
    max_rate = max(rates.values())
    if max_rate == 0:
        return {g: 0.0 for g in rates}
    return {g: round(r / max_rate, 4) for g, r in rates.items()}


def _round_report(report: dict) -> dict:
    rounded = {}
    for k, v in report.items():
        if isinstance(v, dict):
            rounded[k] = {mk: round(mv, 4) if isinstance(mv, float) else mv for mk, mv in v.items()}
        elif isinstance(v, float):
            rounded[k] = round(v, 4)
        else:
            rounded[k] = v
    return rounded


def _interpret(baseline_di: dict, mitigated_di: dict, delta_accuracy: float) -> str:
    flagged_before = [g for g, v in baseline_di.items() if v < 0.8]
    flagged_after = [g for g, v in mitigated_di.items() if v < 0.8]
    resolved = [g for g in flagged_before if g not in flagged_after]
    remaining = list(flagged_after)

    parts = []
    if resolved:
        parts.append(f"Mitigation resolved DI for {len(resolved)} group(s): {', '.join(resolved)}.")
    if remaining:
        parts.append(f"{len(remaining)} group(s) still below 0.8 DI: {', '.join(remaining)}.")
    if not flagged_before:
        parts.append("No groups were below DI threshold before mitigation.")
    parts.append(f"Accuracy changed by {delta_accuracy:+.2%} after fairness constraint.")
    if delta_accuracy < -0.05:
        parts.append("Note: >5pp accuracy decrease. Review feature set or increase data.")
    return " ".join(parts)
