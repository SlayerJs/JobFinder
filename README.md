# JobFinder

A configurable Python tool for discovering job listings, ranking them with DeepSeek, and tracking applications in SQLite. Define your own roles, locations, required criteria, and preferences in YAML.

## Features

- Search multiple job boards and skip previously seen listings.
- Extract job descriptions, flag unavailable pages, and link exact-content duplicates.
- Evaluate listings in batches with input/output budgets and usage accounting.
- Review evidence-backed decisions and four configurable match tiers.
- Track applications, notes, and deadlines from the command line.
- Export Excel summaries and optionally send Discord notifications.

## Setup

Use Python 3.11 or newer. From the project directory:

```sh
python -m venv .venv
# Linux/macOS/WSL:
source .venv/bin/activate
# Windows PowerShell instead:
# .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Copy `.env.example` to `.env` and `config.example.yaml` to `config.local.yaml`. Set `DEEPSEEK_API_KEY` in `.env`. Discord and proxy settings are optional. `DEEPSEEK_MODEL` selects the model; the example uses `deepseek-flash`. Gemini/Groq fallback is not enabled.

Credentials, local configuration, databases, backups, logs, and reports are excluded from Git. Keep applicant-specific information in `config.local.yaml`.

## Configure your search

The example searches for software engineering roles. Replace its keyword and criteria with your own profession or industry. No applicant nationality, contract type, or start-date window is built into the application.

```yaml
sources: [linkedin]
search_profiles:
  - keyword: data analyst
    location: London
    max_pages: 3
criteria:
  required:
    - The offered role must involve data analysis.
    - Reject roles explicitly requiring more than two years of experience.
preferences:
  - Prefer SQL and Python.
```

Use the full example as your starting file. Config files are **complete configurations**, not merged overlays. Selection order:

1. `--config PATH` for `main.py`.
2. The `JOBFINDER_CONFIG` environment variable.
3. `config.local.yaml`, then legacy `config.yaml`, in the working directory.
4. The bundled `config.example.yaml`.

`criteria.required` and `custom_ai_rules` contain mandatory rules. `preferences` affects ranking only. `criteria.tiers` customizes tiers 1–4; `criteria.instructions` supports an advanced free-text rubric. Optional `target.start_date` and `target.end_date` constrain start dates; `target.missing_date` selects `review` or `flexible` when a listing omits its start date.

### Supported sources

| Configuration name | Scope |
| --- | --- |
| `linkedin` | Keyword and location searches |
| `hellowork` | French job board; keyword and location searches |
| `apec` | French job board; keyword search |
| `lesjeudis` | French technology job board; keyword search |
| `francetravail` | French job board; keyword search |
| `welcome_to_the_jungle` | French site adapter; keyword and location searches |

Only LinkedIn is enabled in the example. The included adapters do not provide universal geographic coverage. APEC, LesJeudis, and France Travail do not currently apply the configured location to their search requests; specify required location in your evaluation rules as needed. Stored search locations are hints, not verified listing locations. Site changes can require adapter updates.

APEC accepts an optional `source_options.apec.contract_filter` code. No internship filter is applied by default. Search profiles run sequentially within each source; sources run concurrently.

## Run

Run commands from the project directory:

```sh
python main.py --dry-run
python main.py --once
python main.py --config config.example.yaml --dry-run
python main.py --process-only --once
python main.py
```

Dry run plans pending jobs without scraping, AI calls, job-status changes, or notifications. Database opening performs additive schema migrations. An empty database produces a zero-batch plan.

Normal runs use the configured APIs and optional Discord webhook. The scheduler scrapes every six hours and processes every 15 minutes. A `.env` file is loaded only when starting the application; importing modules for tests does not start the pipeline.

## Token controls

| Setting under `ai` | Purpose |
| --- | --- |
| `batch_input_tokens` | Maximum estimated input per request |
| `max_jobs_per_batch` | Maximum jobs packed into one request |
| `output_tokens_per_job` | Output reservation per decision, plus envelope overhead |
| `run_input_tokens` | Input ceiling per processing cycle, including retries |
| `run_output_tokens` | Output ceiling per processing cycle, including retries |
| `max_retries` | Additional attempts for unresolved results |
| `price_per_million` | Configurable rates for estimated USD costs |

If all eligible jobs fit, one request handles the list. Oversized descriptions enter REVIEW without truncation. Jobs with unresolved responses or insufficient run budget remain pending.

Planning uses **UTF-8 byte length plus overhead**, a conservative estimate rather than the provider tokenizer. Actual API input/output tokens and cache usage are stored separately. Failed calls without usage consume their full reservation and are marked estimated. These are per-cycle planning safeguards, not an exact billing guarantee or daily account cap. Update configured prices for your model and current rates.

Thinking is disabled. The model must return valid decisions for known IDs and quote source evidence for approvals/rejections. Malformed output does not become a rejection. Only unresolved records are retried.

## Review and application tracking

```sh
python manage.py dashboard
python manage.py list --status REVIEW
python manage.py list --status INVALID
python manage.py list --status APPROVED
python manage.py track JOB_ID --status applied --notes 'Sent CV'
python manage.py review JOB_ID APPROVED --tier 2 --reason 'Manually verified'
python manage.py review JOB_ID PENDING --reason 'Retry with a larger budget'
python manage.py audit
```

`track` also accepts `--deadline YYYY-MM-DD`. Application states are `saved`, `applied`, `interview`, `rejected`, and `offer`. The dashboard reports source quality, API usage, estimated costs, and notification backlog.

After editing criteria, obtain the current hash and requeue old evaluations:

```sh
python -c 'from main import criteria_version; print(criteria_version())'
python manage.py reevaluate --version HASH_FROM_PREVIOUS_COMMAND
```

Use `JOBFINDER_CONFIG` when computing a hash for a nondefault configuration. Re-evaluation queues valid, nonduplicate decisions; it does not call the API. Evaluation history is retained. Audit flags damaged descriptions and links exact-content/canonical-URL duplicates without deleting jobs. INVALID listings can be fetched again.

Discord job alerts retry on subsequent processing cycles. A crash between delivery and the database update can produce a duplicate alert. Excel summary delivery is best effort.

## Tests and contributions

```sh
python -m unittest discover -s tests -v
python -m compileall -q main.py manage.py src tests
```

Tests use temporary/in-memory databases and mock API responses. No API keys or browser installation are needed for the offline suite. GitHub Actions runs it on Python 3.11 and 3.12. Live scraping is not validated by these tests.

Keep new adapters under `src/scrapers`, implement `BaseScraper`, register supported sources, and add offline fixtures/tests for parsing changes. Keep personal examples and scraped data out of tests and commits.

## Put the project in Git

For a new repository:

```sh
git init
git add README.md requirements.txt .gitignore .env.example config.example.yaml main.py manage.py src tests .github
git diff --cached --stat
git status --short
```

Review the staged files before committing. `.gitignore` does not remove files already tracked by an existing repository. The project does not configure a remote or publish anything automatically.

After moving the project directory, use `python -m pip` with its virtual-environment interpreter. If your existing virtual environment stops working, recreate it at the new path using the setup instructions.
