
from __future__ import annotations

import io
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from pages_integration import _history_save_area
from gis.crs_mapping import render_project_selector, project_crs_value, project_crs_details, attach_project_coordinates
from targeting.integration import contour_figure
from gis.interactive_maps import create_interactive_geophysical_map, render_map_controls, BASEMAPS
from streamlit_folium import st_folium

from gravity.processing import (
    GRAVITY_STEPS,
    run_gravity_pipeline,
    contour_grid,
    stage_summary,
    serializable_steps,
)


def _source_data():
    """Build gravity input sources, preferring the current synthetic dataset.

    The user can also upload a CSV directly from this page. The current
    synthetic dataframe is kept in Streamlit session_state after generation.
    """
    candidates = []

    synthetic = st.session_state.get("synthetic_df")
    if synthetic is not None:
        gravity_cols = [str(c) for c in synthetic.columns if str(c).startswith("Gravity_")]
        if gravity_cols:
            candidates.append("Current Synthetic Dataset")

    uploaded = st.session_state.get("gravity_uploaded_df")
    if uploaded is not None and not uploaded.empty:
        candidates.append("Uploaded CSV Dataset")

    sample_dir = Path(__file__).parent / "sample_data"
    for name in [
        "raw_gravity.csv",
        "complete_bouguer_gravity.csv",
        "combined_magnetic_gravity.csv",
    ]:
        if (sample_dir / name).exists():
            candidates.append(f"Sample — {name}")
    return candidates


def _load_source(choice: str):
    if choice == "Current Synthetic Dataset":
        return st.session_state["synthetic_df"].copy()
    if choice == "Uploaded CSV Dataset":
        return st.session_state["gravity_uploaded_df"].copy()
    return pd.read_csv(Path(__file__).parent / "sample_data" / choice.replace("Sample — ", ""))


def _fig_to_bytes(fig):
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=180, bbox_inches="tight")
    return buffer.getvalue()


def _stage_fig(df, lat_col, lon_col, values, title, project_crs=4326, cmap="viridis"):
    return contour_figure(
        df.assign(__stage_value=pd.to_numeric(values, errors="coerce")),
        "__stage_value", title, cmap=cmap, units="mGal",
        project_crs=project_crs, lat_col=lat_col, lon_col=lon_col, show_crs_panel=True,
    )


