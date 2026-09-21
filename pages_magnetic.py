
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from pages_integration import _history_save_area
from gis.crs_mapping import render_project_selector, project_crs_value, project_crs_details, attach_project_coordinates
from targeting.integration import contour_figure
from gis.interactive_maps import create_interactive_geophysical_map, render_map_controls, BASEMAPS
from streamlit_folium import st_folium

from magnetic.processing import (
    MAGNETIC_STEPS,
    run_magnetic_pipeline,
    contour_grid,
    stage_summary,
    serializable_steps,
)


def _source_data():
    candidates=[]
    if st.session_state.get("synthetic_df") is not None:
        candidates.append("Current Synthetic Dataset")
    for name in ["ground_magnetic.csv","airborne_magnetic.csv","uav_magnetic.csv"]:
        if (st.session_state.get("phase7_sample_dir") and False):
            pass
        else:
            from pathlib import Path
            p=Path(__file__).parent/"sample_data"/name
            if p.exists(): candidates.append(f"Sample — {name}")
    return candidates


def _load_source(choice: str):
    if choice=="Current Synthetic Dataset":
        return st.session_state.get("synthetic_df").copy()
    name=choice.replace("Sample — ","")
    from pathlib import Path
    return pd.read_csv(Path(__file__).parent/"sample_data"/name)


def _fig_to_bytes(fig):
    buf=io.BytesIO(); fig.savefig(buf,format="png",dpi=180,bbox_inches="tight"); return buf.getvalue()


def _stage_fig(df, lat_col, lon_col, series, title, project_crs=4326, cmap="viridis"):
    return contour_figure(
        df.assign(__stage_value=pd.to_numeric(series, errors="coerce")),
        "__stage_value", title, cmap=cmap, units="nT",
        project_crs=project_crs, lat_col=lat_col, lon_col=lon_col, show_crs_panel=True,
    )


