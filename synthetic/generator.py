
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Body:
    name: str
    lat_offset_km: float
    lon_offset_km: float
    mag_amp_nt: float
    grav_amp_mgal: float
    radius_km: float
    polarity: float = 1.0


SURVEY_TEMPLATES = {
    "Ground Magnetic": {
        "description": "Ground station magnetic survey with line-wise noise, diurnal variation and heading effects.",
        "default_points": 900,
        "has_gravity": False,
    },
    "Airborne Magnetic": {
        "description": "Airborne magnetic survey with flight lines, tie-line offsets, heading/lag effects and altitude.",
        "default_points": 1200,
        "has_gravity": False,
    },
    "UAV Magnetic": {
        "description": "Low-altitude UAV magnetic survey with platform attitude and heading effects.",
        "default_points": 1000,
        "has_gravity": False,
    },
    "Raw Gravity": {
        "description": "Relative gravity station survey with tide/drift, latitude, elevation, terrain and observation noise.",
        "default_points": 700,
        "has_gravity": True,
    },
    "Complete Bouguer Gravity": {
        "description": "Gravity dataset starting at observed/free-air/Bouguer-style product stages, useful for downstream QC and targeting tests.",
        "default_points": 700,
        "has_gravity": True,
    },
    "Combined Magnetic + Gravity": {
        "description": "Integrated synthetic survey designed to test normalization, weighting, confidence, concordance and targeting.",
        "default_points": 1200,
        "has_gravity": True,
    },
}


def _gaussian_body(x_km, y_km, body: Body):
    d2 = (x_km - body.lat_offset_km) ** 2 + (y_km - body.lon_offset_km) ** 2
    shape = np.exp(-0.5 * d2 / max(body.radius_km, 0.1) ** 2)
    return shape * body.polarity


def _project_grid(n_points: int, area_km: float, line_count: int, rng: np.random.Generator):
    per_line = max(2, int(np.ceil(n_points / max(1, line_count))))
    lines = []
    station = 0
    for line_id in range(line_count):
        y = -area_km / 2 + line_id * area_km / max(1, line_count - 1)
        x = np.linspace(-area_km / 2, area_km / 2, per_line)
        jitter = rng.normal(0, area_km / 500, size=per_line)
        for xx, yy in zip(x, y + jitter):
            lines.append((line_id + 1, station, float(xx), float(yy)))
            station += 1
    return lines[:n_points]


