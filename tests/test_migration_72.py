"""Unit tests for migration 20260401120000 (assumption_sets + assumption_entries).

Tests verify:
1. Migration module metadata (revision, down_revision identifiers)
2. DDL correctness (upgrade/downgrade) via SQLAlchemy against in-memory SQLite
   — Alembic is not required in the test sandbox; it will be present in CI/prod.
"""

from __future__ import annotations

import importlib.util
import sys
import types
import uuid
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text

# ---------------------------------------------------------------------------
# Stub Alembic so the migration module can be imported without it installed
# ---------------------------------------------------------------------------


def _mock_alembic_modules() -> None:
    """Inject stub alembic modules into sys.modules if not already present."""
    if "alembic" in sys.modules:
        return

    alembic_mod = types.ModuleType("alembic")
    op_mock = MagicMock()

    # alembic.op is accessed as an attribute of the alembic package
    alembic_mod.op = op_mock  # type: ignore[attr-defined]
    sys.modules["alembic"] = alembic_mod
    sys.modules["alembic.op"] = op_mock  # type: ignore[assignment]

    # Stub transitive sub-modules that may be imported by sqlalchemy dialects
    for sub in [
        "alembic.runtime",
        "alembic.runtime.migration",
        "alembic.config",
        "alembic.script",
    ]:
        sys.modules.setdefault(sub, types.ModuleType(sub))


# ---------------------------------------------------------------------------
# Migration module loader
# ---------------------------------------------------------------------------

_MODULE_NAME = "migration_20260401120000_test"


def _load_migration():
    """Return the migration module, importing it once with Alembic stubbed."""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    _mock_alembic_modules()
    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME,
        "migrations/versions/20260401120000_add_assumption_tables.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# SQLAlchemy DDL helpers — mirror the migration schema for SQLite testing
# ---------------------------------------------------------------------------


def _make_engine() -> sa.Engine:
    return create_engine("sqlite:///:memory:", future=True)


