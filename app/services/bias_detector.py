"""
Core bias detection engine for FairLens.

Uses deterministic pattern matching and scoring -- no external AI calls needed.
Each category has curated word lists, phrase patterns, and contextual rules.
Scoring is on a 0-100 scale where 100 means no bias detected.
"""

import re
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field

from app.models.schemas import BiasScore, FairnessReport, FlaggedPhrase


@dataclass
class BiasPattern:
    pattern: str  # regex pattern
    severity: str  # low, medium, high
    category: str
    suggestion: str
    description: str = ""


# ── Gender Bias Patterns ────────────────────────────────────────────────────

GENDER_PATTERNS: list[BiasPattern] = [
    # Gendered job titles
    BiasPattern(r"\bchairman\b", "medium", "gender", "chairperson or chair"),
    BiasPattern(r"\bchairmen\b", "medium", "gender", "chairpersons or chairs"),
    BiasPattern(r"\bpoliceman\b", "medium", "gender", "police officer"),
    BiasPattern(r"\bpolicemen\b", "medium", "gender", "police officers"),
    BiasPattern(r"\bfireman\b", "medium", "gender", "firefighter"),
    BiasPattern(r"\bfiremen\b", "medium", "gender", "firefighters"),
    BiasPattern(r"\bstewardess\b", "medium", "gender", "flight attendant"),
    BiasPattern(r"\bstewardesses\b", "medium", "gender", "flight attendants"),
    BiasPattern(r"\bmailman\b", "medium", "gender", "mail carrier or postal worker"),
    BiasPattern(r"\bmanpower\b", "medium", "gender", "workforce or staffing"),
    BiasPattern(r"\bman-?made\b", "low", "gender", "synthetic, artificial, or manufactured"),
    BiasPattern(r"\bmanmade\b", "low", "gender", "synthetic, artificial, or manufactured"),
    BiasPattern(r"\bmankind\b", "low", "gender", "humankind or humanity"),
    BiasPattern(r"\bsalesman\b", "medium", "gender", "salesperson or sales representative"),
    BiasPattern(r"\bsalesmen\b", "medium", "gender", "salespeople or sales representatives"),
    BiasPattern(r"\bsaleswoman\b", "medium", "gender", "salesperson or sales representative"),
    BiasPattern(r"\bbusinessman\b", "medium", "gender", "businessperson or entrepreneur"),
    BiasPattern(r"\bbusinessmen\b", "medium", "gender", "businesspeople or entrepreneurs"),
    BiasPattern(r"\bworkman\b", "medium", "gender", "worker"),
    BiasPattern(r"\bforeman\b", "medium", "gender", "supervisor or foreperson"),
    BiasPattern(r"\bcraftsman\b", "medium", "gender", "craftsperson or artisan"),
    BiasPattern(r"\bclergyman\b", "medium", "gender", "clergy member"),
    BiasPattern(r"\bspokesman\b", "medium", "gender", "spokesperson"),
    BiasPattern(r"\bnewsman\b", "medium", "gender", "journalist or reporter"),
    BiasPattern(r"\bweatherman\b", "medium", "gender", "meteorologist or weather forecaster"),
    BiasPattern(r"\bmiddleman\b", "low", "gender", "intermediary or go-between"),

    # Gendered assumptions in professional contexts
    BiasPattern(r"\bmale nurse\b", "medium", "gender", "nurse (remove gendered qualifier)"),
    BiasPattern(r"\bfemale doctor\b", "medium", "gender", "doctor (remove gendered qualifier)"),
    BiasPattern(r"\bfemale engineer\b", "medium", "gender", "engineer (remove gendered qualifier)"),
    BiasPattern(r"\bfemale CEO\b", "medium", "gender", "CEO (remove gendered qualifier)"),
    BiasPattern(r"\bfemale pilot\b", "medium", "gender", "pilot (remove gendered qualifier)"),
    BiasPattern(r"\blady doctor\b", "high", "gender", "doctor (remove gendered qualifier)"),
    BiasPattern(r"\blady lawyer\b", "high", "gender", "lawyer (remove gendered qualifier)"),
    BiasPattern(r"\bgirl boss\b", "medium", "gender", "leader or boss"),
    BiasPattern(r"\bworking mother\b", "medium", "gender", "working parent (or just parent)"),

    # Stereotypical descriptors
    BiasPattern(r"\bbossy\b", "low", "gender", "assertive or direct"),
    BiasPattern(r"\bhysterical\b", "medium", "gender", "upset or irrational"),
    BiasPattern(r"\bshrill\b", "medium", "gender", "loud or high-pitched"),
    BiasPattern(r"\bfeisty\b", "low", "gender", "spirited or determined"),
    BiasPattern(r"\bnagging\b", "medium", "gender", "persistent or insistent"),
    BiasPattern(r"\bcatty\b", "medium", "gender", "critical or spiteful"),
    BiasPattern(r"\bhigh[- ]maintenance\b", "medium", "gender", "particular or detail-oriented"),

    # Generic masculine
    BiasPattern(r"\bhe or she\b", "low", "gender", "they"),
    BiasPattern(r"\bhis or her\b", "low", "gender", "their"),
    BiasPattern(r"\bhe/she\b", "low", "gender", "they"),
    BiasPattern(r"\bhis/her\b", "low", "gender", "their"),
    BiasPattern(r"\b(?:every|each|any)\s+(?:man|guy)\b", "medium", "gender", "everyone or each person"),
]

