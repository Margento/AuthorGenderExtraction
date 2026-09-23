"""
WEB FALLBACK RESOLVER FOR UNRESOLVED AUTHORS
=============================================

Free/local architecture:

    Author
      |
      v
    Ollama (local)
      |  tool calls
      +--> search_web() ----> local SearXNG ----> search results
      |
      +--> fetch_webpage() ---------------------> page text
      |
      v
    final structured AuthorResult

Requirements:
    - Ollama installed and running locally
    - A tool-capable Ollama model (Qwen3 is a good starting point)
    - SearXNG running locally (no search API key required)
    - pip install -U ollama pydantic httpx beautifulsoup4

SearXNG:
    By default this script expects http://127.0.0.1:8080
    Set SEARXNG_URL if it is elsewhere.

Example:
    export SEARXNG_URL="http://127.0.0.1:8080"
    export MODEL="qwen3:4b"
    python web_fallback_resolver.py

No OLLAMA_API_KEY is needed for local Ollama.
No paid search API is used.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Literal, Optional, List
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from ollama import Client, chat


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

ROOT_DIR = Path(os.getenv(
    "ROOT_DIR",
    "/Users/Raluca/Google Drive/My Drive/Lucia"
))

# Qwen3 has current Ollama tool-calling examples in the official docs.
# We can change this to another tool-capable local model.
MODEL = os.getenv("MODEL", "qwen3:4b")

SEARXNG_URL = os.getenv(
    "SEARXNG_URL",
    "http://127.0.0.1:8080"
).rstrip("/")

OUTPUT_SUFFIX = "_webresolved"
CACHE_FILENAME = "_web_fallback_cache.json"

DELAY_SECONDS = float(os.getenv("DELAY_SECONDS", "0.5"))
SEARCH_DELAY_SECONDS = float(os.getenv("SEARCH_DELAY_SECONDS", "0.5"))

DRY_RUN = False
SKIP_EXISTING_OUTPUTS = True
USE_CACHE = True

MAX_TOOL_ROUNDS = 6
MAX_SEARCH_RESULTS = 6
MAX_PAGE_CHARS = 12000
MAX_SEARCH_SNIPPET_CHARS = 3500
REQUEST_TIMEOUT = 15.0

# Keep page downloads modest and avoid sending huge documents to the model.
USER_AGENT = (
    "AuthorMetadataResolver/1.0 "
    "(local research/data-quality script)"
)

local_client = Client()


# ----------------------------------------------------------------------
# Types
# ----------------------------------------------------------------------

Gender = Literal["male", "female", "non-binary", "nonbinary", "unknown"]
Confidence = Literal["high", "medium", "low"]
IdentityConfidence = Literal["high", "medium", "low", "unknown"]
EvidenceStrength = Literal["explicit", "strong", "moderate", "weak", "none"]


MULTILINGUAL_GENDER_TERMS = {
    "masculino": "male",
    "femenino": "female",
    "no binario": "non-binary",
    "desconocido": "unknown",
    "homem": "male",
    "mulher": "female",
    "não binário": "non-binary",
    "desconhecido": "unknown",
    "mascle": "male",
    "femella": "female",
    "no binari": "non-binary",
    "desconegut": "unknown",
    "gizona": "male",
    "emakumea": "female",
    "ez binario": "non-binary",
    "ezezaguna": "unknown",
}


class Source(BaseModel):
    title: str = ""
    url: str
    content: str = ""


class Evidence(BaseModel):
    url: str
    title: str = ""
    source_type: str = ""
    relevant_evidence: str = ""
    evidence_strength: EvidenceStrength = "none"


class AuthorResult(BaseModel):
    author: str
    gender: Gender
    confidence: Confidence
    identity_confidence: IdentityConfidence
    identity_explanation: str
    evidence_strength: EvidenceStrength
    evidence: List[Evidence] = Field(default_factory=list)
    explanation: str
    searched_nation: str = ""
    status: Literal["resolved", "unknown", "error"] = "unknown"


# ----------------------------------------------------------------------
# Cache / file helpers
# ----------------------------------------------------------------------

def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(path: Path, cache: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def is_candidate_file(path: Path) -> bool:
    if path.suffix.lower() != ".json":
        return False
    name = path.name.casefold()
    return (
        ("inconclusive" in name) or ("failed" in name)
        and not name.endswith(f"{OUTPUT_SUFFIX}.json")
        and name != CACHE_FILENAME
    )


def find_candidate_files(root: Path) -> List[Path]:
    return sorted(
        p for p in root.rglob("*.json")
        if is_candidate_file(p)
        and not p.name.endswith(f"{OUTPUT_SUFFIX}.json")
        and p.name != CACHE_FILENAME
    )


def load_author_records(path: Path) -> List[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"    ERROR reading {path}: {e}")
        return []

    if not isinstance(data, list):
        print(f"    Skipping {path}: JSON root is not a list.")
        return []

    return [
        item for item in data
        if isinstance(item, dict) and isinstance(item.get("author"), str)
    ]


def get_nation_from_path(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
        if len(rel.parts) >= 2:
            return rel.parts[-2]
    except ValueError:
        pass
    return path.parent.name


# ----------------------------------------------------------------------
# Web tools
# ----------------------------------------------------------------------

def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def _valid_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def search_web(query: str, nation: str = "") -> str:
    """
    Search the web through the local SearXNG instance.

    Args:
        query: A concise web-search query.
        nation: Optional country/nation context.

    Returns:
        JSON containing title, URL and search-result snippet for each result.
    """
    query = _clean_text(query)
    if not query:
        return json.dumps({"error": "Empty search query"})

    # The model may omit nation when it is already present in the query.
    if nation and nation.casefold() not in query.casefold():
        query = f"{query} {nation}"

    print(f"      WEB SEARCH: {query}")

    try:
        response = httpx.get(
            f"{SEARXNG_URL}/search",
            params={
                "q": query,
                "format": "json",
                "language": "all",
                "safesearch": 1,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return json.dumps({
            "error": f"SearXNG request failed: {e}",
            "query": query,
        })

    results = []
    seen = set()

    for item in data.get("results", []):
        url = item.get("url") or item.get("link")
        if not url or not _valid_http_url(url) or url in seen:
            continue

        seen.add(url)
        results.append({
            "title": _clean_text(item.get("title", "")),
            "url": url,
            "content": _clean_text(
                item.get("content", "")
            )[:MAX_SEARCH_SNIPPET_CHARS],
            "source": item.get("engine", ""),
        })

        if len(results) >= MAX_SEARCH_RESULTS:
            break

    time.sleep(SEARCH_DELAY_SECONDS)

    return json.dumps(
        {"query": query, "results": results},
        ensure_ascii=False,
    )


def fetch_webpage(url: str) -> str:
    """
    Download and extract readable text from one web page.

    Args:
        url: The HTTP/HTTPS URL returned by web search.

    Returns:
        JSON containing the URL, page title and extracted text.
    """
    if not _valid_http_url(url):
        return json.dumps({"error": "Invalid HTTP/HTTPS URL"})

    print(f"      FETCH PAGE: {url}")

    try:
        response = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type and "text/plain" not in content_type:
            return json.dumps({
                "url": url,
                "error": f"Unsupported content type: {content_type}",
            })

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup([
            "script", "style", "noscript", "svg",
            "nav", "footer", "header", "form"
        ]):
            tag.decompose()

        title = _clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
        text = _clean_text(soup.get_text(" ", strip=True))

        return json.dumps({
            "url": url,
            "title": title,
            "content": text[:MAX_PAGE_CHARS],
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({
            "url": url,
            "error": f"Page fetch failed: {e}",
        })


AVAILABLE_TOOLS = {
    "search_web": search_web,
    "fetch_webpage": fetch_webpage,
}


# ----------------------------------------------------------------------
# Research prompt
# ----------------------------------------------------------------------

def build_research_prompt(author: str, nation: str) -> str:
    return f"""
