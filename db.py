"""
db.py

Syncs extracted FAQ data into the micro1.dbo.faqs SQL Server table
using SQLAlchemy, replacing existing rows for a given page title.
"""

import os

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# Connection string is read from the environment so credentials/hosts
# are never hardcoded in source. Raises if the env var isn't set.
try:
    DB_CONN_STR = os.environ["MICRO1_DB_CONN_STR"]
except KeyError as e:
    raise RuntimeError(
        "MICRO1_DB_CONN_STR environment variable is not set. "
        "Example: mssql+pyodbc://@localhost/micro1"
        "?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
    ) from e

# One engine per process; SQLAlchemy pools connections internally, so this
# is created once at import time rather than per call.
engine = create_engine(DB_CONN_STR, fast_executemany=True)


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

    Raises:
        RuntimeError: if the transaction fails and is rolled back.
    """
    delete_sql = text("DELETE FROM faqs WHERE title = :title")
    insert_sql = text(
        """
        INSERT INTO faqs (title, question_no, question, answer)
        VALUES (:title, :question_no, :question, :answer)
        """
    )

    rows = []
    for i, faq in enumerate(faqs, 1):
        question = faq["title"] or ""
        answers = faq["answers"] or [faq["answer"] or ""]

        for ans in answers:
            rows.append(
                {"title": page_title, "question_no": i, "question": question, "answer": ans}
            )

    try:
        # engine.begin() opens a connection, starts a transaction, commits
        # on a clean exit, and rolls back automatically if anything raises.
        with engine.begin() as conn:
            result = conn.execute(delete_sql, {"title": page_title})
            deleted_count = result.rowcount

            if rows:
                conn.execute(insert_sql, rows)

        return deleted_count, len(rows)

    except SQLAlchemyError as e:
        raise RuntimeError(f"Database operation failed and was rolled back: {e}") from e