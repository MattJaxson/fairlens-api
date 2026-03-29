"""
Fairness Reweighting
---------------------
Per-sample weights to align priority group outcome rates toward the
reference group rate, as defined in community configuration.

Algorithm (Section 4 of algorithm spec):
    For individual i in priority group g:
        If y_i = 1: w_i = target_rate / P(Y=1 | A=g)
        If y_i = 0: w_i = (1 - target_rate) / (1 - P(Y=1 | A=g))
    For non-priority groups: w_i = 1.0
"""

import logging
from typing import Any

import numpy as np
import pandas as pd

from app.services.fairness_audit import coerce_favorable, compute_group_rates

logger = logging.getLogger(__name__)


def reweight_samples_with_community(
    data: pd.DataFrame, race_col: str, outcome_col: str, favorable: Any, community_defs: dict,
) -> pd.DataFrame:
    target_group = community_defs.get("fairness_target", "White")
    priority_groups = set(community_defs.get("priority_groups", []))

    groups_in_data = set(data[race_col].dropna().unique())
    if target_group not in groups_in_data:
        raise ValueError(
            f"fairness_target '{target_group}' not found in data. Available: {sorted(groups_in_data)}"
        )

    binary_outcome = (data[outcome_col] == favorable).astype(float)
    group_rates = binary_outcome.groupby(data[race_col]).mean()

    target_rate = float(group_rates.get(target_group, 0.0))
    if target_rate == 0.0:
        raise ValueError(f"Target group '{target_group}' has 0% favorable rate. Cannot reweight.")
    if target_rate == 1.0:
        logger.warning("Target group '%s' has 100%% favorable rate.", target_group)

    missing_priority = priority_groups - groups_in_data
    if missing_priority:
        logger.warning("Priority group(s) %s not found — skipped.", sorted(missing_priority))

    data = data.copy()
    is_favorable = binary_outcome.values.astype(bool)
    row_group = data[race_col].values
    weights = np.ones(len(data), dtype=float)

    for group in priority_groups & groups_in_data:
        group_mask = row_group == group
        g_rate = float(group_rates[group])

        if g_rate == 0.0:
            fav_weight, unfav_weight = 1.0, (1.0 - target_rate)
        elif g_rate == 1.0:
            fav_weight, unfav_weight = target_rate, 1.0
        else:
            fav_weight = target_rate / g_rate
            unfav_weight = (1.0 - target_rate) / (1.0 - g_rate)

        weights[group_mask & is_favorable] = fav_weight
        weights[group_mask & ~is_favorable] = unfav_weight

    data["sample_weight"] = weights
    return data


def build_reweight_report(
    df: pd.DataFrame, race_col: str, outcome_col: str, favorable_value: str, community_defs: dict,
) -> dict:
    df, favorable = coerce_favorable(df, outcome_col, favorable_value)
    original_rates = compute_group_rates(df, race_col, outcome_col, favorable)

    reweighted_df = reweight_samples_with_community(
        data=df.copy(), race_col=race_col, outcome_col=outcome_col,
        favorable=favorable, community_defs=community_defs,
    )
    reweighted_df["sample_weight"] = reweighted_df["sample_weight"].round(4)

    return {
        "status": "success",
        "records": len(reweighted_df),
        "reweighted_data": reweighted_df.to_dict(orient="records"),
        "summary": {
            "original_group_rates": original_rates,
            "target_group": community_defs.get("fairness_target", "unknown"),
            "priority_groups": community_defs.get("priority_groups", []),
        },
    }
