"""
Racial Fairness Audit Engine
-----------------------------
Community-governed disparate impact analysis. Uses community-defined
thresholds instead of hardcoded EEOC 0.8 defaults.
"""

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DI_THRESHOLD_DEFAULT = 0.8


def group_outcomes_by_race(data: pd.DataFrame, race_col: str, outcome_col: str) -> pd.DataFrame:
    if data.empty:
        raise ValueError("Input data is empty.")
    return data.groupby(race_col)[outcome_col].value_counts(normalize=True).unstack().fillna(0)


def disparate_impact(
    data: pd.DataFrame, race_col: str, outcome_col: str,
    privileged: str, unprivileged: str, favorable: Any,
) -> float | None:
    privileged_rate = data.loc[data[race_col] == privileged, outcome_col].value_counts(normalize=True).get(favorable, 0)
    unprivileged_rate = data.loc[data[race_col] == unprivileged, outcome_col].value_counts(normalize=True).get(favorable, 0)
    if privileged_rate == 0:
        logger.warning("Privileged group '%s' has no positive outcomes — DI undefined.", privileged)
        return None
    return unprivileged_rate / privileged_rate


def calculate_racial_bias_score(
    df: pd.DataFrame, sensitive_column: str = "race", outcome_column: str = "outcome",
) -> dict:
    for col in (sensitive_column, outcome_column):
        if col not in df.columns:
            raise ValueError(f"Column '{col}' not found. Available: {list(df.columns)}")
    if df.empty:
        raise ValueError("Dataset is empty.")
    if not pd.api.types.is_numeric_dtype(df[outcome_column]):
        raise ValueError(f"Outcome column '{outcome_column}' must be numeric. Got: {df[outcome_column].dtype}")
    clean = df[[sensitive_column, outcome_column]].dropna()
    n_dropped = len(df) - len(clean)
    if n_dropped > 0:
        logger.warning("%d rows dropped due to missing values.", n_dropped)
    if clean.empty:
        raise ValueError("No valid rows after dropping missing values.")
    group_stats = clean.groupby(sensitive_column)[outcome_column].mean()
    if len(group_stats) < 2:
        return {"group_outcomes": group_stats.to_dict(), "racial_disparity_score": 0.0}
    disparity = group_stats.max() - group_stats.min()
    return {"group_outcomes": group_stats.to_dict(), "racial_disparity_score": round(float(disparity), 4)}


def coerce_favorable(df: pd.DataFrame, outcome_col: str, favorable_value: str) -> tuple[pd.DataFrame, Any]:
    col_dtype = df[outcome_col].dtype
    try:
        if pd.api.types.is_integer_dtype(col_dtype):
            return df, int(favorable_value)
        if pd.api.types.is_float_dtype(col_dtype):
            return df, float(favorable_value)
        if pd.api.types.is_bool_dtype(col_dtype):
            return df, favorable_value.lower() in ("1", "true", "yes")
    except (ValueError, TypeError):
        pass
    df[outcome_col] = df[outcome_col].astype(str)
    return df, favorable_value


def compute_group_rates(df: pd.DataFrame, race_col: str, outcome_col: str, favorable: Any) -> dict[str, float]:
    binary = (df[outcome_col] == favorable).astype(float)
    rates = binary.groupby(df[race_col]).mean().round(4)
    return {str(k): float(v) for k, v in rates.items()}