# ── Race / Ethnicity Bias Patterns ──────────────────────────────────────────

RACE_PATTERNS: list[BiasPattern] = [
    # Coded / exclusionary language
    BiasPattern(r"\bblacklist\b", "low", "race", "blocklist or denylist"),
    BiasPattern(r"\bwhitelist\b", "low", "race", "allowlist or permitlist"),
    BiasPattern(r"\bmaster\s*[-/]?\s*slave\b", "high", "race", "primary/replica, leader/follower, or controller/worker"),
    BiasPattern(r"\bmaster branch\b", "low", "race", "main branch"),
    BiasPattern(r"\bgrandfathered\b", "low", "race", "legacy or pre-existing"),
    BiasPattern(r"\bgrandfather clause\b", "medium", "race", "legacy clause or exemption"),

    # Stereotypical or othering language
    BiasPattern(r"\bexotic\b(?=.*(?:look|beaut|appear|featur))", "medium", "race", "distinctive or striking"),
    BiasPattern(r"\barticulate\b(?=.*(?:for|surprising))", "high", "race", "well-spoken (remove qualifier)"),
    BiasPattern(r"\burban\b(?=.*(?:youth|people|community|culture))", "low", "race", "Consider being more specific about the community"),
    BiasPattern(r"\bminority\b", "low", "race", "underrepresented group or specific group name"),
    BiasPattern(r"\bnon-?white\b", "medium", "race", "people of color or specific group name"),
    BiasPattern(r"\bcolored people\b", "high", "race", "people of color"),
    BiasPattern(r"\borientals?\b", "high", "race", "Asian or specific nationality/ethnicity"),
    BiasPattern(r"\billegal alien\b", "high", "race", "undocumented immigrant or undocumented person"),
    BiasPattern(r"\billegal immigrant\b", "medium", "race", "undocumented immigrant"),
    BiasPattern(r"\boff the reservation\b", "high", "race", "off track or unconventional"),
    BiasPattern(r"\bspirit animal\b", "medium", "race", "inspiration or favorite"),
    BiasPattern(r"\btribe\b(?=.*(?:find|your|my|vibe))", "low", "race", "community, group, or circle"),
    BiasPattern(r"\blow[- ]hanging fruit\b", "low", "race", "easy wins or quick opportunities"),
    BiasPattern(r"\bghetto\b", "high", "race", "under-resourced or economically disadvantaged"),
    BiasPattern(r"\bthug\b", "medium", "race", "criminal or suspect"),
    BiasPattern(r"\bsavage\b(?=.*(?:people|culture|behav))", "high", "race", "aggressive or uncivilized (consider rephrasing entirely)"),

    # Cultural appropriation / insensitivity markers
    BiasPattern(r"\bpow[- ]?wow\b(?!.*(?:native|tribal|indigenous))", "low", "race", "meeting or gathering"),
    BiasPattern(r"\btotem pole\b(?=.*(?:low|bottom|hierarchy))", "low", "race", "hierarchy or ranking"),
]

# ── Age Bias Patterns ───────────────────────────────────────────────────────

