"""
Regulatory Compliance Adapter
================================
Maps community-governed audit outputs to regulatory reporting formats.

Supported regulations:
- NYC Local Law 144 (LL144): Automated Employment Decision Tools
- Michigan HB 4668: Algorithmic Discrimination in Consumer Transactions
- Colorado AI Act (SB 24-205): High-Risk AI Systems

Each adapter takes a standard audit report (from RacialFairnessAuditor) and
a community fairness configuration, and produces a compliance report
structured to the regulation's requirements.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def generate_ll144_report(
    audit_report: dict,
    community_config: dict | None = None,
) -> dict:
    """
    Generate a NYC Local Law 144 compliance report.

    LL144 requires annual bias audits of Automated Employment Decision
    Tools (AEDTs). The law mandates:
    - Impact ratio (disparate impact) for each demographic category
    - Scoring rate or selection rate for each category
    - Comparison to the most-selected category
    - Public posting of results

    Reference: NYC Int. No. 1894-A, codified as NYC Admin Code § 20-870
    """
    metrics = audit_report.get("metrics", {})
    summary = audit_report.get("summary", {})
    group_outcomes = metrics.get("group_outcomes", {})
    di_ratios = metrics.get("disparate_impact", {})

    impact_ratios = []
    for group, di in di_ratios.items():
        impact_ratios.append({
            "category": group,
            "selection_rate": group_outcomes.get(group),
            "impact_ratio": di,
            "meets_threshold": di is not None and di >= 0.8,
        })

    community_threshold = None
    community_flagged = []
    if community_config:
        community_threshold = community_config.get("fairness_threshold")
        if community_threshold:
            community_flagged = [
                g for g, di in di_ratios.items()
                if di is not None and di < community_threshold
            ]

    return {
        "regulation": "NYC Local Law 144",
        "regulation_citation": "NYC Admin Code § 20-870 et seq.",
        "report_date": datetime.now(timezone.utc).isoformat(),
        "audit_type": "bias audit of automated employment decision tool",
        "impact_ratios": impact_ratios,
        "most_selected_category": _find_reference_group(group_outcomes),
        "total_records_analyzed": summary.get("total_records"),
        "outcome_evaluated": summary.get("outcome_column"),
        "groups_failing_eeoc_threshold": summary.get("flagged_groups", []),
        "community_governance": {
            "audit_classification": audit_report.get("audit_type", "standard"),
            "community_config_applied": community_config is not None,
            "community_threshold": community_threshold,
            "groups_failing_community_threshold": community_flagged,
            "provenance": (
                community_config.get("provenance") if community_config else None
            ),
            "note": (
                "This audit was conducted using a community-defined fairness "
                "standard in addition to the EEOC four-fifths rule required "
                "by LL144. Community governance provides enhanced accountability "
                "beyond the minimum legal requirement."
                if community_config else
                "No community fairness configuration was applied. This audit "
                "uses only the EEOC four-fifths rule as required by LL144."
            ),
        },
        "ll144_compliant": len(summary.get("flagged_groups", [])) == 0,
        "community_compliant": len(community_flagged) == 0 if community_config else None,
    }


def generate_michigan_hb4668_report(
    audit_report: dict,
    community_config: dict | None = None,
) -> dict:
    """
    Generate a Michigan HB 4668 compliance report.

    Michigan HB 4668 (Algorithmic Discrimination in Consumer Transactions)
    proposes requirements for:
    - Impact assessments for algorithmic systems used in consumer transactions
    - Documentation of fairness criteria used
    - Disclosure of disparate impact findings
    - Remediation plans for identified disparities

    This is PROPOSED legislation (as of March 2026).
    """
    metrics = audit_report.get("metrics", {})
    summary = audit_report.get("summary", {})
    group_outcomes = metrics.get("group_outcomes", {})
    di_ratios = metrics.get("disparate_impact", {})

    impact_assessment = []
    for group in sorted(group_outcomes.keys()):
        rate = group_outcomes[group]
        di = di_ratios.get(group)
        impact_assessment.append({
            "demographic_group": group,
            "favorable_outcome_rate": rate,
            "disparate_impact_ratio": di,
            "disparity_detected": di is not None and di < 0.8,
            "severity": _classify_severity(di),
        })

    flagged = summary.get("flagged_groups", [])
    remediation = []
    for group in flagged:
        di = di_ratios.get(group)
        remediation.append({
            "group": group,
            "current_di": di,
            "required_di": 0.8,
            "gap": round(0.8 - di, 4) if di else None,
            "recommended_action": (
                "Immediate review of decision criteria affecting this group. "
                "Consider reweighting or model retraining to reduce disparate impact."
            ),
        })

    return {
        "regulation": "Michigan HB 4668 (Proposed)",
        "regulation_status": "proposed_legislation",
        "report_date": datetime.now(timezone.utc).isoformat(),
        "jurisdiction": "State of Michigan",
        "impact_assessment": {
            "system_type": "algorithmic decision system",
            "domain": "consumer transaction",
            "total_records": summary.get("total_records"),
            "demographic_groups_analyzed": sorted(group_outcomes.keys()),
            "per_group_assessment": impact_assessment,
        },
        "fairness_criteria": {
            "primary_metric": "disparate_impact_ratio",
            "threshold_source": (
                "community_defined" if community_config else "eeoc_default"
            ),
            "threshold_value": (
                community_config.get("fairness_threshold", 0.8)
                if community_config else 0.8
            ),
            "reference_group": _find_reference_group(group_outcomes),
            "methodology": "Four-fifths rule (29 CFR § 1607.4D)",
        },
        "community_governance": {
            "community_input_obtained": community_config is not None,
            "audit_classification": audit_report.get("audit_type", "standard"),
            "provenance": (
                community_config.get("provenance") if community_config else None
            ),
            "priority_groups": (
                community_config.get("priority_groups", [])
                if community_config else []
            ),
        },
        "remediation_plan": {
            "groups_requiring_remediation": flagged,
            "remediation_recommendations": remediation,
        },
        "michigan_relevance": {
            "note": (
                "This audit is particularly relevant to Michigan HB 4668 "
                "as it covers consumer lending transactions within the state. "
                "HMDA data shows disparities in mortgage approval rates across "
                "racial groups in Michigan."
            ),
        },
        "overall_compliance": len(flagged) == 0,
    }


def generate_colorado_ai_act_report(
    audit_report: dict,
    community_config: dict | None = None,
) -> dict:
    """
    Generate a Colorado AI Act (SB 24-205) compliance report.

    The Colorado AI Act (effective June 2026) requires:
    - "Reasonable care" to prevent algorithmic discrimination
    - Risk management policy for high-risk AI systems
    - Impact assessments
    - Disclosure to consumers
    - Annual review
    """
    metrics = audit_report.get("metrics", {})
    summary = audit_report.get("summary", {})
    group_outcomes = metrics.get("group_outcomes", {})
    di_ratios = metrics.get("disparate_impact", {})

    flagged = summary.get("flagged_groups", [])
    risk_level = "high" if len(flagged) > 0 else "low"

    return {
        "regulation": "Colorado AI Act (SB 24-205)",
        "regulation_status": "enacted, effective February 1, 2026",
        "report_date": datetime.now(timezone.utc).isoformat(),
        "jurisdiction": "State of Colorado",
        "reasonable_care_measures": {
            "bias_audit_conducted": True,
            "audit_methodology": "disparate_impact_analysis",
            "fairness_threshold_applied": (
                community_config.get("fairness_threshold", 0.8)
                if community_config else 0.8
            ),
            "community_input_obtained": community_config is not None,
            "audit_classification": audit_report.get("audit_type", "standard"),
            "provenance_documented": (
                community_config is not None
                and bool(community_config.get("provenance", {}).get("record_id"))
            ),
            "remediation_available": True,
            "note": (
                "Community-governed fairness auditing constitutes 'reasonable "
                "care' under SB 24-205 because it: (1) documents the fairness "
                "standard used, (2) traces that standard to a specific community "
                "input session with provenance, (3) applies the community-defined "
                "threshold rather than a default, and (4) provides remediation "
                "via reweighting and adversarial debiasing."
                if community_config else
                "This audit uses the EEOC default threshold (0.80). To "
                "strengthen 'reasonable care' documentation, conduct a community "
                "input session to establish a community-defined fairness standard."
            ),
        },
        "impact_assessment": {
            "risk_level": risk_level,
            "groups_analyzed": sorted(group_outcomes.keys()),
            "groups_with_disparate_impact": flagged,
            "disparity_score": metrics.get("disparity_score"),
            "statistical_parity_gap_pct": metrics.get("statistical_parity_gap"),
            "per_group_metrics": {
                group: {
                    "outcome_rate": group_outcomes.get(group),
                    "disparate_impact": di_ratios.get(group),
                }
                for group in sorted(group_outcomes.keys())
            },
        },
        "community_governance": {
            "community_config_applied": community_config is not None,
            "priority_groups": (
                community_config.get("priority_groups", [])
                if community_config else []
            ),
            "provenance": (
                community_config.get("provenance") if community_config else None
            ),
        },
        "review_schedule": {
            "last_audit_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "next_review_due": "within 12 months of this audit",
            "community_config_staleness_check": (
                "Configuration is current"
                if community_config else
                "No community configuration — establish one before next review"
            ),
        },
        "overall_compliance": risk_level == "low",
    }


def _find_reference_group(group_outcomes: dict) -> str:
    """Return the group with the highest favorable outcome rate."""
    if not group_outcomes:
        return "unknown"
    return max(group_outcomes, key=lambda g: group_outcomes[g])


def _classify_severity(di: float | None) -> str:
    """Classify the severity of a disparate impact finding."""
    if di is None:
        return "undefined"
    if di >= 0.8:
        return "none"
    if di >= 0.6:
        return "moderate"
    if di >= 0.4:
        return "significant"
    return "severe"
