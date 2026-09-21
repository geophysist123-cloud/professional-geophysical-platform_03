from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.interpolate import griddata
from scipy.stats import norm
from pyproj import CRS, Transformer

DEFAULT_MAGNETIC_WEIGHT = 60.0
DEFAULT_GRAVITY_WEIGHT = 40.0
EVIDENCE_WEIGHT = 85.0
CONCORDANCE_WEIGHT = 15.0


def robust_z_score(series):
    x = pd.to_numeric(series, errors="coerce").abs()
    valid = x.dropna()
    out = pd.Series(np.nan, index=x.index, dtype=float)
    if len(valid) < 3:
        return out
    med = float(valid.median())
    mad = float((valid - med).abs().median())
    scale = 1.4826 * mad
    if scale <= np.finfo(float).eps:
        out.loc[valid.index] = valid.rank(pct=True).to_numpy() * 100.0
        return out
    rz = (x - med) / scale
    out.loc[rz.notna()] = np.clip(norm.cdf(rz.loc[rz.notna()]) * 100.0, 0.0, 100.0)
    return out


def percentile_score(series):
    x = pd.to_numeric(series, errors="coerce").abs()
    valid = x.dropna()
    out = pd.Series(np.nan, index=x.index, dtype=float)
    if len(valid) < 2:
        return out
    out.loc[valid.index] = valid.rank(pct=True).to_numpy() * 100.0
    return out


def winsorized_minmax_score(series, lower=0.05, upper=0.95):
    x = pd.to_numeric(series, errors="coerce").abs()
    valid = x.dropna()
    out = pd.Series(np.nan, index=x.index, dtype=float)
    if len(valid) < 2:
        return out
    lo, hi = float(valid.quantile(lower)), float(valid.quantile(upper))
    if hi <= lo:
        out.loc[valid.index] = 50.0
        return out
    clipped = x.clip(lo, hi)
    out.loc[valid.index] = ((clipped.loc[valid.index] - lo) / (hi - lo) * 100.0).to_numpy()
    return out


NORMALIZERS = {
    "Robust Z-score — Recommended": robust_z_score,
    "Percentile": percentile_score,
    "Winsorized Min-Max": winsorized_minmax_score,
}


def _first_existing(df, names):
    for n in names:
        if n in df.columns:
            return df[n]
    return pd.Series(np.nan, index=df.index, dtype=float)


def combine_scores(df, normalization="Robust Z-score — Recommended",
                   magnetic_weight=60.0, gravity_weight=40.0,
                   magnetic_col="Mag_Final_Processed_nT",
                   gravity_col="Gravity_Final_Processed_mGal"):
    """Normalize and integrate only explicitly selected corrected anomaly products.

    Raw/intermediate magnetic or gravity fields are never silently substituted.
    """
    out = df.copy()
    if magnetic_col not in out.columns:
        mag = pd.Series(np.nan, index=out.index, dtype=float)
    else:
        mag = pd.to_numeric(out[magnetic_col], errors="coerce")
    if gravity_col not in out.columns:
        grav = pd.Series(np.nan, index=out.index, dtype=float)
    else:
        grav = pd.to_numeric(out[gravity_col], errors="coerce")
    normalizer = NORMALIZERS[normalization]
    mag_norm, grav_norm = normalizer(mag), normalizer(grav)
    total = float(magnetic_weight) + float(gravity_weight)
    if total <= 0:
        magnetic_weight, gravity_weight, total = 60.0, 40.0, 100.0
    mw, gw = float(magnetic_weight) / total, float(gravity_weight) / total
    mp, gp = mag_norm.notna(), grav_norm.notna()
    confidence = pd.Series(np.nan, index=out.index, dtype=float)
    confidence.loc[mp & gp] = 100.0
    confidence.loc[mp & ~gp] = 60.0
    confidence.loc[~mp & gp] = 40.0
    cf = confidence / 100.0
    out["Mag_Normalized"] = mag_norm
    out["Grav_Normalized"] = grav_norm
    out["Data_Confidence"] = confidence
    out["Mag_Contribution"] = mag_norm.fillna(0.0) * mw * cf.fillna(0.0)
    out["Grav_Contribution"] = grav_norm.fillna(0.0) * gw * cf.fillna(0.0)
    out["Evidence_Score"] = out["Mag_Contribution"] + out["Grav_Contribution"]
    both = mp & gp
    out["Concordance"] = np.nan
    out.loc[both, "Concordance"] = (100.0 - (mag_norm.loc[both] - grav_norm.loc[both]).abs()).clip(0.0, 100.0)
    out["Target_Score"] = np.nan
    out.loc[both, "Target_Score"] = out.loc[both, "Evidence_Score"] * 0.85 + out.loc[both, "Concordance"] * 0.15
    one = mp ^ gp
    out.loc[one, "Target_Score"] = out.loc[one, "Evidence_Score"]
    def priority(v):
        if pd.isna(v): return "No Score"
        if v >= 80: return "VERY HIGH"
        if v >= 65: return "HIGH"
        if v >= 50: return "MEDIUM"
        return "LOW"
    out["Target_Priority"] = out["Target_Score"].apply(priority)
    out["Normalization_Method"] = normalization
    out["Magnetic_Input_Product"] = magnetic_col if magnetic_col in out.columns else "Not available"
    out["Gravity_Input_Product"] = gravity_col if gravity_col in out.columns else "Not available"
    return out



