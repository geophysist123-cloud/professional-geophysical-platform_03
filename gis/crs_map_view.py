from __future__ import annotations

import html
import numpy as np
import pandas as pd
from pyproj import CRS
from scipy.interpolate import griddata
import streamlit as st

from targeting.integration import project_coordinates
from gis.map_performance import interactive_limits, prepare_interactive_project_data


@st.cache_data(show_spinner=False, ttl=3600)
def _cached_project_grid(x_values: tuple[float, ...], y_values: tuple[float, ...], z_values: tuple[float, ...], grid_size: int = 180):
    x = np.asarray(x_values, dtype=float)
    y = np.asarray(y_values, dtype=float)
    z = np.asarray(z_values, dtype=float)
    gx = np.linspace(x.min(), x.max(), grid_size)
    gy = np.linspace(y.min(), y.max(), grid_size)
    X, Y = np.meshgrid(gx, gy)
    Z = griddata((x, y), z, (X, Y), method="linear")
    Zn = griddata((x, y), z, (X, Y), method="nearest")
    return gx, gy, np.where(np.isnan(Z), Zn, Z)


def build_project_crs_figure(
    df: pd.DataFrame,
    value_col,
    title: str,
    project_crs=4326,
    interpretation: str = "",
    colorscale: str = "Viridis",
    levels: int = 18,
    height: int = 760,
    show_surface: bool = True,
    show_contours: bool = True,
    show_points: bool = True,
    show_contour_labels: bool = False,
    contour_color: str = "#2b2b2b",
    contour_width: float = 1.2,
    detail_mode: str = "Automatic (recommended)",
):
    """Project CRS map with independent surface, contour, and label controls."""
    import plotly.graph_objects as go
    crs = project_crs if isinstance(project_crs, CRS) else CRS.from_user_input(project_crs)
    work = df.copy()
    if isinstance(value_col, str):
        if value_col not in work.columns:
            return None
        work["__value__"] = pd.to_numeric(work[value_col], errors="coerce")
    else:
        arr = np.asarray(value_col)
        if arr.ndim != 1 or len(arr) != len(work):
            return None
        work["__value__"] = pd.to_numeric(arr, errors="coerce")
    work, downsampled, grid_size, _ = prepare_interactive_project_data(work, crs, value_col="__value__", detail_mode=detail_mode)
    work = work.dropna(subset=["Project_X", "Project_Y", "__value__"]).copy()
    if work.empty:
        return None
    x = work["Project_X"].to_numpy(float); y = work["Project_Y"].to_numpy(float); z = work["__value__"].to_numpy(float)
    fig = go.Figure()
    if len(work) >= 4 and np.unique(x).size >= 2 and np.unique(y).size >= 2 and (show_surface or show_contours):
        gx, gy, Z = _cached_project_grid(tuple(x), tuple(y), tuple(z), int(grid_size))
        if show_surface:
            fig.add_trace(go.Heatmap(
                x=gx, y=gy, z=Z, colorscale=colorscale, zsmooth="best", name="Geophysical surface",
                colorbar={"title":"Value"}, hovertemplate="Easting: %{x:.2f}<br>Northing: %{y:.2f}<br>Value: %{z:.3f}<extra></extra>", showlegend=True,
            ))
        if show_contours:
            fig.add_trace(go.Contour(
                x=gx, y=gy, z=Z, colorscale=colorscale, showscale=False, ncontours=levels,
                contours={"showlabels": bool(show_contour_labels), "showlines": True, "coloring":"none", "labelfont":{"size":10,"color":contour_color}},
                line={"color":contour_color,"width":contour_width}, name="Contour lines",
                hovertemplate="Easting: %{x:.2f}<br>Northing: %{y:.2f}<br>Contour: %{z:.3f}<extra></extra>",
            ))
    if show_points:
        point_text=[str(v) for v in work.get("Point_ID", range(len(work)))]
        fig.add_trace(go.Scattergl(x=x,y=y,mode="markers",marker={"size":6,"symbol":"circle-open","line":{"width":1}},text=point_text,customdata=np.stack([z],axis=1),name="Measured points",hovertemplate="Point: %{text}<br>Easting: %{x:.2f}<br>Northing: %{y:.2f}<br>Value: %{customdata[0]:.3f}<extra></extra>"))
    auth=crs.to_authority(); auth_text=f"{auth[0]}:{auth[1]}" if auth else "Custom CRS"
    unit_x=crs.axis_info[0].unit_name if crs.axis_info else "project units"; unit_y=crs.axis_info[1].unit_name if len(crs.axis_info)>1 else "project units"
    note=f"<b>Project CRS:</b> {html.escape(auth_text)} — {html.escape(crs.name)}<br><b>Axes:</b> X/Easting ({html.escape(unit_x)}), Y/Northing ({html.escape(unit_y)})"
    if downsampled: note += "<br><span style='font-size:11px'><b>Interactive display:</b> spatially decimated for performance; full-resolution data remains available for processing/exports.</span>"
    if interpretation.strip(): note += f"<br><br><b>Interpretation:</b> {html.escape(interpretation.strip())}"
    fig.add_annotation(xref="paper", yref="paper", x=0.01, y=0.99, xanchor="left", yanchor="top", text=note, showarrow=False, align="left", bgcolor="rgba(255,255,255,0.88)", bordercolor="rgba(80,80,80,0.5)", borderwidth=1, font={"size":12})
    fig.update_layout(title=title,height=height,margin={"l":70,"r":30,"t":70,"b":70},dragmode="pan",legend={"orientation":"h","y":-0.12})
    fig.update_xaxes(title=f"X / Easting ({unit_x})",showgrid=True,zeroline=False)
    fig.update_yaxes(title=f"Y / Northing ({unit_y})",showgrid=True,zeroline=False,scaleanchor="x",scaleratio=1)
    return fig

