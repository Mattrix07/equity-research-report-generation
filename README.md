# Equity Research Report Generation

A localhost prototype for generating structured equity research reports and linked Excel valuation models using a multi-agent workflow, dynamic valuation routing and deterministic model engines.

The project is designed around initiation/update-report structures: investment snapshot, executive summary, long-view thesis, scenario framework, company overview, business model, market analysis, competitive landscape, commercial drivers, foundational model plan, dynamic valuation, DCF cross-check, sensitivity analysis, catalysts, risks and appendices.

## What this prototype does

- Runs a FastAPI localhost app.
- Generates a structured initiation, update, quick-view or valuation-only report.
- Pulls public market and financial data with `yfinance`.
- Classifies the company and selects a valuation framework instead of forcing every company through one generic DCF.
- Builds a foundational financial model plan with forecast drivers, required evidence, valuation stack and sensitivity cases.
- Produces an Excel model output with tabs for:
  - Output
  - Source Data
  - Assumptions
  - Forecast
  - WACC
  - DCF
  - Comps
  - Sensitivity
  - Football Field
  - Sector-specific tabs such as Pipeline rNPV, Mining NAV, SaaS Unit Economics or ROE / Book Value Model when applicable
- Runs deterministic Python calculations for:
  - historical ratios
  - technical indicators
  - forecast scenarios
  - baseline DCF cross-check
  - WACC / terminal growth sensitivity
  - revenue growth / EBITDA margin sensitivity
  - simplified peer comps
- Uses agent-style modules for:
  - report management
  - company classification
  - assumption derivation
  - financial model planning
  - dynamic valuation routing
  - company overview
  - market analysis
  - competitive landscape
  - commercial drivers
  - risk review
  - QA
- Produces a browser-viewable HTML report and a downloadable Excel workbook on localhost.

The first version is intentionally practical rather than perfect. It uses deterministic fallbacks when an LLM API key is not configured, so the app can still run locally.

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
│   ├── report/
│   │   ├── excel_exporter.py
│   │   └── templates/
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

Generate a report from the UI. The response will include:

- an HTML report link
- an Excel model download link

Generated files are saved under:

```text
outputs/reports/
outputs/models/
```

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
  "excel_model_url": "/outputs/models/aapl_initiation_model.xlsx"
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

For Nebius Token Factory, use the OpenAI-compatible endpoint and model ID provided by Nebius.

## Current limitations

- This is not investment advice.
- Financial data comes from public `yfinance` fields and may be incomplete for some stocks.
- Forecasting uses structured assumptions and deterministic calculations, but assumptions still require analyst review.
- The Excel model is an analyst-style scaffold, not yet a fully audited institutional model.
- Sector-specific tabs are generated as structured templates first; detailed asset-level models require deeper source data.
- The peer comps module uses a simple default peer set unless extended.

## Intended next upgrades

- Real Excel export of full three-statement balance sheet and cash flow linkages.
- SEC/ASX filings ingestion.
- Broker consensus ingestion.
- More sector-specific forecast templates.
- Healthcare-specific risk-adjusted NPV engine populated from pipeline data.
- Mining NAV engine populated from reserves, mine plans and commodity decks.
- Human-in-the-loop assumption editing.
- PDF export.