AGE_PATTERNS: list[BiasPattern] = [
    # Ageist language (older)
    BiasPattern(r"\boldster\b", "medium", "age", "older adult or senior"),
    BiasPattern(r"\bold-?timer\b", "medium", "age", "experienced person or veteran"),
    BiasPattern(r"\belderly\b", "low", "age", "older adult or senior"),
    BiasPattern(r"\bsenile\b", "high", "age", "Remove this term; specify cognitive condition if relevant"),
    BiasPattern(r"\bover the hill\b", "high", "age", "experienced or seasoned"),
    BiasPattern(r"\bpast (?:his|her|their) prime\b", "high", "age", "Remove this phrase"),
    BiasPattern(r"\bdead wood\b", "high", "age", "underperforming (without age connotation)"),
    BiasPattern(r"\bset in (?:his|her|their) ways\b", "medium", "age", "consistent or established in approach"),
    BiasPattern(r"\btoo old to\b", "high", "age", "Remove age-based limitation"),
    BiasPattern(r"\bcan't teach an old dog\b", "high", "age", "Remove this phrase; people learn at any age"),
    BiasPattern(r"\btechnologically challenged\b", "medium", "age", "still developing technical skills"),
    BiasPattern(r"\bnot tech[- ]savvy\b", "low", "age", "still building technical proficiency"),

    # Ageist language (younger)
    BiasPattern(r"\bmillennial\b(?=.*(?:lazy|entitled|sensitive|snowflake))", "high", "age", "Remove generational stereotype"),
    BiasPattern(r"\bgen[- ]?z\b(?=.*(?:lazy|entitled|attention|phone))", "high", "age", "Remove generational stereotype"),
    BiasPattern(r"\bboomer\b(?=.*(?:out of touch|clueless|dinosaur))", "high", "age", "Remove generational stereotype"),
    BiasPattern(r"\bkids these days\b", "medium", "age", "young people or younger generation"),
    BiasPattern(r"\btoo young to\b", "high", "age", "Remove age-based limitation"),
    BiasPattern(r"\bjust a kid\b", "medium", "age", "young professional or early-career"),
    BiasPattern(r"\binexperienced youth\b", "medium", "age", "early-career professional"),
    BiasPattern(r"\bwet behind the ears\b", "medium", "age", "new to the field or early-career"),
    BiasPattern(r"\bgreen\b(?=.*(?:too|still|very).*(?:young|new))", "low", "age", "early in their career"),

    # Age requirements in job contexts
    BiasPattern(r"\byoung and (?:dynamic|energetic|hungry)\b", "high", "age", "dynamic and energetic (remove 'young')"),
    BiasPattern(r"\bdigital native\b", "medium", "age", "proficient with technology"),
    BiasPattern(r"\brecent graduate\b(?=.*(?:only|must|required))", "medium", "age", "entry-level (avoid age proxies in requirements)"),
    BiasPattern(r"\b(?:10|15|20)\+?\s*years?\s*(?:of\s+)?experience\s*required\b", "medium", "age", "Consider if this much experience is truly required"),
    BiasPattern(r"\bnative internet user\b", "medium", "age", "comfortable with internet technologies"),
]

# ── Disability Bias Patterns ────────────────────────────────────────────────

