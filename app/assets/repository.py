"""Async CRUD repository for energy assets — issue #9.

Uses SQLAlchemy 2.x async session. Serialises/deserialises between the
``Asset`` ORM row (JSON ``config`` column) and the typed Pydantic models.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import AnyAsset, AssetType, BatteryAsset, DemandResponseAsset, GeneratorAsset
from app.db.models import Asset

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ASSET_TYPE_MAP: dict[str, type[AnyAsset]] = {
    AssetType.GENERATOR.value: GeneratorAsset,
    AssetType.BATTERY.value: BatteryAsset,
    AssetType.DEMAND_RESPONSE.value: DemandResponseAsset,
}


def _orm_to_pydantic(row: Asset) -> AnyAsset:
    """Deserialise an ORM row back to the appropriate Pydantic asset model."""
    cls = _ASSET_TYPE_MAP[str(row.asset_type)]
    return cls.model_validate(row.config)


def _pydantic_to_orm(asset: AnyAsset, existing: Asset | None = None) -> Asset:
    """Serialise a Pydantic asset model into an ORM row (or update an existing one)."""
    config = asset.model_dump()
    if existing is not None:
        existing.asset_type = asset.asset_type.value  # type: ignore[assignment]
        existing.name = asset.name  # type: ignore[assignment]
        existing.config = config  # type: ignore[assignment]
        return existing
    return Asset(
        asset_type=asset.asset_type.value,
        name=asset.name,
        config=config,
    )


# ---------------------------------------------------------------------------
# Public CRUD API
# ---------------------------------------------------------------------------


async def create_asset(session: AsyncSession, asset: AnyAsset) -> uuid.UUID:
    """Persist a new asset and return its generated UUID."""
    row = _pydantic_to_orm(asset)
    session.add(row)
    await session.commit()
    return uuid.UUID(str(row.id))


async def get_asset(session: AsyncSession, asset_id: uuid.UUID) -> AnyAsset | None:
    """Return the asset with the given ID, or None if not found."""
    result = await session.execute(select(Asset).where(Asset.id == str(asset_id)))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return _orm_to_pydantic(row)


async def list_assets(
    session: AsyncSession,
    asset_type: AssetType | None = None,
) -> list[AnyAsset]:
    """Return all assets, optionally filtered by ``asset_type``."""
    stmt = select(Asset)
    if asset_type is not None:
        stmt = stmt.where(Asset.asset_type == asset_type.value)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_orm_to_pydantic(row) for row in rows]


async def update_asset(
    session: AsyncSession,
    asset_id: uuid.UUID,
    asset: AnyAsset,
) -> bool:
    """Update an existing asset in-place.

    Returns True if the record was found and updated, False otherwise.
    """
    result = await session.execute(select(Asset).where(Asset.id == str(asset_id)))
    row = result.scalar_one_or_none()
    if row is None:
        return False
    _pydantic_to_orm(asset, existing=row)
    await session.commit()
    return True


async def delete_asset(session: AsyncSession, asset_id: uuid.UUID) -> bool:
    """Delete an asset by ID.

    Returns True if the record was found and deleted, False otherwise.
    """
    result = await session.execute(select(Asset).where(Asset.id == str(asset_id)))
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True
