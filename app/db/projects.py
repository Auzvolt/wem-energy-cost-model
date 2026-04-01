"""CRUD helpers for Project, Site and Scenario ORM models.

All functions are synchronous and accept a SQLAlchemy Session.
Callers are responsible for committing or rolling back.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Project, Scenario, Site

# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------


def list_projects(session: Session) -> list[Project]:
    """Return all projects ordered by name."""
    return session.query(Project).order_by(Project.name).all()


def get_project(session: Session, project_id: int) -> Project | None:
    """Return a single project by primary key, or None."""
    return session.get(Project, project_id)


def create_project(session: Session, name: str, description: str = "") -> Project:
    """Create and persist a new project.

    Args:
        session: Active SQLAlchemy session.
        name: Human-readable project name (must be non-empty).
        description: Optional project description.

    Returns:
        The newly created and flushed Project instance.

    Raises:
        ValueError: If name is blank.
    """
    if not name.strip():
        raise ValueError("Project name must not be empty.")
    project = Project(name=name.strip(), description=description)
    session.add(project)
    session.flush()
    return project


def rename_project(session: Session, project_id: int, name: str) -> Project:
    """Rename an existing project.

    Args:
        session: Active SQLAlchemy session.
        project_id: Primary key of the project to rename.
        name: New name (must be non-empty).

    Returns:
        The updated Project instance.

    Raises:
        ValueError: If project not found or name is blank.
    """
    if not name.strip():
        raise ValueError("Project name must not be empty.")
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError(f"Project {project_id} not found.")
    project.name = name.strip()  # type: ignore[assignment]
    session.flush()
    return project


def delete_project(session: Session, project_id: int) -> None:
    """Delete a project and its cascade-deleted children (sites, scenarios).

    Args:
        session: Active SQLAlchemy session.
        project_id: Primary key of the project to delete.

    Raises:
        ValueError: If project not found.
    """
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError(f"Project {project_id} not found.")
    session.delete(project)
    session.flush()


# ---------------------------------------------------------------------------
# Site CRUD
# ---------------------------------------------------------------------------


def list_sites(session: Session, project_id: int) -> list[Site]:
    """Return all sites for a project ordered by name."""
    return session.query(Site).filter(Site.project_id == project_id).order_by(Site.name).all()


def create_site(
    session: Session,
    project_id: int,
    name: str,
    nmi: str | None = None,
) -> Site:
    """Add a new site to a project.

    Args:
        session: Active SQLAlchemy session.
        project_id: Parent project primary key.
        name: Human-readable site name.
        nmi: Optional National Metering Identifier.

    Returns:
        The newly created and flushed Site instance.

    Raises:
        ValueError: If name is blank or parent project not found.
    """
    if not name.strip():
        raise ValueError("Site name must not be empty.")
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError(f"Project {project_id} not found.")
    site = Site(project_id=project_id, name=name.strip(), nmi=nmi or None)
    session.add(site)
    session.flush()
    return site


def delete_site(session: Session, site_id: int) -> None:
    """Delete a site.

    Args:
        session: Active SQLAlchemy session.
        site_id: Primary key of the site to delete.

    Raises:
        ValueError: If site not found.
    """
    site = session.get(Site, site_id)
    if site is None:
        raise ValueError(f"Site {site_id} not found.")
    session.delete(site)
    session.flush()


# ---------------------------------------------------------------------------
# Scenario CRUD
# ---------------------------------------------------------------------------


def list_scenarios(session: Session, project_id: int) -> list[Scenario]:
    """Return all scenarios for a project ordered by name."""
    return (
        session.query(Scenario)
        .filter(Scenario.project_id == project_id)
        .order_by(Scenario.name)
        .all()
    )


def create_scenario(
    session: Session,
    project_id: int,
    name: str,
    clone_from_id: int | None = None,
) -> Scenario:
    """Create a new scenario, optionally cloning config from an existing one.

    Args:
        session: Active SQLAlchemy session.
        project_id: Parent project primary key.
        name: Human-readable scenario name.
        clone_from_id: Optional ID of a scenario whose config JSON to copy.

    Returns:
        The newly created and flushed Scenario instance.

    Raises:
        ValueError: If name is blank or parent project not found.
    """
    if not name.strip():
        raise ValueError("Scenario name must not be empty.")
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError(f"Project {project_id} not found.")

    config: dict = {}
    if clone_from_id is not None:
        source = session.get(Scenario, clone_from_id)
        if source is not None and source.config:
            import copy

            config = copy.deepcopy(source.config)  # type: ignore[arg-type]

    scenario = Scenario(project_id=project_id, name=name.strip(), config=config)
    session.add(scenario)
    session.flush()
    return scenario


def delete_scenario(session: Session, scenario_id: int) -> None:
    """Delete a scenario.

    Args:
        session: Active SQLAlchemy session.
        scenario_id: Primary key of the scenario to delete.

    Raises:
        ValueError: If scenario not found.
    """
    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise ValueError(f"Scenario {scenario_id} not found.")
    session.delete(scenario)
    session.flush()
