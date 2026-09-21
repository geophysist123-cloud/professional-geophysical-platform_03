from __future__ import annotations

import json

import pandas as pd
import streamlit as st
from pyproj import CRS

from config.crs_registry import (
    CRS_TYPES,
    DEFAULT_CRS,
    SUPPORTED_AUTHORITIES,
    browse_crs,
    crs_details,
    crs_summary,
    parse_crs,
    search_epsg,
    suggest_utm_crs,
    transformer_preview,
)
from config.settings import DEFAULT_DATABASE_URL
from projects.project_manager import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)


def _rerun():
    st.rerun()


def _store_crs_recent(details: dict):
    if not details.get("name"):
        return
    recent = st.session_state.setdefault("crs_recent", [])
    item = {k: details.get(k) for k in ["epsg", "authority", "name", "type", "units", "area", "wkt"]}
    recent[:] = [x for x in recent if not (x.get("authority") == item.get("authority") and x.get("epsg") == item.get("epsg") and x.get("wkt") == item.get("wkt"))]
    recent.insert(0, item)
    del recent[10:]


def _toggle_favorite(details: dict):
    favorites = st.session_state.setdefault("crs_favorites", [])
    key = (details.get("authority"), details.get("epsg"), details.get("wkt"))
    for i, item in enumerate(favorites):
        if (item.get("authority"), item.get("epsg"), item.get("wkt")) == key:
            favorites.pop(i)
            return
    favorites.append({k: details.get(k) for k in ["epsg", "authority", "name", "type", "units", "area", "wkt"]})
    del favorites[25:]


def _crs_card(details: dict, prefix: str, state_key: str):
    if not details.get("name"):
        return None
    st.markdown(f"### {details['name']}")
    a, b, c, d = st.columns(4)
    a.metric("Authority", details.get("authority") or "Custom")
    b.metric("Type", details.get("type") or "—")
    c.metric("Units", details.get("units") or "—")
    d.metric("EPSG", str(details.get("epsg") or "—"))
    st.caption(details.get("area") or "Area of use not available")
    favorites = st.session_state.setdefault("crs_favorites", [])
    is_fav = any((x.get("authority"), x.get("epsg"), x.get("wkt")) == (details.get("authority"), details.get("epsg"), details.get("wkt")) for x in favorites)
    f1, f2, f3 = st.columns(3)
    with f1:
        if st.button("★ Remove from Favorites" if is_fav else "☆ Add to Favorites", key=f"{prefix}_fav"):
            _toggle_favorite(details)
            _store_crs_recent(details)
            st.rerun()
    with f2:
        if st.button("Use this CRS for project form", type="primary", key=f"{prefix}_use"):
            _store_crs_recent(details)
            st.session_state[state_key] = dict(details)
            st.session_state[state_key + "_confirmed"] = True
            st.session_state[state_key + "_version"] = st.session_state.get(state_key + "_version", 0) + 1
            st.rerun()
    with f3:
        st.download_button("Download WKT", details.get("wkt", ""), file_name=f"crs_{details.get('epsg') or 'custom'}.wkt", key=f"{prefix}_wkt")
    with st.expander("CRS properties", expanded=False):
        st.write({k: details.get(k) for k in ["datum", "ellipsoid", "coordinate_system", "authority", "epsg", "type", "units", "area"]})
        st.code(details.get("projjson", ""), language="json")
    return dict(details)