def render_gravity_processing(user: dict):
    st.title("🌎 Gravity Processing & Intermediate Contours")
    project = render_project_selector(user, "grav_project")
    if project is None:
        return
    project_crs = project_crs_value(project)
    auth_text, crs_name, crs_units = project_crs_details(project)
    st.info(f"Project CRS: {auth_text} — {crs_name} — interpolation uses Project X/Y ({crs_units}). Input station Latitude/Longitude are interpreted as WGS 84.")
    st.caption(
        "Build and inspect the gravity reduction chain without overwriting the "
        "raw observation. Every selected stage retains its own anomaly field."
    )

    st.subheader("0️⃣ Choose the gravity data source")
    uploaded_file = st.file_uploader(
        "Upload a gravity CSV (optional)",
        type=["csv"],
        key="grav_csv_upload",
        help="The uploaded CSV becomes an in-session dataset and does not overwrite the synthetic dataset or database.",
    )
    if uploaded_file is not None:
        try:
            uploaded_df = pd.read_csv(uploaded_file)
            if uploaded_df.empty:
                st.error("The uploaded CSV is empty.")
            else:
                st.session_state["gravity_uploaded_df"] = uploaded_df
                st.success(f"Uploaded gravity CSV: {len(uploaded_df):,} rows.")
        except Exception as exc:
            st.error(f"Could not read the uploaded CSV: {exc}")

    sources = _source_data()
    if not sources:
        st.info(
            "No gravity source is available. Generate **Raw Gravity** or **Combined Magnetic + Gravity** in Synthetic Data, "
            "upload a gravity CSV above, or use the included sample files."
        )
        return

    # Prefer the current synthetic gravity dataset when it exists. This fixes the
    # previous behavior where the first sample CSV was selected automatically.
    default_index = sources.index("Current Synthetic Dataset") if "Current Synthetic Dataset" in sources else 0
    source = st.selectbox(
        "Input gravity dataset",
        sources,
        index=default_index,
        key="grav_source",
    )
    if source == "Current Synthetic Dataset":
        st.success("Using the current Synthetic Data session dataset — not a sample CSV.")
    elif source == "Uploaded CSV Dataset":
        st.success("Using the uploaded CSV dataset for this processing session.")
    df = _load_source(source)
    st.success(f"Loaded {len(df):,} measurement points.")

    cols = list(df.columns)
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        lat_col = st.selectbox(
            "Latitude column",
            cols,
            index=cols.index("Latitude") if "Latitude" in cols else 0,
            key="grav_lat",
        )
    with c2:
        lon_col = st.selectbox(
            "Longitude column",
            cols,
            index=cols.index("Longitude") if "Longitude" in cols else 0,
            key="grav_lon",
        )
    with c3:
        elevation_options = ["<none>"] + [c for c in cols if "elev" in c.lower() or "height" in c.lower()]
        elev_col = st.selectbox("Elevation column", elevation_options, key="grav_elev")
    with c4:
        grav_candidates = [
            c for c in cols
            if "Gravity_Raw_mGal" in c or "Observed_Gravity" in c or c == "Gravity_Raw"
        ]
        grav_col = st.selectbox(
            "Input gravity observation",
            cols,
            index=cols.index(grav_candidates[0]) if grav_candidates else 0,
            key="grav_value",
        )

    survey_options = [
        "Ground Gravity",
        "Marine Gravity",
        "Borehole / Downhole Gravity",
        "Regional Gravity",
    ]
    synthetic_template = str(df.get("Survey_Template", pd.Series(dtype=str)).dropna().iloc[0]) if "Survey_Template" in df.columns and df["Survey_Template"].notna().any() else ""
    default_survey = "Marine Gravity" if "Marine" in synthetic_template else "Regional Gravity" if "Regional" in synthetic_template else "Ground Gravity"
    survey = st.selectbox(
        "Survey type",
        survey_options,
        index=survey_options.index(default_survey),
        key="grav_survey",
    )

    st.subheader("1️⃣ Recommended processing chain")
    req_df = pd.DataFrame(
        [
            {
                "Step": step.name,
                "Product": step.product,
                "Requirement": step.requirement,
                "Status": step.status,
                "Purpose": step.description,
            }
            for step in GRAVITY_STEPS
        ]
    )
    st.dataframe(req_df, use_container_width=True, hide_index=True)

    st.subheader("2️⃣ Processing controls")
    st.info(
        "The Mandatory/Optional labels are workflow guidance. The correct chain "
        "depends on the input data level and the anomaly product required by the survey."
    )

    none = "<none>"
    option = lambda tokens: [none] + [c for c in cols if any(t in c.lower() for t in tokens)]

    a, b, c = st.columns(3)
    with a:
        tide_col = st.selectbox("Earth-tide correction", option(["tide"]), key="grav_tide")
        drift_col = st.selectbox("Instrument drift correction", option(["drift"]), key="grav_drift")
    with b:
        lat_corr_col = st.selectbox(
            "Latitude / normal-gravity correction",
            option(["latitude", "normal_gravity", "normal gravity"]),
            key="grav_lat_corr",
        )
        free_air_col = st.selectbox("Free-air correction", option(["free_air", "free air"]), key="grav_freeair")
    with c:
        bouguer_col = st.selectbox("Bouguer correction", option(["bouguer"]), key="grav_bouguer")
        terrain_col = st.selectbox("Terrain correction", option(["terrain"]), key="grav_terrain")

    d, e = st.columns(2)
    with d:
        curvature_col = st.selectbox(
            "Curvature correction (optional / scheme-dependent)",
            option(["curvature"]),
            key="grav_curvature",
        )
    with e:
        isostatic_col = st.selectbox(
            "Isostatic correction (optional)",
            option(["isostatic"]),
            key="grav_isostatic",
        )

    product = st.selectbox(
        "Final gravity product to accept",
        [
            "Observed gravity",
            "Tide-corrected gravity",
            "Drift-corrected gravity",
            "Latitude-corrected stage",
            "Free-Air anomaly",
            "Simple Bouguer anomaly",
            "Complete Bouguer anomaly",
            "Isostatic anomaly",
        ],
        index=6,
        key="grav_product",
    )

    sign = st.radio(
        "Supplied correction convention",
        [
            "Subtract supplied correction/effect",
            "Add supplied signed correction",
        ],
        horizontal=True,
        key="grav_sign",
    )
    apply_qc = st.checkbox("Run QC / robust outlier check", True, key="grav_apply_qc")
    exclude = st.checkbox(
        "Exclude robust outliers from processed fields",
        False,
        key="grav_exclude_qc",
    )
    zthr = st.number_input(
        "Robust outlier threshold |Z|",
        min_value=3.0,
        max_value=12.0,
        value=6.0,
        step=0.5,
        key="grav_zthr",
    )

    if st.button(
        "🌎 Run Gravity Processing",
        type="primary",
        use_container_width=True,
        key="run_gravity_processing",
    ):
        processed, stages, meta = run_gravity_pipeline(
            df=df,
            lat_col=lat_col,
            lon_col=lon_col,
            elevation_col=None if elev_col == none else elev_col,
            gravity_col=grav_col,
            survey_type=survey,
            apply_qc=apply_qc,
            exclude_qc_outliers=exclude,
            tide_col=None if tide_col == none else tide_col,
            drift_col=None if drift_col == none else drift_col,
            latitude_col=None if lat_corr_col == none else lat_corr_col,
            free_air_col=None if free_air_col == none else free_air_col,
            bouguer_col=None if bouguer_col == none else bouguer_col,
            terrain_col=None if terrain_col == none else terrain_col,
            curvature_col=None if curvature_col == none else curvature_col,
            isostatic_col=None if isostatic_col == none else isostatic_col,
            selected_product=product,
            correction_sign=sign,
            qc_z_threshold=float(zthr),
        )

        processed = attach_project_coordinates(processed, project)
        st.session_state["gravity_processing_df"] = processed
        st.session_state["gravity_processing_stages"] = stages
        st.session_state["gravity_processing_meta"] = meta
        st.success(
            f"Processing completed. Final product: {product}. "
            f"Run ID: {meta['run_id']}"
        )

    if "gravity_processing_stages" not in st.session_state:
        return

    processed = st.session_state["gravity_processing_df"]
    stages = st.session_state["gravity_processing_stages"]
    meta = st.session_state["gravity_processing_meta"]

    st.subheader("3️⃣ QC summary")
    m1, m2, m3, m4 = st.columns(4)
    flags = processed["Gravity_QC_Flag"].value_counts(dropna=False)
    m1.metric("Rows", len(processed))
    m2.metric("PASS", int(flags.get("PASS", 0)))
    m3.metric("Outliers", int(flags.get("ROBUST_OUTLIER", 0)))
    m4.metric("Missing", int(flags.get("MISSING", 0)))

    preview_cols = [
        c for c in [
            "Point_ID", "Line_ID", lat_col, lon_col, elev_col if elev_col != none else None,
            grav_col, "Gravity_QC_Flag", "Gravity_Final_Processed_mGal"
        ]
        if c and c in processed.columns
    ]
    st.dataframe(
        processed[preview_cols].head(100),
        use_container_width=True,
        height=300,
    )

    st.subheader("4️⃣ Interactive correction-stage maps")
    st.caption(
        "Every gravity reduction stage has an interactive map. Intermediate stages are diagnostic products; the explicit final product below is the selected endpoint used downstream. "
        "The selected view and basemap are remembered independently for each stage during this session. Switching between Project CRS and Live Web changes presentation only, not the processed values."
    )
    final_stage = next((s for s in stages if s.get("code") == "FINAL_GRAVITY_PRODUCT"), None)
    if final_stage is None:
        # Protect the UI when Streamlit/GitHub still has an older gravity/processing.py.
        base_stages = [s for s in stages if s.get("code") != "QC"]
        if base_stages:
            source_stage = base_stages[-1]
            series = pd.to_numeric(source_stage.get("series"), errors="coerce").copy()
        else:
            series = pd.to_numeric(processed.get("Gravity_Final_Processed_mGal", pd.Series(index=processed.index, dtype=float)), errors="coerce").copy()
        final_stage = {
            "code": "FINAL_GRAVITY_PRODUCT",
            "name": "⭐ Final Gravity Product",
            "product": meta.get("selected_product", "Selected gravity product"),
            "requirement": "Final product",
            "status": "FINAL",
            "series": series,
            "description": "Compatibility final product derived from the last available gravity processing stage.",
        }
        stages = list(stages) + [final_stage]

    processing_stages=[s for s in stages if s["code"] != "FINAL_GRAVITY_PRODUCT"]

    st.markdown("**PROCESSING STAGES**")
    stage_labels=[]
    stage_lookup={}
    ordered_codes=[
        "RAW_OBSERVED","TIDE_CORRECTED","DRIFT_CORRECTED","LATITUDE_CORRECTED",
        "FREE_AIR","SIMPLE_BOUGUER","COMPLETE_BOUGUER","CURVATURE","ISOSTATIC"
    ]
    ordered_stages=sorted(processing_stages, key=lambda s: ordered_codes.index(s["code"]) if s["code"] in ordered_codes else 999)
    for s in ordered_stages:
        suffix = " — SKIPPED" if s.get("status") == "SKIPPED" else ""
        label=f"{s['name']}{suffix}"
        stage_labels.append(label)
        stage_lookup[label]=s

    st.markdown(
        "**Raw / Observed Gravity → After Earth-Tide Correction → After Instrument Drift Correction → "
        "After Latitude / Normal-Gravity Reduction → Free-Air Anomaly → Simple Bouguer Anomaly → "
        "Complete Bouguer Anomaly → After Curvature Correction → Isostatic Anomaly**"
    )
    stage_pick=st.selectbox("Processing stage to view interactively", stage_labels, key="grav_stage_pick")
    selected_stage=stage_lookup[stage_pick]

    st.markdown("────────────────────────")
    st.markdown("**FINAL PRODUCT**")
    st.success(
        f"**{final_stage['name']}** — this is the selected gravity endpoint used for normalization, integration, targeting, interpretation, and reporting. "
        "It is shown separately from the diagnostic processing stages so there is no ambiguity about the downstream input."
    )
    final_toggle=st.toggle("⭐ View Final Gravity Product", value=True, key="grav_final_product_toggle")
    if final_toggle:
        selected_stage=final_stage
    map_id=f"gravity_processing__{selected_stage['code']}"
    controls=render_map_controls(map_id)
    mode=controls["mode"]
    base_map=controls["base_map"]
    show_rail=controls["show_railways"]
    show_roads=controls["show_roads"]
    show_stations=controls["show_stations"]
    show_targets=controls["show_targets"]
    show_surface=controls["show_surface"]
    show_contours=controls["show_contours"]
    mh=controls["height"]
    geo_url=controls["geo_url"]; geo_layer=controls["geo_layer"]; geo_name=controls["geo_name"]
    stage_values=selected_stage["series"]
    if mode == "Project CRS map":
        from gis.crs_map_view import build_project_crs_figure
        fig=build_project_crs_figure(processed, stage_values, f"{selected_stage['name']} — {meta['run_id']}", project_crs=project_crs,
                                     interpretation="Correction-stage diagnostic surface.", height=mh, show_surface=show_surface, show_contours=show_contours, show_contour_labels=controls["show_contour_labels"], contour_color=controls["contour_color"], contour_width=controls["contour_width"], show_points=show_stations, detail_mode=controls["detail_mode"])
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True, config={"displaylogo":False,"scrollZoom":True})
    else:
        live_map=create_interactive_geophysical_map(
            processed, stage_values, f"{selected_stage['name']} — {meta['run_id']}", project_crs=project_crs, project_name=project.name,
            interpretation="Correction-stage diagnostic surface. Use survey-specific gridding and QC before interpretation.",
            base_map=base_map, show_railways=show_rail, show_roads=show_roads, show_stations=show_stations, show_targets=show_targets,
            show_surface=show_surface, show_contours=show_contours, show_contour_labels=controls["show_contour_labels"], contour_color=controls["contour_color"], contour_width=controls["contour_width"], geological_wms_url=geo_url, geological_wms_layer=geo_layer, geological_wms_name=geo_name, map_height=mh, detail_mode=controls["detail_mode"],
        )
        if live_map is not None:
            st_folium(live_map,height=mh,use_container_width=True,returned_objects=[])

    with st.expander("📥 Static exports for all correction stages", expanded=False):
        st.caption("The interactive map above is the primary way to inspect a correction stage. Use these exports when you need files for a report or offline review.")
        for stage in ordered_stages + [final_stage]:
            fig = _stage_fig(processed, lat_col, lon_col, stage["series"], f"{stage['name']} — {meta['run_id']}", project_crs=project_crs, cmap="viridis")
            image = _fig_to_bytes(fig); plt.close(fig)
            st.download_button(
                f"Download {stage['code']} contour PNG", image, f"gravity_{stage['code']}.png",
                "image/png", key=f"dl_gravity_{stage['code']}",
            )

    st.subheader("5️⃣ Stage statistics & processing history")
    st.dataframe(stage_summary(stages), use_container_width=True, hide_index=True)

    history = {
        "run": meta,
        "steps": serializable_steps(stages),
    }
    st.download_button(
        "Download gravity processing history JSON",
        json.dumps(history, indent=2, default=str).encode(),
        "gravity_processing_history.json",
        "application/json",
        use_container_width=True,
    )

    _history_save_area("gravity", processed, stages, {**meta, "source": source, "survey_type": survey, "selected_product": product, "project_id": project.id, "project_crs": auth_text}, user)

    st.subheader("6️⃣ Final processed gravity data")
    d1, d2 = st.columns(2)
    d1.download_button(
        "Download processed CSV",
        processed.to_csv(index=False).encode(),
        "gravity_processed.csv",
        "text/csv",
        use_container_width=True,
    )
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        processed.to_excel(writer, index=False, sheet_name="Gravity_Processed")
    d2.download_button(
        "Download processed Excel",
        buffer.getvalue(),
        "gravity_processed.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
