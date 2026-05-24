"""FastAPI entry point for the equity research report generator."""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
from pathlib import Path

# Allow `python3 src/main.py` from repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from src.config import settings
from src.schemas import ReportRequest
from src.workflow_iterative import generate_report

app = FastAPI(title="Equity Research Report Generator", version="0.2.0")

OUTPUTS_DIR = Path("outputs")
OUTPUTS_DIR.mkdir(exist_ok=True)
(OUTPUTS_DIR / "reports").mkdir(parents=True, exist_ok=True)
(OUTPUTS_DIR / "charts").mkdir(parents=True, exist_ok=True)
(OUTPUTS_DIR / "models").mkdir(parents=True, exist_ok=True)

app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")


def _report_response(report):
    report_url = f"/{report.html_path}" if report.html_path else None
    model_url = f"/{report.excel_model_path}" if report.excel_model_path else None
    return {
        "ticker": report.snapshot.ticker,
        "company_name": report.snapshot.company_name,
        "recommendation": report.recommendation,
        "target_price": report.target_price,
        "upside_downside": report.upside_downside,
        "report_path": report.html_path,
        "report_url": report_url,
        "excel_model_path": report.excel_model_path,
        "excel_model_url": model_url,
    }


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
    return _report_response(report)


@app.post("/report/stream")
def stream_report(request: ReportRequest):
    event_queue: queue.Queue[dict] = queue.Queue()

    def emit(event: dict):
        event_queue.put({"type": "agent", **event})

    def worker():
        try:
            report = generate_report(request, progress_callback=emit)
            event_queue.put({"type": "result", **_report_response(report)})
        except Exception as exc:
            event_queue.put({"type": "error", "detail": str(exc)})
        finally:
            event_queue.put({"type": "done"})

    threading.Thread(target=worker, daemon=True).start()

    def event_stream():
        while True:
            event = event_queue.get()
            yield f"data: {json.dumps(event, default=str)}\n\n"
            if event.get("type") == "done":
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/model/excel")
def create_excel_model(request: ReportRequest):
    return create_initiation_report(request)


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
    return {"status": "ok", "workflow": "iterative_llm_assisted_model_first"}


if __name__ == "__main__":
    print(f"Equity Research Report Generator running on http://localhost:{settings.port}")
    uvicorn.run("src.main:app", host="0.0.0.0", port=settings.port, reload=False)
