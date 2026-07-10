# Live HTTP Audit Tests

These pytest tests exercise the running backend and AI service over HTTP.
They are skipped by default so normal unit tests do not require live servers.

## Run

Start the backend without broad reload watching:

```powershell
cd backend
..\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Or, if reload is needed, scope it to the backend app only:

```powershell
cd backend
..\venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
```

Then run:

```powershell
$env:AUTOCRM_LIVE_TESTS="1"
$env:AUTOCRM_BACKEND_URL="http://localhost:8000"
$env:AUTOCRM_AI_SERVICE_URL="http://localhost:8001"
$env:AUTOCRM_TEST_EMAIL="<admin email>"
$env:AUTOCRM_TEST_PASSWORD="<admin password>"
..\venv\Scripts\pytest.exe tests\test_live_http_audit.py -q -s
```

## Report

The suite prints `AUTOCRM_LIVE_AUDIT_REPORT=<path>` at the end and writes a
redacted JSON report there. Override the output location with:

```powershell
$env:AUTOCRM_AUDIT_REPORT_DIR="C:\path\to\reports"
```

The report includes request name, method, URL, expected result, status code,
elapsed time, response shape, and a redacted response preview.
