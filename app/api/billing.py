"""Stripe billing endpoints for subscription management."""

from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_api_key_record
from app.core.config import settings
from app.models.database import APIKey, User, get_session
from app.models.schemas import (
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
)

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

stripe.api_key = settings.STRIPE_SECRET_KEY

PLAN_PRICE_MAP: dict[str, str] = {
    "pro": settings.STRIPE_PRICE_PRO,
    "enterprise": settings.STRIPE_PRICE_ENTERPRISE,
}


@router.post("/create-checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    request: CheckoutRequest,
    key_record: APIKey = Depends(get_api_key_record),
    session: AsyncSession = Depends(get_session),
) -> CheckoutResponse:
    """Create a Stripe Checkout session for plan upgrade."""
    result = await session.execute(
        select(User).where(User.id == key_record.user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    price_id = PLAN_PRICE_MAP.get(request.plan)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown plan: {request.plan}",
        )

    try:
        # Create or reuse Stripe customer
        if not user.stripe_customer_id:
            customer = stripe.Customer.create(email=user.email)
            user.stripe_customer_id = customer.id
            await session.commit()

        checkout_session = stripe.checkout.Session.create(
            customer=user.stripe_customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=request.success_url,
            cancel_url=request.cancel_url,
            metadata={"user_id": str(user.id), "plan": request.plan},
        )

        return CheckoutResponse(checkout_url=checkout_session.url)

    except stripe.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {str(e)}",
        )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Handle Stripe webhook events for subscription lifecycle."""
    payload = await request.body()

    if not stripe_signature or not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe signature or webhook secret not configured.",
        )

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature.",
        )

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data, session)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data, session)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data, session)

    return {"status": "ok"}


async def _handle_checkout_completed(data: dict, session: AsyncSession) -> None:
    """Upgrade user tier after successful checkout."""
    customer_id = data.get("customer")
    metadata = data.get("metadata", {})
    plan = metadata.get("plan", "pro")

    result = await session.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if user:
        user.tier = plan
        await session.commit()


async def _handle_subscription_updated(data: dict, session: AsyncSession) -> None:
    """Update tier when subscription changes."""
    customer_id = data.get("customer")
    status_value = data.get("status")

    result = await session.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if user and status_value != "active":
        user.tier = "free"
        await session.commit()


async def _handle_subscription_deleted(data: dict, session: AsyncSession) -> None:
    """Downgrade user to free tier when subscription is cancelled."""
    customer_id = data.get("customer")

    result = await session.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if user:
        user.tier = "free"
        await session.commit()


@router.get("/usage")
async def get_usage(
    key_record: APIKey = Depends(get_api_key_record),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get current usage stats for the authenticated user."""
    from sqlalchemy import func
    from app.models.database import UsageLog

    result = await session.execute(
        select(User).where(User.id == key_record.user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Next month start
    if now.month == 12:
        period_end = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        period_end = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)

    # Count usage across ALL of the user's API keys (not just the current one)
    from app.models.database import APIKey as APIKeyModel
    user_key_ids = select(APIKeyModel.id).where(APIKeyModel.user_id == key_record.user_id)

    result = await session.execute(
        select(func.count(UsageLog.id)).where(
            UsageLog.api_key_id.in_(user_key_ids),
            UsageLog.timestamp >= month_start,
        )
    )
    used = result.scalar() or 0

    from app.core.auth import TIER_LIMITS
    limit = TIER_LIMITS.get(user.tier, settings.FREE_TIER_LIMIT)

    return {
        "tier": user.tier,
        "monthly_limit": limit,
        "used_this_month": used,
        "remaining": max(0, limit - used),
        "period_start": month_start.isoformat(),
        "period_end": period_end.isoformat(),
    }


@router.get("/portal", response_model=PortalResponse)
async def customer_portal(
    key_record: APIKey = Depends(get_api_key_record),
    session: AsyncSession = Depends(get_session),
) -> PortalResponse:
    """Generate a Stripe Customer Portal link for managing subscriptions."""
    result = await session.execute(
        select(User).where(User.id == key_record.user_id)
    )
    user = result.scalar_one_or_none()
    if user is None or not user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No billing account found. Subscribe to a plan first.",
        )

    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url="https://fairlens.dev/dashboard",
        )
        return PortalResponse(portal_url=portal_session.url)
    except stripe.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {str(e)}",
        )
