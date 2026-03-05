"""
test_db_model.py — State-of-the-Art Validation Suite
=====================================================
Validates that the backend SQLAlchemy models (db_model.py) are perfectly
aligned with the PostgreSQL schema managed by Prisma migrations.

Run from the backend/ directory:
    python test_db_model.py                       # full suite
    python test_db_model.py --verbose             # extra detail per check
    python test_db_model.py --db-url "postgresql+psycopg2://user:pass@host:port/db"

Connection resolution (in order):
    1. --db-url CLI argument              (highest priority)
    2. TEST_DATABASE_URL env var
    3. DATABASE_URL from creds/.env       (auto-rewrites Docker hostname)

The script auto-detects Docker-internal hostnames (e.g. "postgres") and
rewrites them to "localhost" so tests work outside the container network.

Prerequisites:
    - PostgreSQL running (via docker-compose or Supabase)
    - Prisma migrations applied (`npx prisma migrate deploy`)
    - Backend .env configured with valid DATABASE_URL

Exit codes:
    0 = all checks passed
    1 = one or more checks failed
"""

from __future__ import annotations

import os
import re
import sys
import uuid
import time
import argparse
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set, Tuple
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.engine import Engine

# ── Local imports (backend modules) ──────────────────────────────────────────
from db import normalize_sync_database_url
from config import settings
from db_model import (
    Base,
    Auth,
    UrlEntry,
    UrlStatus,
    IndexAction,
    IndexTask,
)

# Docker-internal hostnames that should be rewritten to localhost
DOCKER_HOSTNAMES = {"postgres", "db", "database", "pg", "postgresql"}

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Prisma-generated table names (source of truth)
EXPECTED_TABLES: Set[str] = {
    "Auth",
    "UrlEntry",
    "IndexTask",
    "Session",
    "ShopFeatureStates",
    "_prisma_migrations",
}

# Tables that the backend SQLAlchemy models manage (subset of above)
BACKEND_TABLES: Set[str] = {"Auth", "UrlEntry", "IndexTask"}

# Prisma-generated enum types
EXPECTED_ENUMS: Dict[str, List[str]] = {
    "UrlStatus": ["PENDING", "PROCESSING", "COMPLETED", "FAILED"],
    "IndexAction": ["INDEX", "DELETE", "IGNORE"],
}

# Full column spec per table: (col_name, pg_type_prefix, nullable, has_default)
# pg_type_prefix is matched case-insensitively against the start of the PG type
AUTH_COLUMNS: List[Tuple[str, str, bool, bool]] = [
    ("id",           "uuid",                  False, False),  # Prisma generates UUID client-side
    ("shop",         "text",                  False, False),
    ("googleConfig", "text",                  True,  False),
    ("bingApiKey",   "text",                  True,  False),
    ("settings",     "json",                  False, False),
    ("createdAt",    "timestamp",             False, True),
    ("updatedAt",    "timestamp",             False, False),
]

URLENTRY_COLUMNS: List[Tuple[str, str, bool, bool]] = [
    ("id",              "uuid",       False, False),  # Prisma generates UUID client-side
    ("shop",            "text",       False, False),
    ("baseId",          "bigint",     False, False),
    ("webUrl",          "text",       False, False),
    ("indexAction",     "varchar|indexaction", False, True),   # Prisma enum: native enum or varchar
    ("status",          "varchar|urlstatus",  False, True),    # Prisma enum: native enum or varchar
    ("attempts",        "integer",    False, True),
    ("isGoogleIndexed", "boolean",    False, True),
    ("isBingIndexed",   "boolean",    False, True),
    ("submittedAt",     "timestamp",  False, True),
    ("lastEventAt",     "timestamp",  False, False),
    ("lastTriedAt",     "timestamp",  True,  False),
    ("lastIndexedAt",   "timestamp",  False, True),
    ("metadata",        "json",       True,  False),
]

INDEXTASK_COLUMNS: List[Tuple[str, str, bool, bool]] = [
    ("id",          "bigint",    False, True),
    ("shop",        "text",      False, False),
    ("url",         "text",      False, False),
    ("isCompleted", "boolean",   False, True),
    ("createdAt",   "timestamp", False, True),
    ("completedAt", "timestamp", True,  False),
]

