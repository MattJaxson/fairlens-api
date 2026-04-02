"""
Adversarial Fairness Pipeline
-------------------------------
Fairlearn ExponentiatedGradient debiasing with pre/post comparison.

Includes Convergence Failsafe: when a community-derived ε is too strict
for the data geometry, the pipeline automatically relaxes ε in 0.01
increments until convergence, and returns a compromise_receipt documenting
the deviation from the community's ideal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.preprocessing import LabelEncoder

logger = logging.getLogger(__name__)

# ── Convergence Failsafe constants ───────────────────────────────────────
# The relaxation ceiling is the EEOC 4/5ths rule (ε=0.20). Relaxing beyond
# the loosest legally grounded threshold means the data cannot support *any*
# meaningful fairness constraint — that is a data problem, not a tuning one.
RELAXATION_STEP: float = 0.01
RELAXATION_CEILING: float = 0.20


@dataclass
class CompromiseReceipt:
    """
    Documents the exact deviation between community intent and mathematical
    reality when ExponentiatedGradient cannot converge at the requested ε.
    """
    compromised: bool
    community_epsilon: float
    converged_epsilon: float
    relaxation_steps: int
    total_relaxation: float
    ceiling_hit: bool
    detail: str


def adversarial_fairness_pipeline(
    data: pd.DataFrame,
    feature_cols: list[str],
    outcome_col: str,
    sensitive_col: str,
    favorable_value: Any,
    constraint: str = "demographic_parity",
    epsilon: float | None = None,
    test_size: float = 0.3,
    random_state: int = 42,
) -> dict:
    """
    Adversarial debiasing via Fairlearn ExponentiatedGradient.

    Parameters
    ----------
    constraint : str
        "demographic_parity" or "equalized_odds".
    epsilon : float | None
        Community-derived ε bound (from Q2Q / CPL). When None, Fairlearn's
        unconstrained default is used (difference_bound not set).
    """
    try:
        from fairlearn.reductions import (
            ExponentiatedGradient,
            DemographicParity,
            EqualizedOdds,
        )
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

    # ── Dynamic constraint injection with Convergence Failsafe ──
    if constraint not in ("demographic_parity", "equalized_odds"):
        raise ValueError(f"Unsupported constraint: {constraint}")

    def _build_constraint(ctype: str, eps: Optional[float]):
        kwargs: dict = {}
        if eps is not None:
            kwargs["difference_bound"] = eps
        if ctype == "demographic_parity":
            return DemographicParity(**kwargs)
        return EqualizedOdds(**kwargs)

    compromise: Optional[CompromiseReceipt] = None
    community_epsilon = epsilon  # preserve the community's original intent

    # Attempt fit at the community-derived ε, relax on failure
    current_eps = epsilon
    relaxation_steps = 0
    converged = False

    while not converged:
        fairness_constraint = _build_constraint(constraint, current_eps)
        estimator = LogisticRegression(
            solver="liblinear", random_state=random_state, max_iter=500,
        )
        mitigator = ExponentiatedGradient(
            estimator, constraints=fairness_constraint,
        )
        try:
            mitigator.fit(X_train, y_train, sensitive_features=s_train)
            y_pred_mitigated = mitigator.predict(X_test)
            converged = True
        except Exception as exc:
            if current_eps is None:
                # No ε was set at all — nothing to relax, propagate error
                raise
            next_eps = round(current_eps + RELAXATION_STEP, 6)
            relaxation_steps += 1
            logger.warning(
                "Convergence failed at ε=%.4f (%s): %s. "
                "Relaxing to ε=%.4f (step %d).",
                current_eps, type(exc).__name__, exc,
                next_eps, relaxation_steps,
            )
            if next_eps > RELAXATION_CEILING:
                # Hit the ceiling — one last attempt at the ceiling value
                current_eps = RELAXATION_CEILING
                fairness_constraint = _build_constraint(constraint, current_eps)
                estimator = LogisticRegression(
                    solver="liblinear", random_state=random_state, max_iter=500,
                )
                mitigator = ExponentiatedGradient(
                    estimator, constraints=fairness_constraint,
                )
                try:
                    mitigator.fit(X_train, y_train, sensitive_features=s_train)
                    y_pred_mitigated = mitigator.predict(X_test)
                    converged = True
                    relaxation_steps += 1
                except Exception:
                    raise ValueError(
                        f"Convergence Failsafe exhausted: model cannot converge "
                        f"even at EEOC ceiling ε={RELAXATION_CEILING}. "
                        f"Original community ε={community_epsilon}. "
                        f"This indicates a data geometry problem — review the "
                        f"dataset for insufficient group representation or "
                        f"degenerate feature distributions."
                    ) from exc
            else:
                current_eps = next_eps

    # Build compromise receipt if relaxation occurred
    if community_epsilon is not None and current_eps != community_epsilon:
        total_relaxation = round(current_eps - community_epsilon, 6)
        compromise = CompromiseReceipt(
            compromised=True,
            community_epsilon=community_epsilon,
            converged_epsilon=current_eps,
            relaxation_steps=relaxation_steps,
            total_relaxation=total_relaxation,
            ceiling_hit=current_eps >= RELAXATION_CEILING,
            detail=(
                f"The community's ideal ε={community_epsilon:.4f} was too strict "
                f"for this dataset. The model required {relaxation_steps} relaxation "
                f"step(s) of {RELAXATION_STEP} to converge at ε={current_eps:.4f}. "
                f"Total deviation: +{total_relaxation:.4f}. "
                f"{'EEOC ceiling reached — maximum legally grounded relaxation applied.' if current_eps >= RELAXATION_CEILING else 'Convergence achieved within community-acceptable range.'}"
            ),
        )

    mitigated_report = classification_report(y_test, y_pred_mitigated, output_dict=True, zero_division=0)
    mitigated_group_rates = _group_positive_rates(y_pred_mitigated, s_raw_test)
    mitigated_di = _disparate_impact_from_rates(mitigated_group_rates)

    delta_accuracy = mitigated_report.get("accuracy", 0) - baseline_report.get("accuracy", 0)

    # Build response with community governance metadata
    result: dict[str, Any] = {
        "status": "success",
        "constraint": constraint,
        "epsilon": current_eps,
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

    # Attach compromise receipt when relaxation was required
    if compromise is not None:
        result["compromise_receipt"] = {
            "compromised": compromise.compromised,
            "community_epsilon": compromise.community_epsilon,
            "converged_epsilon": compromise.converged_epsilon,
            "relaxation_steps": compromise.relaxation_steps,
            "total_relaxation": compromise.total_relaxation,
            "ceiling_hit": compromise.ceiling_hit,
            "detail": compromise.detail,
        }

    return result


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
