
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from scipy.interpolate import griddata


@dataclass(frozen=True)
class MagneticStep:
    order: int
    code: str
    name: str
    mandatory: str
    status: str
    description: str


MAGNETIC_STEPS = [
    MagneticStep(1, "QC", "Quality control", "Required", "READY", "Check coordinates, magnetic values, duplicates and robust outliers before corrections."),
    MagneticStep(2, "DIURNAL", "After Diurnal Correction", "Required for raw time-varying TMI", "READY", "Remove temporal magnetic variation using a base-station/diurnal correction."),
    MagneticStep(3, "REFERENCE_FIELD", "After IGRF / Reference Removal", "Required for magnetic anomaly product", "READY", "Remove the chosen regional/main-field reference from corrected TMI."),
    MagneticStep(4, "HEADING", "After Heading Correction", "Survey-dependent", "OPTIONAL", "Correct heading-dependent aircraft/UAV or instrument effects when demonstrated by survey QA."),
    MagneticStep(5, "LAG", "After Lag Correction", "Airborne/UAV survey-dependent", "OPTIONAL", "Apply time/position lag correction where sensor response and navigation timing require it."),
    MagneticStep(6, "LEVELING", "After Leveling", "Survey-dependent", "OPTIONAL", "Remove line-to-line mismatch using tie lines or an equivalent documented leveling method."),
    MagneticStep(7, "MICROLEVEL", "After Micro-leveling", "Survey-dependent", "OPTIONAL", "Remove short-wavelength residual line noise after leveling without erasing geological signal."),
]


def _num(df: pd.DataFrame, col: str | None) -> pd.Series:
    if not col or col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def _required_fields(df: pd.DataFrame, lat_col: str, lon_col: str, mag_col: str) -> dict[str, Any]:
    lat=_num(df,lat_col); lon=_num(df,lon_col); mag=_num(df,mag_col)
    return {
        "rows": int(len(df)),
        "valid_coordinates": int((lat.notna() & lon.notna()).sum()),
        "missing_coordinates": int((lat.isna() | lon.isna()).sum()),
        "valid_magnetic": int(mag.notna().sum()),
        "missing_magnetic": int(mag.isna().sum()),
        "duplicate_coordinates": int(df.assign(_lat=lat,_lon=lon).duplicated(["_lat","_lon"]).sum()),
    }


def robust_outlier_mask(series: pd.Series, z_threshold: float = 6.0) -> pd.Series:
    x=pd.to_numeric(series,errors="coerce")
    med=x.median()
    mad=(x-med).abs().median()
    if pd.isna(mad) or mad==0:
        return pd.Series(False,index=x.index)
    rz=(x-med)/(1.4826*mad)
    return rz.abs()>z_threshold


def supplied_or_zero(df: pd.DataFrame, col: str | None) -> pd.Series:
    s=_num(df,col)
    return s.fillna(0.0)


