# micro1 FAQ Scraper

A command-line pipeline that scrapes the FAQ section of a [micro1.ai](https://www.micro1.ai) interview-prep page, renders the FAQs to a PDF, and syncs them into a SQL Server table (`dbo.faqs`).

Given a page slug, the pipeline:

1. Downloads the page HTML (`scraper.py`)
2. Parses out question/answer pairs (`scraper.py`)
3. Writes them to a formatted PDF (`pdf_writer.py`)
4. Replaces that page's rows in SQL Server inside a single transaction (`db.py`)

All steps are orchestrated by `scrape_faqs.py`, and the sync can also run automatically via a GitHub Actions workflow on a self-hosted runner.

---

## Project structure

```
micro1A/
├── .github/
│   └── workflows/
│       └── sync-faqs.yml     # CI/CD: runs the sync on push to main
├── .venv/                    # local virtual environment (not committed)
├── .gitattributes
├── .gitignore
├── db.py                     # SQL Server sync
├── models.py                 # shared Faq TypedDict
├── pdf_writer.py             # PDF rendering
├── requirements.txt          # pinned Python dependencies
├── scrape_faqs.py            # CLI entry point
├── scraper.py                # HTML fetch + parse
└── set_db_conn_str.ps1       # PowerShell helper to set MICRO1_DB_CONN_STR locally
```

- **`requirements.txt`** — pins the dependencies listed under [Setup](#setup) (`requests`, `beautifulsoup4`, `fpdf2`, `sqlalchemy`, `pyodbc`) so both local runs and the CI runner install the same versions.
- **`set_db_conn_str.ps1`** — a PowerShell script for setting the `MICRO1_DB_CONN_STR` environment variable on a local Windows machine, so the connection string doesn't have to be typed out manually before every run.
- **`.venv/`** — local Python virtual environment; excluded from version control via `.gitignore`.

---

## Architecture

```
scrape_faqs.py   ← entry point / CLI
    ├── scraper.py      → fetch_html(), extract_faqs()
    ├── pdf_writer.py   → write_faqs_to_pdf()
    ├── db.py           → replace_faqs_in_sql()
    └── models.py       → Faq (shared TypedDict)
```

`models.py` defines the single shared data shape (`Faq`) so `scraper.py`, `pdf_writer.py`, and `db.py` never need to import from one another directly — they all agree on the contract through `models.py`.

---

## Module reference

### `models.py`

Defines the `Faq` TypedDict used everywhere else in the pipeline:

| Field       | Type            | Description |
|-------------|-----------------|-------------|
| `question`  | `str`           | The FAQ question text, from `<h3 class="faq_title">`. |
| `answer`    | `Optional[str]` | The **first** `<p>` of the answer only. Kept for backwards compatibility with callers that only need one paragraph. |
| `answers`   | `List[str]`     | **Every** `<p>` in the answer block, in order. This is the field actually used by the PDF writer and the SQL sync. |

### `scraper.py`

- **`fetch_html(page_slug, timeout=10)`** — GETs `https://www.micro1.ai/interview-prep/{slug}`, sets a browser-like `User-Agent`, raises `requests.exceptions.RequestException` on any network/HTTP failure.
- **`extract_faqs(html)`** — Parses the HTML with BeautifulSoup:
  - Finds every `<h3 class="faq_title">` as a question.
  - Locates the matching `<div class="faq_answer">` (via the enclosing `.faq_item`, falling back to `find_next` if no wrapper is found).
  - Collects **all** `<p>` tags in the answer block into `answers`, and keeps the first one separately as `answer`.
  - Returns a `List[Faq]`.

### `pdf_writer.py`

- **`write_faqs_to_pdf(faqs, output_file, page_title)`** — Renders the FAQ list to a PDF using `fpdf2`:
  - Page title is derived from the slug (`-` → space, title-cased) and rendered as a bold H1.
  - Each question is rendered bold as `Q{n}: {question}`.
  - Each answer paragraph is split into sentences (`split_into_sentences`) and rendered as bullet points.
  - **`sanitize_text`** replaces common Unicode punctuation (smart quotes, em/en dashes, ellipsis, bullets) with Latin-1-safe equivalents, then strips anything else non-Latin-1, since the built-in Helvetica font only supports Latin-1.
  - Raises `RuntimeError` on content-rendering failures (bad/malformed FAQ data) and `OSError` if the file can't be written to disk (permissions, missing directory, disk full).

### `db.py`

- **`replace_faqs_in_sql(faqs, page_title)`** — Syncs scraped FAQs into SQL Server via SQLAlchemy:
  - Reads the connection string from the `MICRO1_DB_CONN_STR` environment variable (raises `RuntimeError` at import time if it's missing — credentials/hosts are never hardcoded).
  - Uses a single `create_engine(..., fast_executemany=True)` per process; SQLAlchemy pools connections internally.
  - Inside one transaction (`engine.begin()`):
    1. `DELETE FROM faqs WHERE title = :title`
    2. Bulk `INSERT` of the freshly scraped rows.
  - If a question has multiple `answers`, **one row is inserted per answer**, all sharing the same `question_no` and `question` text.
  - If anything fails partway (connection drop, constraint violation, bad data), the whole transaction is rolled back automatically — you never end up with old rows deleted but no new rows written, or vice versa.
  - Returns `(deleted_count, inserted_count)`; wraps any `SQLAlchemyError` in a `RuntimeError`.

### `scrape_faqs.py`

CLI entry point:

```bash
python scrape_faqs.py <page-slug>
# e.g.
python scrape_faqs.py python-developer-interview-questions
```

Flow:

1. Fetch HTML → parse FAQs → exit(1) with a message on failure at either step.
2. Exit(1) if zero FAQs were found (nothing to write).
3. Write PDF to `<page-slug>.pdf` in the current directory.
4. Replace rows in SQL Server for that title, printing the deleted/inserted counts.

Every stage prints a status line and fails fast with a clear error message and non-zero exit code, so it's safe to run as a scheduled/batch job.

---

## Setup

### Dependencies

```bash
pip install requests beautifulsoup4 fpdf2 sqlalchemy pyodbc
```

You'll also need the appropriate ODBC driver installed on the host (e.g. "ODBC Driver 17 for SQL Server").

### Environment variables

| Variable               | Required | Description |
|-------------------------|----------|--------------|
| `MICRO1_DB_CONN_STR`   | Yes      | SQLAlchemy connection string for the `micro1` database. Example: `mssql+pyodbc://@localhost/micro1?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes` |

The app will not start (raises `RuntimeError` at import) if this variable isn't set — this is intentional, to avoid ever falling back to a hardcoded connection string.

---

## Database schema

The pipeline writes to `dbo.faqs` in SQL Server. Table definition:

```sql
CREATE TABLE [dbo].[faqs](
	[Id] [int] IDENTITY(1,1) NOT NULL,
	[title] [varchar](256) NULL,
	[question_no] [int] NULL,
	[question] [varchar](1024) NULL,
	[answer] [varchar](4096) NULL,
	[last_updated] [datetime] NOT NULL,
 CONSTRAINT [PK_faqs] PRIMARY KEY CLUSTERED 
(
	[Id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Index [ix_faqs_title]    Script Date: 2026/09/09 20:10:04 ******/
CREATE NONCLUSTERED INDEX [ix_faqs_title] ON [dbo].[faqs]
(
	[title] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, SORT_IN_TEMPDB = OFF, DROP_EXISTING = OFF, ONLINE = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
GO
ALTER TABLE [dbo].[faqs] ADD  CONSTRAINT [DF_faqs_last_updated]  DEFAULT (getdate()) FOR [last_updated]
GO
```

Notes on the schema:

- **`Id`** — surrogate primary key, clustered index, auto-incrementing.
- **`title`** — the page slug passed on the command line (e.g. `python-developer-interview-questions`). Indexed (`ix_faqs_title`) since `replace_faqs_in_sql` filters and deletes by this column on every run.
- **`question_no`** — 1-based position of the question on the page, used to group multiple answer rows (see below) back under the same question.
- **`question`** / **`answer`** — the FAQ text. `answer` holds one paragraph per row.
- **`last_updated`** — defaults to `GETDATE()` at the database level (`DF_faqs_last_updated`), so it's stamped automatically on insert without the application needing to set it.

**Multi-paragraph answers:** if a question's answer block contains multiple `<p>` tags, `db.py` inserts **one row per paragraph**, all sharing the same `title` and `question_no`. Consumers reconstructing the full answer for a question should query `WHERE title = :title AND question_no = :n ORDER BY Id` and concatenate the `answer` values in order.

---

## Data flow example

For a page with 2 FAQs, where the second question has a 2-paragraph answer:

| Id | title | question_no | question | answer |
|----|-------|-------------|----------|--------|
| 1  | python-developer-interview-questions | 1 | What is a decorator? | A decorator is a function that wraps another function... |
| 2  | python-developer-interview-questions | 2 | What is the GIL? | The GIL is a mutex that protects access to Python objects... |
| 3  | python-developer-interview-questions | 2 | What is the GIL? | It means only one thread executes Python bytecode at a time... |

Running the script again for the same slug **deletes all rows where `title = 'python-developer-interview-questions'`** and re-inserts fresh rows in the same transaction, so re-scraping a page is idempotent and never leaves stale or duplicate data.

---

## Error handling summary

| Failure point | Behavior |
|----------------|----------|
| `MICRO1_DB_CONN_STR` not set | `RuntimeError` at import time, before anything runs |
| Network/HTTP error fetching the page | Caught in `scrape_faqs.py`, prints error, exits 1 |
| Parsing failure | Caught, prints error, exits 1 |
| Zero FAQs found | Prints message, exits 1 (nothing written) |
| PDF write failure (disk/permissions) | `OSError`, caught, exits 1 |
| PDF content rendering failure (bad data) | `RuntimeError`, caught, exits 1 |
| SQL failure mid-transaction | Full rollback (delete + insert never partially applied), `RuntimeError`, exits 1 |
| SQL connection failure | `SQLAlchemyError`, caught, exits 1 |

---

## Usage

### Manual (local)

```bash
export MICRO1_DB_CONN_STR="mssql+pyodbc://@localhost/micro1?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
python scrape_faqs.py python-developer-interview-questions
```

On Windows, `set_db_conn_str.ps1` can be used to set `MICRO1_DB_CONN_STR` for the current session instead of typing the connection string out by hand.

Expected output:

```
Fetching page for 'python-developer-interview-questions' ...
Parsing FAQs ...
Found 12 FAQs
Writing PDF ...
Wrote 12 FAQs to python-developer-interview-questions.pdf
Replacing rows for this title in SQL Server (delete + insert in one transaction) ...
Deleted 12 existing row(s) and inserted 14 new row(s) for title 'python-developer-interview-questions'
```

### Automated (CI/CD)

The sync also runs via GitHub Actions, defined in `.github/workflows/sync-faqs.yml`:

| Aspect | Detail |
|---|---|
| **Triggers** | Push to `main`, or manually via `workflow_dispatch`. |
| **Runner** | `self-hosted` — a runner agent installed on your own machine (registered under repo **Settings → Actions → Runners**), so the job can reach a local SQL Server instance that isn't publicly accessible. |
| **Secret** | `MICRO1_DB_CONN_STR` is stored as a repository secret (**Settings → Secrets and variables → Actions**) and injected as an environment variable — the connection string is never committed to the repo. |
| **Steps** | Check out the repo → set up Python 3.11 → `pip install -r requirements.txt` → `python scrape_faqs.py python-developer-interview-questions`. |
| **ODBC driver** | No install step is needed in the workflow itself, since the self-hosted runner is the same Windows machine already configured with ODBC Driver 17 for SQL Server for manual runs. |

Because the workflow currently hardcodes a single slug (`python-developer-interview-questions`) in its final step, syncing additional pages means either adding more `run` steps for each slug or parameterizing the workflow (e.g. via `workflow_dispatch` inputs) to accept a slug at trigger time.
