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

## Local CV workspace

After installing `requirements.txt`, run `python web.py` and open
`http://127.0.0.1:8000`. This is a local, single-user interface with protected
mutation endpoints; run only one web process. It shares `jobs.db` with the CLI.

1. Upload a PDF, DOCX or UTF-8 LaTeX (`.tex`) file, review the extracted text, and correct it.
   Move your name, address and other personal details into the private contact
   block before saving. Common email, international-phone and URL lines are
   separated automatically, but manual review is required. Empty or image-only
   PDFs need pasted text or a text-based replacement; there is no OCR.
2. Review the token estimate and start profile analysis. Review the profile and
   up to five proposed categories. Editable fields expose source fact IDs,
   rationale, role titles, gaps and strong/stretch fit. Add/remove categories,
   check “Approve this category” for the ones you want to use, and save the review.
   An advanced JSON editor is also available.
3. Generate a draft for an approved category. Review the source evidence,
   rewritten claims, change summary and preview. Save edits as new draft revisions.
   Check every factual claim and explicitly approve the revision before it can
   be recommended. Unsupported ideas belong in suggestions, which are not exported.
4. Download DOCX or PDF. Both use the same structured content and original CV
   language, with the private contact block restored locally. PDF uses a Unicode
   TrueType font; set `JOBFINDER_CV_FONT` to an installed font covering your
   language if needed. Check exported layout before sending, especially for scripts
   requiring complex shaping. The layout is single-column and paginated.
5. Classify existing approved postings from the workspace. This action does not
   reassess eligibility or send notifications. New CLI evaluations include compact
   profile/category context once per batch. Approved jobs receive the selected
   category's approved revision, or “CV awaiting approval”; ambiguous matches stay
   unassigned. Excel and Discord show the category, local filename and reason.
   CV documents are never uploaded to Discord or submitted to employers.

### LaTeX versions with your existing layout

Import a complete `.tex` file containing `\begin{document}` and `\end{document}`.
The app preserves the original document class, preamble, custom commands, formatting,
comments and layout. Tailoring changes individual prose spans in place, rather than
rebuilding the document with a different template. Short fields (60 characters or
fewer), names, labels, dates and numbers are protected; longer prose can be edited
and tailored with source evidence. Section order stays as it is in your template.

Use **Your LaTeX source and template** to correct the source, then choose **Extract
text from LaTeX edits** and save the source revision. Extracted facts must still match
the source before generation. Contact fields already in the template remain there;
edit those in the LaTeX source when they change. The private contact block controls
what is excluded from analysis and what is restored in the standard PDF/DOCX exports.
Source/template edits invalidate dependent drafts and require explicit regeneration.

Each generated revision has **Download LaTeX**. Put that file alongside your existing
class/style files, images and fonts, and compile with the same engine you use for the
original (for example, `pdflatex cv-category-2-r3.tex` or `xelatex cv-category-2-r3.tex`).
The app never executes uploaded LaTeX or reads included files. Custom macro expansions,
external `\input` files and arbitrary TeX programming are not expanded for extraction;
review the extracted facts, and inline included CV text in your main file if necessary.
The text preview and optional PDF/DOCX exports use the app’s standard layout; the `.tex`
download preserves yours. Compilation happens in your own LaTeX toolchain.

### Finding and comparing postings

The posting list searches **all stored jobs**, with filters for title/company/location,
eligibility, tier, job board, application category and CV readiness. Sort by newest,
oldest, best tier, title, company, location or category. Choose 25, 50 or 100 results
per page. Filters and sorting are preserved in the URL and across pagination and
reloads. Clear filters to return to the full list. Posting titles open the original
listing, and CV links open the corresponding revision for review and download.

Source files and exports are under ignored `private_cv/`; source text, contact
details, evidence, revisions and task history live in the ignored SQLite database.
These files are private but are not encrypted. Analysis and generation send only
the reviewed facts/profile/category to DeepSeek, not the private contact block.
Treat the database and the private directory together when backing up this workflow.

Unchanged analysis/generation inputs reuse completed results. Source/profile edits
mark dependent results stale; category edits invalidate that category's CVs. Changes
to available matching context require explicit reclassification. Editing a CV
creates a draft while leaving its prior approved revision available. A later approval
becomes the active revision and appends local posting assignments while preserving
the previous assignments in history. Awaiting-approval matches also resolve locally at approval.
Nothing regenerates automatically during scraping.

One background worker records progress and usage by operation. Failed or interrupted
tasks can be retried explicitly from their estimate button; queued work resumes after
restart. The existing `ai` budgets apply per task, including bounded retries. Usage
estimates are conservative byte-based token estimates; actual returned usage is
recorded. Long CVs may require a larger `ai.batch_input_tokens` setting. Provider
failures do not erase eligibility decisions; use posting classification to retry
matching separately.

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
# Optional full browser workflow (mocked DeepSeek; Chromium required):
JOBFINDER_BROWSER_TEST=1 python -m unittest discover -s tests -p 'test_cv_browser.py' -v
```

Tests use temporary/in-memory databases and mock API responses. No API keys or browser installation are needed for the offline suite. GitHub Actions runs it on Python 3.11 and 3.12. Live scraping is not validated by these tests.

Keep new adapters under `src/scrapers`, implement `BaseScraper`, register supported sources, and add offline fixtures/tests for parsing changes. Keep personal examples and scraped data out of tests and commits.
