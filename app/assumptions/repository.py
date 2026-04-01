"""Assumption library repository — async CRUD and versioned retrieval.

Provides database access for assumption sets and entries using SQLAlchemy async.
Every mutating operation calls ``log_change_async()`` within the same session
so audit rows are committed atomically with the data change.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assumptions.audit import log_change_async
from app.assumptions.models import AssumptionCategory, AssumptionEntry, AssumptionSet

# ---------------------------------------------------------------------------
# ORM table references (imported from db.models once available)
# The repository uses raw SQL-compatible queries via SQLAlchemy core/ORM.
# ---------------------------------------------------------------------------


async def get_active_set(session: AsyncSession, as_of_date: date) -> AssumptionSet | None:
    """Retrieve the active assumption set as of a given date.

    The active set is the one where:
    - effective_from <= as_of_date
    - superseded_by IS NULL (not yet superseded)

    If multiple sets qualify, the most recent effective_from wins.

    Args:
        session: SQLAlchemy async session.
        as_of_date: The date for which to retrieve active assumptions.

    Returns:
        The active AssumptionSet, or None if no sets exist.
    """
    # Import here to avoid circular imports during early scaffold phase
    from db.assumption_orm import AssumptionEntryORM, AssumptionSetORM  # noqa: PLC0415

    stmt = (
        select(AssumptionSetORM)
        .where(
            AssumptionSetORM.effective_from <= as_of_date,
            AssumptionSetORM.superseded_by.is_(None),
        )
        .order_by(AssumptionSetORM.effective_from.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None

    # Load entries
    entries_stmt = select(AssumptionEntryORM).where(AssumptionEntryORM.set_id == row.id)
    entries_result = await session.execute(entries_stmt)
    entries = [
        AssumptionEntry.model_validate(e, from_attributes=True)
        for e in entries_result.scalars().all()
    ]

    return AssumptionSet(
        id=row.id,
        name=row.name,
        description=row.description,
        author=row.author,
        created_at=row.created_at,
        effective_from=row.effective_from,
        superseded_by=row.superseded_by,
        entries=entries,
    )


async def create_assumption_set(
    session: AsyncSession,
    name: str,
    effective_from: date,
    description: str | None = None,
    author: str | None = None,
    supersede_current: bool = True,
    actor: str = "system",
) -> AssumptionSet:
    """Create a new assumption set, optionally superseding the current active set.

    An audit row (``create``) is inserted atomically in the same transaction.

    If supersede_current=True and there is an active set, sets ``superseded_by``
    on the old set to the new set's ID.

    Args:
        session: SQLAlchemy async session.
        name: Human-readable name for the set.
        effective_from: Date from which this set becomes active.
        description: Optional description.
        author: Optional author identifier.
        supersede_current: Whether to supersede the currently active set.
        actor: Opaque user/process identifier for the audit record.

    Returns:
        The newly created AssumptionSet (not yet flushed to DB).
    """
    from db.assumption_orm import AssumptionSetORM  # noqa: PLC0415

    new_id = uuid.uuid4()
    now = datetime.utcnow()

    # Supersede the current active set if requested
    if supersede_current:
        await session.execute(
            update(AssumptionSetORM)
            .where(AssumptionSetORM.superseded_by.is_(None))
            .where(AssumptionSetORM.effective_from <= effective_from)
            .values(superseded_by=new_id)
        )

    new_orm = AssumptionSetORM(
        id=new_id,
        name=name,
        description=description,
        author=author,
        created_at=now,
        effective_from=effective_from,
        superseded_by=None,
    )
    session.add(new_orm)
    await session.flush()

    # Audit: record creation within the same transaction
    await log_change_async(
        set_id=new_id,
        operation="create",
        actor=actor,
        new_value={"name": name, "effective_from": str(effective_from)},
        session=session,
    )

    return AssumptionSet(
        id=new_id,
        name=name,
        description=description,
        author=author,
        created_at=now,
        effective_from=effective_from,
        superseded_by=None,
        entries=[],
    )


async def add_entry(
    session: AsyncSession,
    set_id: uuid.UUID,
    category: AssumptionCategory,
    key: str,
    value: object,
    unit: str | None = None,
    source: str | None = None,
    actor: str = "system",
) -> AssumptionEntry:
    """Add an assumption entry to an existing set.

    An audit row (``create``) is inserted atomically in the same transaction.

    Args:
        session: SQLAlchemy async session.
        set_id: UUID of the parent assumption set.
        category: Category enum value.
        key: String identifier for the assumption.
        value: JSON-serialisable value.
        unit: Optional unit label.
        source: Optional provenance label.
        actor: Opaque user/process identifier for the audit record.

    Returns:
        The newly created AssumptionEntry.
    """
    from db.assumption_orm import AssumptionEntryORM  # noqa: PLC0415

    entry_id = uuid.uuid4()
    now = datetime.utcnow()

    orm_entry = AssumptionEntryORM(
        id=entry_id,
        set_id=set_id,
        category=category.value,
        key=key,
        value=value,
        unit=unit,
        source=source,
        created_at=now,
    )
    session.add(orm_entry)
    await session.flush()

    # Audit: record entry creation within the same transaction
    await log_change_async(
        set_id=set_id,
        operation="create",
        actor=actor,
        entry_id=entry_id,
        new_value={"category": category.value, "key": key, "value": value},
        session=session,
    )

    return AssumptionEntry(
        id=entry_id,
        set_id=set_id,
        category=category,
        key=key,
        value=value,
        unit=unit,
        source=source,
        created_at=now,
    )


async def get_entries_by_category(
    session: AsyncSession,
    set_id: uuid.UUID,
    category: AssumptionCategory,
) -> list[AssumptionEntry]:
    """Retrieve all entries of a given category from an assumption set."""
    from db.assumption_orm import AssumptionEntryORM  # noqa: PLC0415

    stmt = select(AssumptionEntryORM).where(
        AssumptionEntryORM.set_id == set_id,
        AssumptionEntryORM.category == category.value,
    )
    result = await session.execute(stmt)
    return [
        AssumptionEntry.model_validate(row, from_attributes=True) for row in result.scalars().all()
    ]
