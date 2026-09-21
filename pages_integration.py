from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from database.geophysical_store import save_processing_run, save_target_run
from database.manager import create_engine_from_url
from database.external_schema import external_schema_status
from gis.crs_mapping import project_crs_value
from gis.interactive_maps import create_interactive_geophysical_map, create_unified_geophysical_map, BASEMAPS, render_map_controls
from streamlit_folium import st_folium
from gis.crs_map_view import build_project_crs_figure, build_unified_project_crs_figure
from targeting.integration import (
    combine_scores, contour_figure, NORMALIZERS,
    DEFAULT_MAGNETIC_WEIGHT, DEFAULT_GRAVITY_WEIGHT,
    EVIDENCE_WEIGHT, CONCORDANCE_WEIGHT,
)


def _active_external():
    return (
        st.session_state.get("db_manager_url", ""),
        st.session_state.get("db_manager_platform", ""),
        st.session_state.get("db_manager_label", ""),
        st.session_state.get("db_manager_schema", "") or "",
    )


def _history_save_area(kind, processed, stages, meta, user):
    url, platform, label, schema = _active_external()
    if not url:
        st.info("No external database is active. You can still download the processing history locally.")
        return
    st.subheader("💾 Save Processing Run to External Database")
    project_key = st.text_input("Project key", value="DEMO_PROJECT", key=f"{kind}_project_key")
    if st.button(f"Save {kind.title()} processing run to database", key=f"save_{kind}_processing", use_container_width=True):
        ok, msg = save_processing_run(
            url, schema, project_key,
            dataset_name=meta.get("source", f"{kind} dataset"),
            modality=kind.upper(), survey_type=meta.get("survey_type", ""),
            run_id=meta["run_id"], stages=stages, processed=processed,
            created_by=user.get("username", "unknown"),
            selected_product=meta.get("selected_product"),
            parameters=meta,
        )
        (st.success if ok else st.error)(msg)


