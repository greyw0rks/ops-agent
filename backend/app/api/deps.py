"""Shared FastAPI dependencies."""

import logging

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Business
from app.db.session import get_db
from app.services.business import BusinessNotFound, get_default_business

logger = logging.getLogger(__name__)


def require_owner(authorization: str | None = Header(default=None)) -> None:
    """Guard the owner-facing API with a shared secret.

    The dashboard reads customer records and approves refunds, so it is not a public
    surface. When `OPS_API_TOKEN` is unset the guard is disabled to keep the local
    demo frictionless — see the startup warning in `app.main`.
    """
    if not settings.api_token:
        return

    expected = f"Bearer {settings.api_token}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def current_business(db: Session = Depends(get_db)) -> Business:
    """The business this deployment serves.

    Single-tenant by design: one deployment, one business. Every query in the
    service layer is still scoped by `business_id`, so becoming multi-tenant is a
    change to this function rather than to the whole codebase.
    """
    try:
        return get_default_business(db)
    except BusinessNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no business configured — run `python -m scripts.seed`",
        ) from exc
