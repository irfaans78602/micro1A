"""
pdf_writer.py

Renders extracted FAQ data to a PDF file using fpdf2.
"""

import re
from typing import List, Optional

from fpdf import FPDF
from fpdf.errors import FPDFException

from models import Faq


def split_into_sentences(text: str) -> List[str]:
    """
    Naive sentence splitter (splits on '. ' while avoiding common abbreviations).
    Good enough for straightforward FAQ-style answers.
    """
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    return [s.strip() for s in sentences if s.strip()]


def sanitize_text(text: Optional[str]) -> Optional[str]:
    """
    Replace common Unicode punctuation with Latin-1 safe equivalents,
    since the default Helvetica font only supports Latin-1.
    """
    if not text:
        return text

    replacements: dict[str, str] = {
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


def write_faqs_to_pdf(faqs: List[Faq], output_file: str, page_title: str) -> None:
    """
    Write FAQ title/answer pairs to a PDF file using fpdf2.

    Raises:
        RuntimeError: if content rendering fails (e.g. a bad font/cell
            operation from unexpected data in a FAQ entry).
        OSError: if the PDF can't be written to disk (permissions,
            missing directory, disk full, etc.) - left as OSError since
            callers may want to distinguish this from content errors.
    """
    i: int = 0
    try:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        # Title
        pdf.set_font("Helvetica", "B", 16)
        pdf.multi_cell(0, 10, sanitize_text(page_title.replace("-", " ").title()))
        pdf.ln(6)

        for i, faq in enumerate(faqs, 1):
            question: str = faq.get("question") or ""
            answers: List[str] = faq.get("answers") or ([faq["answer"]] if faq.get("answer") else [])

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