def _resolve_crs_from_widgets(prefix: str, state_key: str, existing=None):
    """Recover the CRS selection at submit time after any Streamlit rerun."""
    saved = st.session_state.get(state_key)
    if isinstance(saved, dict) and saved.get("name"):
        return saved

    # Search-result selectbox
    choice = st.session_state.get(f"{prefix}_choice")
    if isinstance(choice, str) and choice:
        try:
            code = choice.split(" — ", 1)[0].strip()
            ok, _, crs = parse_crs(code, allow_custom=True)
            if ok and crs:
                details = crs_details(crs)
                st.session_state[state_key] = details
                return details
        except Exception:
            pass

    # UTM suggestion selectbox
    suggestion = st.session_state.get(f"{prefix}_utm_select")
    for item in st.session_state.get(f"{prefix}_utm", []) or []:
        label = f"EPSG:{item.get('epsg')} — {item.get('name')}"
        if suggestion == label:
            try:
                ok, _, crs = parse_crs(f"EPSG:{item.get('epsg')}", allow_custom=False)
                if ok and crs:
                    details = crs_details(crs)
                    st.session_state[state_key] = details
                    return details
            except Exception:
                pass

    # Browse/recent/favorite selections
    for key_name, rows_key in [
        (f"{prefix}_browse_select", f"{prefix}_browse_rows"),
        (f"{prefix}_favorite_select", "crs_favorites"),
        (f"{prefix}_recent_select", "crs_recent"),
    ]:
        chosen = st.session_state.get(key_name)
        for item in st.session_state.get(rows_key, []) or []:
            if rows_key.endswith("browse_rows"):
                label = str(item.get("epsg"))
                definition = f"{item.get('authority') or 'EPSG'}:{item.get('epsg')}"
            else:
                label = f"{item.get('authority') or 'Custom'}:{item.get('epsg') or ''} — {item.get('name')}"
                definition = item.get("wkt") or f"{item.get('authority')}:{item.get('epsg')}"
            if chosen == label:
                try:
                    ok, _, crs = parse_crs(definition, allow_custom=True)
                    if ok and crs:
                        details = crs_details(crs)
                        st.session_state[state_key] = details
                        return details
                except Exception:
                    pass

    custom = st.session_state.get(f"{prefix}_custom")
    if isinstance(custom, str) and custom.strip():
        try:
            ok, _, crs = parse_crs(custom.strip(), allow_custom=True)
            if ok and crs:
                details = crs_details(crs)
                st.session_state[state_key] = details
                return details
        except Exception:
            pass

    if existing is not None:
        existing_wkt = getattr(existing, "crs_wkt", None)
        existing_epsg = getattr(existing, "crs_epsg", None)
        definition = existing_wkt or (f"EPSG:{existing_epsg}" if existing_epsg else None)
        if definition:
            try:
                ok, _, crs = parse_crs(definition, allow_custom=True)
                if ok and crs:
                    details = crs_details(crs)
                    st.session_state[state_key] = details
                    return details
            except Exception:
                pass
    return {"epsg": None, "name": None, "authority": None, "wkt": None, "units": None, "type": None, "area": None}