def generate_synthetic_survey(
    template: str,
    n_points: int | None = None,
    area_km: float = 20.0,
    line_count: int = 30,
    center_lat: float = 30.0,
    center_lon: float = 31.0,
    seed: int = 42,
    noise_percent: float = 5.0,
    missing_mag_percent: float = 0.0,
    missing_grav_percent: float = 0.0,
    include_raw_components: bool = True,
) -> pd.DataFrame:
    if template not in SURVEY_TEMPLATES:
        raise ValueError(f"Unknown synthetic template: {template}")
    spec = SURVEY_TEMPLATES[template]
    n = int(n_points or spec["default_points"])
    if n < 20:
        raise ValueError("At least 20 measurement points are recommended for contour testing.")
    if area_km <= 0:
        raise ValueError("Area size must be positive.")
    if line_count < 1:
        raise ValueError("Line count must be positive.")

    rng = np.random.default_rng(seed)
    points = _project_grid(n, area_km, line_count, rng)
    x = np.array([p[2] for p in points])
    y = np.array([p[3] for p in points])
    line_ids = np.array([p[0] for p in points])
    stations = np.array([p[1] for p in points])

    # Deliberately non-random geological bodies. These act as known-answer targets.
    bodies = [
        Body("Magnetic High A", -4.5, -2.0, 220.0, 8.0, 1.8, 1.0),
        Body("Gravity High B", 4.0, 3.5, 70.0, 11.0, 2.2, 1.0),
        Body("Integrated Target C", 1.0, -4.5, 190.0, 9.0, 1.5, 1.0),
        Body("Magnetic Low D", 5.0, -4.0, 140.0, -6.0, 2.0, -1.0),
    ]

    mag_signal = np.zeros(n)
    grav_signal = np.zeros(n)
    for body in bodies:
        profile = _gaussian_body(x, y, body)
        mag_signal += body.mag_amp_nt * profile
        grav_signal += body.grav_amp_mgal * profile

    # Background regional gradients.
    mag_regional = 41000.0 + 2.5 * x + 1.0 * y
    grav_regional = 980.0 + 0.10 * x - 0.08 * y

    # Survey-time and line effects.
    times = [datetime(2026, 1, 15) + timedelta(seconds=int(i * 15)) for i in stations]
    phase = np.linspace(0, 10 * np.pi, n)
    diurnal = 12.0 * np.sin(phase / 2.0) + 4.0 * np.sin(phase)
    line_heading = 6.0 * np.sin(np.deg2rad((line_ids * 13) % 360))
    line_leveling = rng.normal(0.0, 1.5, line_ids.max() + 1)[line_ids]

    elevation = 100.0 + 0.4 * x - 0.2 * y + 12.0 * np.sin(x / 5.0) + rng.normal(0, 2.0, n)
    tide = 0.35 * np.sin(phase / 1.7)
    drift = np.linspace(0.0, 1.8, n) + rng.normal(0, 0.05, n)
    latitude_effect = 0.2 * (center_lat + y / 111.0 - center_lat)
    free_air = 0.3086 * elevation
    density = 2.67
    bouguer = 0.04193 * density * elevation
    terrain = 0.25 + 0.15 * np.cos(y / 3.0)
    curvature = 0.02 * np.ones(n)
    isostatic = 0.8 * np.sin(x / 6.0)

    mag_noise = rng.normal(0, max(0.1, noise_percent / 100.0 * np.std(mag_signal)), n)
    grav_noise = rng.normal(0, max(0.01, noise_percent / 100.0 * np.std(grav_signal)), n)

    raw_tmi = mag_regional + mag_signal + diurnal + line_heading + mag_noise
    mag_igrf = 41000.0
    mag_after_diurnal = raw_tmi - diurnal
    mag_anomaly = mag_after_diurnal - mag_igrf
    mag_leveled = mag_anomaly + line_leveling
    mag_final = mag_leveled

    raw_gravity = grav_regional + grav_signal + tide + drift + grav_noise
    observed_gravity = raw_gravity - tide - drift
    free_air_anomaly = observed_gravity + free_air - latitude_effect
    simple_bouguer = free_air_anomaly - bouguer
    complete_bouguer = simple_bouguer + terrain + curvature
    isostatic_anomaly = complete_bouguer - isostatic

    # Keep all useful processing components in the synthetic source table.
    lat = center_lat + y / 111.0
    lon = center_lon + x / (111.0 * np.cos(np.deg2rad(center_lat)))

    df = pd.DataFrame({
        "Point_ID": [f"SYN{int(i):05d}" for i in range(n)],
        "Line_ID": [f"L{int(v):03d}" for v in line_ids],
        "Station": stations,
        "Date_Time": times,
        "Latitude": lat,
        "Longitude": lon,
        "Easting_km_local": x,
        "Northing_km_local": y,
        "Elevation_m": elevation,
        "Survey_Template": template,
    })

    if "Magnetic" in template:
        df["Mag_Raw_TMI_nT"] = raw_tmi
        df["Mag_Base_Station_nT"] = mag_regional
        df["Mag_Diurnal_Correction_nT"] = diurnal
        df["Mag_IGRF_Reference_nT"] = mag_igrf
        df["Mag_Heading_Correction_nT"] = line_heading
        df["Mag_Leveling_Correction_nT"] = line_leveling
        df["Mag_Anomaly_nT"] = mag_final
        if template == "Airborne Magnetic":
            df["GPS_Altitude_m"] = elevation + 500 + 15 * np.sin(x / 4.0)
            df["Sensor_Height_m"] = 30.0
            df["Heading_deg"] = (90 + line_ids * 2.5) % 360
            df["Lag_Correction_nT"] = 0.5 * np.sin(phase)
        elif template == "UAV Magnetic":
            df["GPS_Altitude_m"] = elevation + 50 + 3 * np.sin(x / 2.0)
            df["Sensor_Height_m"] = 5.0
            df["Heading_deg"] = (180 + line_ids * 5.0) % 360
            df["Roll_deg"] = 2.0 * np.sin(phase / 1.5)
            df["Pitch_deg"] = 1.5 * np.cos(phase / 1.7)
            df["Yaw_deg"] = df["Heading_deg"]

    if spec["has_gravity"]:
        df["Gravity_Raw_mGal"] = raw_gravity
        df["Gravity_Base_mGal"] = grav_regional
        df["Gravity_Tide_Correction_mGal"] = tide
        df["Gravity_Drift_Correction_mGal"] = drift
        df["Gravity_Latitude_Correction_mGal"] = latitude_effect
        df["Gravity_Free_Air_Correction_mGal"] = free_air
        df["Gravity_Bouguer_Correction_mGal"] = bouguer
        df["Gravity_Terrain_Correction_mGal"] = terrain
        df["Gravity_Curvature_Correction_mGal"] = curvature
        df["Gravity_Isostatic_Correction_mGal"] = isostatic
        df["Gravity_Free_Air_Anomaly_mGal"] = free_air_anomaly
        df["Gravity_Simple_Bouguer_mGal"] = simple_bouguer
        df["Gravity_Complete_Bouguer_mGal"] = complete_bouguer
        df["Gravity_Isostatic_Anomaly_mGal"] = isostatic_anomaly

    # Deliberately introduce missing observations to test Confidence rules.
    if "Magnetic" in template and missing_mag_percent > 0:
        mask = rng.random(n) < missing_mag_percent / 100.0
        mag_cols = [c for c in df.columns if c.startswith("Mag_")]
        df.loc[mask, mag_cols] = np.nan

    if spec["has_gravity"] and missing_grav_percent > 0:
        mask = rng.random(n) < missing_grav_percent / 100.0
        grav_cols = [c for c in df.columns if c.startswith("Gravity_")]
        df.loc[mask, grav_cols] = np.nan

    # Quality flag is independent of missingness and supports QC demonstrations.
    df["Quality_Flag"] = "GOOD"
    outlier_mask = rng.random(n) < 0.01
    df.loc[outlier_mask, "Quality_Flag"] = "CHECK_OUTLIER"

    return df
