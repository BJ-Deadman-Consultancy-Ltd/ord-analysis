"""Connection helper for a local ORD PostgreSQL database.

Connection details are read from the environment (see .env.example) rather
than hardcoded, so this module can be committed safely. Load a `.env` file
with `dotenv.load_dotenv()` before calling `get_engine()`, e.g.:

    from dotenv import load_dotenv
    from ord_analysis.db import get_engine

    load_dotenv()
    engine = get_engine()
"""

import os

from ord_schema.orm.database import get_connection_string
from sqlalchemy import Engine, create_engine


def get_engine() -> Engine:
    """Builds a SQLAlchemy engine for the local ORD database from environment variables.

    Reads ORD_DB_HOST, ORD_DB_PORT, ORD_DB_NAME, ORD_DB_USER, and the password
    from PGPASSWORD -- the same convention used by ord_schema's own
    `orm/scripts/add_datasets.py`.
    """
    connection_string = get_connection_string(
        database=os.environ.get("ORD_DB_NAME", "ord"),
        username=os.environ.get("ORD_DB_USER", "postgres"),
        password=os.environ["PGPASSWORD"],
        host=os.environ.get("ORD_DB_HOST", "localhost"),
        port=int(os.environ.get("ORD_DB_PORT", "5432")),
    )
    return create_engine(connection_string)
