# Equity Research Report Generation

A localhost prototype for generating structured equity research reports and simplified Excel valuation models using a multi-agent workflow, dynamic peer selection, DCF-led valuation and optional native Excel recalculation.

## What this prototype does

- Runs a FastAPI localhost app.
- Generates a structured initiation, update, quick-view or valuation-only report.
- Pulls public market and financial data with `yfinance`.
- Uses a multi-agent LLM committee when enabled.
- Selects peers dynamically rather than relying on a fixed sector peer list.
- Produces a simplified seven-tab Excel model:
  - Assumptions
  - 3 Statement Model
  - WACC
  - DCF
  - Comps Analysis
  - Football Field
  - Sensitivity Analysis
- Uses a fixed template-controlled Excel export path rather than allowing the LLM to invent workbook formulas.
- Validates key workbook links before returning the file.
- Optionally recalculates the workbook through native Microsoft Excel using `xlwings` when `ENABLE_EXCEL_RUNTIME=true`.

The Excel workbook is intentionally simple. The LLMs are used for research, assumptions, narrative, risks and investment committee synthesis. Excel remains the calculation layer.

## Repository structure

```text
equity-research-report-generation/
├── src/
│   ├── main.py
│   ├── config.py
│   ├── schemas.py
│   ├── workflow.py
│   ├── agents/
│   ├── data/
│   ├── engines/
│   ├── excel/
│   │   ├── excel_runtime.py
│   │   └── validate_workbook.py
│   ├── report/
│   │   ├── simplified_excel_exporter.py
│   │   ├── repaired_simplified_excel_exporter.py
│   │   └── renderer.py
│   └── ui/
├── outputs/
│   ├── reports/
│   ├── charts/
│   └── models/
├── requirements.txt
├── .env.example
└── README.md
```

## Setup

```bash
git clone https://github.com/Mattrix07/equity-research-report-generation.git
cd equity-research-report-generation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run

```bash
python3 src/main.py
```

Open:

```text
http://localhost:8080
```

Generated files are saved under:

```text
outputs/reports/
outputs/models/
```

## Excel model approach

The Excel model now follows a controlled template approach:

```text
Python / agents collect data and assumptions
        ↓
Fixed seven-tab Excel model is generated
        ↓
Workbook formulas are patched only from a known cell map
        ↓
Workbook structure is validated
        ↓
Optional native Excel recalculation via xlwings
        ↓
Workbook is returned to the UI
```

This avoids the earlier issue where generated formulas became too complex, circular or inconsistent.

The scenario selector is in:

```text
Assumptions!B3
```

Valid values:

```text
Bear
Base
Bull
```

The selected scenario flows into the 3 Statement Model, WACC, DCF, Football Field and Sensitivity Analysis tabs.

## Optional native Excel recalculation

By default, the app creates a workbook that recalculates when opened in Excel:

```env
ENABLE_EXCEL_RUNTIME=false
```

If you are running locally on a machine with Microsoft Excel installed, you can ask the app to open Excel in the background, recalculate the workbook, save it and return the recalculated file:

```env
ENABLE_EXCEL_RUNTIME=true
```

This requires:

```bash
pip install xlwings
```

`xlwings` is included in `requirements.txt`, but native recalculation still requires Microsoft Excel to be installed on your machine. Keep this disabled on headless servers.

## Example API request

```bash
curl -X POST http://localhost:8080/report/initiation \
  -H "Content-Type: application/json" \
  -d '{"ticker":"AAPL","company_name":"Apple Inc.","report_type":"initiation"}'
```

The JSON response includes:

```json
{
  "report_url": "/outputs/reports/aapl_initiation_report.html",
  "excel_model_url": "/outputs/models/aapl_initiation_simplified_model.xlsx"
}
```

You can also call:

```bash
curl -X POST http://localhost:8080/model/excel \
  -H "Content-Type: application/json" \
  -d '{"ticker":"AAPL","company_name":"Apple Inc.","report_type":"initiation"}'
```

## Optional LLM configuration

The prototype works without an LLM key. If you want LLM-written investment committee commentary, configure an OpenAI-compatible endpoint:

```env
ENABLE_LLM_COMMITTEE=true
OPENAI_API_KEY=your_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

You can route different agents to different models:

```env
LLM_BULL_MODEL=gpt-4o-mini
LLM_BEAR_MODEL=gpt-4o-mini
LLM_VALUATION_MODEL=gpt-4o-mini
LLM_REPORT_WRITER_MODEL=gpt-4o-mini
```

## Current limitations

- This is not investment advice.
- Financial data comes from public `yfinance` fields and may be incomplete for some stocks.
- The workbook is simplified and should be reviewed by a human analyst.
- Native Excel recalculation only works locally where Microsoft Excel is installed.
- The app validates workbook structure and references, but it cannot fully audit accounting judgement or forecast assumptions.