def run_magnetic_pipeline(
    df: pd.DataFrame,
    lat_col: str,
    lon_col: str,
    mag_col: str,
    line_col: str | None = None,
    survey_type: str = "Ground Magnetic",
    apply_qc: bool = True,
    exclude_qc_outliers: bool = False,
    diurnal_col: str | None = None,
    reference_col: str | None = None,
    heading_col: str | None = None,
    lag_col: str | None = None,
    leveling_col: str | None = None,
    microleveling: bool = False,
    correction_sign: str = "Subtract supplied correction/effect",
    qc_z_threshold: float = 6.0,
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    """Process magnetic observations while retaining every intermediate stage.

    The pipeline intentionally does not assume that every survey requires every
    correction. Mandatory/optional labels are guidance; the user must confirm
    the input processing level and survey specifications.
    """
    work=df.copy()
    stats=_required_fields(work,lat_col,lon_col,mag_col)
    work["Mag_QC_Flag"]="PASS"
    outlier=robust_outlier_mask(work[mag_col], qc_z_threshold) if apply_qc else pd.Series(False,index=work.index)
    work.loc[outlier,"Mag_QC_Flag"]="ROBUST_OUTLIER"
    missing=_num(work,mag_col).isna()
    work.loc[missing,"Mag_QC_Flag"]="MISSING"

    if exclude_qc_outliers:
        use_mask=~outlier & ~missing
    else:
        use_mask=~missing

    current=_num(work,mag_col).copy()
    # Keep the raw stage untouched and retain only usable values in the working field.
    stages=[{
        "code":"RAW_TMI","name":"Raw TMI","mandatory":"Input","status":"READY","series":current.copy(),
        "description":"Input field supplied by the user or synthetic demonstration dataset."
    }]

    sign=-1.0 if correction_sign.startswith("Subtract") else 1.0

    def apply_step(code,name,source,required,description):
        nonlocal current
        current=current + sign*supplied_or_zero(work, source)
        current.loc[~use_mask]=np.nan
        stages.append({"code":code,"name":name,"mandatory":required,"status":"APPLIED","series":current.copy(),"description":description})

    if diurnal_col:
        apply_step("DIURNAL_CORRECTED","After Diurnal Correction",diurnal_col,"Required for raw time-varying TMI","Temporal/base-station correction applied.")
    else:
        stages.append({"code":"DIURNAL_CORRECTED","name":"After Diurnal Correction","mandatory":"Required for raw time-varying TMI","status":"SKIPPED","series":current.copy(),"description":"No diurnal correction column was selected."})

    if reference_col:
        apply_step("REFERENCE_REMOVED","After IGRF / Reference Removal",reference_col,"Required for magnetic anomaly product","Reference/main field removed.")
    else:
        stages.append({"code":"REFERENCE_REMOVED","name":"After IGRF / Reference Removal","mandatory":"Required for magnetic anomaly product","status":"SKIPPED","series":current.copy(),"description":"No reference-field column was selected."})

    if heading_col:
        apply_step("HEADING_CORRECTED","After Heading Correction",heading_col,"Survey-dependent","Heading effect/correction applied according to selected sign convention.")
    else:
        stages.append({"code":"HEADING_CORRECTED","name":"After Heading Correction","mandatory":"Survey-dependent","status":"SKIPPED","series":current.copy(),"description":"No heading correction column selected; this stage is optional and survey-dependent."})

    if lag_col:
        apply_step("LAG_CORRECTED","After Lag Correction",lag_col,"Airborne/UAV survey-dependent","Lag effect/correction applied according to selected sign convention.")
    else:
        stages.append({"code":"LAG_CORRECTED","name":"After Lag Correction","mandatory":"Airborne/UAV survey-dependent","status":"SKIPPED","series":current.copy(),"description":"No lag correction column selected; this stage is optional and survey-dependent."})

    if leveling_col:
        apply_step("LEVELED","After Leveling",leveling_col,"Survey-dependent","Line leveling term applied according to selected sign convention.")
    else:
        stages.append({"code":"LEVELED","name":"After Leveling","mandatory":"Survey-dependent","status":"SKIPPED","series":current.copy(),"description":"No line-leveling correction column selected; this stage is optional and survey-dependent."})

    if microleveling:
        if line_col and line_col in work.columns and current.notna().sum() >= 20:
            temp=pd.DataFrame({"value":current,"line":work[line_col].astype(str)})
            global_med=temp["value"].median()
            line_offsets=temp.groupby("line")["value"].median()-global_med
            micro=temp["line"].map(line_offsets).fillna(0.0)
            current=current-micro
            stages.append({"code":"MICROLEVELLED","name":"After Micro-leveling","mandatory":"Survey-dependent","status":"APPLIED","series":current.copy(),"description":"Line-median residual correction applied; always review against geology before accepting."})
        else:
            stages.append({"code":"MICROLEVELLED","name":"After Micro-leveling","mandatory":"Survey-dependent","status":"SKIPPED","series":current.copy(),"description":"Requires a line identifier and usable magnetic data."})
    else:
        stages.append({"code":"MICROLEVELLED","name":"After Micro-leveling","mandatory":"Survey-dependent","status":"SKIPPED","series":current.copy(),"description":"Micro-leveling was not selected; this stage is optional and survey-dependent."})

    # Explicit final product: this is the last applicable magnetic correction stage.
    # It is separate from the intermediate stage list so users can distinguish
    # diagnostics from the product used downstream for normalization/targeting.
    final_stage = {
        "code": "FINAL_MAGNETIC_ANOMALY",
        "name": "Final Magnetic Anomaly",
        "mandatory": "Final product",
        "status": "FINAL",
        "series": current.copy(),
        "description": "Final magnetic anomaly after all selected/applicable corrections. Use this product for normalization, integration, targeting, and interpretation.",
    }
    stages.append(final_stage)

    work["Mag_Final_Processed_nT"]=current
    metadata={
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "survey_type": survey_type,
        "stats": stats,
        "sign_convention": correction_sign,
        "qc_z_threshold": qc_z_threshold,
        "applied_steps": [s["code"] for s in stages if s["status"]=="APPLIED"],
        "final_stage": "FINAL_MAGNETIC_ANOMALY",
    }
    return work, stages, metadata


def contour_grid(lat: pd.Series, lon: pd.Series, values: pd.Series, nx: int=160, ny: int=160):
    lat=pd.to_numeric(lat,errors="coerce"); lon=pd.to_numeric(lon,errors="coerce"); values=pd.to_numeric(values,errors="coerce")
    m=lat.notna() & lon.notna() & values.notna()
    x=lon[m].to_numpy(); y=lat[m].to_numpy(); z=values[m].to_numpy()
    if len(z)<3 or len(np.unique(x))<2 or len(np.unique(y))<2:
        return None
    gx=np.linspace(x.min(),x.max(),nx); gy=np.linspace(y.min(),y.max(),ny)
    X,Y=np.meshgrid(gx,gy)
    Z=griddata((x,y),z,(X,Y),method="linear")
    nearest=griddata((x,y),z,(X,Y),method="nearest")
    if Z is None or np.isnan(Z).all(): Z=nearest
    else: Z=np.where(np.isnan(Z),nearest,Z)
    return X,Y,Z,x,y,z


def stage_summary(stages:list[dict[str,Any]]) -> pd.DataFrame:
    rows=[]
    for s in stages:
        v=pd.to_numeric(s["series"],errors="coerce")
        rows.append({"Step":s["code"],"Name":s["name"],"Requirement":s["mandatory"],"Status":s["status"],"Valid Points":int(v.notna().sum()),"Min":v.min(skipna=True),"Max":v.max(skipna=True),"Mean":v.mean(skipna=True),"Description":s["description"]})
    return pd.DataFrame(rows)


def serializable_steps(stages:list[dict[str,Any]]) -> list[dict[str,Any]]:
    return [{k:v for k,v in s.items() if k!="series"} for s in stages]
