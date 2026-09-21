
from __future__ import annotations

from sqlalchemy import Boolean, DateTime, Float, Integer, MetaData, String, Table, Text, inspect
from sqlalchemy.engine import Engine

EXTERNAL_SCHEMA_VERSION = "2.0"

# The external/project database deliberately does NOT contain platform
# authentication tables. Users, roles and permissions remain in the core
# application database. This schema stores project/geophysical data products.
metadata = MetaData()

application_info = Table(
    "gp_application_info", metadata,
    # SQLite and other DBs accept INTEGER primary keys; SQL Server uses identity
    # automatically only if configured, so we keep a single-row metadata table.
    # The application writes version information explicitly.
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("schema_name", String(150), nullable=False),
    __import__("sqlalchemy").Column("schema_version", String(50), nullable=False),
    __import__("sqlalchemy").Column("initialized_at", DateTime, nullable=False),
)

projects = Table(
    "gp_projects", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("project_key", String(100), nullable=False, unique=True),
    __import__("sqlalchemy").Column("name", String(255), nullable=False),
    __import__("sqlalchemy").Column("country", String(255)),
    __import__("sqlalchemy").Column("region", String(255)),
    __import__("sqlalchemy").Column("crs_epsg", Integer),
    __import__("sqlalchemy").Column("description", Text),
)

datasets = Table(
    "gp_datasets", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("project_key", String(100), nullable=False),
    __import__("sqlalchemy").Column("name", String(255), nullable=False),
    __import__("sqlalchemy").Column("dataset_type", String(80), nullable=False),
    __import__("sqlalchemy").Column("survey_type", String(80)),
    __import__("sqlalchemy").Column("units", String(80)),
    __import__("sqlalchemy").Column("source_description", Text),
    __import__("sqlalchemy").Column("processing_status", String(80)),
)

stations = Table(
    "gp_stations", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("dataset_id", Integer, nullable=False),
    __import__("sqlalchemy").Column("station_id", String(120), nullable=False),
    __import__("sqlalchemy").Column("line_id", String(120)),
    __import__("sqlalchemy").Column("survey_datetime", DateTime),
    __import__("sqlalchemy").Column("latitude", Float, nullable=False),
    __import__("sqlalchemy").Column("longitude", Float, nullable=False),
    __import__("sqlalchemy").Column("elevation_m", Float),
    __import__("sqlalchemy").Column("easting_m", Float),
    __import__("sqlalchemy").Column("northing_m", Float),
    __import__("sqlalchemy").Column("crs_epsg", Integer),
    __import__("sqlalchemy").Column("quality_flag", String(50)),
)

magnetic = Table(
    "gp_magnetic_observations", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("station_pk", Integer, nullable=False),
    __import__("sqlalchemy").Column("raw_tmi_nt", Float),
    __import__("sqlalchemy").Column("base_station_nt", Float),
    __import__("sqlalchemy").Column("diurnal_correction_nt", Float),
    __import__("sqlalchemy").Column("igrf_reference_nt", Float),
    __import__("sqlalchemy").Column("heading_correction_nt", Float),
    __import__("sqlalchemy").Column("lag_correction_nt", Float),
    __import__("sqlalchemy").Column("leveling_correction_nt", Float),
    __import__("sqlalchemy").Column("microleveling_correction_nt", Float),
    __import__("sqlalchemy").Column("final_anomaly_nt", Float),
)

gravity = Table(
    "gp_gravity_observations", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("station_pk", Integer, nullable=False),
    __import__("sqlalchemy").Column("raw_gravity", Float),
    __import__("sqlalchemy").Column("base_station_gravity", Float),
    __import__("sqlalchemy").Column("tide_correction_mgal", Float),
    __import__("sqlalchemy").Column("drift_correction_mgal", Float),
    __import__("sqlalchemy").Column("latitude_correction_mgal", Float),
    __import__("sqlalchemy").Column("free_air_correction_mgal", Float),
    __import__("sqlalchemy").Column("bouguer_correction_mgal", Float),
    __import__("sqlalchemy").Column("terrain_correction_mgal", Float),
    __import__("sqlalchemy").Column("curvature_correction_mgal", Float),
    __import__("sqlalchemy").Column("isostatic_correction_mgal", Float),
    __import__("sqlalchemy").Column("final_anomaly_mgal", Float),
)