# Expected unique constraints per table (set of frozensets of column names)
EXPECTED_UNIQUE: Dict[str, List[Set[str]]] = {
    "Auth":      [{"shop"}],
    "UrlEntry":  [{"shop", "webUrl"}, {"shop", "baseId"}],
    "IndexTask": [{"shop", "url"}],
}

# Expected indexes per table (set of tuples of column names — order matters)
EXPECTED_INDEXES: Dict[str, List[Tuple[str, ...]]] = {
    "Auth": [
        ("shop",),
    ],
    "UrlEntry": [
        ("shop",),
        ("status",),
        ("indexAction",),
        ("lastIndexedAt", "attempts"),
        ("shop", "status", "lastIndexedAt", "attempts"),
    ],
    "IndexTask": [
        ("shop", "isCompleted"),
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# RESULT TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    duration_ms: float = 0.0


@dataclass
class SuiteResult:
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0

    def add(self, result: CheckResult):
        self.checks.append(result)


suite = SuiteResult()
VERBOSE = False


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def run_check(name: str, fn: Callable[[], str]) -> CheckResult:
    """Run a single check function, timing it and catching exceptions."""
    t0 = time.perf_counter()
    try:
        msg = fn()
        elapsed = (time.perf_counter() - t0) * 1000
        result = CheckResult(name=name, passed=True, message=msg, duration_ms=elapsed)
    except AssertionError as e:
        elapsed = (time.perf_counter() - t0) * 1000
        result = CheckResult(name=name, passed=False, message=str(e), duration_ms=elapsed)
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        result = CheckResult(
            name=name,
            passed=False,
            message=f"Unexpected error: {type(e).__name__}: {e}",
            duration_ms=elapsed,
        )
    suite.add(result)
    status = "✅ PASS" if result.passed else "❌ FAIL"
    print(f"  {status}  {name} ({result.duration_ms:.1f}ms)")
    if VERBOSE or not result.passed:
        for line in result.message.strip().split("\n"):
            print(f"         {line}")
    return result


def build_engine(db_url_override: Optional[str] = None) -> Engine:
    """
    Create a synchronous SQLAlchemy engine.

    Resolution order:
      1. db_url_override (--db-url CLI)
      2. TEST_DATABASE_URL env var
      3. DATABASE_URL from config (auto-rewrite Docker hostnames)
    """
    raw_url = (
        db_url_override
        or os.environ.get("TEST_DATABASE_URL")
        or settings.DATABASE_URL
    )

    url = normalize_sync_database_url(raw_url)
    url = _rewrite_docker_host(url)

    return create_engine(
        url,
        pool_pre_ping=True,
        future=True,
        connect_args={"connect_timeout": 10},
    )


def _rewrite_docker_host(url: str) -> str:
    """
    Replace Docker-internal hostnames (e.g. 'postgres') with '127.0.0.1'
    so the test works when run outside the Docker network.
    Also rewrites 'localhost' → '127.0.0.1' to force IPv4 and avoid
    IPv6 issues on Windows/WSL where Docker only binds to IPv4.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    needs_rewrite = hostname.lower() in DOCKER_HOSTNAMES or hostname.lower() == "localhost"
    if needs_rewrite:
        if parsed.port:
            new_netloc = f"{parsed.username}:{parsed.password}@127.0.0.1:{parsed.port}"
        else:
            new_netloc = f"{parsed.username}:{parsed.password}@127.0.0.1"
        rewritten = urlunparse(parsed._replace(netloc=new_netloc))
        return rewritten
    return url


def _display_url(url: str) -> str:
    """Mask password in URL for safe display."""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", url)


@contextmanager
def test_session(engine: Engine):
    """Provide a transactional session that rolls back after use."""
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SECTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_inspect(engine: Engine, section_name: str):
    """
    Try to get an Inspector, recording a FAIL check if connection fails.
    Returns the inspector or None.
    """
    try:
        return inspect(engine)
    except Exception as e:
        run_check(
            f"{section_name} — connect",
            lambda err=e: (_ for _ in ()).throw(
                AssertionError(f"Cannot inspect database: {type(err).__name__}: {err}")
            ),
        )
        return None


def tests_connectivity(engine: Engine) -> bool:
    """Section 1: Basic database connectivity. Returns True if DB is reachable."""
    print("\n━━━ Section 1: Connectivity ━━━")

    def check_ping():
        with engine.connect() as conn:
            row = conn.execute(text("SELECT 1 AS ok")).fetchone()
            assert row is not None and row[0] == 1, "SELECT 1 did not return expected result"
        return "Database is reachable"

    def check_version():
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version()")).fetchone()
            ver = row[0]
            assert "PostgreSQL" in ver, f"Unexpected version string: {ver}"
        return f"Server: {ver.split(',')[0]}"

    def check_current_database():
        with engine.connect() as conn:
            row = conn.execute(text("SELECT current_database()")).fetchone()
            db = row[0]
        return f"Connected to database: {db}"

    ping_result = run_check("Database ping", check_ping)

    if not ping_result.passed:
        # Diagnose the issue
        err_msg = ping_result.message.lower()
        print("\n  ┌─────────────────────────────────────────────────────────┐")
        if "password authentication failed" in err_msg:
            print("  │  DIAGNOSIS: PostgreSQL is reachable but rejecting      │")
            print("  │  credentials. Likely causes:                           │")
            print("  │    • Docker container 'indexer-postgres' is NOT running│")
            print("  │      and a different PostgreSQL is on port 5432        │")
            print("  │    • Password was changed after initial volume creation│")
            print("  │  FIX: cd backend && docker-compose up -d              │")
        elif "could not translate host name" in err_msg or "name or service not known" in err_msg:
            print("  │  DIAGNOSIS: Hostname cannot be resolved.               │")
            print("  │  FIX: Use --db-url with localhost, or ensure Docker is │")
            print("  │  running: cd backend && docker-compose up -d           │")
        elif "connection refused" in err_msg:
            print("  │  DIAGNOSIS: No PostgreSQL server on port 5432.         │")
            print("  │  FIX: cd backend && docker-compose up -d              │")
        else:
            print("  │  DIAGNOSIS: Unknown connectivity error.                │")
            print("  │  Check DATABASE_URL and PostgreSQL status.             │")
        print("  └─────────────────────────────────────────────────────────┘")
        # Still run version/db checks to record them, but return False
        run_check("PostgreSQL version", check_version)
        run_check("Current database", check_current_database)
        return False

    run_check("PostgreSQL version", check_version)
    run_check("Current database", check_current_database)
    return True


def tests_table_existence(engine: Engine):
    """Section 2: Verify all expected tables exist."""
    print("\n━━━ Section 2: Table Existence ━━━")
    inspector = _safe_inspect(engine, "Table Existence")
    if inspector is None:
        return
    actual_tables = set(inspector.get_table_names())

    for table in sorted(EXPECTED_TABLES):
        def check(t=table):
            assert t in actual_tables, (
                f"Table '{t}' missing from database. "
                f"Found: {sorted(actual_tables)}"
            )
            return f"Table '{t}' exists"
        run_check(f"Table '{table}' exists", check)


def tests_enum_types(engine: Engine):
    """Section 3: Verify PostgreSQL enum types and their labels."""
    print("\n━━━ Section 3: Enum Types ━━━")

    for enum_name, expected_labels in EXPECTED_ENUMS.items():
        def check(ename=enum_name, elabels=expected_labels):
            with engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT e.enumlabel "
                    "FROM pg_enum e "
                    "JOIN pg_type t ON e.enumtypid = t.oid "
                    "WHERE t.typname = :name "
                    "ORDER BY e.enumsortorder"
                ), {"name": ename}).fetchall()

                actual_labels = [r[0] for r in rows]
                assert len(actual_labels) > 0, (
                    f"Enum type '{ename}' not found in database"
                )
                assert actual_labels == elabels, (
                    f"Enum '{ename}' labels mismatch.\n"
                    f"  Expected: {elabels}\n"
                    f"  Actual:   {actual_labels}"
                )
            return f"Enum '{ename}' has labels: {actual_labels}"

        run_check(f"Enum '{enum_name}' type & labels", check)


def tests_columns(engine: Engine):
    """Section 4: Verify column names, types, nullability, defaults."""
    print("\n━━━ Section 4: Column Schema Validation ━━━")
    inspector = _safe_inspect(engine, "Column Schema")
    if inspector is None:
        return

    specs: Dict[str, List[Tuple[str, str, bool, bool]]] = {
        "Auth": AUTH_COLUMNS,
        "UrlEntry": URLENTRY_COLUMNS,
        "IndexTask": INDEXTASK_COLUMNS,
    }

    for table_name, col_specs in specs.items():
        raw_cols = inspector.get_columns(table_name)
        col_map: Dict[str, dict] = {c["name"]: c for c in raw_cols}

        # Check no extra / missing columns
        def check_column_set(t=table_name, expected=[c[0] for c in col_specs], actual=col_map):
            expected_set = set(expected)
            actual_set = set(actual.keys())
            missing = expected_set - actual_set
            extra = actual_set - expected_set
            msgs = []
            if missing:
                msgs.append(f"Missing columns: {sorted(missing)}")
            if extra:
                msgs.append(f"Extra columns: {sorted(extra)}")
            assert not msgs, f"Table '{t}': " + "; ".join(msgs)
            return f"Table '{t}' has exactly {len(expected)} expected columns"

        run_check(f"'{table_name}' column set", check_column_set)

        # Check each column's type, nullability, default
        for col_name, type_prefix, nullable, has_default in col_specs:
            def check_col(t=table_name, cn=col_name, tp=type_prefix, nl=nullable, hd=has_default):
                info = col_map.get(cn)
                assert info is not None, f"Column '{cn}' not found in table '{t}'"

                pg_type = str(info["type"]).lower()
                # Support pipe-separated type alternatives (e.g. "varchar|indexaction")
                type_alternatives = [alt.strip().lower() for alt in tp.split("|")]
                type_ok = any(pg_type.startswith(alt) for alt in type_alternatives)
                assert type_ok, (
                    f"Table '{t}'.{cn}: type mismatch. "
                    f"Expected starts with one of {type_alternatives}, got '{pg_type}'"
                )

                actual_nullable = info.get("nullable", True)
                assert actual_nullable == nl, (
                    f"Table '{t}'.{cn}: nullable mismatch. "
                    f"Expected nullable={nl}, got nullable={actual_nullable}"
                )

                actual_default = info.get("default")
                if hd:
                    assert actual_default is not None, (
                        f"Table '{t}'.{cn}: expected a server default but got None"
                    )
                return (
                    f"'{t}'.{cn} → type={pg_type}, nullable={actual_nullable}, "
                    f"default={'yes' if actual_default else 'no'}"
                )

            run_check(f"'{table_name}'.{col_name} schema", check_col)


def tests_primary_keys(engine: Engine):
    """Section 5: Verify primary key columns."""
    print("\n━━━ Section 5: Primary Keys ━━━")
    inspector = _safe_inspect(engine, "Primary Keys")
    if inspector is None:
        return

    expected_pks: Dict[str, List[str]] = {
        "Auth": ["id"],
        "UrlEntry": ["id"],
        "IndexTask": ["id"],
        "Session": ["id"],
        "ShopFeatureStates": ["id"],
    }

    for table, expected_cols in expected_pks.items():
        def check(t=table, exp=expected_cols):
            pk = inspector.get_pk_constraint(t)
            actual_cols = pk.get("constrained_columns", [])
            assert actual_cols == exp, (
                f"Table '{t}' PK mismatch. Expected {exp}, got {actual_cols}"
            )
            return f"Table '{t}' PK: {actual_cols}"
        run_check(f"'{table}' primary key", check)


def tests_unique_constraints(engine: Engine):
    """Section 6: Verify unique constraints (Prisma uses UNIQUE INDEX)."""
    print("\n━━━ Section 6: Unique Constraints ━━━")
    inspector = _safe_inspect(engine, "Unique Constraints")
    if inspector is None:
        return

    for table, expected_uniques in EXPECTED_UNIQUE.items():
        def check(t=table, exp=expected_uniques):
            # Prisma creates UNIQUE INDEX, not UNIQUE CONSTRAINT.
            # Check both: get_unique_constraints() and unique indexes from get_indexes().
            uqs = inspector.get_unique_constraints(t)
            actual_sets = [set(uq["column_names"]) for uq in uqs]

            # Also collect unique indexes
            indexes = inspector.get_indexes(t)
            for idx in indexes:
                if idx.get("unique", False):
                    actual_sets.append(set(idx["column_names"]))

            missing = []
            for eu in exp:
                if eu not in actual_sets:
                    missing.append(eu)
            assert not missing, (
                f"Table '{t}' missing unique constraints/indexes: {missing}\n"
                f"Found: {actual_sets}"
            )
            return f"Table '{t}' unique constraints/indexes: {[sorted(s) for s in actual_sets]}"
        run_check(f"'{table}' unique constraints", check)


def tests_indexes(engine: Engine):
    """Section 7: Verify indexes exist for expected column combinations."""
    print("\n━━━ Section 7: Indexes ━━━")
    inspector = _safe_inspect(engine, "Indexes")
    if inspector is None:
        return

    for table, expected_idxs in EXPECTED_INDEXES.items():
        def check(t=table, exp=expected_idxs):
            raw_indexes = inspector.get_indexes(t)
            # Collect column tuples for all indexes
            actual_idx_cols: List[Tuple[str, ...]] = [
                tuple(idx["column_names"]) for idx in raw_indexes
            ]
            missing = []
            for ei in exp:
                if ei not in actual_idx_cols:
                    missing.append(ei)
            assert not missing, (
                f"Table '{t}' missing indexes on: {missing}\n"
                f"Found index columns: {actual_idx_cols}"
            )
            return f"Table '{t}': all {len(exp)} expected indexes found"
        run_check(f"'{table}' indexes", check)


def tests_sqlalchemy_model_reflection(engine: Engine):
    """Section 8: Verify SQLAlchemy models can reflect against live DB."""
    print("\n━━━ Section 8: SQLAlchemy Model Reflection ━━━")

    for model_cls in [Auth, UrlEntry, IndexTask]:
        def check(cls=model_cls):
            table = cls.__table__
            # Verify mapped columns exist in the model
            col_names = {c.name for c in table.columns}
            assert len(col_names) > 0, f"Model {cls.__name__} has no columns mapped"

            # Attempt a reflected metadata comparison
            from sqlalchemy import MetaData
            meta = MetaData()
            meta.reflect(bind=engine, only=[table.name])
            reflected = meta.tables.get(table.name)
            assert reflected is not None, (
                f"Cannot reflect table '{table.name}' — it may not exist"
            )

            reflected_cols = {c.name for c in reflected.columns}
            model_cols = col_names
            missing_in_db = model_cols - reflected_cols
            assert not missing_in_db, (
                f"Model '{cls.__name__}' has columns not in DB: {missing_in_db}"
            )
            return (
                f"Model '{cls.__name__}' ↔ Table '{table.name}': "
                f"{len(model_cols)} model cols, {len(reflected_cols)} DB cols"
            )
        run_check(f"Model '{model_cls.__name__}' reflects", check)


def tests_crud_operations(engine: Engine):
    """Section 9: CRUD smoke tests (inside a rolled-back transaction)."""
    print("\n━━━ Section 9: CRUD Operations (transactional) ━━━")

    def check_auth_crud():
        with test_session(engine) as session:
            test_id = uuid.uuid4()
            auth = Auth(
                id=test_id,
                shop=f"test-{uuid.uuid4().hex[:8]}.myshopify.com",
                googleConfig=None,
                bingApiKey=None,
                settings={"googleLimit": 200, "bingLimit": 200},
                createdAt=datetime.now(timezone.utc),
                updatedAt=datetime.now(timezone.utc),
            )
            session.add(auth)
            session.flush()

            # Read back
            fetched = session.get(Auth, test_id)
            assert fetched is not None, "Auth INSERT+SELECT failed"
            assert fetched.shop == auth.shop, "Auth shop mismatch after read"
            assert isinstance(fetched.settings, dict), (
                f"Auth.settings should be dict, got {type(fetched.settings)}"
            )

            # Update
            fetched.bingApiKey = "test-key-123"
            session.flush()
            refetched = session.get(Auth, test_id)
            assert refetched.bingApiKey == "test-key-123", "Auth UPDATE failed"

            # to_dict sanity
            d = refetched.to_dict()
            assert "shop" in d and "settings" in d, "Auth.to_dict() missing keys"

        return "Auth: INSERT → SELECT → UPDATE → to_dict() all passed"

    def check_urlentry_crud():
        with test_session(engine) as session:
            test_id = uuid.uuid4()
            entry = UrlEntry(
                id=test_id,
                shop=f"test-{uuid.uuid4().hex[:8]}.myshopify.com",
                baseId=9999999,
                webUrl="https://example.com/test-product",
                indexAction=IndexAction.INDEX,
                status=UrlStatus.PENDING,
                attempts=2,
                isGoogleIndexed=False,
                isBingIndexed=False,
                submittedAt=datetime.now(timezone.utc),
                lastEventAt=datetime.now(timezone.utc),
                lastIndexedAt=datetime.now(timezone.utc),
            )
            session.add(entry)
            session.flush()

            fetched = session.get(UrlEntry, test_id)
            assert fetched is not None, "UrlEntry INSERT+SELECT failed"
            assert fetched.webUrl == "https://example.com/test-product"
            assert fetched.status == UrlStatus.PENDING, (
                f"UrlEntry.status mismatch: {fetched.status}"
            )
            assert fetched.indexAction == IndexAction.INDEX, (
                f"UrlEntry.indexAction mismatch: {fetched.indexAction}"
            )
            assert fetched.isGoogleIndexed is False
            assert fetched.isBingIndexed is False

            # Update status
            fetched.status = UrlStatus.COMPLETED
            fetched.isGoogleIndexed = True
            session.flush()
            refetched = session.get(UrlEntry, test_id)
            assert refetched.status == UrlStatus.COMPLETED, "UrlEntry status UPDATE failed"
            assert refetched.isGoogleIndexed is True, "UrlEntry isGoogleIndexed UPDATE failed"

        return "UrlEntry: INSERT → SELECT → UPDATE (status+flags) all passed"

    def check_indextask_crud():
        with test_session(engine) as session:
            task = IndexTask(
                shop=f"test-{uuid.uuid4().hex[:8]}.myshopify.com",
                url="https://example.com/test-task",
                isCompleted=False,
                createdAt=datetime.now(timezone.utc),
            )
            session.add(task)
            session.flush()

            # ID should be auto-generated
            assert task.id is not None, "IndexTask auto-increment ID not generated"
            assert isinstance(task.id, int), (
                f"IndexTask.id should be int, got {type(task.id)}"
            )

            # Update
            task.isCompleted = True
            task.completedAt = datetime.now(timezone.utc)
            session.flush()
            refetched = session.get(IndexTask, task.id)
            assert refetched.isCompleted is True, "IndexTask isCompleted UPDATE failed"
            assert refetched.completedAt is not None, "IndexTask completedAt UPDATE failed"

        return "IndexTask: INSERT → auto-ID → UPDATE (complete) all passed"

    run_check("Auth CRUD", check_auth_crud)
    run_check("UrlEntry CRUD", check_urlentry_crud)
    run_check("IndexTask CRUD", check_indextask_crud)


def tests_enum_round_trip(engine: Engine):
    """Section 10: Enum round-trip — write all enum values and read them back."""
    print("\n━━━ Section 10: Enum Round-Trip ━━━")

    def check_url_status_enum():
        with test_session(engine) as session:
            results = []
            for s in UrlStatus:
                eid = uuid.uuid4()
                shop = f"enum-test-{uuid.uuid4().hex[:8]}.myshopify.com"
                entry = UrlEntry(
                    id=eid,
                    shop=shop,
                    baseId=hash(shop) % (10**12),
                    webUrl=f"https://example.com/{s.value}",
                    status=s,
                    indexAction=IndexAction.INDEX,
                    submittedAt=datetime.now(timezone.utc),
                    lastEventAt=datetime.now(timezone.utc),
                    lastIndexedAt=datetime.now(timezone.utc),
                )
                session.add(entry)
                session.flush()
                fetched = session.get(UrlEntry, eid)
                assert fetched.status == s, (
                    f"UrlStatus round-trip failed for {s.value}: got {fetched.status}"
                )
                results.append(s.value)
        return f"All UrlStatus values round-tripped: {results}"

    def check_index_action_enum():
        with test_session(engine) as session:
            results = []
            for a in IndexAction:
                eid = uuid.uuid4()
                shop = f"enum-test-{uuid.uuid4().hex[:8]}.myshopify.com"
                entry = UrlEntry(
                    id=eid,
                    shop=shop,
                    baseId=hash(shop) % (10**12),
                    webUrl=f"https://example.com/{a.value}",
                    status=UrlStatus.PENDING,
                    indexAction=a,
                    submittedAt=datetime.now(timezone.utc),
                    lastEventAt=datetime.now(timezone.utc),
                    lastIndexedAt=datetime.now(timezone.utc),
                )
                session.add(entry)
                session.flush()
                fetched = session.get(UrlEntry, eid)
                assert fetched.indexAction == a, (
                    f"IndexAction round-trip failed for {a.value}: got {fetched.indexAction}"
                )
                results.append(a.value)
        return f"All IndexAction values round-tripped: {results}"

    run_check("UrlStatus enum round-trip", check_url_status_enum)
    run_check("IndexAction enum round-trip", check_index_action_enum)


def tests_query_patterns(engine: Engine):
    """Section 11: Validate actual query patterns used by workers."""
    print("\n━━━ Section 11: Worker Query Patterns ━━━")

    def check_l1_data_prep_query():
        """Simulates the query from layer_data_preparation.py fetch_auth_and_urls()."""
        from sqlalchemy import select

        with test_session(engine) as session:
            # This should not throw — validates the query compiles and runs
            stmt = (
                select(UrlEntry)
                .where(UrlEntry.shop == "nonexistent-shop.myshopify.com")
                .where(UrlEntry.status == UrlStatus.PENDING)
                .where(UrlEntry.isGoogleIndexed.is_(False))
                .where(UrlEntry.indexAction != IndexAction.IGNORE)
                .order_by(UrlEntry.attempts.desc())
                .limit(200)
            )
            results = session.execute(stmt).scalars().all()
            assert isinstance(results, list), "Query should return a list"
        return "L1 data-prep query compiles and executes cleanly"

    def check_l3_result_saving_query():
        """Simulates the update pattern from layer_result_saving.py."""
        with test_session(engine) as session:
            # Batch update query — should not throw
            updated = (
                session.query(UrlEntry)
                .filter(
                    UrlEntry.shop == "nonexistent-shop.myshopify.com",
                    UrlEntry.webUrl.in_(["https://example.com/a", "https://example.com/b"]),
                )
                .update(
                    {
                        UrlEntry.isGoogleIndexed: True,
                        UrlEntry.isBingIndexed: True,
                        UrlEntry.status: UrlStatus.COMPLETED,
                        UrlEntry.lastIndexedAt: datetime.now(timezone.utc),
                    },
                    synchronize_session=False,
                )
            )
            assert isinstance(updated, int), "Update should return affected row count"
        return "L3 result-saving batch update compiles and executes cleanly"

    def check_scheduler_auth_query():
        """Simulates the query from scheduler.py fetch_active_shops()."""
        from sqlalchemy import select

        with test_session(engine) as session:
            rows = session.execute(select(Auth.shop)).all()
            assert isinstance(rows, list), "Auth shop query should return a list"
        return "Scheduler auth-shop query compiles and executes cleanly"

    run_check("L1 data-prep query pattern", check_l1_data_prep_query)
    run_check("L3 result-saving update pattern", check_l3_result_saving_query)
    run_check("Scheduler auth-shop query pattern", check_scheduler_auth_query)


def tests_model_to_dict(engine: Engine):
    """Section 12: Validate serialization helpers."""
    print("\n━━━ Section 12: Serialization Helpers ━━━")

    def check_auth_to_dict():
        with test_session(engine) as session:
            auth = Auth(
                id=uuid.uuid4(),
                shop="serialization-test.myshopify.com",
                googleConfig="encrypted-config-data",
                bingApiKey="encrypted-bing-key",
                settings={"googleLimit": 200, "bingLimit": 100, "retryLimit": 3},
                createdAt=datetime.now(timezone.utc),
                updatedAt=datetime.now(timezone.utc),
            )
            session.add(auth)
            session.flush()

            fetched = session.get(Auth, auth.id)
            d = fetched.to_dict()

            required_keys = {"id", "shop", "googleConfig", "bingApiKey", "settings", "createdAt", "updatedAt"}
            missing = required_keys - set(d.keys())
            assert not missing, f"Auth.to_dict() missing keys: {missing}"

            # id should be a string (UUID serialized)
            assert isinstance(d["id"], str), f"Auth.to_dict()['id'] should be str, got {type(d['id'])}"

            # settings should be a dict
            assert isinstance(d["settings"], dict), (
                f"Auth.to_dict()['settings'] should be dict, got {type(d['settings'])}"
            )

            # Timestamps should be ISO strings
            assert isinstance(d["createdAt"], str), "createdAt should be ISO string"

        return "Auth.to_dict() returns correct structure with all keys"

    run_check("Auth.to_dict() structure", check_auth_to_dict)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    global VERBOSE

    parser = argparse.ArgumentParser(description="DB Model Validation Suite")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detail for passing checks")
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Override DATABASE_URL (e.g. postgresql+psycopg2://user:pass@localhost:5432/mydb)",
    )
    args = parser.parse_args()
    VERBOSE = args.verbose

    print("=" * 72)
    print("  DB MODEL VALIDATION SUITE")
    print("  Validates SQLAlchemy models against Prisma-managed PostgreSQL")
    print("=" * 72)
    print(f"  Timestamp : {datetime.now(timezone.utc).isoformat()}")

    t0 = time.perf_counter()

    try:
        engine = build_engine(args.db_url)
        print(f"  DB URL    : {_display_url(str(engine.url))}")
    except Exception as e:
        print(f"\n❌ FATAL: Cannot create database engine: {e}")
        sys.exit(1)

    print("=" * 72)

    # Run all test sections
    connected = tests_connectivity(engine)

    if not connected:
        print("\n" + "─" * 72)
        print("  ⏭  Skipping Sections 2–12 (database unreachable)")
        print("─" * 72)
    else:
        tests_table_existence(engine)
        tests_enum_types(engine)
        tests_columns(engine)
        tests_primary_keys(engine)
        tests_unique_constraints(engine)
        tests_indexes(engine)
        tests_sqlalchemy_model_reflection(engine)
        tests_crud_operations(engine)
        tests_enum_round_trip(engine)
        tests_query_patterns(engine)
        tests_model_to_dict(engine)

    elapsed = time.perf_counter() - t0

    # Print summary
    print("\n" + "=" * 72)
    print("  SUMMARY")
    print("=" * 72)
    print(f"  Total checks : {suite.total}")
    print(f"  Passed       : {suite.passed} ✅")
    print(f"  Failed       : {suite.failed} ❌")
    print(f"  Duration     : {elapsed:.2f}s")

    if suite.failed > 0:
        print("\n  ── Failed Checks ──")
        for c in suite.checks:
            if not c.passed:
                print(f"    ❌ {c.name}")
                for line in c.message.strip().split("\n"):
                    print(f"       {line}")

    print("=" * 72)

    if suite.all_passed:
        print("  🎉 ALL CHECKS PASSED — Models are production-ready")
    else:
        print(f"  ⚠️  {suite.failed} CHECK(S) FAILED — Fix before deploying")

    print("=" * 72)

    engine.dispose()
    sys.exit(0 if suite.all_passed else 1)


if __name__ == "__main__":
    main()
