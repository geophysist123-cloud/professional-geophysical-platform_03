import pandas as pd
import streamlit as st

from auth.admin import (
    delete_role,
    get_audit_logs,
    get_permissions,
    get_roles,
    get_users,
    save_role,
    update_user,
)
from auth.service import create_user, get_user_permissions
from config.settings import DEFAULT_DATABASE_URL
from projects.project_access import (
    assign_project_member,
    create_project,
    list_projects,
    list_roles,
    list_users,
    project_members,
    remove_project_member,
)


def _refresh():
    st.rerun()


def render_administration(current_user):
    db_url = DEFAULT_DATABASE_URL
    st.title("⚙️ Administration")
    st.caption("Users, global roles, permissions, project access and audit history")

    tabs = st.tabs(["Users", "Roles & Permissions", "Project Access", "Audit Log"])

    with tabs[0]:
        render_users(db_url, current_user)
    with tabs[1]:
        render_roles(db_url, current_user)
    with tabs[2]:
        render_project_access(db_url, current_user)
    with tabs[3]:
        render_audit(db_url)


def render_users(db_url, current_user):
    st.subheader("User Management")
    users = get_users(db_url)
    roles = get_roles(db_url)
    role_map = {r["id"]: r["name"] for r in roles}

    with st.expander("➕ Create user", expanded=False):
        with st.form("create_user_form"):
            c1, c2 = st.columns(2)
            username = c1.text_input("Username")
            full_name = c2.text_input("Full name")
            email = c1.text_input("Email")
            password = c2.text_input("Password", type="password")
            selected = st.multiselect("Global roles", options=list(role_map), format_func=lambda x: role_map[x])
            active = st.checkbox("Active", True)
            superadmin = st.checkbox("Super Administrator")
            submitted = st.form_submit_button("Create User", type="primary")
        if submitted:
            ok, msg = create_user(db_url, username, password, email, full_name, superadmin, selected, active)
            (st.success if ok else st.error)(msg)
            if ok:
                _refresh()

    st.markdown("### Existing users")
    if not users:
        st.info("No users found.")
        return

    labels = [f"{u['username']} — {'Active' if u['active'] else 'Inactive'}" for u in users]
    idx = st.selectbox("Select user", range(len(users)), format_func=lambda i: labels[i], key="admin_user_select")
    user = users[idx]

    with st.form(f"edit_user_{user['id']}"):
        c1, c2 = st.columns(2)
        email = c1.text_input("Email", value=user["email"])
        full_name = c2.text_input("Full name", value=user["full_name"])
        active = st.checkbox("Active", value=user["active"])
        superadmin = st.checkbox("Super Administrator", value=user["superadmin"])
        selected_roles = st.multiselect("Global roles", options=list(role_map), default=user["role_ids"], format_func=lambda x: role_map[x])
        new_password = st.text_input("New password (leave blank to keep current)", type="password")
        save = st.form_submit_button("Save User", type="primary")
    if save:
        ok, msg = update_user(db_url, current_user["id"], user["id"], email, full_name, active, superadmin, selected_roles, new_password)
        (st.success if ok else st.error)(msg)
        if ok and user["id"] == current_user["id"]:
            current_user["is_superadmin"] = superadmin
        if ok:
            _refresh()

    rows = [{"Username": u["username"], "Name": u["full_name"], "Email": u["email"], "Active": u["active"], "Superadmin": u["superadmin"], "Roles": ", ".join(u["roles"])} for u in users]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_roles(db_url, current_user):
    st.subheader("Roles & Permissions")
    permissions = get_permissions(db_url)
    roles = get_roles(db_url)
    pmap = {p.id: p.permission_code for p in permissions}
    st.write("Assign granular permissions to reusable global roles. Super Administrators bypass permission checks.")

    options = {0: "➕ New role"}
    options.update({r["id"]: r["name"] for r in roles})
    selected_id = st.selectbox("Role", list(options), format_func=lambda x: options[x], key="role_editor_select")
    current = next((r for r in roles if r["id"] == selected_id), None)

    with st.form("role_editor"):
        name = st.text_input("Role name", value=current["name"] if current else "")
        desc = st.text_area("Description", value=current["description"] if current else "")
        selected_permissions = st.multiselect("Permissions", options=list(pmap), default=current["permission_ids"] if current else [], format_func=lambda x: pmap[x])
        save = st.form_submit_button("Save Role", type="primary")
    if save:
        ok, msg = save_role(db_url, current_user["id"], selected_id or None, name, desc, selected_permissions)
        (st.success if ok else st.error)(msg)
        if ok:
            _refresh()

    if current:
        if st.button("Delete selected role", type="secondary"):
            ok, msg = delete_role(db_url, current_user["id"], current["id"])
            (st.success if ok else st.error)(msg)
            if ok:
                _refresh()

    rows = [{"Role": r["name"], "Description": r["description"], "Users": r["user_count"], "Permissions": ", ".join(r["permissions"])} for r in roles]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_project_access(db_url, current_user):
    st.subheader("Project Access")
    st.caption("Projects are created and edited on the Projects page. This section only assigns existing users to existing projects.")

    c1, c2 = st.columns([4, 1])
    with c1:
        st.write("Select an existing project, then grant an existing active user access to it.")
    with c2:
        if st.button("🔄 Refresh users/projects", use_container_width=True, key="refresh_project_access"):
            st.rerun()

    # Always query fresh data; this makes a newly-created user available without
    # leaving the Administration page.
    projects = list_projects(db_url)
    users = list_users(db_url, include_inactive=False)
    roles = list_roles(db_url)

    if not projects:
        st.info("No projects exist yet. Create the project from Projects → Create Project.")
        return

    if not users:
        st.warning("No active users are available. Create or activate a user under Administration → Users first.")
        return

    pidx = st.selectbox(
        "Project",
        range(len(projects)),
        format_func=lambda i: projects[i].name,
        key="access_project",
    )
    project = projects[pidx]
    members = project_members(db_url, project.id)

    st.markdown(f"**Project:** {project.name}")
    user_options = {u.id: f"{u.username} — {u.full_name or ''}".strip(" —") for u in users}
    role_options = {r.id: r.name for r in roles}
    current_member_ids = {m.user_id for m in members}

    with st.form(f"add_member_{project.id}"):
        uid = st.selectbox(
            "User",
            list(user_options),
            format_func=lambda x: user_options[x],
        )
        rid = st.selectbox(
            "Project role",
            [None] + list(role_options),
            format_func=lambda x: "No project role" if x is None else role_options[x],
        )
        save = st.form_submit_button("Save Project Access", type="primary")

    if save:
        ok, msg = assign_project_member(db_url, current_user["id"], project.id, uid, rid)
        (st.success if ok else st.error)(msg)
        if ok:
            st.rerun()

    st.markdown("### Current project members")
    rows = [
        {
            "ID": m.id,
            "Username": m.user.username,
            "Name": m.user.full_name or "",
            "Email": m.user.email or "",
            "Project role": m.role.name if m.role else "",
        }
        for m in members
    ]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        member_ids = {str(row["ID"]): row["ID"] for row in rows}
        selected_member = st.selectbox(
            "Select membership to remove",
            list(member_ids),
            format_func=lambda x: f"{x} — {next(r['Username'] for r in rows if str(r['ID']) == x)}",
            key=f"remove_member_select_{project.id}",
        )
        if st.button("Remove project access", key=f"remove_access_{project.id}"):
            ok, msg = remove_project_member(db_url, current_user["id"], int(member_ids[selected_member]))
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()
    else:
        st.info("No users are assigned to this project yet. The creator receives access automatically when a project is created.")


def render_audit(db_url):
    st.subheader("Audit Log")
    limit = st.slider("Rows", 50, 1000, 250, 50)
    logs = get_audit_logs(db_url, limit)
    if logs:
        st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)
    else:
        st.info("No audit records yet.")
