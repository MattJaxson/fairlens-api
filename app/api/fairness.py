"""
Racial Fairness API — merged from adaptive-racial-fairness-framework.

Endpoints for disparate impact auditing, reweighting, adversarial debiasing,
compliance checking, and community governance configuration.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import check_usage_limit, log_usage
from app.models.database import APIKey, CommunityConfig, ReportStore, User, get_session
from app.models.schemas import (
    CommunityConfigCreate,
    DebiasRequest,
    RacialAuditRequest,
    ReweightRequest,
)
from app.services.community_governance import (
    DEFAULT_COMMUNITY_DEFS,
    build_community_config,
    is_community_valid,
    validate_community_config,
)
from app.services.fairness_audit import RacialFairnessAuditor, coerce_favorable
from app.services.fairness_reweight import build_reweight_report, reweight_samples_with_community

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/fairness", tags=["fairness"])

MAX_UPLOAD_MB = 50
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

auditor = RacialFairnessAuditor()


# ── Helpers ────────────────────────────────────────────────────────────────


async def _get_community_defs(key_record: APIKey, session: AsyncSession) -> dict:
    """Load community config: enterprise users get their own, others get defaults."""
    user = await session.get(User, key_record.user_id)
    if user and user.tier == "enterprise":
        result = await session.execute(
            select(CommunityConfig).where(
                CommunityConfig.user_id == key_record.user_id,
                CommunityConfig.is_active.is_(True),
            ).order_by(CommunityConfig.created_at.desc()).limit(1)
        )
        config_row = result.scalar_one_or_none()
        if config_row:
            return json.loads(config_row.config_json)
    return DEFAULT_COMMUNITY_DEFS.copy()


def _require_tier(user: User, minimum: str) -> None:
    """Raise 403 if user tier is below minimum."""
    tiers = {"free": 0, "pro": 1, "enterprise": 2}
    if tiers.get(user.tier, 0) < tiers.get(minimum, 0):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This endpoint requires {minimum} tier or above. Current tier: {user.tier}",
        )


async def _read_csv(file: UploadFile) -> pd.DataFrame:
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_UPLOAD_MB}MB limit.")
    df = pd.read_csv(io.BytesIO(contents))
    df.columns = df.columns.str.strip()
    return df


# ── Audit Endpoints ───────────────────────────────────────────────────────


@router.post("/audit")
async def audit_json(
    request: RacialAuditRequest,
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Racial fairness audit on JSON data. Available to all tiers."""
    try:
        df = pd.DataFrame(request.data)
        community_defs = await _get_community_defs(key_record, session)
        report = auditor.build_audit_report(
            df=df, race_col=request.race_col, outcome_col=request.outcome_col,
            favorable_value=request.favorable_value, privileged_group=request.privileged_group,
            community_defs=community_defs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await log_usage(session, key_record.id, "/api/v1/fairness/audit", len(request.data))

    stored = ReportStore(
        report_id=f"fa_{pd.Timestamp.now().strftime('%Y%m%d%H%M%S')}",
        report_type="racial_audit", report_json=json.dumps(report), api_key_id=key_record.id,
    )
    session.add(stored)
    await session.commit()

    return JSONResponse(content=report)


@router.post("/audit/csv")
async def audit_csv(
    file: UploadFile = File(...),
    race_col: str = Form(...),
    outcome_col: str = Form(...),
    favorable_value: str = Form(...),
    privileged_group: str | None = Form(default=None),
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Racial fairness audit on CSV upload. Pro+ tier."""
    user = await session.get(User, key_record.user_id)
    _require_tier(user, "pro")

    try:
        df = await _read_csv(file)
        community_defs = await _get_community_defs(key_record, session)
        report = auditor.build_audit_report(
            df=df, race_col=race_col, outcome_col=outcome_col,
            favorable_value=favorable_value, privileged_group=privileged_group,
            community_defs=community_defs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await log_usage(session, key_record.id, "/api/v1/fairness/audit/csv", len(df))
    return JSONResponse(content=report)


@router.post("/audit/pdf")
async def audit_pdf(
    file: UploadFile = File(...),
    race_col: str = Form(...),
    outcome_col: str = Form(...),
    favorable_value: str = Form(...),
    privileged_group: str | None = Form(default=None),
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Audit CSV and return a PDF compliance report. Pro+ tier."""
    user = await session.get(User, key_record.user_id)
    _require_tier(user, "pro")

    from app.services.report_generator import generate_pdf_report

    try:
        df = await _read_csv(file)
        community_defs = await _get_community_defs(key_record, session)
        report = auditor.build_audit_report(
            df=df, race_col=race_col, outcome_col=outcome_col,
            favorable_value=favorable_value, privileged_group=privileged_group,
            community_defs=community_defs,
        )
        pdf_bytes = generate_pdf_report(report)
    except ImportError:
        raise HTTPException(status_code=501, detail="PDF generation not available.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await log_usage(session, key_record.id, "/api/v1/fairness/audit/pdf", len(df))

    filename = f"fairness_audit_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Remediation ───────────────────────────────────────────────────────────


@router.post("/audit/remediate")
async def audit_remediate(
    file: UploadFile = File(...),
    race_col: str = Form(...),
    outcome_col: str = Form(...),
    favorable_value: str = Form(...),
    privileged_group: str | None = Form(default=None),
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Full remediation loop: audit -> reweight -> post-audit. Pro+ tier."""
    user = await session.get(User, key_record.user_id)
    _require_tier(user, "pro")

    try:
        df = await _read_csv(file)
        community_defs = await _get_community_defs(key_record, session)
        di_threshold = float(community_defs.get("fairness_threshold", 0.8))

        # Pre-mitigation audit
        pre_report = auditor.build_audit_report(
            df=df, race_col=race_col, outcome_col=outcome_col,
            favorable_value=favorable_value, privileged_group=privileged_group,
            community_defs=community_defs,
        )

        flagged_groups = pre_report["summary"]["flagged_groups"]
        if not flagged_groups:
            return JSONResponse(content={
                "status": "success",
                "message": "No flagged groups — remediation not required.",
                "pre_mitigation": pre_report, "post_mitigation": None, "delta": None,
            })

        # Reweight
        df_copy, favorable = coerce_favorable(df.copy(), outcome_col, favorable_value)
        reweighted_df = reweight_samples_with_community(
            data=df_copy, race_col=race_col, outcome_col=outcome_col,
            favorable=favorable, community_defs=community_defs,
        )

        # Post-mitigation weighted rates
        binary = (reweighted_df[outcome_col] == favorable).astype(float)
        sw = reweighted_df["sample_weight"].fillna(1.0)

        post_group_rates: dict[str, float] = {}
        for group in reweighted_df[race_col].unique():
            mask = reweighted_df[race_col] == group
            weighted_sum = (binary[mask] * sw[mask]).sum()
            weight_total = sw[mask].sum()
            post_group_rates[str(group)] = round(float(weighted_sum / weight_total), 4) if weight_total > 0 else 0.0

        ref_group = privileged_group or community_defs.get("fairness_target", "White")
        if ref_group not in post_group_rates:
            ref_group = max(post_group_rates, key=lambda g: post_group_rates[g])
        post_ref_rate = post_group_rates.get(ref_group, 0.0)

        post_di: dict[str, float | None] = {}
        for group, rate in post_group_rates.items():
            if group == ref_group:
                post_di[group] = 1.0
            elif post_ref_rate == 0:
                post_di[group] = None
            else:
                post_di[group] = round(rate / post_ref_rate, 4)

        post_flagged = [g for g, di in post_di.items() if di is not None and di < di_threshold]

        post_report = {
            "status": "success", "audit_type": pre_report["audit_type"],
            "community_config": pre_report["community_config"],
            "summary": {
                "total_records": len(reweighted_df),
                "groups_analyzed": list(post_group_rates.keys()),
                "outcome_column": outcome_col, "favorable_value": favorable_value,
                "flagged_groups": post_flagged,
            },
            "metrics": {
                "disparity_score": round(max(post_group_rates.values()) - min(post_group_rates.values()), 4),
                "group_outcomes": post_group_rates, "disparate_impact": post_di,
                "statistical_parity_gap": round((max(post_group_rates.values()) - min(post_group_rates.values())) * 100, 2),
            },
        }

        # Delta
        pre_di = pre_report["metrics"]["disparate_impact"]
        delta = {
            group: {
                "pre": pre_di.get(group), "post": post_di.get(group),
                "change": (
                    round(post_di[group] - pre_di[group], 4)
                    if pre_di.get(group) is not None and post_di.get(group) is not None else None
                ),
            }
            for group in set(list(pre_di.keys()) + list(post_di.keys()))
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await log_usage(session, key_record.id, "/api/v1/fairness/audit/remediate", len(df))

    return JSONResponse(content={
        "status": "success",
        "flagged_groups_pre": flagged_groups, "flagged_groups_post": post_flagged,
        "pre_mitigation": pre_report, "post_mitigation": post_report, "delta": delta,
    })


# ── Debiasing ─────────────────────────────────────────────────────────────


@router.post("/audit/debias")
async def audit_debias(
    file: UploadFile = File(...),
    race_col: str = Form(...),
    outcome_col: str = Form(...),
    favorable_value: str = Form(...),
    feature_cols: str = Form(..., description="Comma-separated feature columns"),
    constraint: str = Form(default="demographic_parity"),
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Adversarial ML debiasing via Fairlearn. Enterprise tier only."""
    user = await session.get(User, key_record.user_id)
    _require_tier(user, "enterprise")

    from app.services.adversarial_debiaser import adversarial_fairness_pipeline

    try:
        df = await _read_csv(file)
        parsed_features = [c.strip() for c in feature_cols.split(",") if c.strip()]
        if not parsed_features:
            raise HTTPException(status_code=400, detail="feature_cols cannot be empty.")
        df, favorable = coerce_favorable(df, outcome_col, favorable_value)
        result = adversarial_fairness_pipeline(
            data=df, feature_cols=parsed_features, outcome_col=outcome_col,
            sensitive_col=race_col, favorable_value=favorable, constraint=constraint,
        )
    except (ValueError, ImportError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await log_usage(session, key_record.id, "/api/v1/fairness/audit/debias", len(df))
    return JSONResponse(content=result)


# ── Compliance ────────────────────────────────────────────────────────────


@router.post("/audit/compliance")
async def audit_compliance(
    file: UploadFile = File(...),
    race_col: str = Form(...),
    outcome_col: str = Form(...),
    favorable_value: str = Form(...),
    config_json: str = Form(..., description="CDF v1.0 community config as JSON string"),
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Check dataset compliance against a community-defined fairness standard. Pro+ tier."""
    user = await session.get(User, key_record.user_id)
    _require_tier(user, "pro")

    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid config_json: {e}")

    for field in ("priority_groups", "fairness_target", "fairness_threshold"):
        if field not in config:
            raise HTTPException(status_code=400, detail=f"Missing required field: '{field}'")

    try:
        df = await _read_csv(file)

        threshold = float(config["fairness_threshold"])
        ref_group_requested = str(config["fairness_target"])
        priority_groups = config["priority_groups"]
        provenance = config.get("provenance", {})

        df, favorable = coerce_favorable(df, outcome_col, favorable_value)

        # Validate columns
        for col in (race_col, outcome_col):
            if col not in df.columns:
                raise ValueError(f"Column '{col}' not found. Available: {list(df.columns)}")

        binary = (df[outcome_col] == favorable).astype(float)
        group_rates = binary.groupby(df[race_col]).mean().round(4).to_dict()
        group_rates = {str(k): float(v) for k, v in group_rates.items()}

        # Reference group
        if ref_group_requested in group_rates:
            ref = ref_group_requested
        elif "White" in group_rates:
            ref = "White"
        else:
            ref = max(group_rates, key=lambda g: group_rates[g])

        ref_rate = group_rates[ref]

        di_ratios: dict[str, float | None] = {}
        for group, rate in group_rates.items():
            if group == ref:
                di_ratios[group] = 1.0
            elif ref_rate == 0:
                di_ratios[group] = None
            else:
                di_ratios[group] = round(rate / ref_rate, 4)

        flagged = [g for g, di in di_ratios.items() if di is not None and di < threshold]
        passes = len(flagged) == 0
        priority_flagged = [g for g in flagged if g in priority_groups]

        audit_classification = "standard"
        if provenance and provenance.get("record_id") and provenance.get("input_date"):
            participants = provenance.get("input_participants", 0)
            audit_classification = "community_valid" if participants >= 10 else "low_confidence"

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await log_usage(session, key_record.id, "/api/v1/fairness/audit/compliance", len(df))

    return JSONResponse(content={
        "status": "success",
        "verdict": "PASS" if passes else "FAIL",
        "audit_classification": audit_classification,
        "community_config_used": {
            "fairness_target": ref, "fairness_threshold": threshold,
            "priority_groups": priority_groups, "provenance": provenance or None,
        },
        "summary": {
            "total_records": len(df), "groups_analyzed": sorted(group_rates.keys()),
            "reference_group": ref, "flagged_groups": flagged,
            "priority_groups_flagged": priority_flagged, "passes_community_standard": passes,
        },
        "metrics": {"group_rates": group_rates, "disparate_impact": di_ratios,
            "disparity_score": round(max(group_rates.values()) - min(group_rates.values()), 4)},
        "interpretation": (
            f"PASSES community standard (θ={threshold}). All groups meet minimum DI."
            if passes else
            f"FAILS community standard (θ={threshold}). {len(flagged)} group(s) below threshold: {', '.join(flagged)}."
        ),
    })


# ── Reweight ──────────────────────────────────────────────────────────────


@router.post("/reweight")
async def reweight_json(
    request: ReweightRequest,
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Fairness-aware sample reweighting (JSON). All tiers."""
    try:
        df = pd.DataFrame(request.data)
        community_defs = await _get_community_defs(key_record, session)
        report = build_reweight_report(
            df=df, race_col=request.race_col, outcome_col=request.outcome_col,
            favorable_value=request.favorable_value, community_defs=community_defs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await log_usage(session, key_record.id, "/api/v1/fairness/reweight", len(request.data))
    return JSONResponse(content=report)


@router.post("/reweight/csv")
async def reweight_csv(
    file: UploadFile = File(...),
    race_col: str = Form(...),
    outcome_col: str = Form(...),
    favorable_value: str = Form(...),
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Fairness-aware sample reweighting (CSV upload). Pro+ tier."""
    user = await session.get(User, key_record.user_id)
    _require_tier(user, "pro")

    try:
        df = await _read_csv(file)
        community_defs = await _get_community_defs(key_record, session)
        report = build_reweight_report(
            df=df, race_col=race_col, outcome_col=outcome_col,
            favorable_value=favorable_value, community_defs=community_defs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await log_usage(session, key_record.id, "/api/v1/fairness/reweight/csv", len(df))
    return JSONResponse(content=report)


# ── Community Governance ──────────────────────────────────────────────────


@router.post("/community/config", status_code=status.HTTP_201_CREATED)
async def create_community_config(
    request: CommunityConfigCreate,
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Create a community fairness config with provenance. Enterprise only."""
    user = await session.get(User, key_record.user_id)
    _require_tier(user, "enterprise")

    try:
        config = build_community_config(
            priority_groups=request.priority_groups,
            fairness_target=request.fairness_target,
            fairness_threshold=request.fairness_threshold,
            input_protocol=request.input_protocol,
            input_location=request.input_location,
            input_participants=request.input_participants,
            facilitator=request.facilitator,
            notes=request.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Deactivate previous configs
    result = await session.execute(
        select(CommunityConfig).where(
            CommunityConfig.user_id == key_record.user_id,
            CommunityConfig.is_active.is_(True),
        )
    )
    for old in result.scalars().all():
        old.is_active = False

    db_config = CommunityConfig(
        user_id=key_record.user_id,
        config_json=json.dumps(config),
        record_id=config["provenance"]["record_id"],
        is_active=True,
    )
    session.add(db_config)
    await session.commit()

    return JSONResponse(content={
        "status": "created",
        "record_id": config["provenance"]["record_id"],
        "config": config,
        "is_community_valid": is_community_valid(config),
    })


@router.get("/community/config")
async def get_community_config(
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Retrieve current active community config. Pro+ tier."""
    user = await session.get(User, key_record.user_id)
    _require_tier(user, "pro")

    community_defs = await _get_community_defs(key_record, session)
    return JSONResponse(content={
        "config": community_defs,
        "is_community_valid": is_community_valid(community_defs),
    })


@router.post("/community/config/validate")
async def validate_config(
    config: dict,
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Validate a community config. All tiers."""
    is_valid, issues = validate_community_config(config)
    return JSONResponse(content={
        "is_valid": is_valid,
        "is_community_valid": is_community_valid(config),
        "issues": issues,
    })