def render_integration(user: dict):
    st.title("🔗 Integrated Magnetic + Gravity Targeting")
    st.caption("Normalize the final processed magnetic and gravity products, apply 60/40 weighting, calculate Data Confidence and Concordance, map the combined evidence, and optionally save the full run to the external database.")

    mag = st.session_state.get("mag_processing_df")
    grav = st.session_state.get("gravity_processing_df")
    mag_meta = st.session_state.get("mag_processing_meta", {})
    grav_meta = st.session_state.get("gravity_processing_meta", {})
    source = None

    if mag is not None and grav is not None:
        st.success("Using the latest Magnetic and Gravity processing results from this session.")
        join_options = ["Point_ID", "Line_ID + Station", "Latitude + Longitude"]
        join_method = st.selectbox("How should Magnetic and Gravity be joined?", join_options, key="integration_join")
        if join_method == "Point_ID" and "Point_ID" in mag.columns and "Point_ID" in grav.columns:
            source = mag.merge(grav, on="Point_ID", how="outer", suffixes=("_Mag", "_Grav"))
            for c in ["Latitude", "Longitude", "Line_ID"]:
                if f"{c}_Mag" in source.columns: source[c] = source[f"{c}_Mag"].combine_first(source.get(f"{c}_Grav"))
        elif join_method == "Line_ID + Station" and all(c in mag.columns for c in ["Line_ID","Station"]) and all(c in grav.columns for c in ["Line_ID","Station"]):
            source = mag.merge(grav, on=["Line_ID","Station"], how="outer", suffixes=("_Mag", "_Grav"))
        elif "Latitude" in mag.columns and "Longitude" in mag.columns and "Latitude" in grav.columns and "Longitude" in grav.columns:
            keys=["Latitude","Longitude"]
            source = mag.merge(grav, on=keys, how="outer", suffixes=("_Mag","_Grav"))
        else:
            st.warning("The two processing results do not have a compatible join key.")
    else:
        st.info("Run Magnetic Processing and Gravity Processing first. Their latest results will appear here automatically.")
        return

    if source is None or source.empty:
        return

    st.subheader("1️⃣ Final corrected anomaly inputs")
    mag_candidates = [c for c in ["Mag_Final_Processed_nT"] if c in source.columns]
    grav_candidates = [c for c in ["Gravity_Final_Processed_mGal"] if c in source.columns]

    mag_label = mag_meta.get("final_stage", "Final magnetic anomaly")
    grav_label = grav_meta.get("selected_product", "Final gravity product")

    mc1, mc2 = st.columns(2)
    with mc1:
        st.markdown("**Magnetic input to targeting**")
        if not mag_candidates:
            st.error("No final corrected magnetic anomaly is available. Run Magnetic Processing first.")
            return
        magnetic_col = st.selectbox(
            "Magnetic anomaly product",
            mag_candidates,
            index=0,
            format_func=lambda c: f"{mag_label} ({c})",
            key="integration_magnetic_final_product",
        )
    with mc2:
        st.markdown("**Gravity input to targeting**")
        if not grav_candidates:
            st.warning("No final corrected gravity anomaly is available. Run Gravity Processing first, or continue with magnetic-only targeting.")
            gravity_col = "__none__"
        else:
            gravity_col = st.selectbox(
                "Gravity anomaly product",
                ["__none__"] + grav_candidates,
                index=1,
                format_func=lambda c: "No gravity product" if c == "__none__" else f"{grav_label} ({c})",
                key="integration_gravity_final_product",
            )

    gravity_input_col = "" if gravity_col == "__none__" else gravity_col

    st.subheader("2️⃣ Targeting controls")
    c1,c2,c3=st.columns(3)
    with c1: normalization=st.selectbox("Normalization", list(NORMALIZERS.keys()), index=0, key="integration_normalization")
    with c2: mag_weight=st.slider("Magnetic Weight %",0,100,60,key="integration_mag_weight")
    with c3:
        grav_weight=100-mag_weight
        st.metric("Gravity Weight %",f"{grav_weight}%")
    interpretation = st.text_area(
        "Primary interpretation shown on all four contour maps",
        "Integrated geophysical evidence highlights areas that combine strong final corrected anomalies. Review concordance, data confidence, geology and survey quality before making exploration decisions.",
        height=90, key="integration_interpretation"
    )
    st.info("The integrated workflow starts only from the final corrected anomaly products selected above. Normalization is applied after geophysical correction. Raw/intermediate fields are never silently used.")

    scored=combine_scores(source,normalization,mag_weight,grav_weight, magnetic_col=magnetic_col, gravity_col=gravity_input_col)
    st.session_state['integration_scored_df'] = scored.copy()
    m1,m2,m3,m4,m5=st.columns(5)
    conf=scored["Data_Confidence"]
    m1.metric("Both",int(conf.eq(100).sum()))
    m2.metric("Magnetic only",int(conf.eq(60).sum()))
    m3.metric("Gravity only",int(conf.eq(40).sum()))
    m4.metric("No Score",int(conf.isna().sum()))
    m5.metric("VERY HIGH",int(scored["Target_Priority"].eq("VERY HIGH").sum()))

    st.subheader("3️⃣ Combined evidence & target contours")
    scored["Combined_Evidence"] = scored["Evidence_Score"]

    controls = render_map_controls("integration")
    map_mode = controls["mode"]
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

    map_defs=[
        ("Mag_Normalized","🧲 Magnetic normalized"),
        ("Grav_Normalized","🌎 Gravity normalized"),
        ("Evidence_Score","🧲+🌎 Weighted evidence"),
        ("Target_Score","🎯 Target Score"),
    ]
    active_crs = st.session_state.get("selected_project_crs", 4326)
    st.caption(
        "Project CRS map = scientific projected-coordinate view for interpolation and contour inspection. "
        "Live web basemap = geographic Leaflet view with street/satellite/topographic/railway/geology layers. "
        "The geophysical surface is transformed for web display when live mode is selected. "
        "The map uses cached interpolation grids and decimated station markers to keep interaction responsive."
    )
    st.markdown("### 🗂️ Unified ArcGIS-style layer tree")
    unified_layers = {
        "🧲 Magnetic normalized": {"column": "Mag_Normalized", "cmap": "viridis", "opacity": 0.42},
        "🌎 Gravity normalized": {"column": "Grav_Normalized", "cmap": "plasma", "opacity": 0.40},
        "🧲+🌎 Combined evidence": {"column": "Evidence_Score", "cmap": "magma", "opacity": 0.38},
        "🎯 Target score": {"column": "Target_Score", "cmap": "cividis", "opacity": 0.38},
    }
    if map_mode == "Live web basemap":
        unified = create_unified_geophysical_map(
            scored, unified_layers, "Integrated Geophysical Layer Tree", project_crs=active_crs,
            project_name=st.session_state.get("selected_project_name", ""), interpretation=interpretation,
            base_map=base_map, show_roads=show_roads, show_railways=show_rail, show_stations=show_stations,
            show_targets=show_targets, geological_wms_url=geology_url, geological_wms_layer=geology_layer,
            geological_wms_name=geology_name, show_contour_labels=controls["show_contour_labels"], contour_color=controls["contour_color"], contour_width=controls["contour_width"], detail_mode=controls["detail_mode"],
        )
        if unified is not None:
            st_folium(unified, height=map_height, use_container_width=True, returned_objects=[])
    else:
        crs_fig = build_unified_project_crs_figure(
            scored,
            {
                "🧲 Magnetic normalized": {"column": "Mag_Normalized", "colorscale": "Viridis", "opacity": 0.48},
                "🌎 Gravity normalized": {"column": "Grav_Normalized", "colorscale": "Plasma", "opacity": 0.44},
                "🧲+🌎 Combined evidence": {"column": "Evidence_Score", "colorscale": "Magma", "opacity": 0.38},
                "🎯 Target score": {"column": "Target_Score", "colorscale": "Cividis", "opacity": 0.40},
            },
            "Integrated Geophysical Layer Tree — Project CRS", project_crs=active_crs,
            interpretation=interpretation, height=map_height, show_contour_labels=controls["show_contour_labels"], contour_color=controls["contour_color"], contour_width=controls["contour_width"], detail_mode=controls["detail_mode"],
        )
        if crs_fig is not None:
            st.plotly_chart(crs_fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True})

    show_individual = st.checkbox(
        "Show one individual product map (optional)",
        value=False,
        key="integration_show_individual_map",
        help="The unified layer tree above is the fastest way to compare products. Enable this only when you need a single product in a dedicated map.",
    )
    if show_individual:
        labels = {c: t for c, t in map_defs}
        col = st.selectbox("Individual product", list(labels.keys()), format_func=lambda c: labels[c], key="integration_individual_product")
        title = labels[col]
        if scored[col].notna().sum() >= 3:
            st.markdown(f"### {title}")
            if map_mode == "Project CRS map":
                crs_fig = build_project_crs_figure(
                    scored, col, f"{title} — {normalization}",
                    project_crs=active_crs, interpretation=interpretation,
                    colorscale={
                        "Mag_Normalized": "Viridis",
                        "Grav_Normalized": "Plasma",
                        "Evidence_Score": "Magma",
                        "Target_Score": "Cividis",
                    }.get(col, "Viridis"), height=map_height,
                    show_contour_labels=controls["show_contour_labels"],
                    contour_color=controls["contour_color"],
                    contour_width=controls["contour_width"],
                    detail_mode=controls["detail_mode"],
                )
                if crs_fig is not None:
                    st.plotly_chart(crs_fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True})
            else:
                live_map=create_interactive_geophysical_map(
                    scored, col, f"{title} — {normalization}",
                    project_crs=active_crs,
                    project_name=st.session_state.get("selected_project_name", ""),
                    interpretation=interpretation, base_map=base_map,
                    show_railways=show_rail, show_roads=show_roads, show_stations=show_stations, show_targets=show_targets,
                    show_surface=show_surface, show_contours=show_contours,
                    show_contour_labels=controls["show_contour_labels"], contour_color=controls["contour_color"], contour_width=controls["contour_width"],
                    geological_wms_url=geology_url,
                    geological_wms_layer=geology_layer, geological_wms_name=geology_name, map_height=map_height,
                    detail_mode=controls["detail_mode"],
                )
                if live_map is not None:
                    st_folium(live_map, height=map_height, use_container_width=True, returned_objects=[])

    st.subheader("4️⃣ Target table")
    display_cols=[c for c in ["Point_ID","Latitude","Longitude","Mag_Normalized","Grav_Normalized","Mag_Contribution","Grav_Contribution","Evidence_Score","Data_Confidence","Concordance","Target_Score","Target_Priority"] if c in scored.columns]
    st.dataframe(scored[display_cols].sort_values("Target_Score",ascending=False,na_position="last"),use_container_width=True,hide_index=True,height=430)

    st.subheader("5️⃣ Save integrated targeting run")
    url,platform,label,schema=_active_external()
    if url:
        project_key=st.text_input("Project key",value="DEMO_PROJECT",key="integration_project_key")
        run_id=f"TARGET_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"
        if st.button("💾 Save Target Run to External Database",type="primary",use_container_width=True,key="integration_save_target"):
            ok,msg=save_target_run(url,schema,project_key,run_id,scored,normalization,mag_weight,grav_weight,EVIDENCE_WEIGHT,CONCORDANCE_WEIGHT,user.get("username","unknown"))
            (st.success if ok else st.error)(msg)
    else:
        st.caption("Connect an external database in Database Manager to save this targeting run.")

    st.subheader("6️⃣ Export integrated results")
    st.download_button("Download Target Results CSV",scored.to_csv(index=False).encode(),"integrated_target_results.csv","text/csv",use_container_width=True)
    x=io.BytesIO()
    with pd.ExcelWriter(x,engine="openpyxl") as writer: scored.to_excel(writer,index=False,sheet_name="Targets")
    st.download_button("Download Target Results Excel",x.getvalue(),"integrated_target_results.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)

    st.download_button("Download Targeting Run JSON",json.dumps({"run_id":run_id if 'run_id' in locals() else None,"normalization":normalization,"magnetic_weight":mag_weight,"gravity_weight":grav_weight,"evidence_weight":EVIDENCE_WEIGHT,"concordance_weight":CONCORDANCE_WEIGHT},indent=2).encode(),"targeting_run_parameters.json","application/json",use_container_width=True)
