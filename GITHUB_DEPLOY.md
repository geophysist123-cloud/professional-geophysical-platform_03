# GitHub + Streamlit Community Cloud Deployment

## 1. Create the GitHub repository

Create a new repository, for example:

`professional-geophysical-platform`

Use an empty repository. Do not add a second README or other generated files when creating it because this package already contains the project files.

## 2. Upload the project

The repository root must contain `app.py` and `requirements.txt`.

Recommended top-level structure:

```text
professional-geophysical-platform/
├── app.py
├── requirements.txt
├── README.md
├── DEPLOYMENT.md
├── GITHUB_DEPLOY.md
├── .gitignore
├── .python-version
├── .streamlit/
├── auth/
├── config/
├── database/
├── gravity/
├── magnetic/
├── projects/
├── synthetic/
├── targeting/
├── sample_data/
├── tests/
└── pages_*.py
```

Never upload real database passwords, `.env` files, `secrets.toml`, or runtime SQLite database files.

## 3. First local verification

Use Python 3.12 for a deployment-matched environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
python -m streamlit run app.py
```

The current Phase 11 test suite should report 4 passing tests.

## 4. Deploy to Streamlit Community Cloud

Open Streamlit Community Cloud and choose **Create app**.

Set:

- Repository: your GitHub repository
- Branch: `main`
- Main file path: `app.py`
- Python version: `3.12`

Then deploy.

## 5. External SQL Server from Community Cloud

Streamlit Community Cloud includes SQL Server client/ODBC tooling in its container, so the Python `pyodbc` package should be declared in `requirements.txt`.

Use **SQL Server Authentication** for a cloud-hosted SQL Server connection. Windows Integrated Authentication depends on the local Windows security context and is not a suitable authentication mechanism for a Linux-hosted Community Cloud app.

Your SQL Server must be reachable from the internet or through an accessible network path and must allow the Community Cloud source IPs according to your security policy.

## 6. Persistent core database

The platform can use automatic local SQLite for development. For a persistent multi-user cloud deployment, configure a persistent external database as the core application database instead of relying on the local SQLite filesystem.

A real secret should be entered in Streamlit Cloud under **Settings -> Secrets**, not committed to GitHub.

The example file `.streamlit_secrets_example.toml` shows the intended format without containing real credentials.

## 7. Post-deployment checks

After deployment:

1. Open the application.
2. Create/verify the administrator.
3. Open **Production QA**.
4. Confirm required Python packages are installed.
5. Test Synthetic Data.
6. Test Magnetic Processing.
7. Test Gravity Processing.
8. Test Integrated Targeting.
9. Test GIS & Interpretation.
10. Generate a custom PDF report.
11. Test an external database connection using a non-production/test database before connecting to a live exploration database.

## 8. Important security notes

- Never commit credentials to GitHub.
- Use a least-privilege SQL Server account for the application.
- Do not grant `db_owner` unless genuinely required.
- Prefer encrypted SQL connections.
- Use Streamlit Secrets for cloud credentials.
- Keep the Production QA page read-only.
- Review the audit log regularly.


### V5.7 map dependencies
`folium==0.20.0` and `streamlit-folium==0.27.4` are required for the interactive map viewer. Streamlit-folium's current release provides the `st_folium()` component used by the platform.
