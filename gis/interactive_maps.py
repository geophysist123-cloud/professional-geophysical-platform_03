from __future__ import annotations

import base64
import hashlib
import html
import io
from typing import Mapping

import folium
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from branca.colormap import LinearColormap
from folium.plugins import Fullscreen, MousePosition
from pyproj import CRS, Transformer
from scipy.interpolate import griddata

from targeting.integration import project_coordinates
from gis.map_performance import interactive_limits, prepare_interactive_project_data


BASEMAPS = {
    "OpenStreetMap Streets": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attr": "© OpenStreetMap contributors",
        "overlay": False,
    },
    "Esri World Imagery (Satellite)": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attr": "Esri, Maxar, Earthstar Geographics, and the GIS User Community",
        "overlay": False,
    },
    "Esri World Street Map": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        "attr": "Esri, HERE, Garmin, Intermap, increment P Corp., GEBCO, USGS, NGA, EPA, USDA, NPS",
        "overlay": False,
    },
    "Esri World Topographic Map": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        "attr": "Esri, HERE, Garmin, Intermap, increment P Corp., GEBCO, USGS, FAO, NPS, NRCAN, GeoBase, IGN, Kadaster NL, Ordnance Survey, Esri Japan, METI, Esri China (Hong Kong), OpenStreetMap contributors",
        "overlay": False,
    },
    "CartoDB Voyager": {
        "url": "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
        "attr": "© OpenStreetMap contributors © CARTO",
        "overlay": False,
        "subdomains": ["a", "b", "c", "d"],
    },
}

ROAD_TILE = {
    "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Transportation/MapServer/tile/{z}/{y}/{x}",
    "attr": "Esri, HERE, Garmin, FAO, USGS, NGA, EPA, NPS",
}
RAIL_TILE = {
    "url": "https://tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png",
    "attr": "Data © OpenStreetMap contributors, Style © OpenRailwayMap / CC-BY-SA 2.0",
}


def _crs(project_crs=4326) -> CRS:
    return project_crs if isinstance(project_crs, CRS) else CRS.from_user_input(project_crs)


def map_preference(map_id: str, field: str, default):
    key = f"map_pref__{map_id}__{field}"
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def set_map_preference(map_id: str, field: str, value):
    st.session_state[f"map_pref__{map_id}__{field}"] = value


@st.cache_data(show_spinner=False, ttl=3600)
def _cached_grid(x_values: tuple[float, ...], y_values: tuple[float, ...], z_values: tuple[float, ...], grid_size: int = 120):
    x = np.asarray(x_values, dtype=float)
    y = np.asarray(y_values, dtype=float)
    z = np.asarray(z_values, dtype=float)
    gx = np.linspace(x.min(), x.max(), grid_size)
    gy = np.linspace(y.min(), y.max(), grid_size)
    X, Y = np.meshgrid(gx, gy)
    Z = griddata((x, y), z, (X, Y), method="linear")
    Zn = griddata((x, y), z, (X, Y), method="nearest")
    Z = np.where(np.isnan(Z), Zn, Z)
    return X, Y, Z


def _resolve_value_column(df: pd.DataFrame, value_col) -> tuple[pd.DataFrame, str]:
    work = df.copy()
    if isinstance(value_col, str):
        if value_col not in work.columns:
            raise KeyError(f"Map value column '{value_col}' is not present in the dataframe.")
        return work, value_col
    if isinstance(value_col, pd.Series):
        if len(value_col) != len(work):
            raise ValueError("Map value series length does not match the dataframe.")
        work["__map_value__"] = pd.to_numeric(value_col.to_numpy(), errors="coerce")
        return work, "__map_value__"
    arr = np.asarray(value_col)
    if arr.ndim != 1 or len(arr) != len(work):
        raise ValueError("Map values must be a column name or a one-dimensional sequence matching the dataframe length.")
    work["__map_value__"] = pd.to_numeric(arr, errors="coerce")
    return work, "__map_value__"