def render_magnetic_processing(user: dict):
    st.title("🧲 Magnetic Processing & Intermediate Contours")
    project = render_project_selector(user, "mag_project")
    if project is None:
        return
    project_crs = project_crs_value(project)
    auth_text, crs_name, crs_units = project_crs_details(project)
    st.info(f"Project CRS: {auth_text} — {crs_name} — interpolation uses Project X/Y ({crs_units}). Input station Latitude/Longitude are interpreted as WGS 84.")
    st.caption("Every processing stage is retained so the user can inspect the effect of each correction before accepting the final magnetic anomaly.")

    sources=_source_data()
    if not sources:
        st.info("Generate a synthetic survey first, or use the included sample magnetic datasets.")
        return
    source=st.selectbox("Input magnetic dataset",sources,key="mag_source")
    df=_load_source(source)
    st.success(f"Loaded {len(df):,} measurement points.")

    cols=list(df.columns)
    c1,c2,c3=st.columns(3)
    with c1: lat_col=st.selectbox("Latitude column",cols,index=cols.index("Latitude") if "Latitude" in cols else 0,key="mag_lat")
    with c2: lon_col=st.selectbox("Longitude column",cols,index=cols.index("Longitude") if "Longitude" in cols else 0,key="mag_lon")
    mag_defaults=[c for c in cols if "Mag_Raw_TMI" in c or c=="Mag_Anomaly_nT"]
    with c3: mag_col=st.selectbox("Input magnetic field column",cols,index=cols.index(mag_defaults[0]) if mag_defaults else 0,key="mag_value")

    survey=st.selectbox("Survey type",["Ground Magnetic","Airborne Magnetic","UAV Magnetic"],key="mag_survey")
    line_options=["<none>"]+[c for c in cols if c in ["Line_ID","Flight_ID"] or "line" in c.lower()]
    line_choice=st.selectbox("Line identifier (needed for line-leveling/micro-leveling)",line_options,key="mag_line")
    line_col=None if line_choice=="<none>" else line_choice

    st.subheader("1️⃣ Processing requirements")
    st.info("The labels are processing guidance, not a universal substitute for the survey acquisition/processing specification. Confirm the starting data level before applying a correction to avoid double correction.")
    req_df=pd.DataFrame([{
        "Step":s.name,"Code":s.code,"Requirement":s.mandatory,"Status":s.status,"Purpose":s.description
    } for s in MAGNETIC_STEPS])
    st.dataframe(req_df,use_container_width=True,hide_index=True)

    with st.expander("⚙️ Correction controls",expanded=True):
        use_qc=st.checkbox("Run QC / robust outlier check",True,key="mag_apply_qc")
        exclude_qc=st.checkbox("Exclude robust outliers from the processed field",False,key="mag_exclude_qc")
        zthr=st.number_input("Robust outlier threshold |Z|",3.0,12.0,6.0,0.5,key="mag_zthr")
        sign=st.radio("Supplied correction convention",["Subtract supplied correction/effect","Add supplied signed correction"],key="mag_sign")
        none="<none>"
        diurnal_options=[none]+[c for c in cols if "Diurnal" in c]
        reference_options=[none]+[c for c in cols if "IGRF" in c or "Reference" in c]
        heading_options=[none]+[c for c in cols if "Heading" in c]
        lag_options=[none]+[c for c in cols if "Lag" in c]
        level_options=[none]+[c for c in cols if "Leveling" in c]
        a,b,c=st.columns(3)
        with a:
            diurnal=st.selectbox("Diurnal correction",diurnal_options,index=1 if len(diurnal_options)>1 else 0,key="mag_diurnal")
            reference=st.selectbox("IGRF / reference field",reference_options,index=1 if len(reference_options)>1 else 0,key="mag_reference")
        with b:
            heading=st.selectbox("Heading correction (optional)",heading_options,key="mag_heading")
            lag=st.selectbox("Lag correction (optional)",lag_options,key="mag_lag")
        with c:
            leveling=st.selectbox("Line leveling (optional)",level_options,key="mag_leveling")
            micro=st.checkbox("Apply micro-leveling",False,key="mag_micro")

    if st.button("🧲 Run Magnetic Processing",type="primary",use_container_width=True,key="run_mag_processing"):
        processed,stages,meta=run_magnetic_pipeline(
            df,lat_col,lon_col,mag_col,line_col,survey,use_qc,exclude_qc,
            None if diurnal==none else diurnal,
            None if reference==none else reference,
            None if heading==none else heading,
            None if lag==none else lag,
            None if leveling==none else leveling,
            micro,sign,float(zthr),
        )
        processed = attach_project_coordinates(processed, project)
        st.session_state["mag_processing_df"]=processed
        st.session_state["mag_processing_stages"]=stages
        st.session_state["mag_processing_meta"]=meta
        st.success(f"Processing completed: {', '.join(meta['applied_steps']) or 'QC/input stage only'}")

    if "mag_processing_stages" not in st.session_state:
        return

    processed=st.session_state["mag_processing_df"]
    stages=st.session_state["mag_processing_stages"]
    meta=st.session_state["mag_processing_meta"]

    st.subheader("2️⃣ QC summary")
    m1,m2,m3,m4=st.columns(4)
    flags=processed["Mag_QC_Flag"].value_counts(dropna=False)
    m1.metric("Rows",len(processed)); m2.metric("PASS",int(flags.get("PASS",0))); m3.metric("Outliers",int(flags.get("ROBUST_OUTLIER",0))); m4.metric("Missing",int(flags.get("MISSING",0)))
    st.dataframe(processed[[c for c in ["Point_ID","Line_ID",lat_col,lon_col,mag_col,"Mag_QC_Flag","Mag_Final_Processed_nT"] if c in processed.columns]].head(100),use_container_width=True,height=300)

    st.subheader("3️⃣ Interactive correction-stage maps")
    st.caption("Each magnetic processing stage has its own interactive map. Choose a stage to inspect its corrected field; the map updates immediately. Skipped stages remain visible as transparent placeholders so the full processing chain is always auditable. The selected view and basemap are remembered independently for each stage during this session.")

    final_stage = next((s for s in stages if s.get("code") == "FINAL_MAGNETIC_ANOMALY"), None)
    if final_stage is None:
        # Protect the UI when Streamlit/GitHub still has an older magnetic/processing.py.
        # The explicit final stage is preferred; otherwise use the last available
        # processing stage as a compatible final display product.
        base_stages = [s for s in stages if s.get("code") != "QC"]
        if base_stages:
            source_stage = base_stages[-1]
            series = pd.to_numeric(source_stage.get("series"), errors="coerce").copy()
            final_desc = "Compatibility final product derived from the last available magnetic processing stage."
        else:
            series = pd.to_numeric(processed.get("Mag_Final_Processed_nT", pd.Series(index=processed.index, dtype=float)), errors="coerce").copy()
            final_desc = "Compatibility final product derived from Mag_Final_Processed_nT."
        final_stage = {
            "code": "FINAL_MAGNETIC_ANOMALY",
            "name": "Final Magnetic Anomaly",
            "mandatory": "Final product",
            "status": "FINAL",
            "series": series,
            "description": final_desc,
        }
        stages = list(stages) + [final_stage]

    processing_stages=[s for s in stages if s["code"] != "FINAL_MAGNETIC_ANOMALY"]

    st.markdown("**PROCESSING STAGES**")
    processing_stage_labels=[]
    processing_stage_lookup={}
    for s in processing_stages:
        status = s.get("status", "")
        suffix = " — SKIPPED" if status == "SKIPPED" else ""
        label = f"{s['name']}{suffix}"
        processing_stage_labels.append(label)
        processing_stage_lookup[label] = s

    st.markdown("**Raw TMI → After Diurnal Correction → After IGRF / Reference Removal → After Heading Correction → After Lag Correction → After Leveling → After Micro-leveling**")
    stage_pick=st.selectbox("Correction stage to view interactively", processing_stage_labels, key="mag_stage_pick")
    selected_stage=processing_stage_lookup[stage_pick]

    st.markdown("────────────────────────")
    st.markdown("**FINAL PRODUCT**")
    final_label = "⭐ Final Magnetic Anomaly"
    final_selected = st.toggle("View Final Magnetic Anomaly", value=False, key="mag_final_product_toggle")
    if final_selected:
        selected_stage = final_stage
        st.success("⭐ Final Magnetic Anomaly — the final corrected magnetic product used downstream for normalization, integration, targeting, and interpretation.")
    map_id=f"magnetic_processing__{selected_stage['code']}"
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
        export_stages=[s for s in stages if s["code"] != "QC"]
        for s in export_stages:
            fig=_stage_fig(processed,lat_col,lon_col,s["series"],f"{s['name']} — {meta['run_id']}", project_crs=project_crs)
            img=_fig_to_bytes(fig); plt.close(fig)
            st.download_button(f"Download {s['code']} contour PNG",img,f"magnetic_{s['code']}.png","image/png",key=f"dl_{s['code']}")

    st.subheader("4️⃣ Stage statistics & processing history")
    st.dataframe(stage_summary(stages),use_container_width=True,hide_index=True)
    history={"run":meta,"steps":serializable_steps(stages)}
    st.download_button("Download processing history JSON",json.dumps(history,indent=2,default=str).encode(),"magnetic_processing_history.json","application/json",use_container_width=True)

    _history_save_area("magnetic", processed, stages, {**meta, "source": source, "survey_type": survey, "project_id": project.id, "project_crs": auth_text}, user)

    st.subheader("5️⃣ Final processed magnetic data")
    d1,d2=st.columns(2)
    d1.download_button("Download processed CSV",processed.to_csv(index=False).encode(),"magnetic_processed.csv","text/csv",use_container_width=True)
    buf=io.BytesIO()
    with pd.ExcelWriter(buf,engine="openpyxl") as writer:
        processed.to_excel(writer,index=False,sheet_name="Magnetic_Processed")
    d2.download_button("Download processed Excel",buf.getvalue(),"magnetic_processed.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
