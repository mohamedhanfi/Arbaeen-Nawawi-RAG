"""تقييم الاسترجاع: hit@1 و hit@3 على أسئلة بحقيقة معروفة (بدون LLM — مجاني وسريع).

التشغيل:
    python evaluate.py
    python evaluate.py --file eval_questions.json --top-k 3
"""

import argparse
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
import chromadb  # noqa: E402

load_dotenv(BASE / ".env")
if os.environ.get("huggingface_Access_Tokens"):
    login(token=os.environ["huggingface_Access_Tokens"])

TASHKEEL = "".join(chr(c) for c in list(range(0x064B, 0x0660)) + [0x0670])


def normalize_ar(text):
    text = text.translate(str.maketrans("", "", TASHKEEL))
    return re.sub(r"\s+", " ", text).strip()


def main():
    ap = argparse.ArgumentParser(description="Evaluate retrieval hit@k")
    ap.add_argument("--file", default="eval_questions.json")
    ap.add_argument("--top-k", type=int, default=3)
    args = ap.parse_args()

    with open(BASE / args.file, encoding="utf-8") as f:
        questions = json.load(f)

    model = SentenceTransformer(
        "omarelshehy/Arabic-Retrieval-v1.0", device="cpu"
    )
    collection = chromadb.PersistentClient(
        path=str(BASE / "chroma_db")
    ).get_collection(name="arbaeen_nawawi_small")

    hit1 = hitk = 0
    for item in questions:
        qv = model.encode_query(
            normalize_ar(item["question"]), normalize_embeddings=True
        )
        r = collection.query(
            query_embeddings=[qv.tolist()],
            n_results=args.top_k,
            where={"type": "hadith"},
            include=["metadatas"],
        )
        ranked = [m["hadith_number"] for m in r["metadatas"][0]]
        expected = item["expected"]
        h1 = ranked[0] == expected
        hk = expected in ranked
        hit1 += h1
        hitk += hk
        print(f"{'PASS' if h1 else 'fail'}@{args.top_k}={hk} | expected={expected} | got={ranked} | {item['question']}")

    n = len(questions)
    print(f"\nhit@1: {hit1}/{n} = {hit1 / n:.2f}")
    print(f"hit@{args.top_k}: {hitk}/{n} = {hitk / n:.2f}")


if __name__ == "__main__":
    main()
