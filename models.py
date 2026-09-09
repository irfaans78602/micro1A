"""
models.py

Shared type definitions used across the FAQ scraping/sync pipeline.
Keeping this in one place means scraper.py, pdf_writer.py, and db.py
all agree on the exact shape of a "FAQ" without needing to import
from each other.
"""

from typing import List, Optional, TypedDict


class Faq(TypedDict):
    """
    A single scraped FAQ entry.

    question: the question text (from the <h3 class="faq_title"> tag).
              Named "question" rather than "title" to avoid confusion
              with the page title/slug (e.g. "python-developer-
              interview-questions") that this FAQ belongs to - that's
              a separate concept, passed around as page_title.
    answer:   the first <p> of the answer only - kept for backwards
              compatibility with callers that only want one paragraph
    answers:  every <p> in the answer block, in order - this is the
              field the PDF and SQL sync actually use
    """

    question: str
    answer: Optional[str]
    answers: List[str]