You are a cautious bibliographic data-quality assistant.

AUTHOR: {author}
NATION: {nation}

Your task is to investigate whether reliable public web evidence establishes
the author's gender.

You have two tools:
1. search_web(query, nation) — search the web through SearXNG.
2. fetch_webpage(url) — retrieve readable text from a promising result.

RESEARCH RULES:
- You may make multiple searches when identity is ambiguous.
- Prefer authoritative or biographical sources.
- Try to establish that the person in the source is actually the same author.
- Do NOT infer gender from the author's name.
- Do NOT infer gender from photographs, appearance, pronouns guessed from context,
  statistics, nationality, or occupation.
- Accept gender only when a source explicitly establishes it or provides clear
  linguistic evidence that directly identifies the person's gender.
- If identity is uncertain, return unknown.
- If evidence is insufficient, return unknown.
- Do not manufacture URLs or evidence.
- Keep track of the exact URLs from which evidence came.
- Search results can be in English, Spanish, Portuguese, Catalan, Basque or
  other languages.
- Return gender labels only as male, female, non-binary, or unknown.

IMPORTANT:
You are allowed to search more than once. Use fetch_webpage on the strongest
candidate sources when snippets alone are insufficient.

When you have enough evidence, stop researching and provide the final answer.
"""


# ----------------------------------------------------------------------
# Ollama agent loop
# ----------------------------------------------------------------------

def investigate_author(author: str, nation: str) -> AuthorResult:
    messages = [{
        "role": "user",
        "content": build_research_prompt(author, nation),
    }]

    tools = [search_web, fetch_webpage]

    for round_no in range(1, MAX_TOOL_ROUNDS + 1):
        print(f"      Ollama research round {round_no}/{MAX_TOOL_ROUNDS}")

        response = local_client.chat(
            model=MODEL,
            messages=messages,
            tools=tools,
            think=True,
        )

        messages.append(response.message)

        tool_calls = response.message.tool_calls or []

        if not tool_calls:
            break

        for tool_call in tool_calls:
            name = tool_call.function.name
            function = AVAILABLE_TOOLS.get(name)

            if function is None:
                result = json.dumps({
                    "error": f"Unknown tool requested: {name}"
                })
            else:
                try:
                    result = function(**tool_call.function.arguments)
                except Exception as e:
                    result = json.dumps({
                        "error": f"Tool execution failed: {e}"
                    })

            messages.append({
                "role": "tool",
                "tool_name": name,
                "content": str(result),
            })

    # Final pass: no tools, strict Pydantic JSON output.
    final_prompt = """
