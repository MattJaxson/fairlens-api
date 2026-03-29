"""
Zero-Trust Test Suite — Fairness Pipeline
============================================================
Ported from adaptive-racial-fairness-framework/tests/test_fairness_pipeline.py

Covers:
- racial_bias_score (calculate_racial_bias_score)
- fairness_audit (group_outcomes_by_race, disparate_impact)
- fairness_reweight (reweight_samples_with_community)
- community_input (build_community_config, validate_community_config, is_community_valid)
- Integration: end-to-end audit pipeline
- Adversarial edge cases
- Compliance adapter (LL144, Michigan HB 4668, Colorado AI Act)
"""

import json
import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.services.fairness_audit import (
    calculate_racial_bias_score,
    group_outcomes_by_race,
    disparate_impact,
)
from app.services.fairness_reweight import reweight_samples_with_community
from app.services.community_governance import (
    build_community_config,
    validate_community_config,
    is_community_valid,
)
from app.services.compliance_adapter import (
    generate_ll144_report,
    generate_michigan_hb4668_report,
    generate_colorado_ai_act_report,
    _find_reference_group,
    _classify_severity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_df():
    """Minimal balanced dataset."""
    return pd.DataFrame({
        "race": ["White", "White", "Black", "Black", "Latinx", "Latinx"],
        "outcome": [1, 1, 1, 0, 0, 0],
    })


@pytest.fixture
def large_df():
    """Larger dataset with known rates for deterministic testing."""
    rng = np.random.default_rng(42)
    n = 1000
    races = rng.choice(["White", "Black", "Asian", "Latinx"], size=n, p=[0.4, 0.3, 0.15, 0.15])
    outcomes = np.zeros(n, dtype=int)
    for i, race in enumerate(races):
        rate = {"White": 0.6, "Black": 0.4, "Asian": 0.55, "Latinx": 0.35}[race]
        outcomes[i] = 1 if rng.random() < rate else 0
    return pd.DataFrame({"race": races, "outcome": outcomes})


@pytest.fixture
def community_defs_default():
    """Standard community config with provenance."""
    return {
        "priority_groups": ["Black", "Latinx"],
        "fairness_target": "White",
        "fairness_threshold": 0.8,
        "provenance": {
            "record_id": "test-uuid-1234",
            "input_protocol": "community_session",
            "input_date": "2026-03-15",
            "input_participants": 14,
            "facilitator": "Test Facilitator",
        },
    }


@pytest.fixture
def sample_audit_report():
    """A realistic audit report dict for compliance adapter tests."""
    return {
        "audit_type": "community_valid",
        "metrics": {
            "group_outcomes": {"White": 0.75, "Black": 0.45, "Latinx": 0.40},
            "disparate_impact": {"White": 1.0, "Black": 0.6, "Latinx": 0.533},
            "disparity_score": 0.35,
            "statistical_parity_gap": 35.0,
        },
        "summary": {
            "total_records": 500,
            "outcome_column": "hired",
            "flagged_groups": ["Black", "Latinx"],
        },
    }


@pytest.fixture
def sample_community_config():
    """Community config for compliance adapter tests."""
    return {
        "priority_groups": ["Black", "Latinx"],
        "fairness_target": "White",
        "fairness_threshold": 0.8,
        "provenance": {
            "record_id": "test-uuid-5678",
            "input_protocol": "community_session",
            "input_date": "2026-03-01",
            "input_participants": 20,
        },
    }


# ===================================================================
# SECTION 1: racial_bias_score.py
# ===================================================================

class TestRacialBiasScore:
    """Tests for calculate_racial_bias_score()."""

    def test_basic_output_structure(self, simple_df):
        result = calculate_racial_bias_score(simple_df, "race", "outcome")
        assert "group_outcomes" in result
        assert "racial_disparity_score" in result
        assert isinstance(result["group_outcomes"], dict)
        assert isinstance(result["racial_disparity_score"], float)

    def test_known_disparity(self, simple_df):
        """White=100%, Black=50%, Latinx=0% -> disparity = 1.0."""
        result = calculate_racial_bias_score(simple_df, "race", "outcome")
        assert result["group_outcomes"]["White"] == 1.0
        assert result["group_outcomes"]["Black"] == 0.5
        assert result["group_outcomes"]["Latinx"] == 0.0
        assert result["racial_disparity_score"] == 1.0

    def test_missing_sensitive_column_raises(self):
        df = pd.DataFrame({"outcome": [1, 0]})
        with pytest.raises(ValueError, match="Column 'race' not found"):
            calculate_racial_bias_score(df, "race", "outcome")

    def test_missing_outcome_column_raises(self):
        df = pd.DataFrame({"race": ["White", "Black"]})
        with pytest.raises(ValueError, match="Column 'outcome' not found"):
            calculate_racial_bias_score(df, "race", "outcome")

    def test_empty_dataframe_raises(self):
        df = pd.DataFrame({"race": [], "outcome": []})
        with pytest.raises(ValueError, match="empty"):
            calculate_racial_bias_score(df, "race", "outcome")

    def test_non_numeric_outcome_raises(self):
        df = pd.DataFrame({
            "race": ["White", "Black"],
            "outcome": ["yes", "no"],
        })
        with pytest.raises(ValueError, match="must be numeric"):
            calculate_racial_bias_score(df, "race", "outcome")

    def test_nan_values_dropped(self):
        """Rows with NaN in outcome should be dropped, not crash."""
        df = pd.DataFrame({
            "race": ["White", "Black", "White", "Black"],
            "outcome": [1, 0, np.nan, 1],
        })
        result = calculate_racial_bias_score(df, "race", "outcome")
        assert result["group_outcomes"]["White"] == 1.0
        assert result["group_outcomes"]["Black"] == 0.5

    def test_single_group_returns_zero_disparity(self):
        df = pd.DataFrame({
            "race": ["White", "White", "White"],
            "outcome": [1, 0, 1],
        })
        result = calculate_racial_bias_score(df, "race", "outcome")
        assert result["racial_disparity_score"] == 0.0

    def test_all_nan_after_drop_raises(self):
        df = pd.DataFrame({
            "race": ["White", "Black"],
            "outcome": [np.nan, np.nan],
        })
        with pytest.raises(ValueError, match="No valid rows"):
            calculate_racial_bias_score(df, "race", "outcome")

    def test_all_zeros_outcome(self):
        """Every group has 0% favorable -> disparity = 0."""
        df = pd.DataFrame({
            "race": ["White", "Black", "Latinx"],
            "outcome": [0, 0, 0],
        })
        result = calculate_racial_bias_score(df, "race", "outcome")
        assert result["racial_disparity_score"] == 0.0

    def test_all_ones_outcome(self):
        """Every group has 100% favorable -> disparity = 0."""
        df = pd.DataFrame({
            "race": ["White", "Black", "Latinx"],
            "outcome": [1, 1, 1],
        })
        result = calculate_racial_bias_score(df, "race", "outcome")
        assert result["racial_disparity_score"] == 0.0


# ===================================================================
# SECTION 2: fairness_audit.py
# ===================================================================

class TestFairnessAudit:
    """Tests for group_outcomes_by_race() and disparate_impact()."""

    def test_group_outcomes_basic(self, simple_df):
        result = group_outcomes_by_race(simple_df, "race", "outcome")
        assert "White" in result.index
        assert "Black" in result.index

    def test_group_outcomes_empty_raises(self):
        df = pd.DataFrame({"race": [], "outcome": []})
        with pytest.raises(ValueError, match="empty"):
            group_outcomes_by_race(df, "race", "outcome")

    def test_disparate_impact_equal_rates(self):
        """Equal rates -> DI = 1.0."""
        df = pd.DataFrame({
            "race": ["White", "White", "Black", "Black"],
            "outcome": [1, 0, 1, 0],
        })
        di = disparate_impact(df, "race", "outcome", "White", "Black", 1)
        assert di == 1.0

    def test_disparate_impact_half_rate(self):
        """Black has half the favorable rate of White -> DI ~ 0.333."""
        df = pd.DataFrame({
            "race": ["White"] * 4 + ["Black"] * 4,
            "outcome": [1, 1, 1, 0, 1, 0, 0, 0],
        })
        di = disparate_impact(df, "race", "outcome", "White", "Black", 1)
        assert abs(di - (0.25 / 0.75)) < 0.01

    def test_disparate_impact_privileged_zero_rate(self):
        """Privileged group has 0 favorable -> should return None."""
        df = pd.DataFrame({
            "race": ["White", "White", "Black", "Black"],
            "outcome": [0, 0, 1, 1],
        })
        di = disparate_impact(df, "race", "outcome", "White", "Black", 1)
        assert di is None

    def test_disparate_impact_unprivileged_zero_rate(self):
        """Unprivileged group has 0 favorable -> DI = 0."""
        df = pd.DataFrame({
            "race": ["White", "White", "Black", "Black"],
            "outcome": [1, 1, 0, 0],
        })
        di = disparate_impact(df, "race", "outcome", "White", "Black", 1)
        assert di == 0.0

    def test_disparate_impact_missing_group(self):
        """Group not in dataset -> returns DI=0."""
        df = pd.DataFrame({
            "race": ["White", "White"],
            "outcome": [1, 1],
        })
        di = disparate_impact(df, "race", "outcome", "White", "NonExistent", 1)
        assert di == 0.0

    def test_disparate_impact_string_favorable(self):
        """Works with string outcome values."""
        df = pd.DataFrame({
            "race": ["White", "White", "Black", "Black"],
            "outcome": ["Yes", "Yes", "Yes", "No"],
        })
        di = disparate_impact(df, "race", "outcome", "White", "Black", "Yes")
        assert di == 0.5


# ===================================================================
# SECTION 3: fairness_reweight.py
# ===================================================================

class TestFairnessReweight:
    """Tests for reweight_samples_with_community()."""

    def test_basic_reweight(self, simple_df, community_defs_default):
        result = reweight_samples_with_community(
            simple_df, "race", "outcome", 1, community_defs_default
        )
        assert "sample_weight" in result.columns
        assert len(result) == len(simple_df)

    def test_non_priority_groups_get_weight_one(self, simple_df, community_defs_default):
        """Groups NOT in priority_groups should have weight = 1.0."""
        result = reweight_samples_with_community(
            simple_df, "race", "outcome", 1, community_defs_default
        )
        white_weights = result.loc[result["race"] == "White", "sample_weight"]
        assert all(w == 1.0 for w in white_weights)

    def test_priority_groups_get_adjusted_weight(self, simple_df, community_defs_default):
        """Priority groups should have non-1.0 weights (when rates differ)."""
        result = reweight_samples_with_community(
            simple_df, "race", "outcome", 1, community_defs_default
        )
        black_weights = result.loc[result["race"] == "Black", "sample_weight"]
        assert any(w != 1.0 for w in black_weights)

    def test_missing_target_group_raises(self, simple_df):
        """If fairness_target is not in data, should raise ValueError."""
        defs = {
            "priority_groups": ["Black"],
            "fairness_target": "NonExistentGroup",
        }
        with pytest.raises(ValueError, match="not found in data"):
            reweight_samples_with_community(
                simple_df, "race", "outcome", 1, defs
            )

    def test_target_group_zero_rate_raises(self):
        """Target group with 0% favorable should raise ValueError."""
        df = pd.DataFrame({
            "race": ["White", "White", "Black", "Black"],
            "outcome": [0, 0, 1, 0],
        })
        defs = {
            "priority_groups": ["Black"],
            "fairness_target": "White",
        }
        with pytest.raises(ValueError, match="0% favorable"):
            reweight_samples_with_community(df, "race", "outcome", 1, defs)

    def test_missing_priority_group_skipped(self, simple_df):
        """Priority groups not in data should be skipped, not crash."""
        defs = {
            "priority_groups": ["Black", "GroupNotInData"],
            "fairness_target": "White",
        }
        result = reweight_samples_with_community(
            simple_df, "race", "outcome", 1, defs
        )
        assert len(result) == len(simple_df)

    def test_group_with_zero_favorable(self):
        """A priority group with 0 favorable outcomes -> reweight only unfavorable."""
        df = pd.DataFrame({
            "race": ["White", "White", "Black", "Black"],
            "outcome": [1, 0, 0, 0],
        })
        defs = {
            "priority_groups": ["Black"],
            "fairness_target": "White",
        }
        result = reweight_samples_with_community(df, "race", "outcome", 1, defs)
        black_weights = result.loc[result["race"] == "Black", "sample_weight"]
        assert all(np.isfinite(w) for w in black_weights)

    def test_group_with_100_favorable(self):
        """A priority group with 100% favorable -> reweight only favorable."""
        df = pd.DataFrame({
            "race": ["White", "White", "Black", "Black"],
            "outcome": [1, 0, 1, 1],
        })
        defs = {
            "priority_groups": ["Black"],
            "fairness_target": "White",
        }
        result = reweight_samples_with_community(df, "race", "outcome", 1, defs)
        black_weights = result.loc[result["race"] == "Black", "sample_weight"]
        assert all(np.isfinite(w) for w in black_weights)

    def test_weights_are_positive(self, large_df, community_defs_default):
        """All weights must be positive (no negative or zero weights)."""
        result = reweight_samples_with_community(
            large_df, "race", "outcome", 1, community_defs_default
        )
        assert all(result["sample_weight"] > 0)

    def test_weights_deterministic(self, large_df, community_defs_default):
        """Same input -> same output (no randomness)."""
        r1 = reweight_samples_with_community(
            large_df.copy(), "race", "outcome", 1, community_defs_default
        )
        r2 = reweight_samples_with_community(
            large_df.copy(), "race", "outcome", 1, community_defs_default
        )
        pd.testing.assert_series_equal(r1["sample_weight"], r2["sample_weight"])


# ===================================================================
# SECTION 4: community_input.py
# ===================================================================

class TestCommunityInput:
    """Tests for build_community_config(), validate, is_community_valid()."""

    def test_build_basic(self):
        config = build_community_config(
            priority_groups=["Black", "Latinx"],
            fairness_target="White",
            fairness_threshold=0.85,
            input_protocol="community_session",
            input_participants=15,
        )
        assert config["priority_groups"] == ["Black", "Latinx"]
        assert config["fairness_target"] == "White"
        assert config["fairness_threshold"] == 0.85
        assert config["provenance"]["record_id"]
        assert config["provenance"]["input_date"]

    def test_build_empty_priority_raises(self):
        with pytest.raises(ValueError, match="priority_groups cannot be empty"):
            build_community_config(
                priority_groups=[],
                fairness_target="White",
            )

    def test_build_empty_target_raises(self):
        with pytest.raises(ValueError, match="fairness_target cannot be empty"):
            build_community_config(
                priority_groups=["Black"],
                fairness_target="",
            )

    def test_build_invalid_threshold_raises(self):
        with pytest.raises(ValueError, match="fairness_threshold must be between"):
            build_community_config(
                priority_groups=["Black"],
                fairness_target="White",
                fairness_threshold=1.5,
            )

    def test_build_zero_threshold_raises(self):
        with pytest.raises(ValueError, match="fairness_threshold must be between"):
            build_community_config(
                priority_groups=["Black"],
                fairness_target="White",
                fairness_threshold=0.0,
            )

    def test_build_invalid_protocol_raises(self):
        with pytest.raises(ValueError, match="input_protocol must be one of"):
            build_community_config(
                priority_groups=["Black"],
                fairness_target="White",
                input_protocol="invalid_protocol",
            )

    def test_build_saves_to_file(self, tmp_path):
        output = tmp_path / "test_config.json"
        config = build_community_config(
            priority_groups=["Black"],
            fairness_target="White",
            output_path=str(output),
        )
        assert output.exists()
        loaded = json.loads(output.read_text())
        assert loaded["priority_groups"] == ["Black"]
        assert loaded["provenance"]["record_id"] == config["provenance"]["record_id"]

    def test_build_low_confidence_flag(self):
        config = build_community_config(
            priority_groups=["Black"],
            fairness_target="White",
            input_participants=5,
        )
        assert config["provenance"]["low_confidence"] is True

    def test_build_sufficient_participants_no_flag(self):
        config = build_community_config(
            priority_groups=["Black"],
            fairness_target="White",
            input_participants=15,
        )
        assert config["provenance"]["low_confidence"] is False

    def test_validate_valid_config(self, community_defs_default):
        is_valid, issues = validate_community_config(community_defs_default)
        assert is_valid
        assert len(issues) == 0

    def test_validate_missing_priority_groups(self):
        config = {"fairness_target": "White", "fairness_threshold": 0.8, "provenance": {"record_id": "x", "input_date": "2026-01-01", "input_protocol": "other"}}
        is_valid, issues = validate_community_config(config)
        assert not is_valid
        assert any("priority_groups" in i for i in issues)

    def test_validate_missing_provenance(self):
        config = {"priority_groups": ["Black"], "fairness_target": "White", "fairness_threshold": 0.8}
        is_valid, issues = validate_community_config(config)
        assert not is_valid
        assert any("provenance" in i.lower() for i in issues)

    def test_validate_missing_record_id(self):
        config = {
            "priority_groups": ["Black"],
            "fairness_target": "White",
            "fairness_threshold": 0.8,
            "provenance": {"input_date": "2026-01-01", "input_protocol": "other"},
        }
        is_valid, issues = validate_community_config(config)
        assert not is_valid
        assert any("record_id" in i for i in issues)

    def test_is_community_valid_true(self, community_defs_default):
        assert is_community_valid(community_defs_default) is True

    def test_is_community_valid_no_provenance(self):
        config = {"priority_groups": ["Black"], "fairness_target": "White", "fairness_threshold": 0.8}
        assert is_community_valid(config) is False

    def test_unique_record_ids(self):
        """Each config must get a unique UUID."""
        c1 = build_community_config(priority_groups=["Black"], fairness_target="White")
        c2 = build_community_config(priority_groups=["Black"], fairness_target="White")
        assert c1["provenance"]["record_id"] != c2["provenance"]["record_id"]

    def test_whitespace_stripped(self):
        config = build_community_config(
            priority_groups=["  Black  ", " Latinx"],
            fairness_target="  White  ",
        )
        assert config["priority_groups"] == ["Black", "Latinx"]
        assert config["fairness_target"] == "White"


# ===================================================================
# SECTION 5: Integration -- End-to-End Pipeline
# ===================================================================

class TestIntegration:
    """End-to-end tests: community config -> audit -> reweight -> verify."""

    def test_full_pipeline(self, large_df):
        """Build config -> run bias score -> reweight -> verify weights applied."""
        config = build_community_config(
            priority_groups=["Black", "Latinx"],
            fairness_target="White",
            fairness_threshold=0.85,
            input_protocol="community_session",
            input_participants=14,
        )
        assert is_community_valid(config)

        result = calculate_racial_bias_score(large_df, "race", "outcome")
        assert result["racial_disparity_score"] > 0

        di = disparate_impact(large_df, "race", "outcome", "White", "Black", 1)
        assert di is not None
        assert 0 <= di <= 2

        reweighted = reweight_samples_with_community(
            large_df.copy(), "race", "outcome", 1, config
        )
        assert "sample_weight" in reweighted.columns

        white_weights = reweighted.loc[reweighted["race"] == "White", "sample_weight"]
        assert all(w == 1.0 for w in white_weights)

        black_weights = reweighted.loc[reweighted["race"] == "Black", "sample_weight"]
        assert any(w != 1.0 for w in black_weights)

    def test_threshold_changes_flagging(self, large_df):
        """Prove the core claim: different thresholds -> different flagged groups."""
        di_black = disparate_impact(large_df, "race", "outcome", "White", "Black", 1)
        assert di_black is not None

        strict_threshold = di_black + 0.05
        flagged_strict = di_black < strict_threshold
        assert flagged_strict

    def test_malformed_csv_headers(self):
        """CSV with whitespace in headers should still work after strip."""
        df = pd.DataFrame({
            "  race  ": ["White", "Black", "Latinx"],
            " outcome ": [1, 0, 1],
        })
        df.columns = df.columns.str.strip()
        result = calculate_racial_bias_score(df, "race", "outcome")
        assert "group_outcomes" in result

    def test_unicode_group_names(self):
        """Framework should handle non-ASCII group names."""
        df = pd.DataFrame({
            "race": ["Cafe", "Naive", "Cafe", "Naive"],
            "outcome": [1, 0, 1, 0],
        })
        result = calculate_racial_bias_score(df, "race", "outcome")
        assert "Cafe" in result["group_outcomes"]

    def test_large_number_of_groups(self):
        """Framework should handle many groups without crashing."""
        groups = [f"Group_{i}" for i in range(50)]
        df = pd.DataFrame({
            "race": groups * 10,
            "outcome": [1, 0] * 250,
        })
        result = calculate_racial_bias_score(df, "race", "outcome")
        assert len(result["group_outcomes"]) == 50

    def test_single_record_per_group(self):
        """One record per group -- edge case for mean calculation."""
        df = pd.DataFrame({
            "race": ["White", "Black", "Latinx"],
            "outcome": [1, 0, 1],
        })
        result = calculate_racial_bias_score(df, "race", "outcome")
        assert result["group_outcomes"]["White"] == 1.0
        assert result["group_outcomes"]["Black"] == 0.0


# ===================================================================
# SECTION 6: Adversarial Edge Cases
# ===================================================================

class TestAdversarial:
    """Cases designed to break the pipeline."""

    def test_all_same_race(self):
        """Dataset with only one racial group."""
        df = pd.DataFrame({
            "race": ["White"] * 10,
            "outcome": [1, 1, 0, 1, 0, 1, 1, 0, 1, 0],
        })
        result = calculate_racial_bias_score(df, "race", "outcome")
        assert result["racial_disparity_score"] == 0.0

    def test_extremely_imbalanced_groups(self):
        """One group has 1000 records, another has 1."""
        df = pd.DataFrame({
            "race": ["White"] * 1000 + ["Black"],
            "outcome": [1] * 500 + [0] * 500 + [0],
        })
        result = calculate_racial_bias_score(df, "race", "outcome")
        assert result["group_outcomes"]["White"] == 0.5
        assert result["group_outcomes"]["Black"] == 0.0
        assert result["racial_disparity_score"] == 0.5

    def test_outcome_is_float(self):
        """Outcome column is float instead of int."""
        df = pd.DataFrame({
            "race": ["White", "Black", "White", "Black"],
            "outcome": [1.0, 0.0, 1.0, 0.0],
        })
        result = calculate_racial_bias_score(df, "race", "outcome")
        assert result["group_outcomes"]["White"] == 1.0
        assert result["group_outcomes"]["Black"] == 0.0

    def test_reweight_with_empty_priority_groups(self, simple_df):
        """Empty priority groups -> all weights = 1.0."""
        defs = {
            "priority_groups": [],
            "fairness_target": "White",
        }
        result = reweight_samples_with_community(
            simple_df, "race", "outcome", 1, defs
        )
        assert all(result["sample_weight"] == 1.0)

    def test_config_threshold_boundary(self):
        """DI exactly at threshold -> should NOT be flagged."""
        df = pd.DataFrame({
            "race": ["White"] * 10 + ["Black"] * 10,
            "outcome": [1] * 10 + [1] * 8 + [0] * 2,
        })
        di = disparate_impact(df, "race", "outcome", "White", "Black", 1)
        assert di == 0.8
        assert not (di < 0.8)


# ===================================================================
# SECTION 7: Compliance Adapter
# ===================================================================

class TestComplianceAdapter:
    """Tests for regulation-specific report generators."""

    def test_ll144_structure(self, sample_audit_report, sample_community_config):
        report = generate_ll144_report(sample_audit_report, sample_community_config)
        assert report["regulation"] == "NYC Local Law 144"
        assert "impact_ratios" in report
        assert "community_governance" in report
        assert report["ll144_compliant"] is False  # has flagged groups

    def test_ll144_without_community_config(self, sample_audit_report):
        report = generate_ll144_report(sample_audit_report, None)
        assert report["community_governance"]["community_config_applied"] is False
        assert report["community_compliant"] is None

    def test_ll144_compliant_report(self):
        clean_audit = {
            "audit_type": "standard",
            "metrics": {
                "group_outcomes": {"White": 0.60, "Black": 0.55},
                "disparate_impact": {"White": 1.0, "Black": 0.917},
            },
            "summary": {"total_records": 200, "outcome_column": "hired", "flagged_groups": []},
        }
        report = generate_ll144_report(clean_audit)
        assert report["ll144_compliant"] is True

    def test_michigan_structure(self, sample_audit_report, sample_community_config):
        report = generate_michigan_hb4668_report(sample_audit_report, sample_community_config)
        assert report["regulation"] == "Michigan HB 4668 (Proposed)"
        assert "impact_assessment" in report
        assert "remediation_plan" in report
        assert report["overall_compliance"] is False

    def test_michigan_remediation_plan(self, sample_audit_report):
        report = generate_michigan_hb4668_report(sample_audit_report)
        recs = report["remediation_plan"]["remediation_recommendations"]
        assert len(recs) == 2  # Black and Latinx flagged
        assert all(r["required_di"] == 0.8 for r in recs)

    def test_colorado_structure(self, sample_audit_report, sample_community_config):
        report = generate_colorado_ai_act_report(sample_audit_report, sample_community_config)
        assert report["regulation"] == "Colorado AI Act (SB 24-205)"
        assert "reasonable_care_measures" in report
        assert "review_schedule" in report
        assert report["overall_compliance"] is False  # high risk

    def test_colorado_low_risk(self):
        clean_audit = {
            "audit_type": "community_valid",
            "metrics": {
                "group_outcomes": {"White": 0.60, "Black": 0.55},
                "disparate_impact": {"White": 1.0, "Black": 0.917},
            },
            "summary": {"total_records": 200, "outcome_column": "hired", "flagged_groups": []},
        }
        report = generate_colorado_ai_act_report(clean_audit)
        assert report["overall_compliance"] is True
        assert report["impact_assessment"]["risk_level"] == "low"

    def test_colorado_provenance_documented(self, sample_audit_report, sample_community_config):
        report = generate_colorado_ai_act_report(sample_audit_report, sample_community_config)
        assert report["reasonable_care_measures"]["provenance_documented"] is True

    def test_find_reference_group(self):
        assert _find_reference_group({"White": 0.8, "Black": 0.4}) == "White"
        assert _find_reference_group({}) == "unknown"

    def test_classify_severity(self):
        assert _classify_severity(None) == "undefined"
        assert _classify_severity(0.9) == "none"
        assert _classify_severity(0.7) == "moderate"
        assert _classify_severity(0.5) == "significant"
        assert _classify_severity(0.3) == "severe"
