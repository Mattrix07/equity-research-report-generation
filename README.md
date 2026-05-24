# Equity Research Report Generation

A localhost prototype for generating structured equity research reports and linked Excel valuation models using a multi-agent workflow, dynamic peer selection, DCF-led valuation, Financial Modeling Prep statement data where configured, and optional native Excel recalculation.

## What this prototype does

- Runs a FastAPI localhost app.
- Generates a structured initiation, update, quick-view or valuation-only report.
- Uses Financial Modeling Prep as the preferred structured financial-statement provider when `FMP_API_KEY` is configured.
- Falls back to `yfinance` if FMP is not configured or fails.
- Uses a multi-agent LLM committee when enabled.
- Selects peers dynamically rather than relying on a fixed sector peer list.
- Produces a formula-linked Excel model:
  - Assumptions
  - 3 Statement Model
  - WACC
  - DCF
  - Comps Analysis
  - Football Field
  - Sensitivity Analysis
  - Model Audit
- Separates intrinsic DCF value from the DCF-led 12-month target-price bridge.
- Optionally recalculates the workbook through native Microsoft Excel using `xlwings` when `ENABLE_EXCEL_RUNTIME=true`.

The Excel workbook is generated from a fixed template. LLMs are used for research, assumptions, peer selection, risk framing and investment committee synthesis. Excel remains the auditable calculation layer.

## Repository structure

```text
equity-research-report-generation/
├── src/
│   ├── main.py
│   ├── config.py
│   ├── schemas.py
│   ├── workflow_iterative.py
│   ├── agents/
│   ├── data/
│   │   ├── provider.py
│   │   ├── fmp_client.py
│   │   └── yfinance_client.py
│   ├── engines/
│   ├── excel/
│   ├── report/
│   │   ├── formula_model_excel_exporter.py
│   │   ├── validated_model_excel_exporter.py
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

## Configuration

Add your keys to `.env`. Do not commit real API keys.

```env
PORT=8080

# Preferred structured financial statement provider
DATA_PROVIDER=fmp
FMP_API_KEY=your_financial_modeling_prep_api_key_here
FMP_BASE_URL=https://financialmodelingprep.com/stable
FMP_STATEMENT_LIMIT=10
FMP_TIMEOUT_SECONDS=30
MIN_STATEMENT_YEARS=5

# LLM configuration
ENABLE_LLM_COMMITTEE=true
OPENAI_API_KEY=your_openai_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
LLM_MANAGER_MODEL=gpt-4o-mini
LLM_BULL_MODEL=gpt-4o-mini
LLM_BEAR_MODEL=gpt-4o-mini
LLM_VALUATION_MODEL=gpt-4o-mini
LLM_REPORT_WRITER_MODEL=gpt-4o-mini
LLM_QA_MODEL=gpt-4o-mini

# Optional native Excel recalculation
ENABLE_EXCEL_RUNTIME=false
```

### Data provider behaviour

```text
DATA_PROVIDER=fmp
        ↓
Try FMP income statement, balance sheet and cash flow statement
        ↓
If FMP succeeds and returns enough history, use FMP data
        ↓
If FMP fails or is incomplete, fall back to yfinance and mark the source in the workbook audit tab
```

FMP is preferred because it returns structured statement history needed for a better three-statement model. `yfinance` remains useful for market snapshot, price history and fallback data.

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

The Excel model follows a controlled template approach:

```text
FMP/yfinance collect statement data and market data
        ↓
Python normalises historical financials
        ↓
LLM agents derive bounded assumptions when enabled
        ↓
Formula-driven Excel model is generated
        ↓
DCF and sensitivity tabs reference the 3 Statement Model, WACC and Assumptions tabs
        ↓
Optional native Excel recalculation via xlwings
        ↓
Workbook is returned to the UI
```

The workbook contains five historical years and a ten-year Excel forecast view. The historical balance sheet is populated from FMP when available. If FMP is unavailable, the workbook will show the fallback source in the Model Audit tab.

## Example API request

```bash
curl -X POST http://localhost:8080/report/initiation \
  -H "Content-Type: application/json" \
  -d '{"ticker":"NVDA","company_name":"NVIDIA Corporation","report_type":"initiation"}'
```

The JSON response includes:

```json
{
  "report_url": "/outputs/reports/nvda_initiation_report.html",
  "excel_model_url": "/outputs/models/nvda_initiation_formula_model.xlsx"
}
```

You can also call:

```bash
curl -X POST http://localhost:8080/model/excel \
  -H "Content-Type: application/json" \
  -d '{"ticker":"NVDA","company_name":"NVIDIA Corporation","report_type":"initiation"}'
```

## Optional native Excel recalculation

By default, the app creates a workbook that recalculates when opened in Excel:

```env
ENABLE_EXCEL_RUNTIME=false
```

If you are running locally on a machine with Microsoft Excel installed, you can ask the app to open Excel in the background, recalculate the workbook, save it and return the recalculated file:

```env
ENABLE_EXCEL_RUNTIME=true
```

This requires Microsoft Excel to be installed on your machine. Keep this disabled on headless servers.

## Current limitations

- This is not investment advice.
- FMP and yfinance are third-party data sources and may contain gaps or different field definitions.
- The model is formula-linked and more auditable than previous versions, but assumptions still require human review.
- Native Excel recalculation only works locally where Microsoft Excel is installed.
- The app validates model structure and references, but it cannot fully audit accounting judgement or forecast assumptions.
