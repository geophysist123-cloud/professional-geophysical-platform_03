from __future__ import annotations

import pandas as pd
import streamlit as st

from database.drivers import (
    DRIVER_PACKAGES,
    build_database_url,
    install_command,
    installed_odbc_drivers,
    python_driver_available,
)
from database.external_schema import EXTERNAL_SCHEMA_VERSION, EXTERNAL_TABLE_NAMES, external_schema_status, initialize_external_schema
from database.manager import (
    ColumnSpec,
    SUPPORTED_DATABASES,
    create_engine_from_url,
    create_table,
    describe_table,
    drop_table,
    list_schemas,
    list_tables,
    test_connection,
)
from config.settings import DEFAULT_DATABASE_URL


def _session_defaults():
    # The core application database is managed automatically by app.py.
    # Database Manager is intentionally for optional external/project databases only.
    st.session_state.setdefault("db_manager_url", "")
    st.session_state.setdefault("db_manager_label", "")
    st.session_state.setdefault("db_manager_platform", "")
    if st.session_state.get("db_manager_url") == DEFAULT_DATABASE_URL:
        st.session_state.db_manager_url = ""
        st.session_state.db_manager_label = ""
        st.session_state.db_manager_platform = ""


def _connection_form(db_type: str) -> str:
    if db_type == "SQLite":
        path = st.text_input("SQLite database file", value="project_data.db", key="db_sqlite_path")
        return build_database_url(db_type, {"path": path})

    if db_type == "Custom SQLAlchemy URL":
        return st.text_input(
            "SQLAlchemy database URL",
            value="",
            type="password",
            key="db_custom_url",
            help="Use only when you need a SQLAlchemy dialect not listed here.",
        )

    if db_type == "Microsoft SQL Server":
        st.caption("SQL Server uses pyodbc plus a Microsoft SQL Server ODBC driver installed on this machine.")
        if not python_driver_available(db_type):
            st.error("Python driver 'pyodbc' is not installed in the Python environment running Streamlit.")
            st.code(install_command(db_type), language="powershell")
            return ""

        odbc = installed_odbc_drivers()
        sqlserver_odbc = [d for d in odbc if "SQL Server" in d]
        if not sqlserver_odbc:
            st.error("pyodbc is installed, but Windows reports no SQL Server ODBC driver.")
            st.info("Install Microsoft ODBC Driver 17 or 18 for SQL Server, then restart Streamlit.")
            st.code("python -c \"import pyodbc; print(pyodbc.drivers())\"", language="powershell")
            return ""

        # Prefer the newest installed SQL Server driver, but always use the exact
        # name returned by pyodbc.drivers(). This prevents IM002 caused by a
        # hard-coded driver name that is not installed on the machine.
        def _driver_rank(name: str) -> tuple[int, str]:
            import re
            m = re.search(r"ODBC Driver (\d+)", name)
            return (int(m.group(1)) if m else -1, name)

        sqlserver_odbc = sorted(sqlserver_odbc, key=_driver_rank, reverse=True)
        authentication = st.radio(
            "Authentication",
            ["Windows Integrated", "SQL Server Authentication"],
            horizontal=True,
            key="db_mssql_authentication",
        )

        c1, c2 = st.columns(2)
        with c1:
            host = st.text_input(
                "Server / Host",
                value="localhost",
                key="db_mssql_host",
                help="Examples: localhost, SERVER01, 192.168.1.10, or SERVER01\\SQLEXPRESS for a named instance.",
            )
            use_named_instance = "\\" in host
            if use_named_instance:
                st.caption("Named SQL Server instance detected; the port field is not used.")
                port = 1433
            else:
                port = st.number_input("Port", min_value=1, max_value=65535, value=1433, key="db_mssql_port")
            database = st.text_input("Database", key="db_mssql_database")
        with c2:
            driver = st.selectbox(
                "ODBC Driver",
                sqlserver_odbc,
                index=0,
                key="db_mssql_driver",
                help="This list comes directly from pyodbc. The selected name is passed unchanged to SQL Server.",
            )
            if authentication == "SQL Server Authentication":
                username = st.text_input("Username", key="db_mssql_username")
                password = st.text_input("Password", type="password", key="db_mssql_password")
            else:
                username, password = "", ""

        encrypt = st.checkbox("Encrypt connection", value=True, key="db_mssql_encrypt")
        trust = st.checkbox(
            "Trust server certificate",
            value=True,
            key="db_mssql_trust",
            help="Useful for internal SQL Server deployments with a self-signed/untrusted certificate.",
        )
        return build_database_url(db_type, {
            "authentication": authentication,
            "host": host,
            "port": port,
            "database": database,
            "username": username,
            "password": password,
            "odbc_driver": driver,
            "encrypt": encrypt,
            "trust_server_certificate": trust,
            "named_instance": use_named_instance,
        })

    if not python_driver_available(db_type):
        package, _ = DRIVER_PACKAGES[db_type]
        st.error(f"Python database driver '{package}' is not installed.")
        st.code(install_command(db_type), language="powershell")
        return ""

    defaults = {
        "PostgreSQL": ("localhost", 5432),
        "MySQL": ("localhost", 3306),
        "MariaDB": ("localhost", 3306),
        "Oracle": ("localhost", 1521),
    }
    host_default, port_default = defaults[db_type]
    c1, c2 = st.columns(2)
    with c1:
        host = st.text_input("Server / Host", value=host_default, key=f"db_{db_type}_host")
        port = st.number_input("Port", min_value=1, max_value=65535, value=port_default, key=f"db_{db_type}_port")
        username = st.text_input("Username", key=f"db_{db_type}_username")
    with c2:
        database = st.text_input("Database" if db_type != "Oracle" else "Service name", key=f"db_{db_type}_database")
        password = st.text_input("Password", type="password", key=f"db_{db_type}_password")
    values = {"host": host, "port": port, "username": username, "password": password}
    if db_type == "Oracle":
        values["service_name"] = database
    else:
        values["database"] = database
    return build_database_url(db_type, values)


