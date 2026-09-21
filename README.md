# Professional Geophysical Exploration Platform — V5.7.4

Interactive correction-stage maps are first-class views for every Magnetic and Gravity processing stage. Each selected stage can be inspected interactively in Project CRS or Live Web Basemap mode; static PNG downloads remain available separately.

# Professional Geophysical Exploration Platform — V5.2 Deployment Candidate

Production QA and deployment-readiness release of the modular geophysical platform.

## Current capabilities

- Automatic core SQLite platform database
- External database connectivity through SQLAlchemy
- SQL Server / PostgreSQL / MySQL / MariaDB / Oracle architecture
- Users, roles, permissions and administration
- Project-level access and global CRS/EPSG management
- Interactive database/table manager
- Synthetic magnetic and gravity datasets
- Magnetic correction pipeline with intermediate results
- Gravity correction pipeline with intermediate results
- Contour maps from measured station points
- Integrated Magnetic + Gravity targeting
- Robust Z-score — Recommended default
- Percentile and Winsorized Min-Max alternatives
- Magnetic 60% / Gravity 40% default weights
- Data Confidence: 100% / 60% / 40% / No Score
- Concordance only when both signals are available
- Final model: 85% evidence + 15% concordance for two-signal records
- GIS interpretation overlays
- Custom PDF reports
- External processing/target/interpretation/report metadata storage
- Production QA page and deployment checklist

## Run

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Testing

```bash
python -m pytest -q
```

## Security

Never commit passwords, `.env` files, Streamlit secrets, or runtime database files. Use runtime secrets for external database credentials.

## Synthetic data

Synthetic surveys are for software QA and demonstration only. They are not measured geophysical observations.


## Deployment

This package is prepared for GitHub and Streamlit Community Cloud. See `GITHUB_DEPLOY.md` for the deployment checklist.

The recommended Community Cloud Python version for this release is Python 3.12. Streamlit Community Cloud currently defaults to Python 3.12 and allows selecting the deployment Python version in Advanced settings.

For persistent multi-user cloud deployments, use a persistent external database for the core application database rather than relying on a local SQLite file.

## Core database behavior
The core SQLite database is created automatically at startup. Initialization is idempotent and preserves existing users and data.

## Global CRS management (V5.3)

Projects support global coordinate reference system selection through the installed PROJ/EPSG registry. The project screen provides three methods:

- Search the EPSG/PROJ registry by code or CRS name.
- Enter an EPSG code directly (for example `4326` or `32636`).
- Enter a custom PROJ string, WKT, or PROJJSON definition accepted by `pyproj`.

The platform stores the CRS EPSG code (when available), authority, name, WKT definition, and coordinate units so a project can use a local or global CRS without an Egypt-specific assumption.

## Global CRS Explorer — V5.4

The Projects and CRS pages now provide a GIS-style coordinate-system explorer with search, authority/type filters, browse/catalog mode, favorites, recent CRS selections, point-based UTM suggestions, detailed CRS properties, WKT/PROJJSON inspection, and custom CRS input. The project CRS is stored with authority, name, WKT, and units when available.


## V5.5 — CRS-aware mapping

Project CRS now drives geophysical contour interpolation. Station latitude/longitude are treated as WGS 84 geographic coordinates, transformed with PROJ/pyproj into the selected project CRS, and interpolated in Project X/Y. Magnetic, gravity, integrated evidence, and Target Score maps display the project CRS and project units.


## V5.5.2

Project display is backward-compatible with older local databases that may not yet contain the newer CRS metadata attributes. Run the built-in schema update before using the enhanced CRS fields.


## V5.5.4
- Fixed project creation return-value unpacking.
- Clarified CRS button: “Use this CRS for project form”.
- Project is created only by the Create Project action.

## V5.5.5
Project edit saves now refresh the displayed project details and editor state immediately after Save Project.

## V5.6.1 fixes

- Projects page is the single canonical location for creating projects.
- Administration -> Project Access assigns users to existing projects.
- Project creators receive project access automatically.
- Project Access refreshes users and projects from the database.
- New-user Active status is honored at creation time.
- Project editing refreshes the editor widgets from the saved database record.

## Targeting input rule
Integrated targeting uses explicitly selected final corrected magnetic and gravity anomaly products. Normalization is applied only after geophysical correction. Raw or intermediate fields are never silently substituted.

## V5.7 Interactive GIS Maps

The GIS, Magnetic, Gravity, and Integrated Targeting pages use large interactive Leaflet maps via streamlit-folium. Users can pan, zoom, open full screen, switch live basemaps, overlay OpenRailwayMap, and add provider-specific geological WMS layers. Geophysical surfaces are calculated in the selected Project CRS and transformed for geographic display.

Built-in live layers include OpenStreetMap, Esri World Imagery, Esri World Street Map, Esri World Topographic Map, CartoDB Voyager, and OpenRailwayMap. Geological layers are supplied by a WMS endpoint selected by the user; OneGeology exposes participating geological providers through OGC WMS/WFS/WCS services.

## V5.7.3 — Interactive GIS layer tree

Maps now support independent per-map view/basemap preferences during the current session, a GIS-style layer tree, Project CRS vs Live Web views, and cached interpolation/decimated station display for responsive interaction. Live maps expose geophysical surface, contours, stations, targets, roads/transport, railways, and optional geological WMS; web basemaps include streets, satellite, and topography. Project CRS views use the selected project CRS for scientific interpolation and Plotly legend controls as the layer tree.
