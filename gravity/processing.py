
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from scipy.interpolate import griddata


@dataclass(frozen=True)
class GravityStep:
    order: int
    code: str
    name: str
    product: str
    requirement: str
    status: str
    description: str


GRAVITY_STEPS = [
    GravityStep(
        1, "QC", "Quality control", "Input",
        "Required",
        "READY",
        "Check station coordinates, elevations, duplicate stations, missing observations and robust outliers."
    ),
    GravityStep(
        2, "TIDE", "Earth-tide correction", "Observed gravity",
        "Required for raw time-varying observations",
        "READY",
        "Remove the temporal gravitational effect of Earth tides when the input requires it."
    ),
    GravityStep(
        3, "DRIFT", "Instrument drift correction", "Observed gravity",
        "Required for raw/relative gravity",
        "READY",
        "Correct meter drift using base/loop observations or an equivalent documented drift model."
    ),
    GravityStep(
        4, "LATITUDE", "Latitude / normal-gravity correction", "Latitude-corrected stage",
        "Required for standard gravity anomaly reduction",
        "READY",
        "Remove the normal gravity field associated with geographic latitude using the selected reference formula or supplied correction."
    ),
    GravityStep(
        5, "FREE_AIR", "Free-air correction", "Free-air anomaly",
        "Required for Free-Air anomaly",
        "READY",
        "Account for observation elevation relative to the chosen reference datum."
    ),
    GravityStep(
        6, "BOUGUER", "Bouguer slab correction", "Simple Bouguer anomaly",
        "Required for Bouguer anomaly",
        "READY",
        "Remove the gravitational effect of the rock slab between the observation level and the reference datum using the selected density."
    ),
    GravityStep(
        7, "TERRAIN", "Terrain correction", "Complete Bouguer anomaly",
        "Required for Complete Bouguer in the selected reduction scheme",
        "READY",
        "Account for topography not represented by the simple Bouguer slab."
    ),
    GravityStep(
        8, "CURVATURE", "Curvature correction", "Complete Bouguer variant",
        "Product / reduction-scheme dependent",
        "OPTIONAL",
        "Apply Earth-curvature correction where required by the adopted reduction convention."
    ),
    GravityStep(
        9, "ISOSTATIC", "Isostatic correction", "Isostatic anomaly",
        "Optional",
        "OPTIONAL",
        "Remove a regional isostatic model effect when regional/isostatic analysis is desired."
    ),
]


def _num(df: pd.DataFrame, col: str | None) -> pd.Series:
    if not col or col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def robust_outlier_mask(series: pd.Series, z_threshold: float = 6.0) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce")
    med = x.median()
    mad = (x - med).abs().median()
    if pd.isna(mad) or mad == 0:
        return pd.Series(False, index=x.index)
    rz = (x - med) / (1.4826 * mad)
    return rz.abs() > z_threshold


def _required_fields(
    df: pd.DataFrame,
    lat_col: str,
    lon_col: str,
    elevation_col: str | None,
    gravity_col: str,
) -> dict[str, Any]:
    lat = _num(df, lat_col)
    lon = _num(df, lon_col)
    elev = _num(df, elevation_col)
    grav = _num(df, gravity_col)

    return {
        "rows": int(len(df)),
        "valid_coordinates": int((lat.notna() & lon.notna()).sum()),
        "missing_coordinates": int((lat.isna() | lon.isna()).sum()),
        "valid_elevation": int(elev.notna().sum()),
        "missing_elevation": int(elev.isna().sum()),
        "valid_gravity": int(grav.notna().sum()),
        "missing_gravity": int(grav.isna().sum()),
        "duplicate_coordinates": int(
            pd.DataFrame({"lat": lat, "lon": lon}).duplicated(["lat", "lon"]).sum()
        ),
    }


def _add_signed(series: pd.Series, correction: pd.Series, convention: str) -> pd.Series:
    if convention == "Subtract supplied correction/effect":
        return series - correction.fillna(0.0)
    return series + correction.fillna(0.0)


def _zero(df: pd.DataFrame) -> pd.Series:
    return pd.Series(0.0, index=df.index, dtype=float)