@st.cache_data(show_spinner=False, ttl=3600)
def _geo_contour_features_cached(data_key, x_values, y_values, z_values, grid_size: int, contour_count: int):
    x = np.asarray(x_values, dtype=float)
    y = np.asarray(y_values, dtype=float)
    z = np.asarray(z_values, dtype=float)
    if len(x) < 3 or np.unique(x).size < 2 or np.unique(y).size < 2:
        return None
    X, Y, Z = _cached_grid(tuple(x), tuple(y), tuple(z), int(grid_size))
    finite = Z[np.isfinite(Z)]
    if finite.size == 0:
        return None
    vmin, vmax = float(np.nanmin(finite)), float(np.nanmax(finite))
    contour_segments = []
    level_span = abs(vmax - vmin)
    level_tol = max(1.0, abs(vmin), abs(vmax)) * 1e-10
    fig, ax = plt.subplots(figsize=(8, 6))
    if np.isfinite(vmin) and np.isfinite(vmax) and level_span > level_tol:
        contour_levels = np.unique(np.linspace(vmin, vmax, max(4, int(contour_count))))
        cs = ax.contour(X, Y, Z, levels=contour_levels) if contour_levels.size >= 2 else None
    else:
        cs = None
    if cs is not None:
        # Conversion to WGS84 is deliberately done by caller because CRS object
        # hashing can be expensive and we only want to cache numeric geometry.
        for level, segments in zip(cs.levels, cs.allsegs):
            for verts in segments:
                if len(verts) >= 2:
                    contour_segments.append((float(level), verts.astype(float)))
    plt.close(fig)
    return X, Y, Z, vmin, vmax, contour_segments

def _geo_contour_features(df: pd.DataFrame, value_col, project_crs=4326, levels: int = 12, grid_size: int | None = None, max_points: int | None = None, detail_mode: str = "Automatic (recommended)"):
    crs = _crs(project_crs)
    work, value_name = _resolve_value_column(df, value_col)
    display, downsampled, auto_grid, _ = prepare_interactive_project_data(work, project_crs, value_col=value_name, max_points=max_points, detail_mode=detail_mode)
    if display.empty:
        return None
    display[value_name] = pd.to_numeric(display[value_name], errors="coerce")
    display = display.dropna(subset=["Project_X", "Project_Y", value_name])
    if len(display) < 3 or display["Project_X"].nunique() < 2 or display["Project_Y"].nunique() < 2:
        return None
    x = display["Project_X"].to_numpy(float)
    y = display["Project_Y"].to_numpy(float)
    z = display[value_name].to_numpy(float)
    gs = int(grid_size or auto_grid)
    cache_key = hashlib.sha1(np.ascontiguousarray(np.column_stack([x, y, z])).view(np.uint8)).hexdigest()
    payload = _geo_contour_features_cached(cache_key, tuple(x), tuple(y), tuple(z), gs, int(levels))
    if payload is None:
        return None
    X, Y, Z, vmin, vmax, raw_segments = payload
    to_wgs84 = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)
    contour_segments = []
    for level, verts in raw_segments:
        lon, lat = to_wgs84.transform(verts[:, 0], verts[:, 1])
        contour_segments.append((float(level), [[float(a), float(b)] for a, b in zip(lon, lat)]))
    return X, Y, Z, vmin, vmax, contour_segments, display, downsampled, gs


def _raster_png(df: pd.DataFrame, value_col, project_crs=4326, cmap="viridis", alpha=0.65, grid_size=120):
    payload = _geo_contour_features(df, value_col, project_crs, grid_size=grid_size)
    if payload is None:
        return None
    X, Y, Z, vmin, vmax, contour_segments, work, downsampled, used_grid = payload
    fig, ax = plt.subplots(figsize=(10, 7), dpi=150)
    ax.imshow(
        Z,
        extent=[float(X.min()), float(X.max()), float(Y.min()), float(Y.max())],
        origin="lower", cmap=cmap, vmin=vmin, vmax=vmax, alpha=alpha, aspect="auto"
    )
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    return buf.getvalue(), float(X.min()), float(X.max()), float(Y.min()), float(Y.max()), contour_segments, work


