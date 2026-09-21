from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import MetaData, Table, inspect

from database.external_schema import initialize_external_schema
from database.manager import create_engine_from_url


def _table(engine, name: str, schema: str | None = None):
    meta = MetaData()
    return Table(name, meta, autoload_with=engine, schema=schema)


def ensure_phase9_schema(engine, schema: str | None = None) -> dict[str, Any]:
    initialize_external_schema(engine, schema=schema)
    target = schema.strip() if schema else None
    inspector = inspect(engine)
    existing = set(inspector.get_table_names(schema=target))

    from sqlalchemy import Column, DateTime, Float, Integer, String, Table, Text
    meta = MetaData(schema=target)
    Table("gp_processing_runs", meta,
          Column("id", Integer, primary_key=True),
          Column("project_key", String(100), nullable=False),
          Column("dataset_name", String(255)),
          Column("modality", String(40), nullable=False),
          Column("survey_type", String(100)),
          Column("run_id", String(120), nullable=False, unique=True),
          Column("selected_product", String(150)),
          Column("parameters_json", Text),
          Column("created_by", String(120)),
          Column("created_at", DateTime, nullable=False))
    Table("gp_processing_values", meta,
          Column("id", Integer, primary_key=True),
          Column("processing_run_id", Integer, nullable=False),
          Column("station_id", String(120)),
          Column("line_id", String(120)),
          Column("latitude", Float),
          Column("longitude", Float),
          Column("stage_code", String(100), nullable=False),
          Column("stage_order", Integer),
          Column("value", Float),
          Column("units", String(50)),
          Column("qc_flag", String(50)))
    Table("gp_target_runs", meta,
          Column("id", Integer, primary_key=True),
          Column("project_key", String(100), nullable=False),
          Column("run_id", String(120), nullable=False, unique=True),
          Column("normalization_method", String(100), nullable=False),
          Column("magnetic_weight", Float, nullable=False),
          Column("gravity_weight", Float, nullable=False),
          Column("evidence_weight", Float, nullable=False),
          Column("concordance_weight", Float, nullable=False),
          Column("created_by", String(120)),
          Column("created_at", DateTime, nullable=False))
    meta.create_all(engine, checkfirst=True)

    # Backward-compatible columns on gp_targets for databases initialized earlier.
    if "gp_targets" in existing:
        current = {c["name"] for c in inspect(engine).get_columns("gp_targets", schema=target)}
        additions = {
            "run_id": "VARCHAR(120)",
            "normalization_method": "VARCHAR(100)",
            "magnetic_weight": "FLOAT",
            "gravity_weight": "FLOAT",
            "evidence_weight": "FLOAT",
            "concordance_weight": "FLOAT",
        }
        for col, typ in additions.items():
            if col not in current:
                table_ref = f"[{target}].[gp_targets]" if target else "[gp_targets]"
                with engine.begin() as conn:
                    conn.exec_driver_sql(f"ALTER TABLE {table_ref} ADD [{col}] {typ}")

    return {
        "schema": target,
        "processing_runs": inspect(engine).has_table("gp_processing_runs", schema=target),
        "processing_values": inspect(engine).has_table("gp_processing_values", schema=target),
        "target_runs": inspect(engine).has_table("gp_target_runs", schema=target),
    }


def save_processing_run(database_url: str, schema: str | None, project_key: str,
                        dataset_name: str, modality: str, survey_type: str,
                        run_id: str, stages: list[dict[str, Any]], processed: pd.DataFrame,
                        created_by: str, selected_product: str | None = None,
                        parameters: dict[str, Any] | None = None) -> tuple[bool, str]:
    engine = create_engine_from_url(database_url)
    try:
        ensure_phase9_schema(engine, schema)
        runs = _table(engine, "gp_processing_runs", schema)
        values = _table(engine, "gp_processing_values", schema)
        station_col = "Point_ID" if "Point_ID" in processed.columns else None
        line_col = "Line_ID" if "Line_ID" in processed.columns else None
        lat_col = "Latitude" if "Latitude" in processed.columns else ("Lat" if "Lat" in processed.columns else None)
        lon_col = "Longitude" if "Longitude" in processed.columns else ("Lon" if "Lon" in processed.columns else None)
        qc_col = "Mag_QC_Flag" if modality.upper() == "MAGNETIC" else "Gravity_QC_Flag"
        with engine.begin() as conn:
            result = conn.execute(runs.insert().values(
                project_key=project_key, dataset_name=dataset_name,
                modality=modality, survey_type=survey_type, run_id=run_id,
                selected_product=selected_product,
                parameters_json=json.dumps(parameters or {}, default=str),
                created_by=created_by, created_at=datetime.utcnow()))
            run_pk = result.inserted_primary_key[0]
            rows = []
            for order, stage in enumerate(stages, 1):
                series = pd.to_numeric(stage.get("series"), errors="coerce")
                for idx, value in series.items():
                    rows.append({
                        "processing_run_id": run_pk,
                        "station_id": None if station_col is None else str(processed.loc[idx, station_col]),
                        "line_id": None if line_col is None else str(processed.loc[idx, line_col]),
                        "latitude": None if lat_col is None or pd.isna(processed.loc[idx, lat_col]) else float(processed.loc[idx, lat_col]),
                        "longitude": None if lon_col is None or pd.isna(processed.loc[idx, lon_col]) else float(processed.loc[idx, lon_col]),
                        "stage_code": str(stage.get("code", stage.get("name", f"STEP_{order}"))),
                        "stage_order": order,
                        "value": None if pd.isna(value) else float(value),
                        "units": "nT" if modality.upper() == "MAGNETIC" else "mGal",
                        "qc_flag": None if qc_col not in processed.columns else str(processed.loc[idx, qc_col]),
                    })
            if rows:
                conn.execute(values.insert(), rows)
        return True, f"Saved processing run {run_id} ({len(rows):,} stage values)."
    except Exception as exc:
        return False, f"Could not save processing run: {exc}"
    finally:
        engine.dispose()