corrections = Table(
    "gp_correction_steps", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("dataset_id", Integer, nullable=False),
    __import__("sqlalchemy").Column("step_order", Integer, nullable=False),
    __import__("sqlalchemy").Column("method_code", String(100), nullable=False),
    __import__("sqlalchemy").Column("status", String(50), nullable=False),
    __import__("sqlalchemy").Column("mandatory", Boolean, nullable=False, default=False),
    __import__("sqlalchemy").Column("parameters_json", Text),
    __import__("sqlalchemy").Column("created_at", DateTime, nullable=False),
)

anomalies = Table(
    "gp_anomaly_products", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("dataset_id", Integer, nullable=False),
    __import__("sqlalchemy").Column("product_name", String(150), nullable=False),
    __import__("sqlalchemy").Column("product_type", String(80), nullable=False),
    __import__("sqlalchemy").Column("units", String(80)),
    __import__("sqlalchemy").Column("method_summary", Text),
    __import__("sqlalchemy").Column("created_at", DateTime, nullable=False),
)

targets = Table(
    "gp_targets", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("project_key", String(100), nullable=False),
    __import__("sqlalchemy").Column("target_name", String(255), nullable=False),
    __import__("sqlalchemy").Column("latitude", Float),
    __import__("sqlalchemy").Column("longitude", Float),
    __import__("sqlalchemy").Column("mag_normalized", Float),
    __import__("sqlalchemy").Column("grav_normalized", Float),
    __import__("sqlalchemy").Column("mag_contribution", Float),
    __import__("sqlalchemy").Column("grav_contribution", Float),
    __import__("sqlalchemy").Column("data_confidence", Float),
    __import__("sqlalchemy").Column("concordance", Float),
    __import__("sqlalchemy").Column("target_score", Float),
    __import__("sqlalchemy").Column("target_priority", String(50)),
)

contours = Table(
    "gp_contour_products", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("dataset_id", Integer, nullable=False),
    __import__("sqlalchemy").Column("product_name", String(150), nullable=False),
    __import__("sqlalchemy").Column("value_column", String(150)),
    __import__("sqlalchemy").Column("normalization_method", String(100)),
    __import__("sqlalchemy").Column("interpolation_method", String(80)),
    __import__("sqlalchemy").Column("grid_size", Integer),
    __import__("sqlalchemy").Column("created_at", DateTime, nullable=False),
)

interpretations = Table(
    "gp_interpretations", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("project_key", String(100), nullable=False),
    __import__("sqlalchemy").Column("title", String(255), nullable=False),
    __import__("sqlalchemy").Column("text", Text, nullable=False),
    __import__("sqlalchemy").Column("author_username", String(120)),
    __import__("sqlalchemy").Column("created_at", DateTime, nullable=False),
)

reports = Table(
    "gp_reports", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("project_key", String(100), nullable=False),
    __import__("sqlalchemy").Column("report_name", String(255), nullable=False),
    __import__("sqlalchemy").Column("report_format", String(50)),
    __import__("sqlalchemy").Column("created_by", String(120)),
    __import__("sqlalchemy").Column("created_at", DateTime, nullable=False),
)


processing_runs = Table(
    "gp_processing_runs", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("project_key", String(100), nullable=False),
    __import__("sqlalchemy").Column("dataset_name", String(255)),
    __import__("sqlalchemy").Column("modality", String(40), nullable=False),
    __import__("sqlalchemy").Column("survey_type", String(100)),
    __import__("sqlalchemy").Column("run_id", String(120), nullable=False, unique=True),
    __import__("sqlalchemy").Column("selected_product", String(150)),
    __import__("sqlalchemy").Column("parameters_json", Text),
    __import__("sqlalchemy").Column("created_by", String(120)),
    __import__("sqlalchemy").Column("created_at", DateTime, nullable=False),
)

