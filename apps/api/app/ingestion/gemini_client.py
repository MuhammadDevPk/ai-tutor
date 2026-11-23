import base64
import json
import os
from typing import Any, Protocol

import httpx

from app.config import settings
from app.ingestion.parser import ParsedPage


class GeminiClient(Protocol):
    """Protocol for Gemini extraction and vision fallback."""

    def extract_tree(self, pages: list[ParsedPage]) -> dict[str, Any]:
        """Extracts a structured hierarchical syllabus tree from parsed pages."""
        ...

    def vision_extract_text(self, page_image_png: bytes, page_number: int) -> str:
        """Extracts text and math formulas from a rendered page image."""
        ...


def _clean_no_proxy_ipv6() -> None:
    """Defensive cleaner for httpx IPv6 port parsing bug with no_proxy."""
    for var in ("NO_PROXY", "no_proxy"):
        val = os.environ.get(var)
        if val:
            os.environ[var] = ",".join(
                p.strip() for p in val.split(",") if ":" not in p and p.strip()
            )


class HttpGeminiClient:
    """Client for Google Gemini API via generativelanguage.googleapis.com."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self.timeout = timeout
        _clean_no_proxy_ipv6()

    def _get_url(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    def _strip_code_fences(self, text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        return cleaned

    def extract_tree(self, pages: list[ParsedPage]) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        _clean_no_proxy_ipv6()
        page_summaries = []
        for p in pages:
            # Send sample text from each page to extract outline
            sample = p.markdown[:1500] if p.markdown else "[Scanned/visual content]"
            page_summaries.append(f"--- Page {p.page_number} ---\n{sample}")
        doc_text = "\n\n".join(page_summaries)

        prompt = (
            "You are an expert curriculum architect. Analyze the provided document "
            "pages and extract a hierarchical syllabus tree of chapters and "
            "subtopics.\n\n"
            "Requirements:\n"
            "1. Output ONLY a valid JSON object matching this exact schema:\n"
            "{\n"
            '  "chapters": [\n'
            "    {\n"
            '      "title": "string",\n'
            '      "level": 1,\n'
            '      "page_start": 1,\n'
            '      "page_end": 2,\n'
            '      "children": [\n'
            "        {\n"
            '          "title": "string",\n'
            '          "level": 2,\n'
            '          "page_start": 1,\n'
            '          "page_end": 1,\n'
            '          "children": []\n'
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "2. Each node must have title, level (integer starting at 1 for chapters), "
            "page_start (integer, 1-indexed), page_end (integer, 1-indexed), and "
            "children (list of nodes).\n"
            "3. Do not include markdown code fences or explanations. "
            "Return pure JSON only.\n\n"
            f"Document text:\n{doc_text}"
        )

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self._get_url(), json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("No response candidates returned by Gemini API")

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise ValueError("Empty candidate content returned by Gemini API")

        raw_text = parts[0].get("text", "")
        cleaned_json = self._strip_code_fences(raw_text)
        parsed: dict[str, Any] = json.loads(cleaned_json)
        return parsed

    def vision_extract_text(self, page_image_png: bytes, page_number: int) -> str:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        _clean_no_proxy_ipv6()
        b64_image = base64.b64encode(page_image_png).decode("utf-8")
        prompt = (
            f"Extract all readable text, formulas, diagrams, and titles from this "
            f"page image (Page {page_number}).\n"
            "Preserve all mathematical expressions as raw LaTeX syntax ($$...$$ "
            "for display equations, $...$ for inline expressions). Return clean "
            "markdown only, without code blocks or meta commentary."
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": b64_image,
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
            },
        }

        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self._get_url(), json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            return ""

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return ""

        raw_text = str(parts[0].get("text", ""))
        return str(raw_text.strip())


class FakeGeminiClient:
    """Deterministic fake Gemini client for testing with zero network requests."""

    def __init__(
        self,
        canned_tree: dict[str, Any] | None = None,
        canned_vision_text: str | None = None,
    ):
        self.canned_tree = canned_tree or {
            "chapters": [
                {
                    "title": "Descriptive Statistics",
                    "level": 1,
                    "page_start": 1,
                    "page_end": 1,
                    "children": [
                        {
                            "title": "Measures of Dispersion",
                            "level": 2,
                            "page_start": 1,
                            "page_end": 1,
                            "children": [],
                        }
                    ],
                },
                {
                    "title": "Probability Foundations",
                    "level": 1,
                    "page_start": 2,
                    "page_end": 3,
                    "children": [
                        {
                            "title": "Addition Rule",
                            "level": 2,
                            "page_start": 2,
                            "page_end": 2,
                            "children": [],
                        },
                        {
                            "title": "Visual Representations",
                            "level": 2,
                            "page_start": 3,
                            "page_end": 3,
                            "children": [],
                        },
                    ],
                },
            ]
        }
        self.canned_vision_text = canned_vision_text or (
            "# Figure 1.1: Standard Normal Distribution\n\n"
            "The standard normal density function is defined as:\n\n"
            "$$\\phi(z) = \\frac{1}{\\sqrt{2\\pi}} e^{-\\frac{z^2}{2}}$$\n\n"
            "Total area under the curve equals 1."
        )

    def extract_tree(self, pages: list[ParsedPage]) -> dict[str, Any]:
        return self.canned_tree

    def vision_extract_text(self, page_image_png: bytes, page_number: int) -> str:
        return self.canned_vision_text


def get_gemini_client() -> GeminiClient | None:
    """FastAPI dependency: returns HttpGeminiClient if GEMINI_API_KEY is configured,

    else None.
    """
    if settings.GEMINI_API_KEY:
        return HttpGeminiClient(
            api_key=settings.GEMINI_API_KEY,
            model=settings.GEMINI_MODEL,
        )
    return None