def save_target_run(database_url: str, schema: str | None, project_key: str, run_id: str,
                    scored: pd.DataFrame, normalization_method: str,
                    magnetic_weight: float, gravity_weight: float,
                    evidence_weight: float, concordance_weight: float,
                    created_by: str) -> tuple[bool, str]:
    engine = create_engine_from_url(database_url)
    try:
        ensure_phase9_schema(engine, schema)
        runs = _table(engine, "gp_target_runs", schema)
        targets = _table(engine, "gp_targets", schema)
        with engine.begin() as conn:
            conn.execute(runs.insert().values(
                project_key=project_key, run_id=run_id,
                normalization_method=normalization_method,
                magnetic_weight=float(magnetic_weight), gravity_weight=float(gravity_weight),
                evidence_weight=float(evidence_weight), concordance_weight=float(concordance_weight),
                created_by=created_by, created_at=datetime.utcnow()))
            rows = []
            for i, (_, row) in enumerate(scored.iterrows(), 1):
                lat = row.get("Latitude", row.get("Lat")); lon = row.get("Longitude", row.get("Lon"))
                def f(key):
                    v = row.get(key); return None if pd.isna(v) else float(v)
                rows.append({
                    "project_key": project_key,
                    "target_name": str(row.get("Point_ID", f"TARGET_{i:05d}")),
                    "latitude": None if pd.isna(lat) else float(lat),
                    "longitude": None if pd.isna(lon) else float(lon),
                    "mag_normalized": f("Mag_Normalized"), "grav_normalized": f("Grav_Normalized"),
                    "mag_contribution": f("Mag_Contribution"), "grav_contribution": f("Grav_Contribution"),
                    "data_confidence": f("Data_Confidence"), "concordance": f("Concordance"),
                    "target_score": f("Target_Score"),
                    "target_priority": None if pd.isna(row.get("Target_Priority")) else str(row.get("Target_Priority")),
                    "run_id": run_id, "normalization_method": normalization_method,
                    "magnetic_weight": float(magnetic_weight), "gravity_weight": float(gravity_weight),
                    "evidence_weight": float(evidence_weight), "concordance_weight": float(concordance_weight),
                })
            if rows:
                conn.execute(targets.insert(), rows)
        return True, f"Saved target run {run_id} ({len(rows):,} targets)."
    except Exception as exc:
        return False, f"Could not save target run: {exc}"
    finally:
        engine.dispose()


def save_interpretation(database_url: str, schema: str | None, project_key: str, title: str, text: str, author_username: str) -> tuple[bool, str]:
    engine = create_engine_from_url(database_url)
    try:
        ensure_phase9_schema(engine, schema)
        table = _table(engine, "gp_interpretations", schema)
        with engine.begin() as conn:
            conn.execute(table.insert().values(
                project_key=project_key, title=title, text=text,
                author_username=author_username, created_at=datetime.utcnow()
            ))
        return True, "Interpretation saved to external database."
    except Exception as exc:
        return False, f"Could not save interpretation: {exc}"
    finally:
        engine.dispose()


def save_contour_metadata(database_url: str, schema: str | None, dataset_id: int, product_name: str, value_column: str, normalization_method: str, interpolation_method: str = "linear + nearest fill", grid_size: int = 180) -> tuple[bool, str]:
    engine = create_engine_from_url(database_url)
    try:
        ensure_phase9_schema(engine, schema)
        table = _table(engine, "gp_contour_products", schema)
        with engine.begin() as conn:
            conn.execute(table.insert().values(
                dataset_id=int(dataset_id), product_name=product_name, value_column=value_column,
                normalization_method=normalization_method, interpolation_method=interpolation_method,
                grid_size=int(grid_size), created_at=datetime.utcnow()
            ))
        return True, "Contour metadata saved to external database."
    except Exception as exc:
        return False, f"Could not save contour metadata: {exc}"
    finally:
        engine.dispose()


def save_report_metadata(database_url: str, schema: str | None, project_key: str, report_name: str, report_format: str, created_by: str) -> tuple[bool, str]:
    engine = create_engine_from_url(database_url)
    try:
        ensure_phase9_schema(engine, schema)
        table = _table(engine, "gp_reports", schema)
        with engine.begin() as conn:
            conn.execute(table.insert().values(
                project_key=project_key, report_name=report_name, report_format=report_format,
                created_by=created_by, created_at=datetime.utcnow()
            ))
        return True, "Report metadata saved to external database."
    except Exception as exc:
        return False, f"Could not save report metadata: {exc}"
    finally:
        engine.dispose()