def _bounds_to_wgs84(xmin, xmax, ymin, ymax, project_crs):
    crs = _crs(project_crs)
    tx = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)
    corners = [(xmin, ymin), (xmin, ymax), (xmax, ymin), (xmax, ymax)]
    ll = [tx.transform(x, y) for x, y in corners]
    lons = [p[0] for p in ll]; lats = [p[1] for p in ll]
    return [[float(min(lats)), float(min(lons))], [float(max(lats)), float(max(lons))]]


def _add_station_markers(m: folium.Map, df: pd.DataFrame, value_col: str | None = None, max_points: int = 1000):
    work = df.copy()
    lat = pd.to_numeric(work.get("Latitude"), errors="coerce")
    lon = pd.to_numeric(work.get("Longitude"), errors="coerce")
    work["__lat"] = lat; work["__lon"] = lon
    work = work.loc[lat.notna() & lon.notna()].copy()
    if len(work) > max_points:
        # Deterministic line-friendly thinning for marker display only.
        idx = np.linspace(0, len(work) - 1, max_points, dtype=int)
        work = work.iloc[np.unique(idx)]
    fg = folium.FeatureGroup(name="📍 Stations / measured points", show=True)
    for _, row in work.iterrows():
        bits = []
        for col in ["Point_ID", "Line_ID", "Station", "Elevation"]:
            if col in row.index and pd.notna(row[col]):
                bits.append(f"{col}: {row[col]}")
        if value_col and value_col in row.index and pd.notna(row[value_col]):
            bits.append(f"Value: {float(row[value_col]):.3f}")
        folium.CircleMarker(
            location=[float(row["__lat"]), float(row["__lon"])], radius=2.6, weight=0.7,
            fill=True, fill_opacity=0.72,
            tooltip=" | ".join(bits) if bits else None,
            popup="<br>".join(bits) if bits else None,
        ).add_to(fg)
    fg.add_to(m)


def _add_targets(m: folium.Map, df: pd.DataFrame, max_points: int = 1500):
    if "Target_Score" not in df.columns or "Latitude" not in df.columns or "Longitude" not in df.columns:
        return
    work = df.copy()
    work["__score"] = pd.to_numeric(work["Target_Score"], errors="coerce")
    work["__lat"] = pd.to_numeric(work["Latitude"], errors="coerce")
    work["__lon"] = pd.to_numeric(work["Longitude"], errors="coerce")
    work = work.dropna(subset=["__score", "__lat", "__lon"])
    work = work.sort_values("__score", ascending=False).head(max_points)
    if work.empty:
        return
    cmap = LinearColormap(["#2c7bb6", "#ffffbf", "#d7191c"], vmin=0, vmax=100)
    cmap.caption = "Target Score"
    fg = folium.FeatureGroup(name="🎯 Targets", show=True)
    for _, row in work.iterrows():
        priority = str(row.get("Target_Priority", ""))
        score = float(row["__score"])
        folium.CircleMarker(
            location=[float(row["__lat"]), float(row["__lon"])], radius=5.5,
            color=cmap(score), fill=True, fill_color=cmap(score), fill_opacity=0.9,
            tooltip=f"Target: {score:.1f} | {priority}",
            popup=f"Target Score: {score:.2f}<br>Priority: {html.escape(priority)}",
        ).add_to(fg)
    fg.add_to(m)
    cmap.add_to(m)


def _add_common_reference_layers(m: folium.Map, *, show_roads: bool = True, show_railways: bool = True,
                                 geological_wms_url: str = "", geological_wms_layer: str = "", geological_wms_name: str = "Geological map"):
    if show_roads:
        folium.TileLayer(tiles=ROAD_TILE["url"], attr=ROAD_TILE["attr"], name="🛣️ Roads / transportation", overlay=True, control=True, opacity=0.9).add_to(m)
    if show_railways:
        folium.TileLayer(tiles=RAIL_TILE["url"], attr=RAIL_TILE["attr"], name="🚆 Railways", overlay=True, control=True, opacity=0.86, min_zoom=0, max_zoom=19).add_to(m)
    if geological_wms_url.strip() and geological_wms_layer.strip():
        folium.raster_layers.WmsTileLayer(
            url=geological_wms_url.strip(), layers=geological_wms_layer.strip(), fmt="image/png", transparent=True,
            version="1.3.0", name=f"🪨 {geological_wms_name.strip() or 'Geological map'}", overlay=True, control=True,
            opacity=0.72, attr="Geological map service — verify provider attribution and terms",
        ).add_to(m)


