"""Database seed entrypoint.

Run with:
    python -m db.seed

Or called automatically on startup if SEED_ON_STARTUP=true.
"""
from __future__ import annotations

import asyncio
import os
import sys


async def main() -> None:
    seed_on_startup = os.environ.get("SEED_ON_STARTUP", "false").lower() == "true"
    if not seed_on_startup and "--force" not in sys.argv:
        print("Skipping seed — set SEED_ON_STARTUP=true or pass --force to seed.")
        return

    try:
        from db.session import AsyncSessionFactory  # type: ignore[import]
    except ImportError:
        print("WARNING: db.session not available — skipping seed.")
        return

    from app.assumptions.seeds import seed_wa_defaults

    async with AsyncSessionFactory() as session:
        async with session.begin():
            inserted = await seed_wa_defaults(session)
            if inserted:
                print("Seeded WA Market Defaults 2025.")
            else:
                print("Seed already present — skipped.")


if __name__ == "__main__":
    asyncio.run(main())
