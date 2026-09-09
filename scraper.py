"""
scraper.py

Fetches a micro1.ai interview-prep page and extracts FAQ question/answer
pairs from its HTML.
"""

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.micro1.ai/interview-prep/{slug}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def fetch_html(page_slug, timeout=10):
    """
    Fetch the HTML for a given interview-prep page slug.

    Raises:
        requests.exceptions.RequestException: on any network/HTTP failure
            (connection error, timeout, non-2xx status, etc.).
    """
    url = BASE_URL.format(slug=page_slug)
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def extract_faqs(html):
    """
    Extract FAQ title/answer pairs from HTML using BeautifulSoup.
    'answer' keeps the first paragraph only (used for the PDF, unchanged).
    'answers' captures ALL paragraphs for the answer (used for the SQL insert,
    to support multiple answers per question).
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
