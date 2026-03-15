# HSE_vibe_hack

## Standalone analysis module

The repository now contains a separate package, `study_analysis`, for worksheet analysis without `FastAPI`.

The current data model is subject-centric:
- one source document corresponds to one subject;
- multiple worksheets inside that document are treated as parts of the same subject.

It currently supports:
- local `CSV` and `TSV` files;
- public `Google Sheets` links via CSV export across all worksheets;
- direct `CSV` and `TSV` URLs;
- heuristic student matching by name and group;
- optional `LLM` fallback for student row matching;
- automatic `LLM`-assisted worksheet structure analysis for complex headers;
- score extraction from worksheet columns;
- validation, normalization, risk scoring, and rule-based recommendations.

## Quick start

Run the standalone analyzer:

```bash
python3 analyze_sheet.py \
  --source tests/fixtures/algorithms.csv \
  --student "Иванов Иван Иванович" \
  --group "БПМИ231" \
  --view normalized
```

You can also pass a link instead of a file path:

```bash
python3 analyze_sheet.py \
  --source "https://docs.google.com/spreadsheets/d/.../edit#gid=0" \
  --student "Иванов Иван Иванович" \
  --group "БПМИ231" \
  --view normalized
```

Available views:
- `full` - everything, including worksheet-level extraction and validation;
- `extraction` - raw extraction output per worksheet;
- `normalized` - normalized student-facing result.

## Input and output

Input:
- `--source`: one of:
  - local path to `.csv` or `.tsv`
  - public Google Sheets link
  - direct HTTP(S) link to `.csv` or `.tsv`
- `--student`: full student name used for row matching
- `--group`: optional group string used as additional evidence
- `--llm-student-match openai`: optional fallback if heuristic row matching fails
- `--llm-worksheet-structure`: `auto` by default; uses LLM to understand complex multi-row headers and component columns

Output:
- the program prints JSON to stdout
- `--view extraction` returns raw extraction result per worksheet
- `--view normalized` returns the normalized student-facing structure for that subject, aggregated across valid worksheets from the same source
- `--view full` returns both source snapshot and all intermediate artifacts

Example normalized output shape:

```json
{
  "student": {
    "full_name": "Иванов Иван Иванович",
    "group": "БПМИ231"
  },
  "subjects": [
    {
      "name": "algorithms",
      "source_url": "...",
      "components": [],
      "current_weighted_score": 3.8,
      "predicted_score": 6.2,
      "risk_level": "high",
      "confidence": 0.93
    }
  ],
  "deadlines": [],
  "recommendations": [],
  "global_summary": {
    "average_score": 6.2,
    "high_risk_subjects": 1,
    "missing_data_sources": 0
  },
  "warnings": []
}
```

## Local setup

Create and activate a virtual environment, then install the packages:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install openai python-dotenv
```

Create a local `.env` file from the example:

```bash
cp .env.example .env
```

Then put your key into `.env`:

```env
OPENAI_API_KEY=your_real_key_here
STUDY_ANALYSIS_LLM_MODEL=gpt-5-mini
```

Enable LLM fallback for student matching:

```bash
python3 analyze_sheet.py \
  --source "https://docs.google.com/spreadsheets/d/.../edit#gid=0" \
  --student "Иванов Иван Иванович" \
  --group "БПМИ231" \
  --llm-worksheet-structure auto \
  --llm-student-match openai \
  --llm-model gpt-5-mini \
  --view extraction
```

## Telegram bot scaffold

The repository now also contains a local-first Telegram bot scaffold in `app/bot`.

Current shape:
- `aiogram` bot handlers and keyboards
- local `SQLite` storage for profiles and sources
- service layer that calls `study_analysis.AnalysisPipeline`
- a future backend seam in `app/bot/services/backend_api.py`

Run flow:

```bash
python3 -m pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=your_real_token_here
python3 -m app.bot.main
```

The bot currently assumes:
- one Telegram user = one student profile
- one source = one Google Sheets document for one subject
- only public Google Sheets links are accepted in the MVP

## Notes

- `Google Sheets` support currently assumes the sheet is publicly readable.
- When a Google spreadsheet has multiple worksheets, the program downloads each worksheet and aggregates valid components into one combined result.
- For suspicious worksheets with multi-row headers or repeated numeric column labels, the program can ask the LLM to map header rows and meaningful component columns before extraction.
- Direct URL loading assumes the URL serves CSV or TSV text.
- If the heuristic student matcher fails, the optional LLM matcher can suggest a row, but the code still re-validates that row before accepting it.
- The extractor is heuristic for now and is meant to become the core that later can be wrapped by `FastAPI`, Telegram, or the frontend.