processing_values = Table(
    "gp_processing_values", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("processing_run_id", Integer, nullable=False),
    __import__("sqlalchemy").Column("station_id", String(120)),
    __import__("sqlalchemy").Column("line_id", String(120)),
    __import__("sqlalchemy").Column("latitude", Float),
    __import__("sqlalchemy").Column("longitude", Float),
    __import__("sqlalchemy").Column("stage_code", String(100), nullable=False),
    __import__("sqlalchemy").Column("stage_order", Integer),
    __import__("sqlalchemy").Column("value", Float),
    __import__("sqlalchemy").Column("units", String(50)),
    __import__("sqlalchemy").Column("qc_flag", String(50)),
)

target_runs = Table(
    "gp_target_runs", metadata,
    __import__("sqlalchemy").Column("id", Integer, primary_key=True),
    __import__("sqlalchemy").Column("project_key", String(100), nullable=False),
    __import__("sqlalchemy").Column("run_id", String(120), nullable=False, unique=True),
    __import__("sqlalchemy").Column("normalization_method", String(100), nullable=False),
    __import__("sqlalchemy").Column("magnetic_weight", Float, nullable=False),
    __import__("sqlalchemy").Column("gravity_weight", Float, nullable=False),
    __import__("sqlalchemy").Column("evidence_weight", Float, nullable=False),
    __import__("sqlalchemy").Column("concordance_weight", Float, nullable=False),
    __import__("sqlalchemy").Column("created_by", String(120)),
    __import__("sqlalchemy").Column("created_at", DateTime, nullable=False),
)



EXTERNAL_TABLE_NAMES = [t.name for t in metadata.sorted_tables]


def _metadata_for_schema(schema: str | None) -> MetaData:
    target = MetaData(schema=schema or None)
    for table in metadata.sorted_tables:
        table.to_metadata(target, schema=schema or None)
    return target

def initialize_external_schema(engine: Engine, schema: str | None = None) -> dict:
    target_schema = schema.strip() if schema else None
    target_metadata = _metadata_for_schema(target_schema)
    target_metadata.create_all(engine, checkfirst=True)
    inspector = inspect(engine)
    existing = set(inspector.get_table_names(schema=target_schema))
    expected = set(EXTERNAL_TABLE_NAMES)
    found = sorted(existing.intersection(expected))
    missing = sorted(expected - existing)
    if not missing and 'gp_application_info' in existing:
        info_meta = MetaData()
        info = Table('gp_application_info', info_meta, autoload_with=engine, schema=target_schema)
        from datetime import datetime
        from sqlalchemy import select
        with engine.begin() as conn:
            if conn.execute(select(info).limit(1)).first() is None:
                conn.execute(info.insert().values(id=1, schema_name='Professional Geophysical Platform External Schema', schema_version=EXTERNAL_SCHEMA_VERSION, initialized_at=datetime.utcnow()))
    return {'schema': target_schema, 'created_or_verified_tables': found, 'missing_tables': missing, 'table_count': len(found), 'expected_table_count': len(expected), 'ready': not missing, 'schema_version': EXTERNAL_SCHEMA_VERSION}

def external_schema_status(engine: Engine, schema: str | None = None) -> dict:
    target_schema = schema.strip() if schema else None
    existing = set(inspect(engine).get_table_names(schema=target_schema))
    expected = set(EXTERNAL_TABLE_NAMES)
    found = sorted(existing.intersection(expected))
    return {'schema': target_schema, 'found': found, 'missing': sorted(expected-set(found)), 'ready': expected.issubset(existing), 'count': len(found), 'expected': len(expected)}


def expected_external_tables() -> list[str]:
    """Canonical external application tables used by the current platform schema."""
    return [
        "gp_application_info",
        "gp_projects",
        "gp_datasets",
        "gp_stations",
        "gp_magnetic_observations",
        "gp_gravity_observations",
        "gp_correction_steps",
        "gp_anomaly_products",
        "gp_targets",
        "gp_contour_products",
        "gp_interpretations",
        "gp_reports",
        "gp_processing_runs",
        "gp_processing_values",
        "gp_target_runs",
    ]