def _render_crs_picker(prefix: str, existing=None):
    existing_epsg = getattr(existing, "crs_epsg", None) if existing else None
    existing_wkt = getattr(existing, "crs_wkt", None) if existing else None
    st.markdown("#### 🌐 Coordinate Reference System")
    st.caption("GIS-style CRS picker: browse, search, favorites, recent systems, local UTM suggestions, inspect details, or enter a custom CRS.")

    tabs = st.tabs(["🔎 Search", "📚 Browse", "⭐ Favorites", "🕘 Recent", "📍 Suggest for location", "🧩 Custom"])
    state_key = f"{prefix}_selected_crs"
    selected = st.session_state.get(state_key)

    with tabs[0]:
        q = st.text_input("Search by EPSG code, CRS name, authority, or keyword", value=f"EPSG:{existing_epsg}" if existing_epsg else "", placeholder="WGS 84 / UTM zone 36N, 32636, NAD83, ETRS89", key=f"{prefix}_search")
        st.caption("For UTM searches, WGS 84 is intentionally ranked before ETRS89 and other datums. Check the datum in CRS Details before selecting.")
        a1, a2, a3 = st.columns(3)
        with a1:
            authority = st.selectbox("Authority", SUPPORTED_AUTHORITIES, index=0, key=f"{prefix}_authority")
        with a2:
            ctype_label = st.selectbox("Coordinate system type", ["All"] + CRS_TYPES, key=f"{prefix}_type")
        with a3:
            limit = st.slider("Results", 10, 100, 30, 10, key=f"{prefix}_limit")
        if q.strip():
            results = search_epsg(q, limit=limit, authorities=[authority], crs_type=None if ctype_label == "All" else ctype_label, prefer_wgs84=True)
            if results:
                labels = [f"{r['authority']}:{r['epsg']} — {r['name']}" for r in results]
                idx = 0
                if existing_epsg:
                    match = [i for i, r in enumerate(results) if str(r["epsg"]) == str(existing_epsg)]
                    idx = match[0] if match else 0
                choice = st.selectbox("Matching coordinate systems", labels, index=idx, key=f"{prefix}_choice")
                result = results[labels.index(choice)]
                ok, msg, crs = parse_crs(f"{result['authority']}:{result['epsg']}", allow_custom=False)
                if ok and crs:
                    details = crs_details(crs)
                    used = _crs_card(details, f"{prefix}_search_card", f"{prefix}_selected_crs")
                    if used:
                        selected = used
            else:
                st.warning("No matching CRS was found in the installed PROJ database.")
        else:
            st.info("Enter a name, EPSG code, or keyword to search the CRS registry.")

    with tabs[1]:
        b1, b2 = st.columns(2)
        with b1:
            bauth = st.selectbox("Authority", SUPPORTED_AUTHORITIES, key=f"{prefix}_browse_auth")
        with b2:
            btype = st.selectbox("Type", ["All"] + CRS_TYPES, key=f"{prefix}_browse_type")
        if st.button("Load CRS catalog", key=f"{prefix}_browse_load"):
            st.session_state[f"{prefix}_browse_rows"] = browse_crs(bauth, None if btype == "All" else btype, 250)
        rows = st.session_state.get(f"{prefix}_browse_rows", [])
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
            codes = list(df["epsg"].astype(str))
            bc = st.selectbox("Inspect a CRS", codes, key=f"{prefix}_browse_select")
            auth = df.loc[df["epsg"].astype(str) == str(bc), "authority"].iloc[0]
            ok, _, crs = parse_crs(f"{auth}:{bc}", allow_custom=True)
            if ok and crs:
                used = _crs_card(crs_details(crs), f"{prefix}_browse_card", f"{prefix}_selected_crs")
                if used:
                    selected = used

    with tabs[2]:
        favs = st.session_state.get("crs_favorites", [])
        if not favs:
            st.info("No CRS favorites yet.")
        else:
            labels = [f"{x.get('authority') or 'Custom'}:{x.get('epsg') or ''} — {x.get('name')}" for x in favs]
            fi = st.selectbox("Favorite CRS", labels, key=f"{prefix}_favorite_select")
            item = favs[labels.index(fi)]
            ok, _, crs = parse_crs(item.get("wkt") or f"{item.get('authority')}:{item.get('epsg')}", allow_custom=True)
            if ok and crs:
                used = _crs_card(crs_details(crs), f"{prefix}_favorite_card", f"{prefix}_selected_crs")
                if used:
                    selected = used

    with tabs[3]:
        recent = st.session_state.get("crs_recent", [])
        if not recent:
            st.info("No recent CRS selections in this session.")
        else:
            labels = [f"{x.get('authority') or 'Custom'}:{x.get('epsg') or ''} — {x.get('name')}" for x in recent]
            ri = st.selectbox("Recent CRS", labels, key=f"{prefix}_recent_select")
            item = recent[labels.index(ri)]
            ok, _, crs = parse_crs(item.get("wkt") or f"{item.get('authority')}:{item.get('epsg')}", allow_custom=True)
            if ok and crs:
                used = _crs_card(crs_details(crs), f"{prefix}_recent_card", f"{prefix}_selected_crs")
                if used:
                    selected = used

    with tabs[4]:
        st.write("Give the project center point and the platform will suggest suitable UTM CRSs from PROJ.")
        s1, s2 = st.columns(2)
        lon = s1.number_input("Project center longitude", -180.0, 180.0, 31.0, key=f"{prefix}_lon")
        lat = s2.number_input("Project center latitude", -90.0, 90.0, 30.0, key=f"{prefix}_lat")
        if st.button("Suggest CRS for this location", key=f"{prefix}_suggest"):
            st.session_state[f"{prefix}_utm"] = suggest_utm_crs(lon, lat)
        suggestions = st.session_state.get(f"{prefix}_utm", [])
        if suggestions:
            labels = [f"EPSG:{x['epsg']} — {x['name']}" for x in suggestions]
            sc = st.selectbox("Suggested projected CRS", labels, key=f"{prefix}_utm_select")
            item = suggestions[labels.index(sc)]
            ok, _, crs = parse_crs(f"EPSG:{item['epsg']}", allow_custom=False)
            if ok and crs:
                used = _crs_card(crs_details(crs), f"{prefix}_utm_card", f"{prefix}_selected_crs")
                if used:
                    selected = used

    with tabs[5]:
        custom_default = existing_wkt or ""
        custom = st.text_area("Paste WKT / PROJJSON / PROJ / EPSG / CRS name", value=custom_default, height=150, placeholder="EPSG:4326 or a full WKT / PROJJSON definition", key=f"{prefix}_custom")
        if custom.strip():
            ok, msg, crs = parse_crs(custom, allow_custom=True)
            if ok and crs:
                used = _crs_card(crs_details(crs), f"{prefix}_custom_card", f"{prefix}_selected_crs")
                if used:
                    selected = used
            else:
                st.error(msg)

    saved = st.session_state.get(state_key)
    if saved and saved.get("name"):
        return saved
    return _resolve_crs_from_widgets(prefix, state_key, existing=existing)