def _choose_col(df: pd.DataFrame, explicit: str | None, contains: tuple[str, ...]) -> str | None:
    if explicit and explicit in df.columns:
        return explicit
    lower = {str(c).lower(): c for c in df.columns}
    for col in df.columns:
        name = str(col).lower()
        if all(token.lower() in name for token in contains):
            return col
    return None


def run_gravity_pipeline(
    df: pd.DataFrame,
    lat_col: str,
    lon_col: str,
    elevation_col: str | None,
    gravity_col: str,
    survey_type: str = "Ground Gravity",
    apply_qc: bool = True,
    exclude_qc_outliers: bool = False,
    tide_col: str | None = None,
    drift_col: str | None = None,
    latitude_col: str | None = None,
    free_air_col: str | None = None,
    bouguer_col: str | None = None,
    terrain_col: str | None = None,
    curvature_col: str | None = None,
    isostatic_col: str | None = None,
    selected_product: str = "Complete Bouguer anomaly",
    correction_sign: str = "Subtract supplied correction/effect",
    qc_z_threshold: float = 6.0,
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    """
    Process gravity observations while retaining every selected intermediate
    product. For synthetic/reference columns the values are treated as supplied
    correction/effect terms under the chosen sign convention.

    Product logic:
      Observed -> Tide -> Drift -> Latitude -> Free-Air -> Bouguer -> Terrain
      -> optional Curvature -> optional Isostatic.
    """
    work = df.copy()
    stats = _required_fields(work, lat_col, lon_col, elevation_col, gravity_col)

    work["Gravity_QC_Flag"] = "PASS"
    outlier = robust_outlier_mask(work[gravity_col], qc_z_threshold) if apply_qc else pd.Series(False, index=work.index)
    missing = _num(work, gravity_col).isna()

    work.loc[outlier, "Gravity_QC_Flag"] = "ROBUST_OUTLIER"
    work.loc[missing, "Gravity_QC_Flag"] = "MISSING"

    if exclude_qc_outliers:
        use_mask = ~outlier & ~missing
    else:
        use_mask = ~missing

    current = _num(work, gravity_col).copy()

    stages: list[dict[str, Any]] = [
        {
            "code": "RAW_OBSERVED",
            "name": "Raw / input gravity",
            "product": "Input",
            "requirement": "Input",
            "status": "READY",
            "series": current.copy(),
            "description": "Input gravity observation supplied by the user or synthetic demonstration dataset.",
        }
    ]

    def add_stage(code, name, product, requirement, status, description):
        stages.append(
            {
                "code": code,
                "name": name,
                "product": product,
                "requirement": requirement,
                "status": status,
                "series": current.copy(),
                "description": description,
            }
        )

    sign = -1.0 if correction_sign.startswith("Subtract") else 1.0

    def apply_term(code, name, product, requirement, source_col, description):
        nonlocal current
        corr = _num(work, source_col).fillna(0.0)
        current = current + sign * corr
        current.loc[~use_mask] = np.nan
        add_stage(code, name, product, requirement, "APPLIED", description)

    if tide_col:
        apply_term(
            "TIDE_CORRECTED",
            "After earth-tide correction",
            "Observed gravity",
            "Required for raw time-varying observations",
            tide_col,
            "Earth-tide correction applied.",
        )
    else:
        add_stage(
            "TIDE_CORRECTED",
            "After earth-tide correction",
            "Observed gravity",
            "Required for raw time-varying observations",
            "SKIPPED",
            "No tide correction column selected. Confirm that the input is already tide-corrected.",
        )

    if drift_col:
        apply_term(
            "DRIFT_CORRECTED",
            "After instrument-drift correction",
            "Observed gravity",
            "Required for raw/relative gravity",
            drift_col,
            "Instrument drift correction applied.",
        )
    else:
        add_stage(
            "DRIFT_CORRECTED",
            "After instrument-drift correction",
            "Observed gravity",
            "Required for raw/relative gravity",
            "SKIPPED",
            "No drift correction column selected. Confirm that the input is already drift-corrected.",
        )

    if latitude_col:
        apply_term(
            "LATITUDE_CORRECTED",
            "After latitude / normal-gravity correction",
            "Latitude-corrected stage",
            "Required for standard gravity anomaly reduction",
            latitude_col,
            "Latitude/normal-gravity correction applied.",
        )
    else:
        add_stage(
            "LATITUDE_CORRECTED",
            "After latitude / normal-gravity correction",
            "Latitude-corrected stage",
            "Required for standard gravity anomaly reduction",
            "SKIPPED",
            "No supplied latitude/normal-gravity correction selected.",
        )

    # For a standard anomaly workflow, Free-Air is an addition to observed
    # gravity after reference gravity has been accounted for. The synthetic
    # sample contains a precomputed free-air correction term.
    if free_air_col:
        free_air = _num(work, free_air_col).fillna(0.0)
        current = current + sign * free_air
        current.loc[~use_mask] = np.nan
        add_stage(
            "FREE_AIR",
            "Free-air anomaly",
            "Free-air anomaly",
            "Required for Free-Air anomaly",
            "APPLIED",
            "Free-air correction applied using the selected input term and sign convention.",
        )
    else:
        add_stage(
            "FREE_AIR",
            "Free-air anomaly",
            "Free-air anomaly",
            "Required for Free-Air anomaly",
            "SKIPPED",
            "No free-air correction selected.",
        )

    if bouguer_col:
        apply_term(
            "SIMPLE_BOUGUER",
            "Simple Bouguer anomaly",
            "Simple Bouguer anomaly",
            "Required for Bouguer anomaly",
            bouguer_col,
            "Bouguer slab correction applied.",
        )
    else:
        add_stage(
            "SIMPLE_BOUGUER",
            "Simple Bouguer anomaly",
            "Simple Bouguer anomaly",
            "Required for Bouguer anomaly",
            "SKIPPED",
            "No Bouguer slab correction selected.",
        )

    if terrain_col:
        # The supplied terrain effect may be positive and conventionally added
        # to the simple Bouguer anomaly. Respect the user's selected convention.
        apply_term(
            "COMPLETE_BOUGUER",
            "Complete Bouguer anomaly",
            "Complete Bouguer anomaly",
            "Required for Complete Bouguer in the selected reduction scheme",
            terrain_col,
            "Terrain correction applied.",
        )
    else:
        add_stage(
            "COMPLETE_BOUGUER",
            "Complete Bouguer anomaly",
            "Complete Bouguer anomaly",
            "Required for Complete Bouguer in the selected reduction scheme",
            "SKIPPED",
            "No terrain correction selected.",
        )

    if curvature_col:
        apply_term(
            "CURVATURE",
            "After curvature correction",
            "Complete Bouguer variant",
            "Product / reduction-scheme dependent",
            curvature_col,
            "Curvature correction applied.",
        )
    elif selected_product in {"Complete Bouguer anomaly", "Isostatic anomaly"}:
        add_stage(
            "CURVATURE",
            "After curvature correction",
            "Complete Bouguer variant",
            "Product / reduction-scheme dependent",
            "SKIPPED",
            "No curvature correction selected; this is allowed where the adopted reduction does not require it.",
        )

    if isostatic_col:
        apply_term(
            "ISOSTATIC",
            "Isostatic anomaly",
            "Isostatic anomaly",
            "Optional",
            isostatic_col,
            "Isostatic correction applied using the supplied model term.",
        )
    elif selected_product == "Isostatic anomaly":
        add_stage(
            "ISOSTATIC",
            "Isostatic anomaly",
            "Isostatic anomaly",
            "Optional",
            "SKIPPED",
            "Isostatic product selected but no correction column was supplied.",
        )

    # Resolve the final product scientifically: if curvature is explicitly
    # applied and the user selected Complete Bouguer, the final product should
    # include that curvature correction rather than silently reverting to the
    # pre-curvature Complete Bouguer field. Likewise, Isostatic is only final
    # when the supplied isostatic term was actually applied.
    if selected_product == "Observed gravity":
        product_stage = "RAW_OBSERVED"
    elif selected_product == "Tide-corrected gravity":
        product_stage = "TIDE_CORRECTED"
    elif selected_product == "Drift-corrected gravity":
        product_stage = "DRIFT_CORRECTED"
    elif selected_product == "Latitude-corrected stage":
        product_stage = "LATITUDE_CORRECTED"
    elif selected_product == "Free-Air anomaly":
        product_stage = "FREE_AIR"
    elif selected_product == "Simple Bouguer anomaly":
        product_stage = "SIMPLE_BOUGUER"
    elif selected_product == "Complete Bouguer anomaly":
        product_stage = "CURVATURE" if curvature_col else "COMPLETE_BOUGUER"
    elif selected_product == "Isostatic anomaly":
        product_stage = "ISOSTATIC"
    else:
        product_stage = "COMPLETE_BOUGUER"

    final_entry = next((s for s in reversed(stages) if s["code"] == product_stage), stages[-1])
    final = pd.to_numeric(final_entry["series"], errors="coerce")

    # Explicit final product stage for downstream normalization/integration.
    # Unlike intermediate diagnostics, this is the selected endpoint of the
    # gravity reduction chain. For anomaly products it is an anomaly; for an
    # observed/corrected selection it remains the selected gravity product.
    if product_stage == "CURVATURE":
        display_product = "Complete Bouguer anomaly (curvature-corrected)"
    else:
        display_product = selected_product
    final_name = f"⭐ Final Gravity Product — {display_product}"
    final_entry_explicit = {
        "code": "FINAL_GRAVITY_PRODUCT",
        "name": final_name,
        "product": selected_product,
        "requirement": "Final product",
        "status": "FINAL",
        "series": final.copy(),
        "description": (
            f"Final selected gravity product after all selected/applicable corrections up to "
            f"'{display_product}'. Use this explicit final product for normalization, "
            "integration, targeting, interpretation, and reporting. Confirm any SKIPPED "
            "upstream correction represents an input already corrected to the required level."
        ),
    }
    stages.append(final_entry_explicit)

    work["Gravity_Final_Processed_mGal"] = final

    for item in stages:
        work[f"Gravity_{item['code']}_mGal"] = pd.to_numeric(item["series"], errors="coerce")

    metadata = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "survey_type": survey_type,
        "selected_product": selected_product,
        "stats": stats,
        "sign_convention": correction_sign,
        "qc_z_threshold": qc_z_threshold,
        "applied_steps": [s["code"] for s in stages if s["status"] == "APPLIED"],
        "final_stage": "FINAL_GRAVITY_PRODUCT",
        "final_source_stage": product_stage,
    }
    return work, stages, metadata


