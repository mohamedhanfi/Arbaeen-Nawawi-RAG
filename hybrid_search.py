"""بحث هجين تجريبي: BM25 (rank_bm25) + الكثيف بدمج RRF — بدون لمس الإمبدنجز.

التشغيل:
    python hybrid_search.py
"""

import json
import os
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent

from dotenv import load_dotenv  # noqa: E402
from huggingface_hub import login  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402
from rank_bm25 import BM25Okapi  # noqa: E402
import chromadb  # noqa: E402

load_dotenv(BASE / ".env")
if os.environ.get("huggingface_Access_Tokens"):
    login(token=os.environ["huggingface_Access_Tokens"])

TASHKEEL = "".join(chr(c) for c in list(range(0x064B, 0x0660)) + [0x0670])


def normalize_ar(text):
    text = text.translate(str.maketrans("", "", TASHKEEL))
    return re.sub(r"\s+", " ", text).strip()


def tokenize_ar(text):
    return normalize_ar(text).split()


def rrf_fuse(dense_ranked, bm25_ranked, k=60):
    """دمج RRF: 1/(k+rank) لكل قائمة (الرتب تبدأ من 1)."""
    scores = {}
    for rank, hn in enumerate(dense_ranked, 1):
        scores[hn] = scores.get(hn, 0.0) + 1.0 / (k + rank)
    for rank, hn in enumerate(bm25_ranked, 1):
        scores[hn] = scores.get(hn, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: -x[1])


def main():
    with open(BASE / "data" / "documents.json", encoding="utf-8") as f:
        documents = json.load(f)

    hadith_docs = [d for d in documents if d["metadata"]["type"] == "hadith"]
    corpus = [tokenize_ar(d["content"]) for d in hadith_docs]
    bm25 = BM25Okapi(corpus)

    model = SentenceTransformer(
        "omarelshehy/Arabic-Retrieval-v1.0", device="cpu"
    )
    collection = chromadb.PersistentClient(
        path=str(BASE / "chroma_db")
    ).get_collection(name="arbaeen_nawawi_small")

    demo = ["ما هي مراتب الدين؟", "حديث النهي عن الغضب"]
    for query in demo:
        nq = normalize_ar(query)
        qv = model.encode_query(nq, normalize_embeddings=True)
        r = collection.query(
            query_embeddings=[qv.tolist()],
            n_results=5,
            where={"type": "hadith"},
            include=["metadatas"],
        )
        dense_ranked = [m["hadith_number"] for m in r["metadatas"][0]]
        bm25_scores = bm25.get_scores(nq.split())
        bm25_ranked = [
            hadith_docs[i]["metadata"]["hadith_number"]
            for i in sorted(range(len(bm25_scores)), key=lambda i: -bm25_scores[i])[:5]
        ]
        fused = rrf_fuse(dense_ranked, bm25_ranked)[:3]
        print(f"Query: {query}")
        print(f"  dense: {dense_ranked}")
        print(f"  bm25:  {bm25_ranked}")
        print(f"  fused: {[(hn, round(s, 4)) for hn, s in fused]}")


if __name__ == "__main__":
    main()
