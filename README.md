# Equity Research Report Generation

A localhost prototype for generating structured equity research reports using a multi-agent workflow plus deterministic Python valuation engines.

This project is designed around an initiation-report structure similar to the user's baseline report: investment snapshot, executive summary, long-view thesis, scenario framework, company overview, business model, market analysis, competitive landscape, commercial drivers, financial overview, DCF valuation, scenario analysis, sensitivity analysis, catalysts, risks, and appendices.

## What this prototype does

- Runs a FastAPI localhost app.
- Generates a structured initiation, update, or quick-view report.
- Pulls public market and financial data with `yfinance`.
- Runs deterministic Python calculations for:
  - historical ratios
  - technical indicators
  - forecast scenarios
  - DCF valuation
  - WACC / terminal growth sensitivity
  - revenue growth / EBITDA margin sensitivity
  - simplified peer comps
- Uses agent-style modules for:
  - report management
  - company overview
  - industry and market analysis
  - competitive landscape
  - commercial drivers
  - risk review
  - QA
  - report writing
- Produces a browser-viewable HTML report on localhost.

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

## Example request

From the UI, enter:

```text
AAPL
```

or call the API directly:

```bash
curl -X POST http://localhost:8080/report/initiation \
  -H "Content-Type: application/json" \
  -d '{"ticker":"AAPL","company_name":"Apple Inc.","report_type":"initiation"}'
```

## Optional LLM configuration

The prototype works without an LLM key. If you want to add LLM-written narrative later, configure an OpenAI-compatible endpoint:

```env
OPENAI_API_KEY=your_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

For Nebius Token Factory, use the OpenAI-compatible endpoint and model ID provided by Nebius.

## Current limitations

- This is not investment advice.
- Financial data comes from public `yfinance` fields and may be incomplete for some stocks.
- Forecasting uses structured assumptions and deterministic calculations, but assumptions still require analyst review.
- The peer comps module uses a simple default peer set unless extended.
- The report is a prototype baseline, not yet a polished institutional PDF output.

## Intended next upgrades

- PDF export.
- Excel model export.
- SEC/ASX filings ingestion.
- Broker consensus ingestion.
- More sector-specific forecast templates.
- Healthcare-specific risk-adjusted NPV model.
- Human-in-the-loop assumption editing.
