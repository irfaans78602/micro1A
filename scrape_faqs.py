"""
scrape_faqs.py

Entry point. Fetches a micro1.ai interview-prep page, writes its FAQs to
a PDF, and syncs them into the micro1.dbo.faqs SQL Server table.

Usage:
    python scrape_faqs.py <page-slug>
"""

import sys
from typing import List, NoReturn

import requests
from sqlalchemy.exc import SQLAlchemyError

from scraper import fetch_html, extract_faqs
from pdf_writer import write_faqs_to_pdf
from db import replace_faqs_in_sql
from models import Faq


def _usage_and_exit() -> NoReturn:
    print("Usage: python scrape_faqs.py <page-slug>")
    print("Example: python scrape_faqs.py python-developer-interview-questions")
    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        _usage_and_exit()

    title: str = sys.argv[1]

    print(f"Fetching page for '{title}' ...")
    try:
        html: str = fetch_html(title)
    except requests.exceptions.RequestException as e:
        print(f"Error: failed to fetch page: {e}")
        sys.exit(1)

    print("Parsing FAQs ...")
    try:
        faqs: List[Faq] = extract_faqs(html)
    except Exception as e:
        print(f"Error: failed to parse FAQs from page: {e}")
        sys.exit(1)

    print(f"Found {len(faqs)} FAQs")
    if not faqs:
        print("No FAQs found on the page; nothing to write. Exiting.")
        sys.exit(1)

    output_file: str = f"{title}.pdf"

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
    except SQLAlchemyError as e:
        print(f"Error: could not connect to the database: {e}")
        sys.exit(1)

    print(f"Deleted {deleted} existing row(s) and inserted {inserted} new row(s) for title '{title}'")


if __name__ == "__main__":
    main()