def _add_geophysical_overlay(
    m, df, value_col, label, project_crs, cmap="viridis", show_surface=True, show_contours=True,
    show_contour_labels=False, contour_color="#2b2b2b", contour_width=1.2, opacity=0.62, grid_size=120,
    detail_mode="Automatic (recommended)",
):
    payload = _raster_png(df, value_col, project_crs, cmap=cmap, alpha=opacity, grid_size=grid_size)
    if payload is None:
        return False
    png, xmin, xmax, ymin, ymax, contour_segments, _ = payload
    bounds = _bounds_to_wgs84(xmin, xmax, ymin, ymax, project_crs)
    image_b64 = base64.b64encode(png).decode("ascii")
    surface_fg = folium.FeatureGroup(name=f"🌡️ {label} surface", show=show_surface)
    folium.raster_layers.ImageOverlay(
        image=f"data:image/png;base64,{image_b64}", bounds=bounds, opacity=1.0,
        interactive=True, cross_origin=False, zindex=300,
    ).add_to(surface_fg)
    surface_fg.add_to(m)

    if show_contours and contour_segments:
        contour_fg = folium.FeatureGroup(name=f"〰️ {label} contours", show=True)
        features = [
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": {"level": round(level, 4)}}
            for level, coords in contour_segments
        ]
        geojson = folium.GeoJson(
            {"type": "FeatureCollection", "features": features},
            style_function=lambda feat: {"color": contour_color, "weight": float(contour_width), "opacity": 0.82},
            tooltip=folium.GeoJsonTooltip(fields=["level"], aliases=["Contour value"], sticky=False),
        )
        geojson.add_to(contour_fg)
        contour_fg.add_to(m)
        if show_contour_labels:
            label_fg = folium.FeatureGroup(name=f"🔢 {label} contour values", show=True)
            # Keep labels sparse: one label at the midpoint of the longest segment per level.
            for level, coords in contour_segments:
                if len(coords) < 2:
                    continue
                mid = coords[len(coords) // 2]
                folium.Marker(
                    location=[mid[1], mid[0]],
                    icon=folium.DivIcon(html=f'<div style="font-size:10px;font-weight:600;color:{contour_color};background:rgba(255,255,255,.78);padding:1px 3px;border-radius:2px;border:1px solid rgba(0,0,0,.15);">{level:.3f}</div>'),
                ).add_to(label_fg)
            label_fg.add_to(m)
    return True


def _map_base_layers(m: folium.Map, initial_base: str):
    for name, spec in BASEMAPS.items():
        kwargs = dict(tiles=spec["url"], attr=spec["attr"], name=name, overlay=False, control=True)
        if spec.get("subdomains"):
            kwargs["subdomains"] = spec["subdomains"]
        kwargs["show"] = (name == initial_base)
        folium.TileLayer(**kwargs).add_to(m)
    # Leaflet selects the first base layer by default; reorder by enabling the requested layer
    # through a small browser-side snippet without storing bulky state in Python.
    if initial_base in BASEMAPS and initial_base != "OpenStreetMap Streets":
        m.get_root().html.add_child(folium.Element(f"<script>setTimeout(function(){{var layers=document.querySelectorAll('.leaflet-control-layers-base label span');}},100);</script>"))


def create_interactive_geophysical_map(
    df: pd.DataFrame,
    value_col,
    title: str,
    project_crs=4326,
    project_name: str = "",
    interpretation: str = "",
    base_map: str = "OpenStreetMap Streets",
    show_railways: bool = True,
    show_roads: bool = True,
    show_stations: bool = True,
    show_targets: bool = True,
    show_surface: bool = True,
    show_contours: bool = True,
    show_contour_labels: bool = False,
    contour_color: str = "#2b2b2b",
    contour_width: float = 1.2,
    geological_wms_url: str = "",
    geological_wms_layer: str = "",
    geological_wms_name: str = "Geological WMS",
    map_height: int = 820,
    overlay_opacity: float = 0.62,
    detail_mode: str = "Automatic (recommended)",
):
    work, value_name = _resolve_value_column(df, value_col)
    work["Latitude"] = pd.to_numeric(work.get("Latitude"), errors="coerce")
    work["Longitude"] = pd.to_numeric(work.get("Longitude"), errors="coerce")
    work[value_name] = pd.to_numeric(work[value_name], errors="coerce")
    work = work.dropna(subset=["Latitude", "Longitude", value_name])
    if work.empty:
        return None

    lat0 = float(work["Latitude"].mean()); lon0 = float(work["Longitude"].mean())
    m = folium.Map(location=[lat0, lon0], zoom_start=9, tiles=None, control_scale=True, prefer_canvas=True)
    _map_base_layers(m, base_map)
    _add_common_reference_layers(m, show_roads=show_roads, show_railways=show_railways, geological_wms_url=geological_wms_url, geological_wms_layer=geological_wms_layer, geological_wms_name=geological_wms_name)
    _, auto_grid, max_markers = interactive_limits(len(work), detail_mode)
    _add_geophysical_overlay(m, work, value_name, title, project_crs, cmap="viridis", show_surface=show_surface, show_contours=show_contours, show_contour_labels=show_contour_labels, contour_color=contour_color, contour_width=contour_width, opacity=overlay_opacity, grid_size=auto_grid, detail_mode=detail_mode)
    if show_stations:
        _add_station_markers(m, work, value_col=value_name, max_points=max_markers)
    if show_targets:
        _add_targets(m, work)

    m.fit_bounds([[float(work["Latitude"].min()), float(work["Longitude"].min())], [float(work["Latitude"].max()), float(work["Longitude"].max())]], padding=(16, 16))
    Fullscreen(position="topleft", title="Open full screen", title_cancel="Exit full screen").add_to(m)
    MousePosition(position="bottomleft", separator=" | ", prefix="Lon/Lat:", num_digits=5).add_to(m)
    folium.map.LayerControl(collapsed=True, position="topright").add_to(m)
    crs = CRS.from_user_input(project_crs)
    auth = crs.to_authority()
    auth_text = f"{auth[0]}:{auth[1]}" if auth else "Custom CRS"
    html_block = f"<div style='position:fixed;top:14px;left:55px;z-index:9999;background:rgba(255,255,255,.92);padding:8px 11px;border-radius:6px;border:1px solid #888;max-width:310px;max-height:120px;overflow:auto;pointer-events:none;box-shadow:0 1px 4px rgba(0,0,0,.25);'><b>{html.escape(title)}</b><br><span style='font-size:12px;'>Project: {html.escape(project_name or '—')} | CRS: {html.escape(auth_text)} — {html.escape(crs.name)}</span>{f'<hr style="margin:5px 0"><span style="font-size:12px;"><b>Interpretation:</b> {html.escape(interpretation.strip())}</span>' if interpretation.strip() else ''}</div>"
    m.get_root().html.add_child(folium.Element(html_block))
    return m


def create_unified_geophysical_map(
    df: pd.DataFrame,
    layers: Mapping[str, Mapping[str, object]],
    title: str,
    project_crs=4326,
    project_name: str = "",
    interpretation: str = "",
    base_map: str = "OpenStreetMap Streets",
    show_roads: bool = True,
    show_railways: bool = True,
    show_stations: bool = True,
    show_targets: bool = True,
    geological_wms_url: str = "",
    geological_wms_layer: str = "",
    geological_wms_name: str = "Geological map",
    show_contour_labels: bool = False,
    contour_color: str = "#2b2b2b",
    contour_width: float = 1.2,
    detail_mode: str = "Automatic (recommended)",
):
    coords = df.copy()
    coords["Latitude"] = pd.to_numeric(coords.get("Latitude"), errors="coerce")
    coords["Longitude"] = pd.to_numeric(coords.get("Longitude"), errors="coerce")
    coords = coords.dropna(subset=["Latitude", "Longitude"])
    if coords.empty:
        return None
    m = folium.Map(location=[float(coords["Latitude"].mean()), float(coords["Longitude"].mean())], zoom_start=9, tiles=None, control_scale=True, prefer_canvas=True)
    _map_base_layers(m, base_map)
    _add_common_reference_layers(m, show_roads=show_roads, show_railways=show_railways, geological_wms_url=geological_wms_url, geological_wms_layer=geological_wms_layer, geological_wms_name=geological_wms_name)
    for name, spec in layers.items():
        col = spec.get("column")
        if not col or col not in coords.columns:
            continue
        _add_geophysical_overlay(
            m, coords, col, name, project_crs, cmap=str(spec.get("cmap", "viridis")),
            show_surface=bool(spec.get("show_surface", True)), show_contours=bool(spec.get("show_contours", True)),
            show_contour_labels=show_contour_labels, contour_color=contour_color, contour_width=contour_width,
            opacity=float(spec.get("opacity", 0.45)), grid_size=None, detail_mode=detail_mode,
        )
    if show_stations:
        _, _, max_markers = interactive_limits(len(coords), detail_mode)
        _add_station_markers(m, coords, value_col=None, max_points=max_markers)
    if show_targets:
        _add_targets(m, coords)
    m.fit_bounds([[float(coords["Latitude"].min()), float(coords["Longitude"].min())], [float(coords["Latitude"].max()), float(coords["Longitude"].max())]], padding=(16, 16))
    Fullscreen(position="topleft", title="Open full screen", title_cancel="Exit full screen").add_to(m)
    MousePosition(position="bottomleft", separator=" | ", prefix="Lon/Lat:", num_digits=5).add_to(m)
    folium.map.LayerControl(collapsed=True, position="topright").add_to(m)
    crs = CRS.from_user_input(project_crs)
    auth = crs.to_authority(); auth_text = f"{auth[0]}:{auth[1]}" if auth else "Custom CRS"
    panel = f"<div style='position:fixed;top:14px;left:55px;z-index:9999;background:rgba(255,255,255,.92);padding:8px 11px;border-radius:6px;border:1px solid #888;max-width:320px;max-height:120px;overflow:auto;pointer-events:none;box-shadow:0 1px 4px rgba(0,0,0,.25);'><b>{html.escape(title)}</b><br><span style='font-size:12px;'>Project: {html.escape(project_name or '—')} | CRS: {html.escape(auth_text)} — {html.escape(crs.name)}</span>{f'<hr style="margin:5px 0"><span style="font-size:12px;"><b>Interpretation:</b> {html.escape(interpretation.strip())}</span>' if interpretation.strip() else ''}</div>"
    m.get_root().html.add_child(folium.Element(panel))
    return m


def render_map_controls(map_id: str, *, include_mode: bool = True, include_geology: bool = True):
    """Render compact per-map controls whose choices persist independently by map_id."""
    st.caption("Map controls are remembered independently for this map during the session. Layer visibility can also be changed from the map's ArcGIS-style layer tree.")
    if include_mode:
        mode = st.radio(
            "View",
            ["Project CRS map", "Live web basemap"],
            horizontal=True,
            index=0 if map_preference(map_id, "mode", "Project CRS map") == "Project CRS map" else 1,
            key=f"ui_{map_id}_mode",
        )
        set_map_preference(map_id, "mode", mode)
    else:
        mode = "Live web basemap"

    if mode == "Live web basemap":
        base_options = list(BASEMAPS.keys())
        current = map_preference(map_id, "basemap", base_options[0])
        if current not in base_options:
            current = base_options[0]
        base_map = st.selectbox("Basemap", base_options, index=base_options.index(current), key=f"ui_{map_id}_basemap")
        set_map_preference(map_id, "basemap", base_map)
    else:
        base_map = map_preference(map_id, "basemap", list(BASEMAPS.keys())[0])

    c1, c2, c3 = st.columns(3)
    with c1:
        show_roads = st.checkbox("Roads / transport", value=bool(map_preference(map_id, "roads", True)), key=f"ui_{map_id}_roads")
    with c2:
        show_railways = st.checkbox("Railways", value=bool(map_preference(map_id, "railways", True)), key=f"ui_{map_id}_railways")
    with c3:
        show_stations = st.checkbox("Stations", value=bool(map_preference(map_id, "stations", True)), key=f"ui_{map_id}_stations")
    set_map_preference(map_id, "roads", show_roads)
    set_map_preference(map_id, "railways", show_railways)
    set_map_preference(map_id, "stations", show_stations)

    show_targets = st.checkbox("Targets", value=bool(map_preference(map_id, "targets", True)), key=f"ui_{map_id}_targets")
    show_surface = st.checkbox("Geophysical surface", value=bool(map_preference(map_id, "surface", True)), key=f"ui_{map_id}_surface")
    show_contours = st.checkbox("Contour lines", value=bool(map_preference(map_id, "contours", True)), key=f"ui_{map_id}_contours")
    set_map_preference(map_id, "targets", show_targets)
    set_map_preference(map_id, "surface", show_surface)
    set_map_preference(map_id, "contours", show_contours)

    with st.expander("🎨 Contour display", expanded=False):
        show_contour_labels = st.checkbox("Show contour values", value=bool(map_preference(map_id, "contour_labels", False)), key=f"ui_{map_id}_contour_labels")
        contour_color = st.color_picker("Contour line color", value=str(map_preference(map_id, "contour_color", "#2b2b2b")), key=f"ui_{map_id}_contour_color")
        contour_width = st.slider("Contour line width", 0.5, 4.0, float(map_preference(map_id, "contour_width", 1.2)), 0.1, key=f"ui_{map_id}_contour_width")
    set_map_preference(map_id, "contour_labels", show_contour_labels)
    set_map_preference(map_id, "contour_color", contour_color)
    set_map_preference(map_id, "contour_width", contour_width)
    detail_mode = st.selectbox(
        "Interactive detail",
        ["Automatic (recommended)", "Balanced", "High detail"],
        index=["Automatic (recommended)", "Balanced", "High detail"].index(str(map_preference(map_id, "detail_mode", "Automatic (recommended)"))),
        key=f"ui_{map_id}_detail_mode",
        help="Automatic keeps large projects responsive. Full-resolution processing and exports are unaffected.",
    )
    set_map_preference(map_id, "detail_mode", detail_mode)
    st.caption("Interactive maps use cached, spatially balanced display decimation for large datasets. Raw/processed data and scientific exports remain full resolution.")

    if include_geology:
        with st.expander("🪨 Geological WMS overlay", expanded=False):
            geo_url = st.text_input("WMS service URL", value=map_preference(map_id, "geo_url", ""), key=f"ui_{map_id}_geo_url", placeholder="https://.../wms")
            geo_layer = st.text_input("WMS layer", value=map_preference(map_id, "geo_layer", ""), key=f"ui_{map_id}_geo_layer", placeholder="layer_name")
            geo_name = st.text_input("Layer label", value=map_preference(map_id, "geo_name", "Geological map"), key=f"ui_{map_id}_geo_name")
            set_map_preference(map_id, "geo_url", geo_url)
            set_map_preference(map_id, "geo_layer", geo_layer)
            set_map_preference(map_id, "geo_name", geo_name)
    else:
        geo_url = geo_layer = ""
        geo_name = "Geological map"

    h = int(map_preference(map_id, "height", 820))
    height = st.slider("Map height (px)", 550, 1100, h, 50, key=f"ui_{map_id}_height")
    set_map_preference(map_id, "height", height)
    return {
        "mode": mode, "base_map": base_map, "show_roads": show_roads, "show_railways": show_railways,
        "show_stations": show_stations, "show_targets": show_targets, "show_surface": show_surface,
        "show_contours": show_contours, "show_contour_labels": show_contour_labels, "contour_color": contour_color, "contour_width": contour_width,
        "geo_url": geo_url, "geo_layer": geo_layer, "geo_name": geo_name,
        "detail_mode": detail_mode, "height": height,
    }