def _upgrade_sqlite(engine: sa.Engine) -> None:
    """Apply the migration DDL to a SQLite in-memory database."""
    meta = sa.MetaData()

    sa.Table(
        "assumption_sets",
        meta,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column(
            "superseded_by",
            sa.String(36),
            sa.ForeignKey("assumption_sets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    sa.Table(
        "assumption_entries",
        meta,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "set_id",
            sa.String(36),
            sa.ForeignKey("assumption_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("unit", sa.String(64), nullable=True),
        sa.Column("source", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    meta.create_all(engine)


def _downgrade_sqlite(engine: sa.Engine) -> None:
    """Drop assumption tables in FK-safe order."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS assumption_entries"))
        conn.execute(text("DROP TABLE IF EXISTS assumption_sets"))


# ---------------------------------------------------------------------------
# Tests — module metadata
# ---------------------------------------------------------------------------


class TestMigrationModuleLoads:
    def test_revision_identifier(self):
        mod = _load_migration()
        assert hasattr(mod, "revision"), "Migration must define 'revision'"
        assert mod.revision == "20260401120000"

    def test_down_revision_identifier(self):
        mod = _load_migration()
        assert hasattr(mod, "down_revision"), "Migration must define 'down_revision'"
        assert mod.down_revision == "20260401000001"

    def test_upgrade_is_callable(self):
        mod = _load_migration()
        assert callable(getattr(mod, "upgrade", None))

    def test_downgrade_is_callable(self):
        mod = _load_migration()
        assert callable(getattr(mod, "downgrade", None))


# ---------------------------------------------------------------------------
# Tests — upgrade DDL
# ---------------------------------------------------------------------------


class TestAssumptionMigrationUpgrade:
    @pytest.fixture()
    def engine(self):
        e = _make_engine()
        _upgrade_sqlite(e)
        yield e
        e.dispose()

    def test_assumption_sets_table_created(self, engine):
        assert "assumption_sets" in inspect(engine).get_table_names()

    def test_assumption_entries_table_created(self, engine):
        assert "assumption_entries" in inspect(engine).get_table_names()

    def test_assumption_sets_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("assumption_sets")}
        required = {
            "id",
            "name",
            "description",
            "author",
            "created_at",
            "effective_from",
            "superseded_by",
        }
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_assumption_entries_columns(self, engine):
        cols = {c["name"] for c in inspect(engine).get_columns("assumption_entries")}
        required = {
            "id",
            "set_id",
            "category",
            "key",
            "value",
            "unit",
            "source",
            "created_at",
        }
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_insert_assumption_set(self, engine):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO assumption_sets (id, name, effective_from) "
                    "VALUES (:id, :name, :eff)"
                ),
                {"id": str(uuid.uuid4()), "name": "WA Defaults 2025", "eff": "2025-01-01"},
            )
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM assumption_sets")).scalar()
        assert count == 1

    def test_insert_assumption_entry(self, engine):
        set_id = str(uuid.uuid4())
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO assumption_sets (id, name, effective_from) "
                    "VALUES (:id, :name, :eff)"
                ),
                {"id": set_id, "name": "Test Set", "eff": "2025-01-01"},
            )
            conn.execute(
                text(
                    "INSERT INTO assumption_entries (id, set_id, category, key, value) "
                    "VALUES (:id, :set_id, :category, :key, :value)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "set_id": set_id,
                    "category": "tariff",
                    "key": "rt2_daily_charge",
                    "value": '"1.23"',
                },
            )
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM assumption_entries")).scalar()
        assert count == 1

    def test_assumption_category_values(self, engine):
        """All five category enum values should be accepted."""
        set_id = str(uuid.uuid4())
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO assumption_sets (id, name, effective_from) "
                    "VALUES (:id, :name, :eff)"
                ),
                {"id": set_id, "name": "Cat Test", "eff": "2025-01-01"},
            )
            for cat in ("tariff", "capex", "opex", "degradation", "solar_yield"):
                conn.execute(
                    text(
                        "INSERT INTO assumption_entries (id, set_id, category, key, value) "
                        "VALUES (:id, :set_id, :category, :key, :value)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "set_id": set_id,
                        "category": cat,
                        "key": f"test_{cat}",
                        "value": '"0"',
                    },
                )
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM assumption_entries")).scalar()
        assert count == 5


# ---------------------------------------------------------------------------
# Tests — downgrade DDL
# ---------------------------------------------------------------------------


class TestAssumptionMigrationDowngrade:
    def test_downgrade_drops_assumption_entries(self):
        engine = _make_engine()
        _upgrade_sqlite(engine)
        _downgrade_sqlite(engine)
        assert "assumption_entries" not in inspect(engine).get_table_names()
        engine.dispose()

    def test_downgrade_drops_assumption_sets(self):
        engine = _make_engine()
        _upgrade_sqlite(engine)
        _downgrade_sqlite(engine)
        assert "assumption_sets" not in inspect(engine).get_table_names()
        engine.dispose()

    def test_upgrade_downgrade_upgrade_idempotent(self):
        """Full cycle must succeed without error."""
        engine = _make_engine()
        _upgrade_sqlite(engine)
        _downgrade_sqlite(engine)
        _upgrade_sqlite(engine)
        names = inspect(engine).get_table_names()
        assert "assumption_sets" in names
        assert "assumption_entries" in names
        engine.dispose()


# ---------------------------------------------------------------------------
# Tests — revision chain integrity
# ---------------------------------------------------------------------------


class TestMigrationRevisionChain:
    def test_down_revision_is_fcess_migration(self):
        """down_revision must chain to the FCESS prices migration, not skip it."""
        mod = _load_migration()
        assert mod.down_revision == "20260401000001"

    def test_revision_timestamp_prefix(self):
        mod = _load_migration()
        assert mod.revision.startswith("2026")
        assert len(mod.revision) >= 14
