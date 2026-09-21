import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from auth.service import authenticate_user, create_user, get_user_permissions
from config.settings import APP_NAME, APP_VERSION, DEFAULT_DATABASE_URL
from database.repository import test_database_connection
from database.schema import create_application_schema
from pages_administration import render_administration
from pages_projects import render_projects, render_crs_registry
from pages_database import render_database_manager
from pages_synthetic import render_synthetic_data
from pages_magnetic import render_magnetic_processing
from pages_gravity import render_gravity_processing
from pages_integration import render_integration
from pages_gis import render_gis
from pages_reports import render_reports
from pages_qa import render_qa

st.set_page_config(page_title=APP_NAME, page_icon="🌍", layout="wide")


def init_session():
    st.session_state.setdefault("authenticated", False)
    st.session_state.setdefault("user", None)
    st.session_state.setdefault("permissions", set())
    st.session_state.setdefault("core_database_ready", False)


def ensure_database_ready():
    if st.session_state.get("core_database_ready"):
        return True, ""
    try:
        create_application_schema(DEFAULT_DATABASE_URL)
        st.session_state["core_database_ready"] = True
        return True, ""
    except SQLAlchemyError as exc:
        return False, f"Database initialization failed: {exc}"


def login_screen():
    st.title("🔐 Professional Geophysical Platform")
    st.subheader("Sign in")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)
    if submitted:
        try:
            user = authenticate_user(DEFAULT_DATABASE_URL, username, password)
            if user:
                st.session_state.authenticated = True
                st.session_state.user = user
                st.session_state.permissions = get_user_permissions(DEFAULT_DATABASE_URL, user["id"])
                st.rerun()
            else:
                st.error("Invalid username/password or inactive account.")
        except SQLAlchemyError as exc:
            st.error(f"Database is not ready: {exc}")
            st.info("Use 'Initialize / Update Database Schema' below and try again.")

    st.divider()
    st.success("Core database: SQLite — automatically created and maintained by the platform.")
    st.caption("First-time setup: create the first administrator. No database configuration is required.")
    with st.form("bootstrap_admin"):
        st.markdown("### Create first administrator")
        name = st.text_input("Full name")
        username = st.text_input("Admin username")
        email = st.text_input("Email")
        password = st.text_input("Admin password", type="password")
        confirm = st.text_input("Confirm password", type="password")
        create = st.form_submit_button("Create Administrator")
    if create:
        if password != confirm:
            st.error("Passwords do not match.")
        else:
            try:
                create_application_schema(DEFAULT_DATABASE_URL)
                st.session_state["core_database_ready"] = True
                ok, message = create_user(DEFAULT_DATABASE_URL, username=username, password=password,
                                          email=email, full_name=name, is_superadmin=True)
                (st.success if ok else st.error)(message)
            except SQLAlchemyError as exc:
                st.error(f"Could not create administrator: {exc}")


def dashboard():
    user = st.session_state.user
    permissions = st.session_state.permissions
    is_admin = bool(user.get("is_superadmin"))
    with st.sidebar:
        st.success(f"Signed in as **{user['username']}**")
        if user.get("full_name"):
            st.caption(user["full_name"])
        if is_admin:
            st.warning("Super Administrator")

        pages = ["Dashboard", "Projects", "Synthetic Data", "Magnetic Processing", "Gravity Processing", "Integrated Targeting", "GIS & Interpretation", "Reports", "Production QA"]
        if is_admin:
            pages.append("Database Manager")
        if "MANAGE_PROJECTS" in permissions or is_admin:
            pages.append("CRS Registry")
        if "MANAGE_USERS" in permissions or is_admin:
            pages.append("Administration")
        page = st.radio("Navigation", pages, key="navigation")
        if st.button("Log out", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.user = None
            st.session_state.permissions = set()
            st.rerun()

    if page == "Database Manager":
        render_database_manager(user)
        return
    if page == "Administration":
        render_administration(user)
        return
    if page == "Projects":
        render_projects(user)
        return
    if page == "Synthetic Data":
        render_synthetic_data(user)
        return
    if page == "Magnetic Processing":
        render_magnetic_processing(user)
        return
    if page == "Gravity Processing":
        render_gravity_processing(user)
        return
    if page == "Integrated Targeting":
        render_integration(user)
        return
    if page == "GIS & Interpretation":
        render_gis(user)
        return
    if page == "Reports":
        render_reports(user)
        return
    if page == "Production QA":
        render_qa(user)
        return
    if page == "CRS Registry":
        render_crs_registry()
        return

    st.title("🌍 Professional Geophysical Exploration Platform")
    st.success(f"V{APP_VERSION} — Projects, global CRS and database management foundation is active.")
    cols = st.columns(4)
    cols[0].metric("Authentication", "Active")
    cols[1].metric("Database", "Connected")
    cols[2].metric("CRS", "Global EPSG")
    cols[3].metric("Permissions", len(permissions))
    st.header("Platform Dashboard")
    st.info("Phase 4 establishes global project management, project visibility and EPSG/PROJ CRS validation. Geophysical data engines follow in the next phases.")


init_session()
db_ready, db_message = ensure_database_ready()
if not db_ready:
    st.error(db_message)
if not st.session_state.authenticated:
    login_screen()
else:
    dashboard()
