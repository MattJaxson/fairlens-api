"""
Q2Q Translation Matrix — Qualitative-to-Quantitative mapping.

Translates bounded community survey inputs (Likert 1–10) into Fairlearn
constraint hyperparameters (ε for DemographicParity / EqualizedOdds).

Scaling rationale
-----------------
The core mapping from a 1–10 community strictness rating to an epsilon
boundary uses the **logistic CDF** (standard sigmoid):

    ε = ε_max / (1 + exp(k · (r - r₀)))

where:
    r   = community strictness rating (1–10)
    r₀  = midpoint of the Likert scale = 5.5
    k   = steepness parameter derived from the constraint that ε(1) ≈ ε_max
          and ε(10) ≈ ε_min.  Solved: k = ln(ε_max/ε_min - 1) / (r₀ - 1)
    ε_max = maximum tolerable disparity (lenient end, default 0.20)
    ε_min = minimum practical epsilon (strict end, default 0.005)

The logistic CDF is the standard choice for mapping ordinal scales to
continuous bounded parameters because it:
    1. Guarantees monotonic decrease (stricter → smaller ε),
    2. Has smooth, symmetric inflection at the midpoint,
    3. Saturates naturally at both extremes (no clipping artefacts),
    4. Is widely used in psychometric IRT models for Likert data.

Aggregation uses the **median** of participant responses (robust to
outliers in small-n community sessions) with the **interquartile range**
reported as a consensus-width metric.

References:
    - Agarwal et al. 2018, "A Reductions Approach to Fair Classification"
      (defines ε-relaxed constraint framework used by Fairlearn)
    - Embretson & Reise 2000, "Item Response Theory for Psychologists"
      (logistic CDF as link function for ordinal survey data)
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Scaling constants ──────────────────────────────────────────────────────
# These are NOT magic numbers — they are the documented boundary conditions
# of the logistic mapping, grounded in Fairlearn's constraint semantics.

LIKERT_MIN: int = 1       # least strict
LIKERT_MAX: int = 10      # most strict
LIKERT_MIDPOINT: float = (LIKERT_MIN + LIKERT_MAX) / 2  # 5.5

EPSILON_MAX: float = 0.20   # ε at rating = 1: ~20% disparity tolerated
EPSILON_MIN: float = 0.005  # ε at rating = 10: near-zero tolerance

# Steepness parameter solved from boundary conditions:
#   ε(1)  = ε_max / (1 + exp(k·(1 - 5.5))) ≈ ε_max   → numerator ≈ ε_max
#   ε(10) = ε_max / (1 + exp(k·(10 - 5.5))) ≈ ε_min
#   → 1 + exp(k · 4.5) ≈ ε_max / ε_min
#   → k = ln(ε_max/ε_min - 1) / (LIKERT_MIDPOINT - LIKERT_MIN)
STEEPNESS: float = math.log(EPSILON_MAX / EPSILON_MIN - 1) / (LIKERT_MIDPOINT - LIKERT_MIN)


# ── Core data structures ──────────────────────────────────────────────────

@dataclass(frozen=True)
class SurveyResponse:
    """A single participant's bounded survey input."""
    strictness_rating: int            # 1 (lenient) – 10 (strictest)
    preferred_constraint: str = "demographic_parity"  # or "equalized_odds"

    def __post_init__(self) -> None:
        if not (LIKERT_MIN <= self.strictness_rating <= LIKERT_MAX):
            raise ValueError(
                f"strictness_rating must be {LIKERT_MIN}–{LIKERT_MAX}, "
                f"got {self.strictness_rating}"
            )
        if self.preferred_constraint not in ("demographic_parity", "equalized_odds"):
            raise ValueError(
                f"preferred_constraint must be 'demographic_parity' or "
                f"'equalized_odds', got '{self.preferred_constraint}'"
            )


@dataclass(frozen=True)
class AggregatedSurvey:
    """Robust aggregate of a community session's survey responses."""
    median_strictness: float
    mean_strictness: float
    iqr: float                        # interquartile range — consensus width
    n_participants: int
    constraint_majority: str          # whichever constraint got more votes
    constraint_split: dict[str, int]  # {"demographic_parity": 12, "equalized_odds": 3}
    all_ratings: list[int]


@dataclass(frozen=True)
class Q2QOutput:
    """
    Final translation: the quantitative parameters Fairlearn needs.

    This object is the formal output of the Q2Q Translation Matrix and
    can be serialised directly into the CommunityConfig provenance record.
    """
    epsilon: float
    constraint_type: str              # "demographic_parity" | "equalized_odds"
    survey_aggregate: AggregatedSurvey
    scaling_parameters: dict = field(default_factory=dict)


# ── Aggregation ────────────────────────────────────────────────────────────

def aggregate_survey(responses: list[SurveyResponse]) -> AggregatedSurvey:
    """
    Aggregate bounded survey inputs using robust statistics.

    Uses **median** (not mean) as the central tendency because:
      - Community sessions are small-n (10–30 people)
      - A single outlier (rating 1 among 9s) should not drag the aggregate
      - Median is the MLE of the Laplace distribution, which better models
        heavy-tailed ordinal data than the Gaussian assumption of the mean

    The IQR is reported as a consensus-width metric: a narrow IQR means
    strong agreement, a wide IQR flags sessions that may need facilitated
    re-discussion.
    """
    if not responses:
        raise ValueError("Cannot aggregate zero survey responses.")

    ratings = np.array([r.strictness_rating for r in responses], dtype=np.float64)

    # Constraint preference: simple majority
    constraint_counts: dict[str, int] = {}
    for r in responses:
        constraint_counts[r.preferred_constraint] = (
            constraint_counts.get(r.preferred_constraint, 0) + 1
        )
    constraint_majority = max(constraint_counts, key=constraint_counts.get)  # type: ignore[arg-type]

    q1 = float(np.percentile(ratings, 25))
    q3 = float(np.percentile(ratings, 75))

    return AggregatedSurvey(
        median_strictness=float(np.median(ratings)),
        mean_strictness=round(float(np.mean(ratings)), 4),
        iqr=round(q3 - q1, 4),
        n_participants=len(responses),
        constraint_majority=constraint_majority,
        constraint_split=constraint_counts,
        all_ratings=sorted(int(r) for r in ratings),
    )