Using only the web-search and webpage evidence present in the conversation,
produce the final AuthorResult.

Be conservative:
- unknown is preferable to an unsupported conclusion;
- identity must be sufficiently established;
- every Evidence.url must be an exact URL that appeared in the tool results;
- do not invent sources;
- gender labels must be English only.

Return only the requested structured result.
"""

    messages.append({
        "role": "user",
        "content": final_prompt,
    })

    final_response = local_client.chat(
        model=MODEL,
        messages=messages,
        format=AuthorResult.model_json_schema(),
        options={"temperature": 0},
    )

    result = AuthorResult.model_validate_json(
        final_response.message.content
    )

    # Hard safety check: evidence URLs must have appeared in our tool output.
    allowed_urls = set()
    for message in messages:
        if message.get("role") != "tool":
            continue

        try:
            payload = json.loads(message.get("content", ""))
        except Exception:
            continue

        if isinstance(payload, dict):
            url = payload.get("url")
            if url:
                allowed_urls.add(url)

            for item in payload.get("results", []):
                if isinstance(item, dict) and item.get("url"):
                    allowed_urls.add(item["url"])

    result.evidence = [
        e for e in result.evidence
        if e.url in allowed_urls
    ]

    # Conservative identity handling.
    if result.identity_confidence in {"low", "unknown"}:
        result.gender = "unknown"
        result.status = "unknown"
    elif result.gender == "unknown":
        result.status = "unknown"
    else:
        result.status = "resolved"

    result.searched_nation = nation
    return result


# ----------------------------------------------------------------------
# Process one file
# ----------------------------------------------------------------------

def process_file(path: Path, root: Path, cache: dict) -> dict:
    print(f"\nProcessing: {path}")

    nation = get_nation_from_path(path, root)
    records = load_author_records(path)

    if not records:
        print("No usable author records.")
        return {"processed": 0, "resolved": 0, "unknown": 0, "errors": 0}

    output_path = path.with_name(path.stem + OUTPUT_SUFFIX + path.suffix)

    if SKIP_EXISTING_OUTPUTS and output_path.exists():
        print(f"Output already exists: {output_path}")
        return {"processed": 0, "resolved": 0, "unknown": 0, "errors": 0}

    output_records = []
    counts = {"processed": 0, "resolved": 0, "unknown": 0, "errors": 0}

    local_results: dict[str, AuthorResult] = {}

    for i, record in enumerate(records, 1):
        author = record["author"]
        print(f"\n[{i}/{len(records)}] {author}")

        if DRY_RUN:
            enriched = dict(record)
            enriched["web_fallback"] = {
                "author": author,
                "status": "dry_run",
                "searched_nation": nation,
            }
            output_records.append(enriched)
            continue

        # Same author appearing multiple times in one file.
        if author in local_results:
            result = local_results[author]
            print("    Reusing result.")
        else:
            # Persistent cache keyed by author + nation.
            cache_key = f"{nation}::{author}"

            if USE_CACHE and cache_key in cache:
                try:
                    result = AuthorResult.model_validate(cache[cache_key])
                    print("    Reusing persistent cache.")
                except Exception:
                    result = investigate_author(author, nation)
            else:
                try:
                    result = investigate_author(author, nation)
                except Exception as e:
                    print(f"      LLM investigation failed: {e}")
                    result = AuthorResult(
                        author=author,
                        gender="unknown",
                        confidence="low",
                        identity_confidence="unknown",
                        identity_explanation="Evaluation error",
                        evidence_strength="none",
                        evidence=[],
                        explanation=f"Error: {e}",
                        searched_nation=nation,
                        status="error",
                    )

            if USE_CACHE:
                cache[cache_key] = result.model_dump()

        local_results[author] = result

        enriched = dict(record)
        enriched["web_fallback"] = result.model_dump()
        output_records.append(enriched)

        counts["processed"] += 1

        if result.status == "resolved":
            counts["resolved"] += 1
        elif result.status == "error":
            counts["errors"] += 1
        else:
            counts["unknown"] += 1

        print(
            f"    Result: {result.gender} "
            f"({result.confidence} confidence; "
            f"identity {result.identity_confidence})"
        )

        time.sleep(DELAY_SECONDS)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output_records, f, ensure_ascii=False, indent=2)

    print(f"\nSaved: {output_path}")
    return counts


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> None:
    if not ROOT_DIR.exists():
        raise FileNotFoundError(f"ROOT_DIR does not exist: {ROOT_DIR}")

    cache_path = ROOT_DIR / CACHE_FILENAME
    cache = load_cache(cache_path) if USE_CACHE else {}

    candidate_files = find_candidate_files(ROOT_DIR)
    print(f"\nFound {len(candidate_files)} candidate files")
    print(f"Ollama model: {MODEL}")
    print(f"SearXNG: {SEARXNG_URL}")

    total_counts = {
        "processed": 0,
        "resolved": 0,
        "unknown": 0,
        "errors": 0,
    }

    for path in candidate_files:
        counts = process_file(path, ROOT_DIR, cache)

        for key in total_counts:
            total_counts[key] += counts[key]

        if USE_CACHE:
            save_cache(cache_path, cache)

    print("\nFINAL SUMMARY")
    print(f"Authors processed: {total_counts['processed']}")
    print(f"Resolved: {total_counts['resolved']}")
    print(f"Unknown: {total_counts['unknown']}")
    print(f"Errors: {total_counts['errors']}")
    print(f"Cache entries: {len(cache)}")


if __name__ == "__main__":
    main()
