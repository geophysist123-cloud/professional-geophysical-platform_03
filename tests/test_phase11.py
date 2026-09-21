import numpy as np
import pandas as pd

from synthetic.generator import generate_synthetic_survey
from magnetic.processing import run_magnetic_pipeline
from gravity.processing import run_gravity_pipeline
from targeting.integration import combine_scores


def test_synthetic_ground_magnetic():
    df = generate_synthetic_survey("Ground Magnetic", 120, 10, 12, 30.0, 31.0, 42, 3.0, 0, 0)
    assert len(df) == 120
    assert df["Latitude"].notna().all()
    assert df["Longitude"].notna().all()
    assert df["Mag_Raw_TMI_nT"].notna().all()


def test_magnetic_pipeline_preserves_rows():
    df = generate_synthetic_survey("Ground Magnetic", 120, 10, 12, 30.0, 31.0, 42, 3.0, 0, 0)
    out, stages, meta = run_magnetic_pipeline(
        df, "Latitude", "Longitude", "Mag_Raw_TMI_nT",
        diurnal_col="Mag_Diurnal_Correction_nT",
        reference_col="Mag_IGRF_Reference_nT",
        leveling_col=None,
    )
    assert len(out) == len(df)
    assert len(stages) >= 3
    assert out["Mag_Final_Processed_nT"].notna().sum() > 100
    assert meta["run_id"]


def test_gravity_pipeline_preserves_rows():
    df = generate_synthetic_survey("Raw Gravity", 120, 10, 12, 30.0, 31.0, 42, 3.0, 0, 0)
    out, stages, meta = run_gravity_pipeline(
        df, "Latitude", "Longitude", "Elevation_m", "Gravity_Raw_mGal",
        tide_col="Gravity_Tide_Correction_mGal",
        drift_col="Gravity_Drift_Correction_mGal",
        free_air_col="Gravity_Free_Air_Correction_mGal",
        bouguer_col="Gravity_Bouguer_Correction_mGal",
        terrain_col="Gravity_Terrain_Correction_mGal",
    )
    assert len(out) == len(df)
    assert len(stages) >= 4
    assert out["Gravity_Final_Processed_mGal"].notna().sum() > 100
    assert meta["run_id"]


def test_targeting_confidence_and_concordance():
    n = 10
    df = pd.DataFrame({
        "Latitude": np.linspace(30, 30.1, n),
        "Longitude": np.linspace(31, 31.1, n),
        "Mag_Final_Processed_nT": np.linspace(10, 100, n),
        "Gravity_Final_Processed_mGal": np.linspace(1, 10, n),
    })
    df.loc[1, "Gravity_Final_Processed_mGal"] = np.nan
    df.loc[2, "Mag_Final_Processed_nT"] = np.nan
    df.loc[3, ["Mag_Final_Processed_nT", "Gravity_Final_Processed_mGal"]] = np.nan
    scored = combine_scores(df)
    assert scored.loc[0, "Data_Confidence"] == 100.0
    assert scored.loc[1, "Data_Confidence"] == 60.0
    assert scored.loc[2, "Data_Confidence"] == 40.0
    assert pd.isna(scored.loc[3, "Data_Confidence"])
    assert pd.notna(scored.loc[0, "Concordance"])
    assert pd.isna(scored.loc[1, "Concordance"])
    assert pd.isna(scored.loc[2, "Concordance"])
    assert pd.isna(scored.loc[3, "Target_Score"])
