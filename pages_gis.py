from __future__ import annotations

import io
from datetime import datetime, timezone

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
from gis.interactive_maps import create_interactive_geophysical_map, BASEMAPS, render_map_controls
from gis.crs_map_view import build_project_crs_figure

from database.geophysical_store import save_interpretation
from targeting.integration import combine_scores, contour_figure, NORMALIZERS
from gis.crs_mapping import render_project_selector, project_crs_value, project_crs_details, attach_project_coordinates


def _current_data():
    scored = st.session_state.get('integration_scored_df')
    if isinstance(scored, pd.DataFrame) and not scored.empty:
        return scored.copy()
    mag = st.session_state.get('mag_processing_df')
    grav = st.session_state.get('gravity_processing_df')
    if mag is None or grav is None:
        return None
    if 'Point_ID' in mag.columns and 'Point_ID' in grav.columns:
        source = mag.merge(grav, on='Point_ID', how='outer', suffixes=('_Mag', '_Grav'))
        for c in ('Latitude', 'Longitude', 'Line_ID'):
            if f'{c}_Mag' in source.columns:
                source[c] = source[f'{c}_Mag'].combine_first(source.get(f'{c}_Grav'))
    elif all(c in mag.columns for c in ('Line_ID', 'Station')) and all(c in grav.columns for c in ('Line_ID', 'Station')):
        source = mag.merge(grav, on=['Line_ID', 'Station'], how='outer', suffixes=('_Mag', '_Grav'))
    elif all(c in mag.columns for c in ('Latitude', 'Longitude')) and all(c in grav.columns for c in ('Latitude', 'Longitude')):
        source = mag.merge(grav, on=['Latitude', 'Longitude'], how='outer', suffixes=('_Mag', '_Grav'))
    else:
        return None
    scored = combine_scores(source, 'Robust Z-score — Recommended', 60, 40)
    st.session_state['integration_scored_df'] = scored
    return scored


def _figure_with_interpretation(df, value_col, title, cmap, units, interpretation):
    fig = contour_figure(df, value_col, title, cmap, units)
    ax = fig.axes[0]
    if interpretation.strip():
        ax.text(
            0.02, 0.98, interpretation.strip(), transform=ax.transAxes,
            va='top', ha='left', fontsize=9,
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.82, edgecolor='black')
        )
    return fig


