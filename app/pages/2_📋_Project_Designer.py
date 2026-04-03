"""Project Designer page — configure projects, sites, assets, tariffs and scenarios."""

from __future__ import annotations

import streamlit as st

from app.db.models import ScenarioStatus
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
from app.db.session import SessionLocal
from app.ui.session import CURRENT_PROJECT_ID, USER_ROLE

st.set_page_config(page_title="Project Designer", layout="wide")

# ---------------------------------------------------------------------------
# Auth / role
# ---------------------------------------------------------------------------
role: str = st.session_state.get(USER_ROLE, "analyst")
is_admin: bool = role == "admin"

st.title("📋 Project Designer")

# ---------------------------------------------------------------------------
# Sidebar — project selector
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Projects")

    with SessionLocal() as _session:
        all_projects = list_projects(_session)

    project_names: dict[int, str] = {int(p.id): str(p.name) for p in all_projects}

    # Ensure current project id is still valid
    current_id: int | None = st.session_state.get(CURRENT_PROJECT_ID)
    if current_id not in project_names:
        current_id = int(all_projects[0].id) if all_projects else None
        st.session_state[CURRENT_PROJECT_ID] = current_id

    selected_id: int | None
    if project_names:
        selected_id = st.selectbox(
            "Active project",
            options=list(project_names.keys()),
            format_func=lambda pid: project_names[pid],
            index=list(project_names.keys()).index(current_id)
            if current_id in project_names
            else 0,
        )
        st.session_state[CURRENT_PROJECT_ID] = selected_id
    else:
        selected_id = None
        st.info("No projects yet. Create one below.")

    if is_admin:
        st.divider()
        with st.expander("➕ Create project"):
            new_name = st.text_input("Project name", key="new_project_name")
            new_desc = st.text_input("Description (optional)", key="new_project_desc")
            if st.button("Create", key="btn_create_project"):
                if new_name.strip():
                    with SessionLocal() as sess:
                        proj = create_project(sess, new_name.strip(), new_desc)
                        sess.commit()
                        st.session_state[CURRENT_PROJECT_ID] = proj.id
                    st.rerun()
                else:
                    st.error("Project name required.")

        if selected_id is not None:
            with st.expander("✏️ Rename project"):
                rename_val = st.text_input(
                    "New name",
                    value=project_names.get(selected_id, ""),
                    key="rename_project_val",
                )
                if st.button("Rename", key="btn_rename_project"):
                    if rename_val.strip():
                        with SessionLocal() as sess:
                            rename_project(sess, selected_id, rename_val.strip())
                            sess.commit()
                        st.rerun()
                    else:
                        st.error("Name required.")

            with st.expander("🗑️ Delete project"):
                st.warning(
                    f"Permanently delete **{project_names.get(selected_id, '')}** "
                    "and all its sites and scenarios?"
                )
                if st.button("Confirm delete", key="btn_delete_project", type="primary"):
                    with SessionLocal() as sess:
                        delete_project(sess, selected_id)
                        sess.commit()
                    st.session_state[CURRENT_PROJECT_ID] = None
                    st.rerun()
    else:
        st.caption("🔒 Read-only mode — admin required for project changes.")


# ---------------------------------------------------------------------------
# Main content — only shown when a project is selected
# ---------------------------------------------------------------------------
if selected_id is None:
    st.info("Create a project in the sidebar to get started.")
    st.stop()

assert selected_id is not None  # narrow type for mypy

with SessionLocal() as _session:
    active_project = get_project(_session, selected_id)

if active_project is None:
    st.error("Selected project could not be loaded.")
    st.stop()

assert active_project is not None  # narrow type for mypy

st.subheader(f"🗂️ {active_project.name}")
if active_project.description:
    st.caption(active_project.description)

tab_sites, tab_assets, tab_tariff, tab_scenarios = st.tabs(
    ["🏭 Sites", "🔋 Assets", "💡 Tariff", "📊 Scenarios"]
)

