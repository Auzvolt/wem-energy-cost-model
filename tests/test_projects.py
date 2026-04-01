"""Tests for app.db.projects CRUD helper functions."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base
from app.db.projects import (
    create_project,
    create_scenario,
    create_site,
    delete_project,
    delete_scenario,
    delete_site,
    get_project,
    list_projects,
    list_scenarios,
    list_sites,
    rename_project,
)


@pytest.fixture
def db() -> Session:
    """In-memory SQLite session with all ORM tables."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------


def test_create_and_list_projects(db: Session) -> None:
    assert list_projects(db) == []
    proj = create_project(db, "Test Project", "A description")
    db.commit()
    projects = list_projects(db)
    assert len(projects) == 1
    assert projects[0].name == "Test Project"
    assert projects[0].id == proj.id


def test_get_project(db: Session) -> None:
    proj = create_project(db, "Fetch Me")
    db.commit()
    fetched = get_project(db, int(proj.id))
    assert fetched is not None
    assert fetched.name == "Fetch Me"


def test_get_project_not_found(db: Session) -> None:
    result = get_project(db, 9999)
    assert result is None


def test_rename_project(db: Session) -> None:
    proj = create_project(db, "Old Name")
    db.commit()
    renamed = rename_project(db, int(proj.id), "New Name")
    db.commit()
    assert renamed.name == "New Name"
    assert get_project(db, int(proj.id)).name == "New Name"


def test_delete_project(db: Session) -> None:
    proj = create_project(db, "To Delete")
    db.commit()
    delete_project(db, int(proj.id))
    db.commit()
    assert get_project(db, int(proj.id)) is None
    assert list_projects(db) == []


# ---------------------------------------------------------------------------
# Site CRUD
# ---------------------------------------------------------------------------


def test_create_and_list_sites(db: Session) -> None:
    proj = create_project(db, "Site Project")
    db.commit()
    pid = int(proj.id)

    assert list_sites(db, pid) == []
    site = create_site(db, pid, "Main Site", nmi="6305000001")
    db.commit()
    sites = list_sites(db, pid)
    assert len(sites) == 1
    assert sites[0].name == "Main Site"
    assert sites[0].nmi == "6305000001"


def test_delete_site(db: Session) -> None:
    proj = create_project(db, "Proj")
    db.commit()
    pid = int(proj.id)
    site = create_site(db, pid, "Site A")
    db.commit()
    delete_site(db, int(site.id))
    db.commit()
    assert list_sites(db, pid) == []


# ---------------------------------------------------------------------------
# Scenario CRUD
# ---------------------------------------------------------------------------


def test_create_and_list_scenarios(db: Session) -> None:
    proj = create_project(db, "Scenario Project")
    db.commit()
    pid = int(proj.id)

    assert list_scenarios(db, pid) == []
    sc = create_scenario(db, pid, "Base Case")
    db.commit()
    scenarios = list_scenarios(db, pid)
    assert len(scenarios) == 1
    assert scenarios[0].name == "Base Case"


def test_clone_scenario(db: Session) -> None:
    proj = create_project(db, "Clone Project")
    db.commit()
    pid = int(proj.id)
    base = create_scenario(db, pid, "Base")
    db.commit()

    clone = create_scenario(db, pid, "Clone", clone_from_id=int(base.id))
    db.commit()
    scenarios = list_scenarios(db, pid)
    assert len(scenarios) == 2
    assert clone.name == "Clone"


def test_delete_scenario(db: Session) -> None:
    proj = create_project(db, "Del Proj")
    db.commit()
    pid = int(proj.id)
    sc = create_scenario(db, pid, "To Delete")
    db.commit()
    delete_scenario(db, int(sc.id))
    db.commit()
    assert list_scenarios(db, pid) == []


def test_delete_project_cascades_sites_and_scenarios(db: Session) -> None:
    proj = create_project(db, "Cascade")
    db.commit()
    pid = int(proj.id)
    create_site(db, pid, "Site X")
    create_scenario(db, pid, "SC X")
    db.commit()
    delete_project(db, pid)
    db.commit()
    assert list_sites(db, pid) == []
    assert list_scenarios(db, pid) == []