def render_gis(user: dict):
    st.title('🗺️ GIS & Interpretation Maps')
    project = render_project_selector(user, 'gis_project')
    if project is None:
        return
    auth_text, crs_name, crs_units = project_crs_details(project)
    st.info(f'**Project CRS:** {auth_text} — {crs_name} — units: {crs_units}. Contour interpolation is performed in Project X/Y after transforming the station coordinates from WGS 84 longitude/latitude.')
    df = _current_data()
    if df is None or df.empty:
        st.info('Run Magnetic Processing and Gravity Processing first, then Integrated Targeting.')
        return

    st.subheader('Map controls')
    controls = render_map_controls("gis")
    mode = controls["mode"]
    c1, c2, c3 = st.columns(3)
    with c1:
        norm = st.selectbox('Normalization', list(NORMALIZERS.keys()), index=0, key='gis_normalization')
    with c2:
        mag_w = st.slider('Magnetic Weight %', 0, 100, 60, key='gis_mag_weight')
    with c3:
        st.metric('Gravity Weight %', f'{100-mag_w}%')

    scored = combine_scores(df, norm, mag_w, 100-mag_w)
    scored = attach_project_coordinates(scored, project)
    scored['Evidence_Score'] = scored['Mag_Contribution'] + scored['Grav_Contribution']
    st.session_state['integration_scored_df'] = scored

    interpretation = st.text_area(
        'Primary interpretation to display on maps',
        value='High-score zones indicate stronger integrated magnetic and gravity evidence. Review these areas with geology, structure, acquisition quality and other exploration constraints before follow-up work.',
        height=110,
        key='gis_primary_interpretation',
    )
    st.caption('The selected normalization is recalculated immediately. The measured survey points are included on each contour.')

    specs = [
        ('Mag_Normalized', '🧲 Magnetic normalized contour', 'viridis', '0–100'),
        ('Grav_Normalized', '🌎 Gravity normalized contour', 'plasma', '0–100'),
        ('Evidence_Score', '🧲+🌎 Weighted evidence contour', 'magma', '0–100'),
        ('Target_Score', '🎯 Target Score contour', 'cividis', '0–100'),
    ]
    base_map = controls["base_map"]
    show_rail = controls["show_railways"]
    show_roads = controls["show_roads"]
    show_stations = controls["show_stations"]
    show_targets = controls["show_targets"]
    show_surface = controls["show_surface"]
    show_contours = controls["show_contours"]
    map_height = controls["height"]
    geology_url = controls["geo_url"]
    geology_layer = controls["geo_layer"]
    geology_name = controls["geo_name"]

    st.checkbox(
        "Show one individual product map (optional)",
        value=False,
        key="gis_show_individual_map",
        help="Use the unified Integrated Targeting map for multi-layer comparison. This option renders only one product here to keep large projects responsive.",
    )
    if st.session_state.get("gis_show_individual_map", False):
        spec_map = {c: (title, cmap, units) for c, title, cmap, units in specs}
        selected_col = st.selectbox("Individual product", list(spec_map.keys()), format_func=lambda c: spec_map[c][0], key="gis_individual_product")
        col, (title, cmap, units) = selected_col, spec_map[selected_col]
        if pd.to_numeric(scored[col], errors='coerce').notna().sum() < 3:
            st.warning(f'{title}: insufficient points for a contour map.')
        elif mode == 'Project CRS map':
            crs_fig = build_project_crs_figure(
                scored, col, f'{title} — {norm}', project_crs=project_crs_value(project),
                interpretation=interpretation, show_surface=show_surface, show_contours=show_contours,
                show_contour_labels=controls["show_contour_labels"], contour_color=controls["contour_color"], contour_width=controls["contour_width"],
                show_points=show_stations, detail_mode=controls["detail_mode"], colorscale={
                    'Mag_Normalized':'Viridis','Grav_Normalized':'Plasma','Evidence_Score':'Magma','Target_Score':'Cividis'
                }.get(col, 'Viridis'), height=map_height,
            )
            if crs_fig is not None:
                st.plotly_chart(crs_fig, use_container_width=True, config={'displaylogo': False, 'scrollZoom': True})
        else:
            live_map = create_interactive_geophysical_map(
                scored, col, f'{title} — {norm}', project_crs=project_crs_value(project),
                project_name=project.name, interpretation=interpretation, base_map=base_map,
                show_railways=show_rail, show_roads=show_roads, show_stations=show_stations, show_targets=show_targets,
                show_surface=show_surface, show_contours=show_contours,
                show_contour_labels=controls["show_contour_labels"], contour_color=controls["contour_color"], contour_width=controls["contour_width"],
                geological_wms_url=geology_url, geological_wms_layer=geology_layer, geological_wms_name=geology_name,
                map_height=map_height, detail_mode=controls["detail_mode"],
            )
            if live_map is not None:
                st_folium(live_map, height=map_height, use_container_width=True, returned_objects=[])

        fig = contour_figure(
            scored, col, f'{title} — {norm}', cmap, units,
            project_crs=project_crs_value(project), show_crs_panel=True, interpretation=interpretation
        )
        buf = io.BytesIO(); fig.savefig(buf, format='png', dpi=200, bbox_inches='tight'); plt.close(fig)
        st.download_button(
            f'Download {title} with interpretation', buf.getvalue(),
            f'{col.lower()}_annotated_contour.png', 'image/png',
            key=f'gis_dl_{col}',
        )
    else:
        st.info("Individual maps are hidden to keep the page fast. Use Integrated Targeting → Unified ArcGIS-style layer tree to compare all four products together.")

    st.subheader('Interpretation summary')
    high = scored[scored['Target_Score'].ge(80)] if 'Target_Score' in scored else scored.iloc[0:0]
    st.metric('VERY HIGH targets', len(high))
    st.write(interpretation)

    url = st.session_state.get('db_manager_url', '')
    schema = st.session_state.get('db_manager_schema', '') or None
    if url:
        project_key = st.text_input('Project key for saved interpretation', 'DEMO_PROJECT', key='gis_project_key')
        if st.button('💾 Save Primary Interpretation to External Database', key='gis_save_interpretation'):
            ok, msg = save_interpretation(url, schema, project_key, 'Primary Geophysical Interpretation', interpretation, user.get('username', 'unknown'))
            (st.success if ok else st.error)(msg)

    st.session_state['map_interpretation'] = {
        'text': interpretation,
        'normalization': norm,
        'magnetic_weight': mag_w,
        'gravity_weight': 100-mag_w,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'author': user.get('username', 'unknown'),
        'project_id': project.id,
        'project_name': project.name,
        'project_crs': auth_text,
    }
