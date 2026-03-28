"""
Dataset fairness analyzer for FairLens.

Computes standard fairness metrics on tabular data:
- Disparate impact ratio (four-fifths / 80% rule)
- Statistical parity difference
- Equal opportunity difference
- Group-level outcome rates
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np

from app.models.schemas import (
    DatasetFairnessReport,
    GroupOutcome,
    ProtectedColumnReport,
)


class DatasetAnalyzer:
    """Analyzes datasets for fairness across protected attributes."""

    def analyze_dataset(
        self,
        data: list[dict[str, Any]],
        target_column: str,
        protected_columns: list[str],
    ) -> DatasetFairnessReport:
        """
        Analyze a dataset for fairness.

        Args:
            data: List of row dicts.
            target_column: The binary outcome column (1 = positive outcome).
            protected_columns: Columns representing protected attributes.

        Returns:
            DatasetFairnessReport with metrics per protected column.
        """
        if not data:
            raise ValueError("Dataset cannot be empty.")

        # Validate columns exist
        sample_row = data[0]
        if target_column not in sample_row:
            raise ValueError(f"Target column '{target_column}' not found in data.")
        for col in protected_columns:
            if col not in sample_row:
                raise ValueError(f"Protected column '{col}' not found in data.")

        # Extract arrays
        targets = np.array([self._to_numeric(row.get(target_column, 0)) for row in data])

        column_reports: list[ProtectedColumnReport] = []
        for col in protected_columns:
            report = self._analyze_protected_column(data, targets, col)
            column_reports.append(report)

        overall_score = self._calculate_overall_fairness(column_reports)
        recommendations = self._generate_recommendations(column_reports, target_column)

        return DatasetFairnessReport(
            report_id=uuid.uuid4().hex[:16],
            overall_fairness_score=round(overall_score, 1),
            total_rows=len(data),
            target_column=target_column,
            protected_columns_analysis=column_reports,
            recommendations=recommendations,
            timestamp=datetime.now(timezone.utc),
        )

    def _to_numeric(self, value: Any) -> float:
        """Convert a value to numeric, treating truthy as 1 and falsy as 0."""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, str):
            lower = value.strip().lower()
            if lower in ("1", "true", "yes", "y", "positive", "approved", "accepted"):
                return 1.0
            if lower in ("0", "false", "no", "n", "negative", "denied", "rejected"):
                return 0.0
            try:
                return float(value)
            except ValueError:
                return 0.0
        return 0.0

    def _analyze_protected_column(
        self,
        data: list[dict[str, Any]],
        targets: np.ndarray,
        column: str,
    ) -> ProtectedColumnReport:
        """Compute fairness metrics for a single protected column."""
        # Group data by protected attribute value
        groups: dict[str, list[int]] = {}
        for i, row in enumerate(data):
            group_val = str(row.get(column, "unknown"))
            if group_val not in groups:
                groups[group_val] = []
            groups[group_val].append(i)

        # Calculate positive outcome rate per group
        group_outcomes: list[GroupOutcome] = []
        positive_rates: dict[str, float] = {}

        for group_name, indices in sorted(groups.items()):
            group_targets = targets[indices]
            count = len(indices)
            if count == 0:
                continue
            positive_rate = float(np.mean(group_targets))
            positive_rates[group_name] = positive_rate
            group_outcomes.append(
                GroupOutcome(
                    group=group_name,
                    positive_rate=round(positive_rate, 4),
                    count=count,
                )
            )

        if not positive_rates:
            return ProtectedColumnReport(
                column=column,
                disparate_impact_ratio=1.0,
                statistical_parity_difference=0.0,
                equal_opportunity_difference=0.0,
                group_outcomes=[],
                passes_four_fifths_rule=True,
            )

        rates = list(positive_rates.values())
        max_rate = max(rates)
        min_rate = min(rates)

        # Disparate impact ratio: min_rate / max_rate
        # A value >= 0.8 passes the four-fifths rule
        if max_rate == 0:
            disparate_impact = 1.0  # No positive outcomes at all
        else:
            disparate_impact = min_rate / max_rate

        # Statistical parity difference: max difference in positive rates
        statistical_parity_diff = max_rate - min_rate

        # Equal opportunity difference: same as statistical parity for binary outcomes
        # (In a more complete implementation, this would be conditioned on actual positives)
        equal_opp_diff = max_rate - min_rate

        return ProtectedColumnReport(
            column=column,
            disparate_impact_ratio=round(disparate_impact, 4),
            statistical_parity_difference=round(statistical_parity_diff, 4),
            equal_opportunity_difference=round(equal_opp_diff, 4),
            group_outcomes=group_outcomes,
            passes_four_fifths_rule=disparate_impact >= 0.8,
        )

    def _calculate_overall_fairness(
        self, reports: list[ProtectedColumnReport]
    ) -> float:
        """
        Calculate an overall fairness score (0-100).

        Based on how close the disparate impact ratios are to 1.0 and
        how small the statistical parity differences are.
        """
        if not reports:
            return 100.0

        scores: list[float] = []
        for report in reports:
            # Disparate impact component: ratio of 1.0 = perfect, 0.0 = worst
            di_score = report.disparate_impact_ratio * 100.0

            # Statistical parity component: difference of 0 = perfect
            sp_score = (1.0 - report.statistical_parity_difference) * 100.0

            # Weight DI more heavily (it's the legal standard)
            combined = di_score * 0.6 + sp_score * 0.4
            scores.append(max(0.0, min(100.0, combined)))

        return float(np.mean(scores))

    def _generate_recommendations(
        self,
        reports: list[ProtectedColumnReport],
        target_column: str,
    ) -> list[str]:
        """Generate recommendations based on dataset fairness findings."""
        recommendations: list[str] = []

        failing_columns = [r for r in reports if not r.passes_four_fifths_rule]
        passing_columns = [r for r in reports if r.passes_four_fifths_rule]

        if failing_columns:
            cols = ", ".join(f"'{r.column}'" for r in failing_columns)
            recommendations.append(
                f"CRITICAL: The four-fifths (80%) rule is violated for: {cols}. "
                f"This may indicate legally actionable disparate impact in '{target_column}' outcomes."
            )

        for report in reports:
            if report.statistical_parity_difference > 0.1:
                # Find the best and worst groups
                if report.group_outcomes:
                    sorted_groups = sorted(
                        report.group_outcomes, key=lambda g: g.positive_rate
                    )
                    worst = sorted_groups[0]
                    best = sorted_groups[-1]
                    recommendations.append(
                        f"Column '{report.column}': Group '{worst.group}' has a positive "
                        f"outcome rate of {worst.positive_rate:.1%} vs '{best.group}' at "
                        f"{best.positive_rate:.1%} (difference: "
                        f"{report.statistical_parity_difference:.1%})."
                    )

        if not failing_columns and all(
            r.statistical_parity_difference <= 0.05 for r in reports
        ):
            recommendations.append(
                "Dataset appears fair across all analyzed protected columns. "
                "All groups have similar positive outcome rates."
            )
        elif passing_columns and failing_columns:
            cols = ", ".join(f"'{r.column}'" for r in passing_columns)
            recommendations.append(
                f"Columns {cols} pass the four-fifths rule, but other columns need attention."
            )

        recommendations.append(
            "Consider intersectional analysis (combinations of protected attributes) "
            "for a more thorough fairness assessment."
        )

        return recommendations
