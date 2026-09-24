"""معايرة SIM_THRESHOLD: يطبع المسافات والتشابه لأسئلة داخل وخارج الموضوع.

التشغيل:
    python calibrate_threshold.py
"""

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


def l2_to_similarity(d):
    return max(0.0, 1.0 - float(d) / 2.0)


IN_TOPIC = [
    "ما هي مراتب الدين؟",
    "ما حكم الغضب في الإسلام؟",
    "ما هي أركان الإسلام؟",
    "حديث الاستقامة",
    "حديث لا ضرر ولا ضرار",
]
OFF_TOPIC = [
    "ما عاصمة فرنسا؟",
    "كيف أطبخ الكشري؟",
    "من فاز بكأس العالم الأخيرة؟",
]


def main():
    model = SentenceTransformer(
        "omarelshehy/Arabic-Retrieval-v1.0", device="cpu"
    )
    collection = chromadb.PersistentClient(
        path=str(BASE / "chroma_db")
    ).get_collection(name="arbaeen_nawawi_small")

    print("=== داخل الموضوع ===")
    in_sims = []
    for q in IN_TOPIC:
        qv = model.encode_query(normalize_ar(q), normalize_embeddings=True)
        r = collection.query(
            query_embeddings=[qv.tolist()], n_results=1,
            where={"type": "hadith"}, include=["metadatas", "distances"],
        )
        d = r["distances"][0][0]
        s = l2_to_similarity(d)
        in_sims.append(s)
        print(f"sim={s:.3f} dist={d:.3f} | hadith {r['metadatas'][0][0]['hadith_number']} | {q}")

    print("=== خارج الموضوع ===")
    off_sims = []
    for q in OFF_TOPIC:
        qv = model.encode_query(normalize_ar(q), normalize_embeddings=True)
        r = collection.query(
            query_embeddings=[qv.tolist()], n_results=1,
            where={"type": "hadith"}, include=["metadatas", "distances"],
        )
        d = r["distances"][0][0]
        s = l2_to_similarity(d)
        off_sims.append(s)
        print(f"sim={s:.3f} dist={d:.3f} | hadith {r['metadatas'][0][0]['hadith_number']} | {q}")

    print(f"\nأدنى تشابه داخل الموضوع: {min(in_sims):.3f}")
    print(f"أعلى تشابه خارج الموضوع: {max(off_sims):.3f}")
    print("القيمة المقترحة بينهما (القيمة الحالية SIM_THRESHOLD في web_app.py)")


if __name__ == "__main__":
    main()