# ── Epsilon mapping ────────────────────────────────────────────────────────

def rating_to_epsilon(
    rating: float,
    *,
    eps_max: float = EPSILON_MAX,
    eps_min: float = EPSILON_MIN,
) -> float:
    """
    Map a strictness rating to a Fairlearn ε boundary via logistic CDF.

    The logistic function guarantees:
      - Monotonic decrease: higher rating → smaller ε
      - Smooth saturation: no hard clipping at boundaries
      - Symmetric inflection at the Likert midpoint (5.5)

    Parameters
    ----------
    rating : float
        Aggregated community strictness (typically the median, 1.0–10.0).
    eps_max : float
        Maximum epsilon (lenient end). Default 0.20.
    eps_min : float
        Minimum epsilon (strict end). Default 0.005.

    Returns
    -------
    float
        The ε boundary for Fairlearn's constraint, in [eps_min, eps_max].
    """
    if not (LIKERT_MIN <= rating <= LIKERT_MAX):
        raise ValueError(
            f"Rating must be {LIKERT_MIN}–{LIKERT_MAX}, got {rating}"
        )

    k = math.log(eps_max / eps_min - 1) / (LIKERT_MIDPOINT - LIKERT_MIN)
    eps = eps_max / (1.0 + math.exp(k * (rating - LIKERT_MIDPOINT)))

    # Clamp to documented bounds (guards against float drift)
    return max(eps_min, min(eps_max, eps))


# ── Fairlearn constraint builder ──────────────────────────────────────────

def build_fairlearn_constraint(
    constraint_type: str,
    epsilon: float,
) -> object:
    """
    Instantiate a Fairlearn constraint object with the community-derived ε.

    Parameters
    ----------
    constraint_type : str
        "demographic_parity" or "equalized_odds"
    epsilon : float
        The ε bound from ``rating_to_epsilon()``.

    Returns
    -------
    fairlearn.reductions.Moment
        Ready to pass to ``ExponentiatedGradient(constraints=...)``.

    Notes
    -----
    Fairlearn's ``DemographicParity(difference_bound=ε)`` constrains:
        |P(ŷ=1|A=a) − P(ŷ=1|A=b)| ≤ ε   ∀ groups a,b

    ``EqualizedOdds(difference_bound=ε)`` constrains:
        |P(ŷ=1|A=a,Y=y) − P(ŷ=1|A=b,Y=y)| ≤ ε   ∀ groups a,b; y∈{0,1}
    """
    try:
        from fairlearn.reductions import DemographicParity, EqualizedOdds
    except ImportError as exc:
        raise ImportError(
            "fairlearn is required for Q2Q constraint generation."
        ) from exc

    if constraint_type == "demographic_parity":
        return DemographicParity(difference_bound=epsilon)
    elif constraint_type == "equalized_odds":
        return EqualizedOdds(difference_bound=epsilon)
    else:
        raise ValueError(
            f"Unsupported constraint_type: '{constraint_type}'. "
            f"Must be 'demographic_parity' or 'equalized_odds'."
        )


# ── Full pipeline ──────────────────────────────────────────────────────────

def translate(
    responses: list[SurveyResponse],
    *,
    eps_max: float = EPSILON_MAX,
    eps_min: float = EPSILON_MIN,
    constraint_override: Optional[str] = None,
) -> Q2QOutput:
    """
    Full Q2Q pipeline: survey responses → Fairlearn hyperparameters.

    1. Aggregate responses (median, IQR, constraint majority vote).
    2. Map median strictness → ε via logistic CDF.
    3. Package as Q2QOutput with full audit trail.

    Parameters
    ----------
    responses : list[SurveyResponse]
        Raw bounded survey inputs from community session participants.
    eps_max : float
        Lenient-end epsilon. Default 0.20.
    eps_min : float
        Strict-end epsilon. Default 0.005.
    constraint_override : str, optional
        Force a specific constraint type instead of majority vote.
    """
    agg = aggregate_survey(responses)
    epsilon = rating_to_epsilon(agg.median_strictness, eps_max=eps_max, eps_min=eps_min)
    constraint_type = constraint_override or agg.constraint_majority

    # Recompute k for the audit trail
    k = math.log(eps_max / eps_min - 1) / (LIKERT_MIDPOINT - LIKERT_MIN)

    output = Q2QOutput(
        epsilon=round(epsilon, 6),
        constraint_type=constraint_type,
        survey_aggregate=agg,
        scaling_parameters={
            "function": "logistic_cdf",
            "formula": "ε = ε_max / (1 + exp(k · (r - r₀)))",
            "eps_max": eps_max,
            "eps_min": eps_min,
            "k": round(k, 6),
            "r0": LIKERT_MIDPOINT,
            "input_rating": agg.median_strictness,
            "output_epsilon": round(epsilon, 6),
        },
    )

    logger.info(
        "Q2Q translation: %d participants, median=%.1f, ε=%.4f, constraint=%s",
        agg.n_participants, agg.median_strictness, epsilon, constraint_type,
    )

    return output