DISABILITY_PATTERNS: list[BiasPattern] = [
    # Ableist language
    BiasPattern(r"\bcrazy\b", "low", "disability", "surprising, chaotic, or intense"),
    BiasPattern(r"\binsane\b", "low", "disability", "extraordinary, intense, or unbelievable"),
    BiasPattern(r"\blame\b(?=.*(?:excuse|argument|attempt|idea))", "low", "disability", "weak, unconvincing, or inadequate"),
    BiasPattern(r"\bcrippling\b", "medium", "disability", "debilitating, severe, or devastating"),
    BiasPattern(r"\bcrippled\b", "high", "disability", "person with a disability or impaired"),
    BiasPattern(r"\bhandicapped\b", "medium", "disability", "person with a disability or accessible"),
    BiasPattern(r"\bwheelchair[- ]bound\b", "medium", "disability", "wheelchair user or uses a wheelchair"),
    BiasPattern(r"\bconfined to a wheelchair\b", "medium", "disability", "uses a wheelchair"),
    BiasPattern(r"\bsuffering from\b", "medium", "disability", "living with or has (condition)"),
    BiasPattern(r"\bafflicted with\b", "medium", "disability", "has or living with"),
    BiasPattern(r"\bvictim of\b(?=.*(?:disease|disability|condition|disorder))", "medium", "disability", "person with (condition)"),
    BiasPattern(r"\bstricken with\b", "medium", "disability", "diagnosed with or has"),
    BiasPattern(r"\bmentally? (?:retarded|challenged)\b", "high", "disability", "person with an intellectual disability"),
    BiasPattern(r"\bretarded\b", "high", "disability", "Remove this term"),
    BiasPattern(r"\bpsycho\b", "high", "disability", "Remove this term"),
    BiasPattern(r"\bschizo\b", "high", "disability", "Remove this term; use specific diagnosis if relevant"),
    BiasPattern(r"\bspaz\b", "high", "disability", "Remove this term"),
    BiasPattern(r"\bidiot\b", "medium", "disability", "foolish or uninformed"),
    BiasPattern(r"\bmoron\b", "high", "disability", "Remove this term"),
    BiasPattern(r"\bimbecile\b", "high", "disability", "Remove this term"),
    BiasPattern(r"\bdumb\b(?=.*(?:idea|thing|move|decision))", "low", "disability", "foolish, uninformed, or poor"),
    BiasPattern(r"\bturn a blind eye\b", "low", "disability", "ignore or overlook"),
    BiasPattern(r"\bturn a deaf ear\b", "low", "disability", "ignore or disregard"),
    BiasPattern(r"\bfalling on deaf ears\b", "low", "disability", "being ignored"),
    BiasPattern(r"\bblind spot\b", "low", "disability", "oversight or gap"),
    BiasPattern(r"\bblind to\b", "low", "disability", "unaware of or overlooking"),
    BiasPattern(r"\btone[- ]deaf\b", "low", "disability", "insensitive or out of touch"),
    BiasPattern(r"\bspecial needs\b", "medium", "disability", "disabled or person with a disability"),
    BiasPattern(r"\bdifferently[- ]abled\b", "low", "disability", "disabled (preferred by disability community)"),
    BiasPattern(r"\bnormal\b(?=.*(?:vs|versus|compared|unlike).*(?:disab|impair|handicap))", "medium", "disability", "non-disabled"),
    BiasPattern(r"\bable[- ]bodied\b", "low", "disability", "non-disabled"),
]

CATEGORY_PATTERNS: dict[str, list[BiasPattern]] = {
    "gender": GENDER_PATTERNS,
    "race": RACE_PATTERNS,
    "age": AGE_PATTERNS,
    "disability": DISABILITY_PATTERNS,
}

# Severity weights for scoring
SEVERITY_WEIGHTS: dict[str, float] = {
    "low": 2.0,
    "medium": 5.0,
    "high": 10.0,
}

# Confidence adjustments based on text length
MIN_CONFIDENCE_TEXT_LENGTH = 20  # Below this, confidence drops
HIGH_CONFIDENCE_TEXT_LENGTH = 200  # Above this, confidence is high


