# Deployment Guide

## Local

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## GitHub

Repository root should contain `app.py`, `requirements.txt`, `README.md`, and the Python packages used by the application. Do not commit passwords, secret files, or SQLite runtime databases.

## Streamlit Community Cloud

Select the GitHub repository, the `main` branch, and `app.py` as the entrypoint. Community Cloud installs dependencies from `requirements.txt` and launches the application.

## Database deployment

The core application database is automatically managed locally by the platform. External/project databases are configured at runtime through Database Manager or through a secure deployment secret mechanism.

For SQL Server on a local Windows workstation, the Python `pyodbc` package and a compatible Microsoft ODBC Driver for SQL Server must both be installed. For cloud deployment, choose a database/driver combination supported by the deployment environment and configure credentials through secrets rather than source code.


## Community Cloud SQL Server

Community Cloud provides SQL Server client/ODBC tooling in its container. Keep `pyodbc` in `requirements.txt`. Use SQL Server Authentication for cloud connections; Windows Integrated authentication is intended for the local Windows environment and should not be treated as the cloud authentication path.

See `GITHUB_DEPLOY.md` for the full deployment sequence and secrets guidance.
