"""Create (or drop and recreate) the database schema.

Usage:
    python -m scripts.init_db          # create anything missing
    python -m scripts.init_db --drop   # drop everything first
"""

import argparse
import logging

from sqlalchemy import text

from app.db.models import Base
from app.db.session import engine

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("init_db")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop", action="store_true", help="drop all tables before creating")
    args = parser.parse_args()

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    log.info("connected to %s", engine.url.render_as_string(hide_password=True))

    if args.drop:
        Base.metadata.drop_all(engine)
        log.info("dropped %d tables", len(Base.metadata.sorted_tables))

    Base.metadata.create_all(engine)
    log.info("schema ready: %s", ", ".join(t.name for t in Base.metadata.sorted_tables))


if __name__ == "__main__":
    main()
