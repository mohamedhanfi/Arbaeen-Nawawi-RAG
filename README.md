# Arbaeen Nawawi: Arabic RAG Q&A

Ask questions in Arabic about *Al-Arbaeen Al-Nawawiyyah* and get answers grounded in the book itself.

The system finds the most relevant hadith, shows its full text with the explanation (sharh) and the narrator's biography, then writes a short sourced answer. The LLM answers **only from the retrieved excerpt**, cites hadith numbers, and says "I don't know" when the answer isn't in the text.

<!-- Add a screenshot or GIF here: ![Demo](docs/demo.gif) -->

## Contents

- [Arbaeen Nawawi: Arabic RAG Q\&A](#arbaeen-nawawi-arabic-rag-qa)
  - [Contents](#contents)
  - [Overview](#overview)
  - [How It Works](#how-it-works)
  - [Quick Start](#quick-start)
    - [Example](#example)
  - [Project Structure](#project-structure)
  - [Models](#models)
  - [Retrieval Quality](#retrieval-quality)
  - [Limitations and Roadmap](#limitations-and-roadmap)
  - [Data Sources and Disclaimer](#data-sources-and-disclaimer)
  - [Author](#author)
  - [License](#license)

## Overview

- **Corpus:** 42 hadiths with explanations and narrator biographies, indexed as 116 documents (42 matn, 42 sharh, 32 bios).
- **Source book:** a scanned 32-page PDF with no text layer, so OCR is required.
- **Search:** semantic search over Arabic embeddings in a local ChromaDB index.
- **Generation:** grounded answers via OpenRouter, with automatic fallback to a backup model.
- **Matching:** diacritics are stripped on both the index side and the query side.
- **Runtime:** CPU-friendly. Embeddings are precomputed, so only the query is embedded on the fly.

## How It Works

```mermaid
flowchart LR
    A[Scanned PDF] --> B[OCR + cleaning]
    B --> C[Hadith extraction]
    C --> D[116 documents]
    D --> E[Embeddings]
    E --> F[(ChromaDB)]

    Q[Question] --> N[Normalize + embed]
    N --> R[Retrieve closest hadith]
    F --> R
    R --> L[LLM answer from excerpt]
    R --> U[Web UI]
    L --> U
```

The top row is built once offline. The bottom row runs on every question: the query goes through the same normalization and embedding, the closest hadith is retrieved, and the LLM writes the answer using only that excerpt. The sharh and narrator biography are fetched by hadith number and shown alongside.

## Quick Start

**Requirements:** Python 3.11 and an [OpenRouter](https://openrouter.ai/) API key. Tesseract OCR is only needed for the legacy OCR cells.

```bash
git clone https://github.com/mohamedhanfi/Arbaeen-Nawawi-RAG.git
cd Arbaeen-Nawawi-RAG
pip install -r requirements.txt
```

Create a `.env` file in the project root (it is git-ignored, so never put keys in code):

```env
huggingface_Access_Tokens=hf_...
OPENROUTER_API_KEY=sk-or-v1-...
```

Run the app (silent, no terminal window):

double-click `run_web.vbs` (opens the browser automatically).

For visible logs use `run_web_debug.bat`; to stop the server use `stop_web.vbs`.

Or manually (one process serves API + frontend, no CORS):

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8501
```

Then open <http://localhost:8501>. API docs (dev only): <http://localhost:8501/docs>.

### Example

```text
> ما هو حديث النهي عن الغضب؟

حديث رقم 16: النهي عن الغضب

عن أبي هريرة رضي الله عنه قال: جاء رجل إلى النبي ﷺ وقال: أوصني، فقال: (لا تغضب).
رواه البخاري.

[شرح الحديث 16]
لم يبين هذا الرجل... قال: (لا تغضب) الغضب: بين النبي ﷺ أنه جمرة
يلقيها الشيطان في قلب ابن آدم...

[معلومات الراوي]
أبو هريرة هو عبد الرحمن بن صخر الدوسي...
```

## Project Structure

```text
.
├── backend/                    # FastAPI: config.py, rag.py, main.py (API + static frontend)
├── frontend/                   # Static chat UI: index.html, styles.css, app.js
├── run_web.vbs                 # Silent Windows launcher (no terminal)
├── requirements.txt
├── .env                        # API keys (git-ignored)
├── Book/
│   └── Arbaeen-Nawawi-book.pdf
├── src/                        # Data pipeline, in order
│   ├── document_loading.ipynb  # PDF -> images -> EasyOCR -> ocr_pages.json
│   ├── text_cleaning.ipynb     # OCR correction and diacritic stripping
│   ├── hadith_extraction.ipynb # Split the 42 hadiths with metadata
│   ├── create_documents.ipynb  # Build the 116 searchable documents
│   ├── embeddings.ipynb        # Vectorize documents + accuracy tests
│   ├── chromadb.ipynb          # Load into ChromaDB
│   └── retrieval.ipynb         # Search function + 10-question test
├── data/
│   ├── ocr_pages.json                 # Raw OCR output
│   ├── cleaned_pages.json             # After LLM correction
│   ├── corrected_pages(F V).json      # Final corrected pages
│   ├── hadith_extraction.json         # 42 hadiths from the OCR
│   ├── hadith_extraction_clean.json   # Main data file
│   ├── documents.json                 # The 116 indexed documents
│   └── hadith_embeddings.npy          # 116 x 768 vectors
└── chroma_db/                  # Local vector database
```

If `documents.json` changes, rebuild `hadith_embeddings.npy` and then the ChromaDB collection. If `chroma_db/` goes out of sync, delete it and rebuild via `src/chromadb.ipynb`.

## Models

| Role | Model |
|---|---|
| OCR | EasyOCR (Arabic) + PyMuPDF |
| Embeddings | `omarelshehy/Arabic-Retrieval-v1.0` (768-dim) |
| Generation | `nvidia/nemotron-3-ultra-550b-a55b:free`, fallback `nex-agi/nex-n2.5-mini:free` (OpenRouter) |

## Retrieval Quality

| Evaluation | Result |
|---|---|
| Mini-eval (`embeddings.ipynb`) | 5 / 5 |
| 10-question eval (`retrieval.ipynb`) | 8 / 10 |
| Same eval after diacritic normalization | 9 / 10 |

Diacritic normalization on both sides is mandatory: the indexed texts are vocalized, while user queries are not. The remaining failures are indirect sub-topic questions.

## Limitations and Roadmap

**Limitations**

- Only the single best-matching hadith is retrieved.
- No similarity threshold, so off-topic questions still return the nearest hadith.
- Free OpenRouter models can be rate-limited.
- The evaluation set is small (10 questions).

**Roadmap**

- [ ] Retrieve top 3 hadiths and show related ones
- [ ] Similarity threshold with a "no relevant hadith found" state
- [ ] Hybrid search (BM25 + embeddings) and an optional reranker
- [ ] Larger evaluation set with hit@1 / hit@3
- [ ] Streaming answers and better error handling
- [ ] UI redesign (tabs, Arabic typography, dark mode)
- [ ] Public demo on Hugging Face Spaces or Streamlit Cloud

## Data Sources and Disclaimer

Indexed matn, sharh, and narrator bios come from alnawawiforty.com. Page numbers and hadith boundaries come from the book's OCR, so edition differences may exist. Check the source site's terms before redistributing the scraped data.

