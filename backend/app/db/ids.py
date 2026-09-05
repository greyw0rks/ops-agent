"""Human-readable prefixed identifiers.

Every row gets an id like `cus_7f3a91c4`. They are short enough to read out in a
demo, unique enough for a single-tenant deployment, and they make the audit log
legible without joins.
"""

import secrets

PREFIXES = {
    "business": "biz",
    "service": "svc",
    "customer": "cus",
    "booking": "book",
    "conversation": "conv",
    "message": "msg",
    "task": "task",
    "approval": "apr",
    "agent_run": "run",
    "agent_action": "act",
    "business_policy": "pol",
    "refund": "ref",
    "supplier_invoice": "inv",
}


def new_id(entity: str) -> str:
    """Generate an id for the given entity name."""
    prefix = PREFIXES.get(entity, entity[:4])
    return f"{prefix}_{secrets.token_hex(4)}"


def id_factory(entity: str):
    """Return a zero-argument callable for use as a SQLAlchemy column default."""
    return lambda: new_id(entity)