def render_database_manager(user):
    _session_defaults()
    if not bool(user.get("is_superadmin")):
        st.error("Database management requires Super Administrator privileges.")
        return

    st.title("🗄️ Database & Table Manager")
    st.caption("Connect to optional external/project databases, inspect schemas, and create/manage tables without exposing raw SQL execution.")

    st.info("Core platform database: SQLite — created and maintained automatically. You do not need to configure it here.")

    with st.expander("🔌 External Database Connection", expanded=not bool(st.session_state.db_manager_url)):
        db_type = st.selectbox("Database platform", list(SUPPORTED_DATABASES.keys()), key="db_platform")
        try:
            url = _connection_form(db_type)
        except Exception as exc:
            st.error(f"Could not build connection: {exc}")
            url = ""

        c1, c2 = st.columns(2)
        with c1:
            default_label = f"{db_type} connection"
            label = st.text_input("Connection label", value=default_label, key="db_connection_label")
        with c2:
            if st.button("Test Connection", use_container_width=True, disabled=not bool(url)):
                ok, msg = test_connection(url)
                (st.success if ok else st.error)(msg)

        if st.button("Use This Connection", type="primary", use_container_width=True, disabled=not bool(url)):
            ok, msg = test_connection(url)
            if ok:
                st.session_state.db_manager_url = url
                st.session_state.db_manager_label = label.strip() or default_label
                st.session_state.db_manager_platform = db_type
                st.success(f"Active connection: {st.session_state.db_manager_label}")
                st.rerun()
            st.error(msg)
        st.info("External database credentials are kept only in the current Streamlit session. Do not commit database passwords or URLs containing passwords to GitHub.")

    url = st.session_state.get("db_manager_url", "")
    if not url:
        st.info("No external database is connected. Choose a platform above and select 'Use This Connection' when you are ready.")
        return

    if st.button("Disconnect External Database", use_container_width=True):
        st.session_state.db_manager_url = ""
        st.session_state.db_manager_label = ""
        st.session_state.db_manager_platform = ""
        st.rerun()

    try:
        engine = create_engine_from_url(url)
        schemas = list_schemas(engine)
        active_platform = st.session_state.get("db_manager_platform", "")
        preferred_schema = None
        if active_platform == "Microsoft SQL Server" and "dbo" in schemas:
            preferred_schema = "dbo"
        elif active_platform == "PostgreSQL" and "public" in schemas:
            preferred_schema = "public"
        elif "public" in schemas:
            preferred_schema = "public"
        elif "main" in schemas:
            preferred_schema = "main"
        schema_options = ["(default)"] + schemas
        schema_index = schema_options.index(preferred_schema) if preferred_schema in schema_options else 0
        schema_choice = st.selectbox("Schema", schema_options, index=schema_index)
        schema = None if schema_choice == "(default)" else schema_choice
        tables = list_tables(engine, schema)
    except Exception as exc:
        st.error(f"Could not inspect database: {exc}")
        return

    live_status = external_schema_status(engine, schema)
    if live_status["ready"]:
        st.success(f"Verified in database: {live_status['count']}/{live_status['expected']} application tables exist in schema '{live_status['schema'] or '(default)'}'.")
    else:
        st.warning(f"Database currently contains {live_status['count']}/{live_status['expected']} application tables in schema '{live_status['schema'] or '(default)'}'.")

    st.subheader("Database Overview")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Connection", st.session_state.db_manager_label)
    m2.metric("Schemas", len(schemas))
    m3.metric("Tables", len(tables))
    try:
        schema_status = external_schema_status(engine, schema)
        m4.metric("Geophysical Schema", "Ready" if schema_status["ready"] else "Not initialized")
    except Exception:
        schema_status = {"ready": False, "count": 0, "expected": len(EXTERNAL_TABLE_NAMES)}

    st.info(
        "The core platform database remains automatic SQLite. "
        "This external database is optional and is intended for project/geophysical data. "
        "It does not store platform passwords or roles."
    )

    schema_tab, tab1, tab2, tab3 = st.tabs(
        ["🚀 Initialize Geophysics Schema", "📋 Tables", "➕ Create Table", "⚠️ Manage Table"]
    )

    with schema_tab:
        st.markdown("### Standard Geophysical Project Schema")
        st.write(
            f"Schema version **{EXTERNAL_SCHEMA_VERSION}** — "
            f"{len(EXTERNAL_TABLE_NAMES)} application tables."
        )
        st.dataframe(
            pd.DataFrame({"Standard table": EXTERNAL_TABLE_NAMES}),
            use_container_width=True,
            hide_index=True,
        )

        if schema_status.get("ready"):
            st.success(
                f"Geophysics application schema is ready: "
                f"{schema_status['count']}/{schema_status['expected']} tables found."
            )
        else:
            st.warning(
                f"External database is not fully initialized: "
                f"{schema_status.get('count', 0)}/{schema_status.get('expected', len(EXTERNAL_TABLE_NAMES))} tables found."
            )

        confirm = st.checkbox(
            "I understand that this will create missing application tables but will not drop existing tables.",
            key="confirm_external_schema",
        )
        if st.button(
            "Initialize / Update Geophysics Application Schema",
            type="primary",
            use_container_width=True,
            disabled=not confirm,
        ):
            try:
                result = initialize_external_schema(engine, schema)
                if result["ready"]:
                    st.success(
                        f"Schema initialized and verified in '{result['schema'] or '(default)'}': "
                        f"{result['table_count']}/{result['expected_table_count']} tables exist in the target database."
                    )
                else:
                    st.error(
                        f"Schema initialization incomplete: {len(result['missing_tables'])} tables are missing."
                    )
                    st.write("Missing tables:", result["missing_tables"])
                st.rerun()
            except Exception as exc:
                st.error(f"Could not initialize the external schema: {exc}")

    with tab1:
        if tables:
            st.dataframe(pd.DataFrame({"Table": tables}), use_container_width=True, hide_index=True)
            selected = st.selectbox("Inspect table", tables)
            if selected:
                st.dataframe(pd.DataFrame(describe_table(engine, selected, schema)), use_container_width=True, hide_index=True)
        else:
            st.info("No tables found in this schema.")
    with tab2:
        count = st.number_input("Number of columns", min_value=1, max_value=50, value=5, step=1)
        default_rows = pd.DataFrame([
            {"name": "id" if i == 0 else f"field_{i}", "data_type": "INTEGER" if i == 0 else "TEXT", "nullable": False if i == 0 else True, "primary_key": i == 0, "default": ""}
            for i in range(int(count))
        ])
        edited = st.data_editor(
            default_rows,
            num_rows="fixed",
            use_container_width=True,
            hide_index=True,
            column_config={
                "data_type": st.column_config.SelectboxColumn("data_type", options=["INTEGER", "BIGINT", "FLOAT", "REAL", "DOUBLE", "BOOLEAN", "DATETIME", "TIMESTAMP", "TEXT", "STRING", "VARCHAR"]),
                "nullable": st.column_config.CheckboxColumn("nullable"),
                "primary_key": st.column_config.CheckboxColumn("primary_key"),
            },
            key="create_table_editor",
        )
        new_table = st.text_input("New table name")
        if st.button("Create Table", type="primary"):
            try:
                specs = [ColumnSpec(str(r["name"]), str(r["data_type"]), bool(r["nullable"]), bool(r["primary_key"]), str(r["default"]) if pd.notna(r["default"]) else None) for _, r in edited.iterrows()]
                create_table(engine, new_table, specs, schema)
                st.success(f"Table '{new_table}' created successfully.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not create table: {exc}")
    with tab3:
        if not tables:
            st.info("No tables available.")
        else:
            selected = st.selectbox("Table to manage", tables, key="manage_table")
            st.dataframe(pd.DataFrame(describe_table(engine, selected, schema)), use_container_width=True, hide_index=True)
            st.warning("Dropping a table permanently removes its database structure and data. This action is restricted to Super Administrators.")
            confirm = st.checkbox("I understand this will permanently drop the selected table.")
            if st.button("Drop Table", type="secondary", disabled=not confirm):
                try:
                    drop_table(engine, selected, schema)
                    st.success(f"Table '{selected}' dropped.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not drop table: {exc}")
    engine.dispose()
