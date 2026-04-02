"""Analysis endpoints for text bias detection and dataset fairness."""

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import check_usage_limit, log_usage
from app.models.database import APIKey, ReportStore, get_session
from app.models.schemas import (
    DatasetAnalysisRequest,
    DatasetFairnessReport,
    FairnessReport,
    TextAnalysisRequest,
)
from app.services.bias_detector import TextBiasDetector
from app.services.dataset_analyzer import DatasetAnalyzer
from app.services.provenance import get_active_receipt

router = APIRouter(prefix="/api/v1/analyze", tags=["analysis"])

bias_detector = TextBiasDetector()
dataset_analyzer = DatasetAnalyzer()


@router.post("/text", response_model=FairnessReport)
async def analyze_text(
    request: TextAnalysisRequest,
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> FairnessReport:
    """
    Analyze text for bias across specified categories.

    Returns a fairness report with per-category scores, flagged phrases,
    and actionable recommendations. If the caller's account has an active
    community config with a CPL entry, a ``provenance_receipt`` is included
    proving which community standard governed the analysis.
    """
    report = bias_detector.analyze_text(request.text, request.categories)

    # Attach provenance receipt if the user has a ledger entry
    receipt = await get_active_receipt(session, key_record.user_id)
    if receipt is not None:
        report.provenance_receipt = receipt

    # Log usage
    await log_usage(
        session=session,
        api_key_id=key_record.id,
        endpoint="/api/v1/analyze/text",
        tokens_used=report.text_length,
    )

    # Store report for later retrieval
    stored = ReportStore(
        report_id=report.report_id,
        report_type="text",
        report_json=report.model_dump_json(),
        api_key_id=key_record.id,
    )
    session.add(stored)
    await session.commit()

    return report


@router.post("/dataset", response_model=DatasetFairnessReport)
async def analyze_dataset(
    request: DatasetAnalysisRequest,
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> DatasetFairnessReport:
    """
    Analyze a dataset for fairness across protected attributes.

    Computes disparate impact ratio, statistical parity difference,
    and group-level outcome rates. Includes ``provenance_receipt`` when
    the caller has an active CPL entry.
    """
    try:
        report = dataset_analyzer.analyze_dataset(
            data=request.data,
            target_column=request.target_column,
            protected_columns=request.protected_columns,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Attach provenance receipt
    receipt = await get_active_receipt(session, key_record.user_id)
    if receipt is not None:
        report.provenance_receipt = receipt

    # Log usage
    await log_usage(
        session=session,
        api_key_id=key_record.id,
        endpoint="/api/v1/analyze/dataset",
        tokens_used=len(request.data),
    )

    # Store report
    stored = ReportStore(
        report_id=report.report_id,
        report_type="dataset",
        report_json=report.model_dump_json(),
        api_key_id=key_record.id,
    )
    session.add(stored)
    await session.commit()

    return report


@router.get("/report/{report_id}")
async def get_report(
    report_id: str,
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Retrieve a previously generated report by ID."""
    result = await session.execute(
        select(ReportStore).where(
            ReportStore.report_id == report_id,
            ReportStore.api_key_id == key_record.id,
        )
    )
    stored = result.scalar_one_or_none()

    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' not found or not accessible with this API key.",
        )

    return json.loads(stored.report_json)
