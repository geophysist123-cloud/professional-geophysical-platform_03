from __future__ import annotations

import pandas as pd
import streamlit as st
from pyproj import CRS

from config.settings import DEFAULT_DATABASE_URL
from projects.project_manager import get_project, list_projects
from targeting.integration import project_coordinates


def accessible_projects(user: dict):
    return list_projects(
        DEFAULT_DATABASE_URL,
        user_id=user.get("id"),
        is_superadmin=bool(user.get("is_superadmin")),
    )


def render_project_selector(user: dict, key_prefix: str = "map_project"):
    """Render a project selector and return the selected SQLAlchemy Project."""
    projects = accessible_projects(user)
    if not projects:
        st.warning("No project is available to the current user. Create or assign a project first.")
        return None

    options = {p.id: p.name for p in projects}
    current_id = st.session_state.get("selected_project_id")
    if current_id not in options:
        current_id = projects[0].id

    selected_id = st.selectbox(
        "Project",
        list(options),
        index=list(options).index(current_id),
        format_func=lambda x: options[x],
        key=f"{key_prefix}_select",
    )
    project = get_project(DEFAULT_DATABASE_URL, selected_id)
    if project:
        st.session_state["selected_project_id"] = project.id
        st.session_state["selected_project_name"] = project.name
        st.session_state["selected_project_crs"] = project.crs_wkt or project.crs_epsg or 4326
    return project


def project_crs_value(project) -> str | int:
    if project is None:
        return 4326
    return project.crs_wkt or project.crs_epsg or 4326


def attach_project_coordinates(df: pd.DataFrame, project) -> pd.DataFrame:
    return project_coordinates(df, project_crs=project_crs_value(project))


def project_crs_details(project):
    if project is None:
        crs = CRS.from_epsg(4326)
    else:
        crs = CRS.from_user_input(project_crs_value(project))
    auth = crs.to_authority()
    auth_text = f"{auth[0]}:{auth[1]}" if auth else "Custom CRS"
    units = ", ".join(sorted({a.unit_name for a in crs.axis_info if a.unit_name}))
    return auth_text, crs.name, units
