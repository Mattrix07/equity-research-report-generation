"""FastAPI entry point for the equity research report generator."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow `python3 src/main.py` from repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from src.config import settings
from src.schemas import ReportRequest
from src.workflow import generate_report

app = FastAPI(title="Equity Research Report Generator", version="0.1.0")

OUTPUTS_DIR = Path("outputs")
OUTPUTS_DIR.mkdir(exist_ok=True)
(OUTPUTS_DIR / "reports").mkdir(parents=True, exist_ok=True)
(OUTPUTS_DIR / "charts").mkdir(parents=True, exist_ok=True)
(OUTPUTS_DIR / "models").mkdir(parents=True, exist_ok=True)

app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")


@app.get("/", response_class=HTMLResponse)
def serve_ui() -> HTMLResponse:
    ui_path = Path(__file__).parent / "ui" / "index.html"
    return HTMLResponse(ui_path.read_text(encoding="utf-8"))


@app.post("/report/initiation")
def create_initiation_report(request: ReportRequest):
    try:
        report = generate_report(request)
    except Exception as exc:  # pragma: no cover - surfaced to localhost user
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    report_url = f"/{report.html_path}" if report.html_path else None
    return {
        "ticker": report.snapshot.ticker,
        "company_name": report.snapshot.company_name,
        "recommendation": report.recommendation,
        "target_price": report.target_price,
        "upside_downside": report.upside_downside,
        "report_path": report.html_path,
        "report_url": report_url,
    }


@app.post("/report/update")
def create_update_report(request: ReportRequest):
    request.report_type = "update"
    return create_initiation_report(request)


@app.post("/report/quick")
def create_quick_report(request: ReportRequest):
    request.report_type = "quick"
    return create_initiation_report(request)


@app.post("/valuation/dcf")
def create_dcf_only(request: ReportRequest):
    request.report_type = "valuation_only"
    return create_initiation_report(request)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    print(f"Equity Research Report Generator running on http://localhost:{settings.port}")
    uvicorn.run("src.main:app", host="0.0.0.0", port=settings.port, reload=False)