# ---------------------------------------------------------------------------
# Tab: Sites
# ---------------------------------------------------------------------------
with tab_sites:
    st.subheader("Sites")

    with SessionLocal() as sess:
        sites = list_sites(sess, selected_id)

    if sites:
        for site in sites:
            col_name, col_nmi, col_del = st.columns([3, 2, 1])
            col_name.write(site.name)
            col_nmi.write(site.nmi or "—")
            if is_admin and col_del.button("Delete", key=f"del_site_{site.id}"):
                with SessionLocal() as sess:
                    delete_site(sess, int(site.id))
                    sess.commit()
                st.rerun()
    else:
        st.info("No sites configured for this project.")

    if is_admin:
        st.divider()
        with st.expander("➕ Add site"):
            site_name = st.text_input("Site name", key="new_site_name")
            site_nmi = st.text_input("NMI (optional)", key="new_site_nmi")
            if st.button("Add site", key="btn_add_site"):
                if site_name.strip():
                    with SessionLocal() as sess:
                        create_site(sess, selected_id, site_name.strip(), site_nmi.strip() or None)
                        sess.commit()
                    st.rerun()
                else:
                    st.error("Site name required.")
    else:
        st.caption("🔒 Admin required to add or delete sites.")


# ---------------------------------------------------------------------------
# Tab: Assets
# ---------------------------------------------------------------------------
with tab_assets:
    st.subheader("Assets")
    st.info(
        "Asset library integration coming soon. You will be able to configure BESS, solar PV, genset, and EV charger assets here."
    )


# ---------------------------------------------------------------------------
# Tab: Tariff
# ---------------------------------------------------------------------------
with tab_tariff:
    st.subheader("Tariff")
    st.info(
        "Tariff selection coming soon. You will be able to link Western Power tariff schedules and loss factors to each site here."
    )


# ---------------------------------------------------------------------------
# Tab: Scenarios
# ---------------------------------------------------------------------------
with tab_scenarios:
    st.subheader("Scenarios")

    _STATUS_COLOURS: dict[str, str] = {
        ScenarioStatus.draft: "🟡",
        ScenarioStatus.running: "🔵",
        ScenarioStatus.complete: "🟢",
        ScenarioStatus.failed: "🔴",
    }

    with SessionLocal() as sess:
        scenarios = list_scenarios(sess, selected_id)

    if scenarios:
        for sc in scenarios:
            badge = _STATUS_COLOURS.get(sc.status, "⚪")
            col_name, col_status, col_del = st.columns([4, 1, 1])
            col_name.write(f"**{sc.name}**")
            col_status.write(
                f"{badge} {sc.status.value if hasattr(sc.status, 'value') else sc.status}"
            )
            if is_admin and col_del.button("Delete", key=f"del_sc_{sc.id}"):
                with SessionLocal() as sess2:
                    delete_scenario(sess2, int(sc.id))
                    sess2.commit()
                st.rerun()
    else:
        st.info("No scenarios yet for this project.")

    if is_admin:
        st.divider()
        col_new, col_clone = st.columns(2)

        with col_new, st.expander("➕ New scenario"):
            sc_name = st.text_input("Scenario name", key="new_sc_name")
            if st.button("Create", key="btn_create_sc"):
                if sc_name.strip():
                    with SessionLocal() as sess:
                        create_scenario(sess, selected_id, sc_name.strip())
                        sess.commit()
                    st.rerun()
                else:
                    st.error("Scenario name required.")

        with col_clone:
            if scenarios:
                with st.expander("📋 Clone scenario"):
                    sc_options: dict[int, str] = {int(sc.id): str(sc.name) for sc in scenarios}
                    clone_from = st.selectbox(
                        "Clone from",
                        options=list(sc_options.keys()),
                        format_func=lambda sid: sc_options[sid],
                        key="clone_sc_from",
                    )
                    clone_name = st.text_input("New scenario name", key="clone_sc_name")
                    if st.button("Clone", key="btn_clone_sc"):
                        if clone_name.strip():
                            with SessionLocal() as sess:
                                create_scenario(
                                    sess,
                                    selected_id,
                                    clone_name.strip(),
                                    clone_from_id=clone_from,
                                )
                                sess.commit()
                            st.rerun()
                        else:
                            st.error("New scenario name required.")
    else:
        st.caption("🔒 Admin required to create or delete scenarios.")
