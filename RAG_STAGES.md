# Arbaeen-Nawawi RAG — full technical reference

Arabic retrieval-augmented Q&A over the book *Arbaeen Nawawi* (42 hadiths).
Stack: EasyOCR → ChromaDB → Sentence Transformers → Streamlit → OpenRouter.
Everything runs locally on CPU except LLM generation (cloud API).

## 1. Architecture

```
OFFLINE (built once):
  Book PDF (32 scanned pages)
    → OCR + RTL line ordering + ornament fixes        [document_loading.ipynb]
    → data/ocr_pages.json            [{page, lines} × 32]
    → LLM correction + rule fixes + tashkeel strip    [text_cleaning.ipynb]
    → data/corrected_pages(F V).json [{page, text} × 32]
    → boundary detection + narrator/matn/source split [hadith_extraction.ipynb]
    → data/hadith_extraction.json    [42 × {hadith_number,title,narrator,text,source,pages}]
    → merge with website scrape                       (one-shot scripts, removed after use)
    → data/hadith_extraction_clean.json               [42 × {hadith_number,id_label,title,narrator,
                                                       hadith_text,source,sharh,rawi_bio,pages,page_title}]
    → 116 documents (42 matn + 42 sharh + 32 rawi_bio) [create_documents.ipynb]
    → data/documents.json            [{content, metadata} × 116]
    → embeddings (768-dim, normalized)                [embeddings.ipynb]
    → data/hadith_embeddings.npy     (116, 768) float32
    → ChromaDB collection arbaeen_nawawi_small        [chromadb.ipynb]

ONLINE (per question) — web_app.py:
  question → normalize (strip tashkeel) → encode_query → ChromaDB top-3 (type=hadith)
    → SIM_THRESHOLD gate (0.35) → labeled context → LLM (streamed)
    → verify cited hadith numbers → answer + top-1 matn
    → on-demand: sharh / rawi bio / related (by hadith_number)
```

## 2. Retrieval — finding the closest hadith (`retrieve()` in `web_app.py`)

1. **Normalize:** tashkeel stripped (`U+064B–U+065F`, `U+0670`) + whitespace collapsed.
   Indexed texts are unvocalized and so are queries — this single step fixed
   exact-title misses (proven: 8/10 → 9/10).
2. **Encode:** `omarelshehy/Arabic-Retrieval-v1.0` (BERT-based, AraBERTv02,
   768-dim), `encode_query(..., normalize_embeddings=True)` on CPU.
3. **Search:** ChromaDB cosine over 116 vectors, `where={"type": "hadith"}`
   (matn only — sharh/bios are fetched later by `hadith_number`, never searched
   into the answer path).
4. **Gate:** top-3 returned with raw l2-squared distances, converted via
   `similarity = max(0, 1 - d/2)` (Chroma default space on unit vectors).
   If best similarity < `SIM_THRESHOLD = 0.35` → friendly "no suitable hadith"
    message, no LLM call. Calibrated threshold 0.35
    (in-topic questions score ≥ 0.499, off-topic ≤ 0.231).

## 3. Augmentation — building the LLM context

- Top-3 excerpts labeled (`[Hadith 2 — Ranks of Religion]`) and joined
  (1000 chars each) into one context block.
- Short follow-ups (< 8 words) also carry the previous Q/A as context —
  without changing the DB search itself.
- Implementation: inline in the `web_app.py` submit flow + `short_query_context()`.

## 4. Generation — writing the final answer (`generate_answer()`)

- Models (OpenRouter): `nvidia/nemotron-3-ultra-550b-a55b:free` primary,
  `nex-agi/nex-n2.5-mini:free` fallback; `temperature=0`, `max_tokens=512`,
  client `timeout=60`, 2 attempts per model, output streamed via `st.write_stream`.
- Strict system prompt: answer only from the excerpts, cite hadith numbers,
  say "I don't know" when absent, no added details.
- Post-check `verify_mentions()`: every cited number (Arabic-Indic digits
  included) must exist in the retrieved set, else a light warning.
  (Limitation: word-form ordinals like "الثاني" are not detected.)

## 5. Data schemas

**documents.json** — 116 × `{content, metadata}`:
- `type=hadith` (42): content = `title + "\n\n" + hadith_text`;
  metadata = `{hadith_number:int, title, type, narrator, pages:list}`.