class TextBiasDetector:
    """Deterministic bias detection engine using pattern matching and scoring."""

    def analyze_text(self, text: str, categories: list[str] | None = None) -> FairnessReport:
        """
        Analyze text for bias across specified categories.

        Args:
            text: The text to analyze.
            categories: List of categories to check. Defaults to all.

        Returns:
            FairnessReport with scores and flagged phrases.
        """
        if categories is None:
            categories = list(CATEGORY_PATTERNS.keys())

        # Validate categories
        valid_categories = [c for c in categories if c in CATEGORY_PATTERNS]

        text_lower = text.lower()
        text_length = len(text.split())
        bias_scores: list[BiasScore] = []

        for category in valid_categories:
            score, flagged = self._analyze_category(text, text_lower, category)
            confidence = self._calculate_confidence(text_length, len(flagged), category)
            bias_scores.append(
                BiasScore(
                    category=category,
                    score=round(score, 1),
                    confidence=round(confidence, 3),
                    flagged_phrases=flagged,
                )
            )

        overall_score = self._calculate_overall_score(bias_scores)
        recommendations = self._generate_recommendations(bias_scores)

        return FairnessReport(
            report_id=uuid.uuid4().hex[:16],
            overall_score=round(overall_score, 1),
            bias_scores=bias_scores,
            recommendations=recommendations,
            text_length=text_length,
            categories_analyzed=valid_categories,
            timestamp=datetime.now(timezone.utc),
        )

    def _analyze_category(
        self, text: str, text_lower: str, category: str
    ) -> tuple[float, list[FlaggedPhrase]]:
        """Analyze text for a single bias category. Returns (score, flagged_phrases)."""
        patterns = CATEGORY_PATTERNS.get(category, [])
        flagged: list[FlaggedPhrase] = []
        total_penalty = 0.0

        for bp in patterns:
            for match in re.finditer(bp.pattern, text_lower):
                # Get the matched text from the original (preserving case)
                start, end = match.start(), match.end()
                original_phrase = text[start:end]

                flagged.append(
                    FlaggedPhrase(
                        phrase=original_phrase,
                        start=start,
                        end=end,
                        category=category,
                        severity=bp.severity,
                        suggestion=bp.suggestion,
                    )
                )
                total_penalty += SEVERITY_WEIGHTS[bp.severity]

        # Score: start at 100 and subtract penalties, floor at 0
        # Scale penalty by text length so longer texts aren't penalized more harshly
        word_count = max(len(text.split()), 1)
        # Normalize: penalty per 100 words
        normalized_penalty = (total_penalty / word_count) * 100
        score = max(0.0, 100.0 - normalized_penalty)

        return score, flagged

    def _calculate_confidence(
        self, word_count: int, flags_found: int, category: str
    ) -> float:
        """
        Calculate confidence in the bias score.

        Confidence is higher when:
        - Text is longer (more context)
        - More patterns were checked
        """
        # Base confidence from text length
        if word_count < MIN_CONFIDENCE_TEXT_LENGTH:
            length_factor = word_count / MIN_CONFIDENCE_TEXT_LENGTH
        elif word_count >= HIGH_CONFIDENCE_TEXT_LENGTH:
            length_factor = 1.0
        else:
            length_factor = 0.7 + 0.3 * (
                (word_count - MIN_CONFIDENCE_TEXT_LENGTH)
                / (HIGH_CONFIDENCE_TEXT_LENGTH - MIN_CONFIDENCE_TEXT_LENGTH)
            )

        # Pattern coverage factor: we have more patterns for some categories
        pattern_count = len(CATEGORY_PATTERNS.get(category, []))
        coverage_factor = min(1.0, pattern_count / 20.0)

        confidence = length_factor * 0.7 + coverage_factor * 0.3
        return min(1.0, max(0.1, confidence))

    def _calculate_overall_score(self, bias_scores: list[BiasScore]) -> float:
        """Calculate weighted overall fairness score across all categories."""
        if not bias_scores:
            return 100.0

        # Weight by confidence so less-certain scores contribute less
        total_weight = sum(bs.confidence for bs in bias_scores)
        if total_weight == 0:
            return 100.0

        weighted_sum = sum(bs.score * bs.confidence for bs in bias_scores)
        return weighted_sum / total_weight

    def _generate_recommendations(self, bias_scores: list[BiasScore]) -> list[str]:
        """Generate actionable recommendations based on findings."""
        recommendations: list[str] = []

        for bs in bias_scores:
            if not bs.flagged_phrases:
                continue

            high_severity = [fp for fp in bs.flagged_phrases if fp.severity == "high"]
            medium_severity = [fp for fp in bs.flagged_phrases if fp.severity == "medium"]
            low_severity = [fp for fp in bs.flagged_phrases if fp.severity == "low"]

            category_label = bs.category.replace("_", " ").title()

            if high_severity:
                phrases = ", ".join(
                    f'"{fp.phrase}"' for fp in high_severity[:3]
                )
                recommendations.append(
                    f"[{category_label} - High Priority] Remove or replace: {phrases}. "
                    f"These terms are considered highly biased or offensive."
                )

            if medium_severity:
                count = len(medium_severity)
                recommendations.append(
                    f"[{category_label} - Medium Priority] Found {count} instance(s) of "
                    f"moderately biased language. Consider using inclusive alternatives."
                )

            if low_severity and not high_severity and not medium_severity:
                recommendations.append(
                    f"[{category_label} - Low Priority] Minor stylistic suggestions "
                    f"found ({len(low_severity)} instances). Consider inclusive alternatives "
                    f"for marginally biased terms."
                )

        if not recommendations:
            recommendations.append(
                "No significant bias detected. The text appears to use inclusive language."
            )
        else:
            recommendations.append(
                "Review each flagged phrase in context -- some flags may be false positives "
                "depending on the specific usage and domain."
            )

        return recommendations