def build_unified_project_crs_figure(df: pd.DataFrame, layers: dict[str, dict[str, object]], title: str, project_crs=4326, interpretation: str = "", height: int = 840, show_contour_labels: bool = False, contour_color: str = "#2b2b2b", contour_width: float = 1.2, detail_mode: str = "Automatic (recommended)"):
    """Build one Project-CRS map where each geophysical product is an independent Plotly legend layer."""
    import plotly.graph_objects as go

    crs = project_crs if isinstance(project_crs, CRS) else CRS.from_user_input(project_crs)
    work = df.copy()
    work, downsampled, grid_size, _ = prepare_interactive_project_data(work, crs, detail_mode=detail_mode)
    work["__lat__"] = pd.to_numeric(work.get("Latitude"), errors="coerce")
    work["__lon__"] = pd.to_numeric(work.get("Longitude"), errors="coerce")
    fig = go.Figure()
    for label, spec in layers.items():
        col = spec.get("column")
        if not col or col not in work.columns:
            continue
        values = pd.to_numeric(work[col], errors="coerce")
        valid = work["Project_X"].notna() & work["Project_Y"].notna() & values.notna()
        if valid.sum() < 4:
            continue
        x = work.loc[valid, "Project_X"].to_numpy(float); y = work.loc[valid, "Project_Y"].to_numpy(float); z = values.loc[valid].to_numpy(float)
        if np.unique(x).size < 2 or np.unique(y).size < 2:
            continue
        gx, gy, Z = _cached_project_grid(tuple(x), tuple(y), tuple(z), grid_size)
        fig.add_trace(go.Contour(
            x=gx, y=gy, z=Z, colorscale=str(spec.get("colorscale", "Viridis")), ncontours=18,
            showscale=False, visible=bool(spec.get("visible", True)), name=label,
            contours={"showlabels": bool(show_contour_labels), "showlines": True, "labelfont": {"size": 9, "color": contour_color}, "coloring": "heatmap"}, line={"color": contour_color, "width": contour_width}, opacity=float(spec.get("opacity", 0.5)),
            hovertemplate=f"{html.escape(label)}<br>Easting: %{{x:.2f}}<br>Northing: %{{y:.2f}}<br>Value: %{{z:.3f}}<extra></extra>",
        ))
    valid_points = work["Project_X"].notna() & work["Project_Y"].notna()
    if valid_points.sum():
        pts = work.loc[valid_points].copy()
        point_text = [str(v) for v in pts.get("Point_ID", range(len(pts)))]
        fig.add_trace(go.Scattergl(
            x=pts["Project_X"], y=pts["Project_Y"], mode="markers", name="📍 Stations",
            marker={"size": 5, "symbol": "circle-open", "line": {"width": 1}}, text=point_text,
            hovertemplate="Point: %{text}<br>Easting: %{x:.2f}<br>Northing: %{y:.2f}<extra></extra>",
        ))
    if "Target_Score" in work.columns:
        tv = pd.to_numeric(work["Target_Score"], errors="coerce")
        v = valid_points & tv.notna()
        if v.any():
            pts = work.loc[v]
            fig.add_trace(go.Scattergl(
                x=pts["Project_X"], y=pts["Project_Y"], mode="markers", name="🎯 Targets",
                marker={"size": 8, "symbol": "diamond", "opacity": 0.85},
                customdata=np.stack([tv.loc[v].to_numpy(float)], axis=1),
                hovertemplate="Target score: %{customdata[0]:.2f}<br>Easting: %{x:.2f}<br>Northing: %{y:.2f}<extra></extra>",
            ))
    auth = crs.to_authority(); auth_text = f"{auth[0]}:{auth[1]}" if auth else "Custom CRS"
    ux = crs.axis_info[0].unit_name if crs.axis_info else "project units"; uy = crs.axis_info[1].unit_name if len(crs.axis_info) > 1 else "project units"
    note = f"<b>Project CRS:</b> {html.escape(auth_text)} — {html.escape(crs.name)}<br><b>Axes:</b> X/Easting ({html.escape(ux)}), Y/Northing ({html.escape(uy)})<br><span style='font-size:11px'>Click legend items to turn layers on/off.</span>"
    if downsampled:
        note += "<br><span style='font-size:11px'><b>Interactive display:</b> spatially decimated for performance; full-resolution data remains available for processing/exports.</span>"
    if interpretation.strip(): note += f"<br><br><b>Interpretation:</b> {html.escape(interpretation.strip())}"
    fig.add_annotation(xref="paper", yref="paper", x=0.01, y=0.99, xanchor="left", yanchor="top", text=note, showarrow=False, align="left", bgcolor="rgba(255,255,255,0.88)", bordercolor="rgba(80,80,80,0.5)", borderwidth=1, font={"size":12})
    fig.update_layout(title=title, height=height, margin={"l":70,"r":30,"t":70,"b":70}, dragmode="pan", legend={"orientation":"v","x":1.02,"y":1.0})
    fig.update_xaxes(title=f"X / Easting ({ux})", showgrid=True, zeroline=False)
    fig.update_yaxes(title=f"Y / Northing ({uy})", showgrid=True, zeroline=False, scaleanchor="x", scaleratio=1)
    return fig