def render_projects(current_user):
    db_url = DEFAULT_DATABASE_URL
    is_admin = bool(current_user.get("is_superadmin")) or "MANAGE_PROJECTS" in st.session_state.get("permissions", set())

    st.title("📁 Projects")
    st.caption("Global project management with an ArcGIS-style coordinate system picker")

    # Always read projects fresh on each script run. After a successful save, we
    # also refresh the selected project in the same run so the new values are
    # visible immediately instead of requiring the user to leave and re-enter.
    projects = list_projects(
        db_url,
        user_id=current_user["id"],
        is_superadmin=bool(current_user.get("is_superadmin")),
    )

    if is_admin:
        with st.expander("➕ Create project", expanded=False):
            name = st.text_input("Project name", placeholder="e.g. Western Desert Integrated Geophysics", key="create_project_name")
            description = st.text_area("Description", key="create_project_description")
            c1, c2 = st.columns(2)
            country = c1.text_input("Country / countries", key="create_project_country")
            region = c2.text_input("Region / basin / block", key="create_project_region")
            crs_new = _render_crs_picker("create_project")
            submitted = st.button("Create Project", type="primary", key="create_project_submit")
            if submitted:
                crs_new = _resolve_crs_from_widgets("create_project", "create_project_selected_crs")
                if not name.strip():
                    st.error("Project name is required.")
                elif not crs_new.get("name"):
                    st.error("Select or define a valid project CRS.")
                else:
                    ok, msg = create_project(
                        db_url, current_user["id"], name, description, country, region,
                        crs_new.get("epsg"), crs_new.get("authority"), crs_new.get("name"),
                        crs_new.get("wkt"), crs_new.get("units")
                    )
                    if ok:
                        st.success(msg)
                        # Force a fresh database read on the very next render.
                        st.session_state["projects_refresh_nonce"] = st.session_state.get("projects_refresh_nonce", 0) + 1
                        st.rerun()
                    else:
                        st.error(msg)

    # Reload after create in case the list changed.
    if st.session_state.get("projects_refresh_nonce"):
        projects = list_projects(
            db_url,
            user_id=current_user["id"],
            is_superadmin=bool(current_user.get("is_superadmin")),
        )
        st.session_state["projects_refresh_nonce"] = 0

    if not projects:
        st.info("No projects are currently visible to this account. An administrator can create a project and grant project access.")
        return

    st.markdown("### Your accessible projects")
    rows = []
    for p in projects:
        crs_epsg = getattr(p, "crs_epsg", None)
        crs_authority = getattr(p, "crs_authority", None)
        crs_name = getattr(p, "crs_name", None)
        coordinate_units = getattr(p, "coordinate_units", None)
        info = crs_summary(crs_epsg) if crs_epsg else {"name": crs_name or "Custom CRS", "type": "", "area": "", "units": coordinate_units or ""}
        crs_label = f"{crs_authority or 'EPSG'}:{crs_epsg} — {crs_name or info['name']}" if crs_epsg else (crs_name or "Not specified")
        rows.append({"ID": p.id, "Project": p.name, "Country": p.country or "", "Region": p.region or "", "CRS": crs_label})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    options = {p.id: p.name for p in projects}
    valid_ids = list(options)
    previous_id = st.session_state.get("project_open")
    selected_id = previous_id if previous_id in valid_ids else valid_ids[0]
    selected_id = st.selectbox("Open project", valid_ids, index=valid_ids.index(selected_id), format_func=lambda x: options[x], key="project_open")

    # Always fetch the currently selected record fresh from the database.
    project = get_project(db_url, selected_id)
    if not project:
        st.error("Project could not be loaded.")
        return

    edit_saved = False

    if is_admin:
        edit_rev_key = f"edit_revision_{project.id}"
        edit_rev = st.session_state.get(edit_rev_key, 0)
        edit_prefix = f"edit_project_{project.id}_{edit_rev}"
        with st.expander("✏️ Edit project", expanded=True):
            name = st.text_input("Project name", value=project.name, key=f"edit_name_{project.id}_{edit_rev}")
            description = st.text_area("Description", value=project.description or "", key=f"edit_desc_{project.id}_{edit_rev}")
            c1, c2 = st.columns(2)
            country = c1.text_input("Country / countries", value=project.country or "", key=f"edit_country_{project.id}_{edit_rev}")
            region = c2.text_input("Region / basin / block", value=project.region or "", key=f"edit_region_{project.id}_{edit_rev}")
            crs_edit = _render_crs_picker(edit_prefix, existing=project)
            save = st.button("Save Project", type="primary", key=f"edit_save_{project.id}_{edit_rev}")
            if save:
                crs_edit = _resolve_crs_from_widgets(edit_prefix, f"{edit_prefix}_selected_crs", existing=project)
                if not name.strip():
                    st.error("Project name is required.")
                elif not crs_edit.get("name"):
                    st.error("A valid project CRS is required.")
                else:
                    ok, msg = update_project(
                        db_url, current_user["id"], project.id, name, description, country, region,
                        crs_edit.get("epsg"), crs_edit.get("authority"), crs_edit.get("name"),
                        crs_edit.get("wkt"), crs_edit.get("units")
                    )
                    if ok:
                        refreshed = get_project(db_url, project.id)
                        if refreshed is not None:
                            # Update the local record immediately, then bump widget keys so the
                            # editor is reconstructed from the freshly persisted values.
                            project = refreshed
                            st.session_state[edit_rev_key] = edit_rev + 1
                        st.session_state["projects_flash"] = f"✅ {msg} Project details refreshed from the database."
                        st.rerun()
                    else:
                        st.error(msg)

    flash = st.session_state.pop("projects_flash", None)
    if flash:
        st.success(flash)

    st.divider()
    st.subheader(project.name)
    if project.description:
        st.write(project.description)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Country", project.country or "—")
    c2.metric("Region", project.region or "—")
    project_crs_epsg = getattr(project, "crs_epsg", None)
    project_crs_authority = getattr(project, "crs_authority", None)
    project_crs_name = getattr(project, "crs_name", None)
    project_coordinate_units = getattr(project, "coordinate_units", None)
    c3.metric("CRS", f"{project_crs_authority or 'EPSG'}:{project_crs_epsg}" if project_crs_epsg else "Custom")
    c4.metric("CRS type", (crs_summary(project_crs_epsg).get("type") if project_crs_epsg else "Custom") or "—")
    st.info(f"**{project_crs_name or 'Custom CRS'}** — {project_coordinate_units or 'units not reported'} — {crs_summary(project_crs_epsg).get('area','') if project_crs_epsg else 'Project-defined CRS'}")

    if is_admin:
        with st.expander("🗑️ Delete project"):
            st.warning("Deletion is blocked when datasets exist, to protect data history.")
            if st.button("Delete this project", key=f"delete_{project.id}"):
                ok, msg = delete_project(db_url, current_user["id"], project.id)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)


def render_crs_registry():
    st.title("🌐 Global CRS Explorer")
    st.caption("A GIS-style coordinate system explorer powered by the installed PROJ database.")
    _render_crs_picker("registry")
