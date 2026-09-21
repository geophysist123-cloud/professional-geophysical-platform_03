from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st
from pyproj import CRS, Transformer


def interactive_limits(n_points: int, detail_mode: str = "Automatic (recommended)") -> tuple[int, int, int]:
    """Return (max_interpolation_points, grid_size, max_station_markers).

    These limits apply only to interactive rendering. Scientific processing and
    static/export products continue to use the full processed dataset.
    """
    n = int(max(0, n_points))
    mode = str(detail_mode or "Automatic (recommended)")
    if mode == "High detail":
        if n <= 2_000: return min(n, 2_000), 110, min(n, 800)
        if n <= 10_000: return 6_000, 95, 1_000
        if n <= 50_000: return 10_000, 85, 900
        if n <= 250_000: return 12_000, 75, 700
        return 15_000, 65, 500
    if mode == "Balanced":
        if n <= 2_000: return min(n, 1_500), 100, min(n, 600)
        if n <= 10_000: return 5_000, 85, 800
        if n <= 50_000: return 7_000, 75, 650
        if n <= 250_000: return 9_000, 65, 500
        return 11_000, 60, 400
    # Automatic: optimize for a fast interactive browser while preserving shape.
    if n <= 2_000: return min(n, 1_200), 90, min(n, 450)
    if n <= 10_000: return 4_000, 80, 650
    if n <= 50_000: return 6_000, 70, 500
    if n <= 250_000: return 8_000, 60, 400
    return 10_000, 55, 300


def _pick_spatially_balanced(df: pd.DataFrame, max_points: int, x_col: str, y_col: str) -> pd.DataFrame:
    if len(df) <= max_points:
        return df.copy()
    work = df.copy()
    x = pd.to_numeric(work[x_col], errors="coerce")
    y = pd.to_numeric(work[y_col], errors="coerce")
    valid = x.notna() & y.notna()
    work = work.loc[valid].copy()
    if len(work) <= max_points:
        return work

    # Spatially balanced display decimation: choose approximately one sample per
    # occupied grid cell. This avoids the visual bias of taking every Nth row on
    # line-based surveys while remaining deterministic and cheap.
    side = max(2, int(math.ceil(math.sqrt(max_points))))
    xmin, xmax = float(x.loc[work.index].min()), float(x.loc[work.index].max())
    ymin, ymax = float(y.loc[work.index].min()), float(y.loc[work.index].max())
    xr = max(xmax - xmin, 1e-12)
    yr = max(ymax - ymin, 1e-12)
    bx = np.clip(((pd.to_numeric(work[x_col], errors="coerce") - xmin) / xr * side).astype(int), 0, side - 1)
    by = np.clip(((pd.to_numeric(work[y_col], errors="coerce") - ymin) / yr * side).astype(int), 0, side - 1)
    work["__bin_x"] = bx.to_numpy()
    work["__bin_y"] = by.to_numpy()

    # Prefer the point closest to each cell centre so line geometry stays visible.
    centers_x = xmin + (work["__bin_x"].to_numpy() + 0.5) * xr / side
    centers_y = ymin + (work["__bin_y"].to_numpy() + 0.5) * yr / side
    dist2 = (pd.to_numeric(work[x_col], errors="coerce").to_numpy() - centers_x) ** 2 + (
        pd.to_numeric(work[y_col], errors="coerce").to_numpy() - centers_y
    ) ** 2
    work["__cell_distance"] = dist2
    picked = work.sort_values(["__bin_y", "__bin_x", "__cell_distance"]).drop_duplicates(["__bin_y", "__bin_x"], keep="first")

    if len(picked) > max_points:
        picked = picked.iloc[np.linspace(0, len(picked) - 1, max_points, dtype=int)]
    return picked.drop(columns=["__bin_x", "__bin_y", "__cell_distance"], errors="ignore")


def prepare_interactive_project_data(
    df: pd.DataFrame,
    project_crs,
    value_col: Optional[str] = None,
    max_points: Optional[int] = None,
    detail_mode: str = "Automatic (recommended)",
) -> tuple[pd.DataFrame, bool, int, int]:
    """Prepare a compact display frame using existing Project_X/Y when available."""
    out = df.copy()
    crs = project_crs if isinstance(project_crs, CRS) else CRS.from_user_input(project_crs)
    auth = crs.to_string()
    existing_crs = out["Project_CRS"].iloc[0] if "Project_CRS" in out.columns and len(out) else ""
    if "Project_X" not in out.columns or "Project_Y" not in out.columns or str(existing_crs) != auth:
        # Projection is done in a cached vectorized operation when required.
        lat = pd.to_numeric(out.get("Latitude"), errors="coerce")
        lon = pd.to_numeric(out.get("Longitude"), errors="coerce")
        if lat is None or lon is None:
            return out.iloc[0:0].copy(), False, 0, 0
        x, y = cached_project_xy(tuple(lon.fillna(np.nan)), tuple(lat.fillna(np.nan)), auth)
        out["Project_X"] = x
        out["Project_Y"] = y
        out["Project_CRS"] = auth

    n = len(out)
    smart_max, grid_size, max_markers = interactive_limits(n, detail_mode)
    limit = int(max_points or smart_max)
    display = _pick_spatially_balanced(out, limit, "Project_X", "Project_Y")
    return display, len(display) < n, grid_size, max_markers


@st.cache_data(show_spinner=False, ttl=3600)
def cached_project_xy(lon_values: tuple[float, ...], lat_values: tuple[float, ...], crs_string: str):
    lon = np.asarray(lon_values, dtype=float)
    lat = np.asarray(lat_values, dtype=float)
    tx = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_user_input(crs_string), always_xy=True)
    x = np.full(len(lon), np.nan, dtype=float)
    y = np.full(len(lat), np.nan, dtype=float)
    valid = np.isfinite(lon) & np.isfinite(lat)
    if valid.any():
        xx, yy = tx.transform(lon[valid], lat[valid])
        x[valid] = xx
        y[valid] = yy
    return x, y
