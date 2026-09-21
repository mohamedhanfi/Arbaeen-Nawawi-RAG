"""
Build clean hadith JSON from website scrape + book page numbers.

Inputs:
    data/alnawawiforty_website.json  (output of src/scrape_alnawawiforty.py)
    data/hadith_extraction.json      (old OCR file — used ONLY for `pages`)

Output (default):
    data/hadith_extraction_clean.json  — list of dicts:
        hadith_number, id_label, title, narrator, hadith_text,
        source, sharh, rawi_bio, pages, page_title

Usage:
    python src/build_hadith_json.py
    python src/build_hadith_json.py --output data/hadith_extraction_clean.json
"""

import argparse
import json
import re
from pathlib import Path

TASH = re.compile(r'[\u064B-\u0652\u0640]')

OLD_FALLBACK_SOURCE = {}  # filled from old file when website has no source


def strip_tash(s: str) -> str:
    return TASH.sub('', s or '')


def clean_spaces(s: str) -> str:
    """Collapse whitespace inside ONE paragraph (newlines become spaces)."""
    s = re.sub(r'\s+', ' ', s or '').strip()
    s = re.sub(r'\s*،\s*', '، ', s)
    s = re.sub(r'([.،؛:؟!])\s*\1+', r'\1', s)  # collapse doubled punctuation: ، ، -> ،
    s = re.sub(r'\s+([.،؛:؟!])', r'\1', s)  # attach punctuation: كلمة . -> كلمة.
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def clean_paras(s: str) -> str:
    """Flatten to one flowing line.

    The site's 'nn' breaks split mid-sentence all over the place, so
    keeping them as \\n fills the text with junk newlines. A single
    clean flowing string reads better and chunks better for RAG.
    """
    return flat(s)


def flat(s: str) -> str:
    """Flatten paragraphs to one line for narrator/source parsing."""
    return clean_spaces((s or '').replace('\n', ' '))


def clean_hadith_text(t: str) -> str:
    t = clean_paras(t)
    t = re.sub(r'^(rn|nn)+\s*', '', t)  # site artifact, e.g. hadith 12 starts with "rn"
    return t.strip()


def with_taraddi(n: int, narrator: str) -> str:
    """Append (رَضِيَ اللهُ تَعَالَى عَنْهُ) after the narrator name.

    Hadith 5's narrator is Aisha (female) so she gets عَنْهَا.
    """
    if not narrator or 'رضي الله' in narrator or 'رَضِيَ' in narrator:
        return narrator
    narrator = re.sub(r'\s*[-–]+\s*$', '', narrator).strip()  # dangling dash, e.g. عائشة -
    # mushaf-style ornate brackets ﴿ ﴾ (U+FD3F/U+FD3E) — closest thing to
    # the ﷺ ligature, since Unicode has no ligature for رضي الله عنه
    suffix = '\ufd3fرَضِيَ اللهُ تَعَالَى عَنْهَا\ufd3e' if n == 5 else '\ufd3fرَضِيَ اللهُ تَعَالَى عَنْهُ\ufd3e'
    return f'{narrator} {suffix}'


def extract_narrator(full_text: str) -> str:
    norm = flat(strip_tash(full_text))
    norm = re.sub(r'^[^ء-غف-ي]*?عن\s+', '', norm)  # drop leading عن + any stray latin chars
    # word-boundary regex so attached colons (قال:) still match
    m = re.search(r'\s(قالت|قال|رضي|سمعت|قلت|قالوا|أنه|انه|أن|ان)\b', norm)
    cand = norm[:m.start()].strip() if m and m.start() > 0 else norm.strip()
    cand = re.sub(r'\s*رضي.*$', '', cand).strip()
    cand = re.sub(r'\s*أقال.*$', '', cand).strip()
    return clean_spaces(cand)


def extract_source(full_text: str, hadith_number: int) -> str:
    norm = flat(strip_tash(full_text))
    m = re.search(r'(رواه|متفق عليه|أخرجه)', norm)
    if m:
        src = norm[m.start():].strip()
        # hadith 27 page merges a second narration (وابصة) — cut it off.
        # It starts right after "رواه مسلم." so any position past the
        # first few chars is a spillover, not part of the source.
        cut = re.search(r'وعن وابصة', src)
        if cut and cut.start() > 5:
            src = src[:cut.start()].strip()
        return clean_spaces(src).rstrip(' .') + ('.' if not src.rstrip().endswith('.') else '')
    # website has no source for these -> fall back to old OCR file's source
    return OLD_FALLBACK_SOURCE.get(hadith_number, '')


def main() -> None:
    ap = argparse.ArgumentParser(description='Merge website scrape into clean hadith JSON')
    ap.add_argument('--web', default='data/alnawawiforty_website.json')
    ap.add_argument('--old', default='data/hadith_extraction.json')
    ap.add_argument('--output', default='data/hadith_extraction_clean.json')
    args = ap.parse_args()

    web = json.loads(Path(args.web).read_text(encoding='utf-8'))
    old = json.loads(Path(args.old).read_text(encoding='utf-8'))
    pages_map = {o['hadith_number']: o.get('pages', []) for o in old}
    source_map = {o['hadith_number']: o.get('source', '') for o in old}
    global OLD_FALLBACK_SOURCE
    OLD_FALLBACK_SOURCE = source_map

    out = []
    for w in sorted(web, key=lambda x: x['hadith_number']):
        if 'error' in w:
            print(f"SKIP {w.get('hadith_number')}: scrape error, no data")
            continue
        n = w['hadith_number']
        text = clean_hadith_text(w.get('hadith_text', ''))
        out.append({
            'hadith_number': n,
            'id_label': w.get('id_label', ''),
            'title': w.get('title', ''),
            'narrator': with_taraddi(n, extract_narrator(text)),
            'hadith_text': text,
            'source': extract_source(text, n),
            'sharh': clean_paras(w.get('sharh', '')),
            'rawi_bio': clean_paras(w.get('rawi_bio', '')),
            'pages': pages_map.get(n, []),
            'page_title': w.get('page_title', ''),
        })

    missing_src = [o['hadith_number'] for o in out if not o['source']]
    missing_narr = [o['hadith_number'] for o in out if not o['narrator']]
    if missing_src:
        print(f'WARNING: empty source for: {missing_src}')
    if missing_narr:
        print(f'WARNING: empty narrator for: {missing_narr}')

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Saved {len(out)} items -> {args.output}')


if __name__ == '__main__':
    main()
