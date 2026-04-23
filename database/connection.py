import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from config.settings import settings


def get_db_path() -> Path:
    path = Path(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_checkpoints_path(org_slug: str = "default") -> Path:
    """Per-org LangGraph checkpoint file under data/checkpoints/{slug}.db."""
    db = Path(settings.database_path)
    checkpoints_dir = db.parent / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    return checkpoints_dir / f"{org_slug}.db"


def init_db() -> None:
    """Initialize the v2 multi-tenant database schema."""
    schema_path = Path(__file__).parent / "schema_v2.sql"
    with open(schema_path) as f:
        schema = f.read()
    # Strip PRAGMA lines — executescript() ignores isolation_level and may
    # conflict with WAL/foreign_keys pragmas set mid-transaction.
    # The get_conn() context manager sets these on every connection.
    ddl_only = "\n".join(
        line for line in schema.splitlines()
        if not line.strip().upper().startswith("PRAGMA")
    )
    with sqlite3.connect(get_db_path(), timeout=15.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=OFF")  # off during bulk DDL to avoid ordering issues
        conn.executescript(ddl_only)
        conn.execute("PRAGMA foreign_keys=ON")


def get_tactics_db_path() -> Path:
    """Path to the separate tactics intelligence SQLite database."""
    db = Path(settings.database_path)
    path = db.parent / "tactics_intel.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_tactics_checkpoints_path() -> Path:
    """Separate SQLite file for tactics pipeline LangGraph checkpoints."""
    path = get_tactics_db_path().parent / "tactics_intel_checkpoints.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def init_tactics_db() -> None:
    """Initialize the tactics database schema."""
    schema_path = Path(__file__).parent / "tactics_schema.sql"
    with open(schema_path) as f:
        schema = f.read()
    with sqlite3.connect(get_tactics_db_path(), timeout=15.0, isolation_level=None) as conn:
        conn.executescript(schema)


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for a SQLite connection with row_factory."""
    # isolation_level=None enables SQLite autocommit mode, dodging Python's implicit BEGIN
    # which causes 'database is locked' errors under asyncio concurrency.
    conn = sqlite3.connect(get_db_path(), detect_types=sqlite3.PARSE_DECLTYPES, timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")  # wait up to 30 s before raising locked error
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_tactics_conn() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for a SQLite connection to the tactics database."""
    conn = sqlite3.connect(get_tactics_db_path(), detect_types=sqlite3.PARSE_DECLTYPES,
                           timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
    finally:
        conn.close()
