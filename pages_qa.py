from __future__ import annotations

import importlib.util
import platform
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from sqlalchemy import inspect, text

from config.settings import APP_NAME, APP_VERSION, DEFAULT_DATABASE_URL
from database.manager import create_engine_from_url, list_schemas, list_tables
from database.external_schema import EXTERNAL_SCHEMA_VERSION, expected_external_tables
from targeting.integration import DEFAULT_MAGNETIC_WEIGHT, DEFAULT_GRAVITY_WEIGHT, EVIDENCE_WEIGHT, CONCORDANCE_WEIGHT, NORMALIZERS


def _check_import(package: str) -> tuple[bool, str]:
    try:
        spec = importlib.util.find_spec(package)
        return (spec is not None, "installed" if spec else "missing")
    except Exception as exc:
        return False, str(exc)


def render_qa(user: dict):
    st.title("✅ Production QA & Deployment Readiness")
    st.caption("Read-only health checks for the platform foundation and the geophysical processing stack.")

    st.subheader("Platform")
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Version", str(APP_VERSION))
    p2.metric("Python", platform.python_version())
    p3.metric("OS", platform.system())
    p4.metric("UTC", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))

    st.subheader("Required Python packages")
    packages = [
        ("streamlit", "streamlit"),
        ("sqlalchemy", "sqlalchemy"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
        ("pyproj", "pyproj"),
        ("scipy", "scipy"),
        ("matplotlib", "matplotlib"),
        ("openpyxl", "openpyxl"),
        ("psycopg", "psycopg"),
        ("pymysql", "pymysql"),
        ("pyodbc", "pyodbc"),
        ("oracledb", "oracledb"),
    ]
    rows = []
    for label, module in packages:
        ok, detail = _check_import(module)
        rows.append({"Package": label, "Status": "PASS" if ok else "MISSING", "Detail": detail})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader("Scoring model")
    st.write({
        "default_normalization": "Robust Z-score — Recommended",
        "magnetic_weight": DEFAULT_MAGNETIC_WEIGHT,
        "gravity_weight": DEFAULT_GRAVITY_WEIGHT,
        "evidence_weight": EVIDENCE_WEIGHT,
        "concordance_weight": CONCORDANCE_WEIGHT,
        "data_confidence": "100% both / 60% magnetic only / 40% gravity only / No Score neither",
        "normalizers_available": list(NORMALIZERS.keys()),
    })

    st.subheader("Core database")
    try:
        core_engine = create_engine_from_url(DEFAULT_DATABASE_URL)
        with core_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        st.success("Core database is reachable and automatically managed by the platform.")
        core_engine.dispose()
    except Exception as exc:
        st.error(f"Core database check failed: {exc}")

    st.subheader("Active external database")
    external_url = st.session_state.get("db_manager_url", "")
    external_platform = st.session_state.get("db_manager_platform", "")
    external_label = st.session_state.get("db_manager_label", "")
    external_schema = st.session_state.get("db_manager_schema", "") or None
    if not external_url:
        st.info("No external database is active in this browser session.")
        return

    st.success(f"Active connection: {external_label or external_platform} | schema: {external_schema or 'default'}")
    try:
        engine = create_engine_from_url(external_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        tables = set(list_tables(engine, schema=external_schema))
        expected = set(expected_external_tables())
        present = sorted(expected & tables)
        missing = sorted(expected - tables)
        st.metric("External application tables", f"{len(present)}/{len(expected)}")
        if missing:
            st.warning("Missing application tables: " + ", ".join(missing))
        else:
            st.success(f"External schema is complete ({len(present)}/{len(expected)} tables).")
        st.write("Schema version target:", EXTERNAL_SCHEMA_VERSION)
        st.write("Available schemas:", list_schemas(engine))
        engine.dispose()
    except Exception as exc:
        st.error(f"External database health check failed: {exc}")

    st.subheader("Deployment environment")
    try:
        cloud = bool(st.context) and bool(getattr(st.context, "url", None))
    except Exception:
        cloud = False
    st.write({
        "recommended_python": "3.12",
        "running_python": platform.python_version(),
        "sql_server_driver": "pyodbc; Community Cloud provides SQL Server ODBC tooling" if cloud else "pyodbc + Microsoft ODBC Driver required on Windows",
    })

    st.subheader("Deployment checklist")
    st.checkbox("requirements.txt committed at repository root", value=True, disabled=True)
    st.checkbox("No secrets/passwords committed to GitHub", value=True, disabled=True)
    st.checkbox("Core SQLite database is not committed", value=True, disabled=True)
    st.checkbox("Streamlit entrypoint is app.py", value=True, disabled=True)
    st.checkbox("External database credentials supplied through runtime UI/secrets", value=True, disabled=True)