- `type=sharh` (42): content = `title + "\n\n" + sharh`; no narrator field.
- `type=rawi_bio` (32, one per unique narrator string): metadata uses
  `hadith_numbers` (list) instead of `hadith_number`.
- Note: ChromaDB rejects lists in metadata, so `pages`/`hadith_numbers` are
  stored stringified (`"4, 5"`) — filtering on them needs string handling.

**ChromaDB** (`chroma_db/`, collection `arbaeen_nawawi_small`): 116 documents
with precomputed 768-dim embeddings; default l2 space; rebuilt by
`chromadb.ipynb` (delete + recreate, so re-runs are idempotent).

## 6. Models

| Role | Model | Where | Notes |
|---|---|---|---|
| Embeddings (docs + queries) | `omarelshehy/Arabic-Retrieval-v1.0` | `embeddings.ipynb`, `web_app.retrieve` | Local, CPU, 768-dim, `encode_document`/`encode_query` |
| Answer generation | `nvidia/nemotron-3-ultra-550b-a55b:free` → `nex-agi/nex-n2.5-mini:free` | `web_app.generate_answer` | OpenRouter, temp 0, streamed |
| OCR | EasyOCR (`ar`) + PyMuPDF rendering (300–400 dpi) | `document_loading.ipynb` | Custom RTL line grouping (y-cluster 0.6×median-h, right-to-left sort); geometric basmala rule (h > 2×median, top 25%, conf < 0.2) + literal ﷺ map |
| OCR correction (build-time) | `inclusionai/ling-3.0-flash-vl:free` + per-page rule dict | `text_cleaning.ipynb` | Prompt forbids memorized correction, temp 0 |
| Retired/experimental | `qwen3.8-27b:free` (chronic 429s), `ling` VLM (free tier removed → 404), MiniLM-L12-v2, bge-m3 (evaluated, not adopted) | — | Kept out of the live path |

## 7. UI (`web_app.py` + `style.css` + `.streamlit/config.toml`)

- RTL Arabic throughout; emerald/gold/cream theme; Amiri (hadith/sharh) + Cairo (UI) via Google Fonts.
- Start screen: 6 proven preset cards (2-col grid) when history is empty.
- Per answer: generated text → hadith badges (number/narrator/pages) + matn card → 👍/👎 + copy → follow-up message with 3 buttons (sharh / rawi / related), each posted as its own chat message.
- Sidebar: about + clear-chat; fixed religious disclaimer footer; responsive CSS with mobile breakpoint.
- Backend traces (model names, match scores, technical errors) are hidden from users by design.

## 8. Run & reproduce

```bash
pip install -r requirements.txt          # + requests beautifulsoup4 lxml numpy rank_bm25 (used but undeclared)
# .env keys: huggingface_Access_Tokens, OPENROUTER_API_KEY (never in code)
streamlit run web_app.py                 # or double-click run_web.vbs (silent)
```

Rebuild order after data changes: `hadith_extraction_clean.json`
→ `create_documents.ipynb` → `embeddings.ipynb` → `chromadb.ipynb`
(the `.npy` is order-coupled to `documents.json`; the chroma notebook asserts dims/counts).

## 9. Measured quality

- Embedding mini-eval: **5/5**; extended 10-Q eval: **8/10 → 9/10** after normalization.
- Extended 10-question eval (same 10, `type=hadith` filter): **hit@1 = hit@3 = 9/10**.
- Remaining failure mode: indirect sub-topic questions at low confidence
  (e.g. "signs of the Hour in Gabriel's hadith") — needs score threshold (done)
  + hybrid search (demoed, not yet in the app).

## 10. Known limitations (honest list)

- Indexed wording comes from alnawawiforty.com, not the book's print;
  page numbers/boundaries come from the book OCR — edition differences possible.
- Narrator `taraddi` phrases with ﴿﴾ ornaments are synthesized, not photographed.
- Some manual OCR corrections were reconstructed from memory (unverifiable cases).
- The book's own marginalia (`قوله` notes) is excluded from the index.
- Same person under different narrator strings yields duplicated bios (e.g. Abu Hurairah ×8).
- Free-tier LLM/embedding APIs rate-limit (429s) — retries + fallback chain mitigate, not eliminate.
- No automated tests; validation is notebooks + recorded eval outputs.
