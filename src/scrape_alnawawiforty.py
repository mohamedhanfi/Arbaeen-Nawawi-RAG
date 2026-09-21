"""
Web scraping for https://alnawawiforty.com/
Scrapes hadith 1..42 (nass + sharh + rawi bio + audio + youtube).

Usage:
    python src/scrape_alnawawiforty.py
    python src/scrape_alnawawiforty.py --output data/alnawawiforty_website.json
    python src/scrape_alnawawiforty.py --start 1 --end 5 --delay 0.5 --output test.json

Output JSON: list of dicts with keys:
    hadith_number, title, id_label, hadith_text, sharh, rawi_bio,
    audio_url, video_embed_url, youtube_id, source_url, page_title

Requires: requests, beautifulsoup4, lxml
    pip install requests beautifulsoup4 lxml
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://alnawawiforty.com/hadith-{n}.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (Arbaeen-Nawawi-RAG research)"}


def _one_line(text: str) -> str:
    """Single-line field: collapse all whitespace, drop site artifacts."""
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"^(?:rn|nn)+\s*", "", text)  # stray markers at start (e.g. hadith 12)
    text = text.replace("nn", " ")
    return re.sub(r"\s+", " ", text).strip()


def _clean_paras(text: str) -> str:
    """Paragraph-preserving clean.

    The site uses literal 'nn' as paragraph breaks: each chunk becomes
    its own paragraph joined by a blank line, so Arabic reads in
    paragraphs instead of one giant wall of text.
    """
    raw = re.sub(r"\s+", " ", text or "").strip()
    raw = re.sub(r"^(?:rn|nn)+\s*", "", raw)
    paras = [re.sub(r"\s+", " ", p).strip() for p in raw.split("nn")]
    paras = [p for p in paras if p]
    return "\n\n".join(paras)


def parse_page(n: int, html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    def get_text(selector: str) -> str:
        el = soup.select_one(selector)
        return _clean_paras(el.get_text(" ", strip=True)) if el else ""

    def get_attr(selector: str, attr: str) -> str:
        el = soup.select_one(selector)
        return el[attr].strip() if el is not None and el.has_attr(attr) else ""

    def get_one(selector: str) -> str:
        el = soup.select_one(selector)
        return _one_line(el.get_text(" ", strip=True)) if el else ""

    title = get_one("#alhadith label[for=title]") or get_one(".hed_title label[for=title]")
    video_src = get_attr("#video iframe", "src")
    m = re.search(r"(?:embed/|v=|youtu\.be/)([\w-]{6,})", video_src)

    return {
        "hadith_number": n,
        "title": title,
        "id_label": get_one("#alhadith label[for=id]"),
        "hadith_text": get_text("#alhadith .textContent h2"),
        "sharh": get_text("#s_alhadith .textContent h2"),
        "rawi_bio": get_text("#t_alhadith .textContent h2"),
        "audio_url": get_attr("#video audio", "src"),
        "video_embed_url": video_src,
        "youtube_id": m.group(1) if m else "",
        "source_url": url,
        "page_title": _one_line(soup.title.get_text(" ", strip=True)) if soup.title else "",
    }


def scrape_range(start: int = 1, end: int = 42, delay: float = 0.4) -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)
    results: list[dict] = []
    for n in range(start, end + 1):
        url = BASE_URL.format(n=n)
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            r.encoding = "utf-8"
            item = parse_page(n, r.text, url)
            if not item["hadith_text"]:
                print(f"WARNING hadith {n}: empty text", file=sys.stderr)
            results.append(item)
            print(f"OK {n} text={len(item['hadith_text'])} sharh={len(item['sharh'])} rawi={len(item['rawi_bio'])}")
        except Exception as e:  # keep going, record failure
            print(f"FAIL {n} {url}: {e!r}", file=sys.stderr)
            results.append({"hadith_number": n, "source_url": url, "error": str(e)})
        time.sleep(delay)
    return results


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Scrape alnawawiforty.com 42 hadith")
    ap.add_argument("--output", default="data/alnawawiforty_website.json", help="Output JSON path")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=42)
    ap.add_argument("--delay", type=float, default=0.4, help="Delay between requests (sec)")
    args = ap.parse_args()

    data = scrape_range(args.start, args.end, args.delay)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    failed = sum(1 for x in data if "error" in x)
    print(f"Saved {len(data)} items ({failed} failed) -> {out}")


if __name__ == "__main__":
    main()
