from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, MetaData, String, Text, Table, inspect
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


TYPE_MAP = {
    "INTEGER": Integer,
    "BIGINT": Integer,
    "FLOAT": Float,
    "REAL": Float,
    "DOUBLE": Float,
    "BOOLEAN": Boolean,
    "DATETIME": DateTime,
    "TIMESTAMP": DateTime,
    "TEXT": Text,
    "STRING": String(255),
    "VARCHAR": String(255),
}

SUPPORTED_DATABASES = {
    "SQLite": "sqlite:///geophysical_platform.db",
    "PostgreSQL": "postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE",
    "MySQL": "mysql+pymysql://USER:PASSWORD@HOST:3306/DATABASE",
    "MariaDB": "mariadb+pymysql://USER:PASSWORD@HOST:3306/DATABASE",
    "Microsoft SQL Server": "mssql+pyodbc://USER:PASSWORD@HOST:1433/DATABASE?driver=ODBC+Driver+18+for+SQL+Server",
    "Oracle": "oracle+oracledb://USER:PASSWORD@HOST:1521/?service_name=SERVICE",
    "Custom SQLAlchemy URL": "",
}


@dataclass
class ColumnSpec:
    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False
    default: str | None = None


def create_engine_from_url(url: str) -> Engine:
    if not url or not url.strip():
        raise ValueError("Database URL is required.")
    return create_engine(url.strip(), pool_pre_ping=True)


def test_connection(url: str) -> tuple[bool, str]:
    engine = None
    try:
        engine = create_engine_from_url(url)
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True, "Connection successful."
    except Exception as exc:
        return False, f"Connection failed: {exc}"
    finally:
        if engine is not None:
            engine.dispose()


def list_schemas(engine: Engine) -> list[str]:
    return inspect(engine).get_schema_names()


def list_tables(engine: Engine, schema: str | None = None) -> list[str]:
    return sorted(inspect(engine).get_table_names(schema=schema))


def describe_table(engine: Engine, table_name: str, schema: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for col in inspect(engine).get_columns(table_name, schema=schema):
        rows.append({
            "name": col.get("name"),
            "type": str(col.get("type")),
            "nullable": bool(col.get("nullable", True)),
            "primary_key": False,
            "default": col.get("default"),
        })
    pk = inspect(engine).get_pk_constraint(table_name, schema=schema).get("constrained_columns") or []
    for row in rows:
        row["primary_key"] = row["name"] in pk
    return rows


def create_table(engine: Engine, table_name: str, columns: list[ColumnSpec], schema: str | None = None) -> None:
    if not table_name.strip():
        raise ValueError("Table name is required.")
    if not columns:
        raise ValueError("At least one column is required.")
    if any(not c.name.strip() for c in columns):
        raise ValueError("Every column must have a name.")
    names = [c.name.strip().lower() for c in columns]
    if len(names) != len(set(names)):
        raise ValueError("Column names must be unique.")

    metadata = MetaData()
    sa_columns = []
    from sqlalchemy import Column
    for spec in columns:
        typ = TYPE_MAP.get(spec.data_type.upper())
        if typ is None:
            raise ValueError(f"Unsupported data type: {spec.data_type}")
        sa_type = typ if not isinstance(typ, type) else typ
        kwargs = {"nullable": spec.nullable, "primary_key": spec.primary_key}
        if spec.default and spec.default.strip():
            # Defaults are intentionally limited to database-neutral literal text.
            from sqlalchemy import text
            kwargs["server_default"] = text(spec.default.strip())
        sa_columns.append(Column(spec.name.strip(), sa_type, **kwargs))

    table = Table(table_name.strip(), metadata, *sa_columns, schema=(schema.strip() if schema else None))
    metadata.create_all(engine, tables=[table], checkfirst=True)


def drop_table(engine: Engine, table_name: str, schema: str | None = None) -> None:
    metadata = MetaData()
    table = Table(table_name, metadata, schema=(schema.strip() if schema else None), autoload_with=engine)
    table.drop(engine, checkfirst=True)