def _project_crs_input(project_crs=None):
    if project_crs is None:
        return CRS.from_epsg(4326)
    if isinstance(project_crs, CRS):
        return project_crs
    return CRS.from_user_input(project_crs)


def project_coordinates(df, project_crs=None, lat_col=None, lon_col=None):
    """Return a copy with Project_X/Project_Y generated from WGS84 lon/lat.

    Input geographic coordinates are interpreted as WGS84. This is deliberate:
    uploaded/synthetic station tables in the current platform store longitude and
    latitude as the portable geographic coordinates. The selected project CRS is
    then used for interpolation and contouring. For a future dataset with a
    different source CRS, reproject the source coordinates to WGS84 first or pass
    already transformed project X/Y columns to the mapping layer.
    """
    out = df.copy()
    lat_col = lat_col or ("Latitude" if "Latitude" in out.columns else "Lat")
    lon_col = lon_col or ("Longitude" if "Longitude" in out.columns else "Lon")
    if lat_col not in out.columns or lon_col not in out.columns:
        raise ValueError("Latitude/Longitude columns are required for CRS transformation.")
    lon = pd.to_numeric(out[lon_col], errors="coerce")
    lat = pd.to_numeric(out[lat_col], errors="coerce")
    valid = lon.notna() & lat.notna()
    crs = _project_crs_input(project_crs)
    transformer = Transformer.from_crs(CRS.from_epsg(4326), crs, always_xy=True)
    x = pd.Series(np.nan, index=out.index, dtype=float)
    y = pd.Series(np.nan, index=out.index, dtype=float)
    if valid.any():
        tx, ty = transformer.transform(lon.loc[valid].to_numpy(), lat.loc[valid].to_numpy())
        x.loc[valid] = tx
        y.loc[valid] = ty
    out["Project_X"] = x
    out["Project_Y"] = y
    out["Project_CRS"] = crs.to_string()
    out["Project_CRS_Name"] = crs.name
    return out


def contour_figure(df, value_col, title, cmap="viridis", units="", project_crs=None,
                   lat_col=None, lon_col=None, show_crs_panel=True, interpretation=None):
    import matplotlib.pyplot as plt
    work = project_coordinates(df, project_crs=project_crs, lat_col=lat_col, lon_col=lon_col)
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    work = work.dropna(subset=["Project_X", "Project_Y", value_col])
    work = work.groupby(["Project_X", "Project_Y"], as_index=False)[value_col].mean()

    fig, ax = plt.subplots(figsize=(10, 7))
    if len(work) < 3 or work["Project_X"].nunique() < 2 or work["Project_Y"].nunique() < 2:
        sc = ax.scatter(work["Project_X"], work["Project_Y"], c=work[value_col], s=18, cmap=cmap)
        if len(work): fig.colorbar(sc, ax=ax, label=units)
    else:
        x = work["Project_X"].to_numpy()
        y = work["Project_Y"].to_numpy()
        z = work[value_col].to_numpy()
        gx = np.linspace(x.min(), x.max(), 180)
        gy = np.linspace(y.min(), y.max(), 180)
        X, Y = np.meshgrid(gx, gy)
        Z = griddata((x, y), z, (X, Y), method="linear")
        Zn = griddata((x, y), z, (X, Y), method="nearest")
        Z = np.where(np.isnan(Z), Zn, Z)
        cf = ax.contourf(X, Y, Z, levels=16, cmap=cmap, alpha=0.88)
        cs = ax.contour(X, Y, Z, levels=16, linewidths=0.5)
        ax.clabel(cs, inline=True, fontsize=7, fmt="%.1f")
        ax.scatter(x, y, s=12, facecolors="none", edgecolors="black", linewidths=0.45, label="Measured points")
        ax.legend(loc="best")
        fig.colorbar(cf, ax=ax, label=units)

    crs = _project_crs_input(project_crs)
    ax.set_xlabel(f"X / Easting ({crs.axis_info[0].unit_name if crs.axis_info else 'project units'})")
    ax.set_ylabel(f"Y / Northing ({crs.axis_info[1].unit_name if len(crs.axis_info) > 1 else 'project units'})")
    ax.set_title(title)
    if show_crs_panel:
        auth = crs.to_authority()
        auth_text = f"{auth[0]}:{auth[1]}" if auth else "Custom CRS"
        ax.text(0.99, 0.01, f"Project CRS: {auth_text}\n{crs.name}", transform=ax.transAxes,
                ha="right", va="bottom", fontsize=8,
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.82, edgecolor="black"))
    if interpretation:
        ax.text(0.02, 0.98, str(interpretation).strip(), transform=ax.transAxes,
                va="top", ha="left", fontsize=8,
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.82, edgecolor="black"))
    fig.tight_layout()
    return fig
