import sys
import re
from bs4 import BeautifulSoup
import requests
from fpdf import FPDF
from fpdf.errors import FPDFException
import pyodbc


def extract_faqs(html):
    """
    Extract FAQ title/answer pairs from HTML using BeautifulSoup.
    'answer' keeps the first paragraph only (used for the PDF, unchanged).
    'answers' captures ALL paragraphs for the answer (used for the SQL insert,
    to support multiple answers per question).= .
    """
    soup = BeautifulSoup(html, "html.parser")
    faqs = []

    titles = soup.find_all("h3", class_="faq_title")

    for title_tag in titles:
        title = title_tag.get_text(strip=True)

        faq_item = title_tag.find_parent(class_="faq_item")
        if faq_item:
            answer_div = faq_item.find("div", class_="faq_answer")
        else:
            answer_div = title_tag.find_next("div", class_="faq_answer")

        if answer_div:
            p_tag = answer_div.find("p")
            answer = p_tag.get_text(strip=True) if p_tag else answer_div.get_text(strip=True)

            p_tags = answer_div.find_all("p")
            if p_tags:
                answers = [p.get_text(strip=True) for p in p_tags if p.get_text(strip=True)]
            else:
                answers = [answer] if answer else []
        else:
            answer = None
            answers = []

        faqs.append({"title": title, "answer": answer, "answers": answers})

    return faqs


def split_into_sentences(text):
    """
    Naive sentence splitter (splits on '. ' while avoiding common abbreviations).
    Good enough for straightforward FAQ-style answers.
    """
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    return [s.strip() for s in sentences if s.strip()]


def sanitize_text(text):
    """
    Replace common Unicode punctuation with Latin-1 safe equivalents,
    since the default Helvetica font only supports Latin-1.
    """
    if not text:
        return text

    replacements = {
        "\u2014": "-",   # em dash —
        "\u2013": "-",   # en dash –
        "\u2018": "'",   # left single quote '
        "\u2019": "'",   # right single quote '
        "\u201c": '"',   # left double quote "
        "\u201d": '"',   # right double quote "
        "\u2026": "...", # ellipsis …
        "\u2022": "-",   # bullet •
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)

    # Catch-all: strip any remaining non-Latin-1 characters
    return text.encode("latin-1", errors="ignore").decode("latin-1")


def write_faqs_to_pdf(faqs, output_file, page_title):
    """
    Write FAQ title/answer pairs to a PDF file using fpdf2.

    Raises:
        RuntimeError: if content rendering fails (e.g. a bad font/cell
            operation from unexpected data in a FAQ entry).
        OSError: if the PDF can't be written to disk (permissions,
            missing directory, disk full, etc.) - left as OSError since
            callers may want to distinguish this from content errors.
    """
    try:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        # Title
        pdf.set_font("Helvetica", "B", 16)
        pdf.multi_cell(0, 10, sanitize_text(page_title.replace("-", " ").title()))
        pdf.ln(6)

        i = 0
        for i, faq in enumerate(faqs, 1):
            question = faq.get("title") or ""
            answers = faq.get("answers") or ([faq["answer"]] if faq.get("answer") else [])

            # Question - bold
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(0, 8, sanitize_text(f"Q{i}: {question}"))
            pdf.ln(2)

            # Answer - bullet points, regular weight
            pdf.set_font("Helvetica", "", 11)
            if answers:
                for para in answers:
                    for sentence in split_into_sentences(para):
                        pdf.multi_cell(0, 7, sanitize_text(f"- {sentence}"))
                        pdf.ln(1)
            else:
                pdf.multi_cell(0, 7, sanitize_text("- N/A"))

            pdf.ln(6)  # space between Q&A blocks

    except FPDFException as e:
        raise RuntimeError(f"Failed to render PDF content (question {i}): {e}") from e
    except (KeyError, TypeError, AttributeError) as e:
        raise RuntimeError(f"Malformed FAQ data while building PDF (question {i}): {e}") from e

    try:
        pdf.output(output_file)
    except (OSError, PermissionError) as e:
        raise OSError(f"Could not write PDF to '{output_file}': {e}") from e
    except FPDFException as e:
        raise RuntimeError(f"Failed to finalize PDF output: {e}") from e


DB_CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=localhost;"
    "DATABASE=micro1;"
    "Trusted_Connection=yes;"
)


def replace_faqs_in_sql(faqs, page_title):
    """
    Delete existing rows for page_title and insert the freshly-scraped
    rows, all within a single transaction. If anything fails (connection
    drop, bad data, constraint violation, etc.), the whole operation is
    rolled back so we never end up with old rows deleted but no new rows
    written (or vice versa).

    If a question has multiple answers (multiple <p> tags), one row
    is inserted per answer, all sharing the same question_no/question.

    Returns (deleted_count, inserted_count).
    """
    insert_sql = """
        INSERT INTO faqs (title, question_no, question, answer)
        VALUES (?, ?, ?, ?)
    """

    rows = []
    for i, faq in enumerate(faqs, 1):
        question = faq["title"] or ""
        answers = faq["answers"] or [faq["answer"] or ""]

        for ans in answers:
            rows.append((page_title, i, question, ans))

    conn = None
    try:
        conn = pyodbc.connect(DB_CONN_STR, timeout=10)
        conn.autocommit = False
        cursor = conn.cursor()

        cursor.execute("DELETE FROM faqs WHERE title = ?", (page_title,))
        deleted_count = cursor.rowcount

        if rows:
            cursor.executemany(insert_sql, rows)

        conn.commit()
        cursor.close()
        return deleted_count, len(rows)

    except pyodbc.Error as e:
        if conn is not None:
            try:
                conn.rollback()
            except pyodbc.Error:
                pass
        raise RuntimeError(f"Database operation failed and was rolled back: {e}") from e

    finally:
        if conn is not None:
            conn.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: python scrape_faqs.py <page-slug>")
        print("Example: python scrape_faqs.py python-developer-interview-questions")
        sys.exit(1)

    title = sys.argv[1]

    url = f"https://www.micro1.ai/interview-prep/{title}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    print(f"Fetching {url} ...")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error: failed to fetch {url}: {e}")
        sys.exit(1)
    html = response.text

    print("Parsing FAQs ...")
    try:
        faqs = extract_faqs(html)
    except Exception as e:
        print(f"Error: failed to parse FAQs from page: {e}")
        sys.exit(1)

    print(f"Found {len(faqs)} FAQs")
    if not faqs:
        print("No FAQs found on the page; nothing to write. Exiting.")
        sys.exit(1)

    output_file = f"{title}.pdf"

    print("Writing PDF ...")
    try:
        write_faqs_to_pdf(faqs, output_file, title)
    except OSError as e:
        print(f"Error: could not write the PDF file: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"Wrote {len(faqs)} FAQs to {output_file}")

    print("Replacing rows for this title in SQL Server (delete + insert in one transaction) ...")
    try:
        deleted, inserted = replace_faqs_in_sql(faqs, title)
    except RuntimeError as e:
        print(f"Error: {e}")
        print("No changes were committed to the database.")
        sys.exit(1)
    except pyodbc.Error as e:
        print(f"Error: could not connect to the database: {e}")
        sys.exit(1)

    print(f"Deleted {deleted} existing row(s) and inserted {inserted} new row(s) for title '{title}'")


if __name__ == "__main__":
    main()