def contour_grid(
    lat: pd.Series,
    lon: pd.Series,
    values: pd.Series,
    nx: int = 160,
    ny: int = 160,
):
    lat = pd.to_numeric(lat, errors="coerce")
    lon = pd.to_numeric(lon, errors="coerce")
    values = pd.to_numeric(values, errors="coerce")
    mask = lat.notna() & lon.notna() & values.notna()

    x = lon[mask].to_numpy()
    y = lat[mask].to_numpy()
    z = values[mask].to_numpy()

    if len(z) < 3 or len(np.unique(x)) < 2 or len(np.unique(y)) < 2:
        return None

    gx = np.linspace(x.min(), x.max(), nx)
    gy = np.linspace(y.min(), y.max(), ny)
    X, Y = np.meshgrid(gx, gy)

    Z = griddata((x, y), z, (X, Y), method="linear")
    nearest = griddata((x, y), z, (X, Y), method="nearest")

    if Z is None or np.isnan(Z).all():
        Z = nearest
    else:
        Z = np.where(np.isnan(Z), nearest, Z)

    return X, Y, Z, x, y, z


def stage_summary(stages: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for item in stages:
        values = pd.to_numeric(item["series"], errors="coerce")
        rows.append(
            {
                "Step": item["code"],
                "Name": item["name"],
                "Product": item["product"],
                "Requirement": item["requirement"],
                "Status": item["status"],
                "Valid Points": int(values.notna().sum()),
                "Min": values.min(skipna=True),
                "Max": values.max(skipna=True),
                "Mean": values.mean(skipna=True),
                "Description": item["description"],
            }
        )
    return pd.DataFrame(rows)


def serializable_steps(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in item.items() if key != "series"}
        for item in stages
    ]
