Scrapes FAQ content from a micro1.ai interview-prep page, writes it to a PDF, and syncs it into a SQL Server `faqs` table.

## What it does

1. Fetches `https://www.micro1.ai/interview-prep/<page-slug>`
2. Parses out FAQ questions (`h3.faq_title`) and answers (`div.faq_answer`) with BeautifulSoup
3. Writes a formatted PDF (`<page-slug>.pdf`) with every answer paragraph as a bulleted, sentence-split list
4. Replaces existing rows for that title in `micro1.dbo.faqs` (SQL Server, Windows Auth) — deletes old rows and inserts fresh ones in a single transaction

## Requirements

- Python 3
- `beautifulsoup4`, `requests`, `fpdf2`, `pyodbc`
- ODBC Driver 17 for SQL Server installed locally
- SQL Server running on `localhost`, database `micro1`, with a `faqs` table:
  ```sql
  CREATE TABLE faqs (
      title       NVARCHAR(255),
      question_no INT,
      question    NVARCHAR(MAX),
      answer      NVARCHAR(MAX)
  );
  ```

## Usage

```
python scrape_faqs.py <page-slug>
```

Example:

```
python scrape_faqs.py python-developer-interview-questions
```

Output:
- `python-developer-interview-questions.pdf` written to the current directory
- Matching rows in `micro1.dbo.faqs` replaced (old rows for that title deleted, new ones inserted)

## Data model

Each scraped FAQ produces:
- `title` — question text
- `answer` — first paragraph only (used internally as a fallback)
- `answers` — all paragraphs under the answer (used for both PDF and SQL output)

If a question has multiple `<p>` answer paragraphs, the PDF lists them all as bullets, and SQL gets one row per paragraph (same `title`/`question_no`/`question`, different `answer`).

## Error handling

- **Fetch failures** (network/HTTP errors) print a message and exit — no partial output is written.
- **Parse failures** exit before touching the PDF or DB.
- **Empty FAQ result** exits early rather than writing a blank PDF or wiping DB rows for that title.
- **PDF writing** distinguishes two failure modes:
  - Content/rendering errors (bad data shape, fpdf cell errors) → `RuntimeError`, includes the question number where it failed.
  - File I/O errors (bad path, permissions, disk full) → `OSError`, includes the target path.
  - A malformed FAQ entry (missing keys) does *not* crash the whole PDF — it renders as a blank question with `N/A` and processing continues.
- **Database writes** are wrapped in a single transaction (`autocommit = False`): the delete and insert both succeed or both roll back. A failed insert can never leave you with deleted rows and nothing to replace them.
- All failure paths print a clear message and exit with a non-zero status; no exceptions propagate as raw tracebacks to the end user.

## Known limitations

- Sentence splitting is a naive regex (`. ` boundary before a capital letter) — may mis-split on abbreviations or decimals.
- DB connection string is hardcoded to `localhost` / Windows Authentication — not configurable via CLI or env vars yet.
- Only Latin-1-safe characters render correctly in the PDF (Helvetica font limitation); other Unicode is stripped after common punctuation substitution.