class RacialFairnessAuditor:
    """Full racial fairness audit with community governance support."""

    def build_audit_report(
        self,
        df: pd.DataFrame,
        race_col: str,
        outcome_col: str,
        favorable_value: str,
        privileged_group: str | None = None,
        community_defs: dict | None = None,
    ) -> dict:
        if community_defs is None:
            community_defs = {}

        df, favorable = coerce_favorable(df, outcome_col, favorable_value)

        # Validate
        missing = [c for c in (race_col, outcome_col) if c not in df.columns]
        if missing:
            raise ValueError(f"Column(s) not found: {missing}. Available: {list(df.columns)}")
        if df.empty:
            raise ValueError("Dataset is empty.")

        from app.services.community_governance import is_community_valid

        di_threshold = float(community_defs.get("fairness_threshold", DI_THRESHOLD_DEFAULT))

        # Bias score
        df["_binary_outcome"] = (df[outcome_col] == favorable).astype(float)
        bias_result = calculate_racial_bias_score(df, sensitive_column=race_col, outcome_column="_binary_outcome")
        group_outcomes = {str(k): round(float(v), 4) for k, v in bias_result["group_outcomes"].items()}
        disparity_score = float(bias_result["racial_disparity_score"])

        # Reference group
        if privileged_group and privileged_group in group_outcomes:
            ref_group = privileged_group
        elif "White" in group_outcomes:
            ref_group = "White"
        else:
            ref_group = max(group_outcomes, key=lambda g: group_outcomes[g])

        ref_rate = group_outcomes[ref_group]

        # DI per group
        di_ratios: dict[str, float | None] = {}
        for group in group_outcomes:
            if group == ref_group:
                di_ratios[group] = 1.0
                continue
            di = disparate_impact(df, race_col, outcome_col, ref_group, group, favorable)
            di_ratios[group] = round(float(di), 4) if di is not None else None

        # Statistical parity gap
        all_rates = list(group_outcomes.values())
        stat_parity_gap = round((max(all_rates) - min(all_rates)) * 100, 2) if all_rates else 0.0

        # Flagged groups
        flagged_groups = [g for g, di in di_ratios.items() if di is not None and di < di_threshold]

        # Findings
        findings: list[str] = []
        for group, rate in group_outcomes.items():
            if group == ref_group:
                continue
            di = di_ratios.get(group)
            pct = round(rate * 100)
            ref_pct = round(ref_rate * 100)
            if di is None:
                findings.append(
                    f"{group}: {pct}% favorable rate; DI undefined (reference group has no positive outcomes)."
                )
            elif di < di_threshold:
                severity = "substantially below" if di < 0.5 else "below"
                findings.append(
                    f"{group}: {pct}% vs {ref_pct}% ({ref_group}), DI={di:.2f} — {severity} {di_threshold} threshold."
                )
            else:
                findings.append(
                    f"{group}: {pct}% vs {ref_pct}% ({ref_group}), DI={di:.2f} — within acceptable range."
                )
        findings.append(f"Statistical Parity Gap: {stat_parity_gap:.0f} percentage points.")

        # Recommendation
        if flagged_groups:
            n = len(flagged_groups)
            gw = "group falls" if n == 1 else "groups fall"
            recommendation = (
                f"Immediate review recommended. {n} {gw} below DI threshold of {di_threshold} "
                f"({', '.join(flagged_groups)}), indicating potential discriminatory outcomes."
            )
        else:
            recommendation = (
                f"No disparate impact detected. All groups meet or exceed the {di_threshold} threshold."
            )

        audit_type = "community_valid" if is_community_valid(community_defs) else "standard"

        return {
            "status": "success",
            "audit_type": audit_type,
            "community_config": {
                "priority_groups": community_defs.get("priority_groups", []),
                "fairness_target": community_defs.get("fairness_target", ref_group),
                "fairness_threshold": di_threshold,
                "provenance": community_defs.get("provenance") or None,
            },
            "summary": {
                "total_records": len(df),
                "groups_analyzed": list(group_outcomes.keys()),
                "outcome_column": outcome_col,
                "favorable_value": favorable_value,
                "flagged_groups": flagged_groups,
            },
            "metrics": {
                "disparity_score": disparity_score,
                "group_outcomes": group_outcomes,
                "disparate_impact": di_ratios,
                "statistical_parity_gap": stat_parity_gap,
            },
            "findings": findings,
            "recommendation": recommendation,
        }
