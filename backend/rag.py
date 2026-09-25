"""منطق الاسترجاع والتوليد — بلا أي اعتماد على Streamlit."""

import functools
import os
import re
from pathlib import Path

from . import config

BASE = Path(__file__).resolve().parent.parent


def normalize_ar(text):
    text = text.translate(str.maketrans("", "", config.TASHKEEL))
    return re.sub(r"\s+", " ", text).strip()


def l2_to_similarity(d):
    # مجموعة ChromaDB بالمسافة الافتراضية l2 (مربعة) على متجهات normalized:
    # cosine = 1 - d/2
    return max(0.0, 1.0 - float(d) / 2.0)


PUNCT_CLASS = "[-؟?.,:؛!()\\[\\]\"'«»—–]"


def clean_tok(w):
    return re.sub(PUNCT_CLASS, "", w)


def stem_ar(w):
    # مجرد تجريد سوابق/لواحق شائعة — ليس صرفا كاملا
    for p in ("وبال", "بال", "كال", "لل", "ولل", "فال", "ال", "و"):
        if w.startswith(p) and len(w) - len(p) >= 3:
            w = w[len(p):]
            break
    for s in ("ات", "ون", "ين", "ان", "ها", "هم", "هن", "كم", "نا"):
        if w.endswith(s) and len(w) - len(s) >= 2:
            w = w[:-len(s)]
            break
    for s in ("ة", "ه", "ي"):
        if w.endswith(s) and len(w) - len(s) >= 2:
            w = w[:-len(s)]
            break
    return w


def smart_truncate(text, limit=1000):
    # قص عند حد جملة/فقرة قريب من الحد بدل القطع الأعمى
    text = text.strip()
    if len(text) <= limit:
        return text
    cut_at = int(limit * 0.8)
    window = text[cut_at:limit]
    cuts = [m.end() for m in re.finditer(r"[.،:؟!؟\n]+", window)]
    if cuts:
        return text[:cut_at + cuts[-1]].strip()
    return text[:limit].strip()


@functools.lru_cache(maxsize=1)
def get_embedding_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(config.EMB_MODEL, device="cpu")


@functools.lru_cache(maxsize=1)
def get_collection():
    import chromadb

    client = chromadb.PersistentClient(path=str(BASE / "chroma_db"))
    return client.get_collection(name=config.COLLECTION_NAME)


@functools.lru_cache(maxsize=1)
def get_title_index():
    # جذوع كلمات عناوين الـ42 حديثا + أوزان IDF — تبنى مرة واحدة
    from collections import Counter
    collection = get_collection()
    res = collection.get(where={"type": "hadith"}, include=["metadatas"])
    index = {}
    for meta in res["metadatas"]:
        hn = meta.get("hadith_number")
        stems = {stem_ar(c) for c in (clean_tok(w) for w in normalize_ar(meta.get("title", "")).split()) if c}
        index[hn] = {s for s in stems if len(s) >= 2} - config.AR_STOPWORDS
    df = Counter()
    for stems in index.values():
        for s in stems:
            df[s] += 1
    weights = {s: 1.0 / c for s, c in df.items()}
    return index, weights


@functools.lru_cache(maxsize=1)
def get_bm25_index():
    # يبنى مرة واحدة فقط من نصوص المتون
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        return None, None
    collection = get_collection()
    res = collection.get(where={"type": "hadith"}, include=["documents", "metadatas"])
    tokenized, hns = [], []
    for doc, meta in zip(res["documents"], res["metadatas"]):
        tokenized.append(normalize_ar(doc).split())
        hns.append(meta.get("hadith_number"))
    if not tokenized:
        return None, None
    return BM25Okapi(tokenized), hns


def get_llm_client():
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(BASE / ".env")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY غير موجود في .env")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key, timeout=60.0)


def retrieve(query, top_k=5):
    model = get_embedding_model()
    collection = get_collection()
    qv = model.encode_query(normalize_ar(query), normalize_embeddings=True)
    return collection.query(
        query_embeddings=[qv.tolist()],
        n_results=top_k,
        where={"type": "hadith"},
        include=["documents", "metadatas", "distances"],
    )


def rrf_fuse(dense_ranked, bm25_ranked, k=60):
    scores = {}
    for rank, hn in enumerate(dense_ranked, 1):
        scores[hn] = scores.get(hn, 0.0) + 1.0 / (k + rank)
    for rank, hn in enumerate(bm25_ranked, 1):
        scores[hn] = scores.get(hn, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda hn: -scores[hn])


def fuse_ranking(query, metas5, docs5, dists5):
    # يرجع [(meta, doc, dist|None)] مرتبة — العتبة تبقى على الأفضل الكثيف
    dense_hns = [m.get("hadith_number") for m in metas5]
    if not config.USE_HYBRID:
        return [(metas5[i], docs5[i], dists5[i]) for i in range(min(3, len(metas5)))]
    bm25, hns = get_bm25_index()
    if bm25 is None:
        return [(metas5[i], docs5[i], dists5[i]) for i in range(min(3, len(metas5)))]
    order = sorted(range(len(hns)), key=lambda i: -bm25.get_scores(normalize_ar(query).split())[i])
    bm25_ranked = [hns[i] for i in order[:5]]
    by_hn = {}
    for m, d, dd in zip(metas5, docs5, dists5):
        by_hn.setdefault(m.get("hadith_number"), (m, d, dd))
    out = []
    for hn in rrf_fuse(dense_hns[:5], bm25_ranked, config.RRF_K)[:3]:
        if hn in by_hn:
            out.append(by_hn[hn])
        else:
            doc, meta = fetch_hadith(hn)
            if doc is None:
                continue
            out.append((meta, doc, None))
    return out or [(metas5[0], docs5[0], dists5[0])]


def resolve_direct_reference(question):
    # مرجع صريح برقم/ترتيب/عنوان مميز → رقم الحديث، وإلا None (نرجع للبحث الدلالي)
    q = normalize_ar(question)
    conv = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    m = re.search(r"(?:الحديث|حديث)\s*(?:رقم\s*)?([0-9٠-٩]+)", q)
    if m:
        hn = int(m.group(1).translate(conv))
        if 1 <= hn <= 42:
            return hn
    ords = "|".join(sorted(config.ORDINAL_MASCULINE, key=len, reverse=True))
    m = re.search(r"(?:الحديث|حديث)\s+(" + ords + r")", q)
    if m:
        return config.ORDINAL_MASCULINE[m.group(1)]
    qtokens = {stem_ar(c) for c in (clean_tok(w) for w in q.split()) if c} - config.AR_STOPWORDS
    qtokens = {s for s in qtokens if len(s) >= 2}
    index, weights = get_title_index()
    best, best_score = None, 0.0
    for hn in sorted(index):
        sc = sum(weights.get(s, 0) for s in qtokens & index[hn])
        if sc > best_score:
            best, best_score = hn, sc
    if best is not None and best_score >= 1.0:
        return best
    return None


def verify_mentions(answer, valid_numbers):
    # أرقام رقمية (تشمل المشرقية) + صيغ لفظية مذكرة فقط
    conv = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    nums = re.findall(r"حديث\s*(?:رقم\s*)?([0-9٠-٩]+)", answer)
    mentioned = {int(n.translate(conv)) for n in nums}
    ords = "|".join(sorted(config.ORDINAL_MASCULINE, key=len, reverse=True))
    for w in re.findall(r"(?:الحديث|حديث)\s+(" + ords + r")", answer):
        mentioned.add(config.ORDINAL_MASCULINE[w])
    return mentioned - set(valid_numbers)


def fetch_sharh(hadith_number):
    collection = get_collection()
    res = collection.get(
        where={"$and": [{"type": "sharh"}, {"hadith_number": hadith_number}]},
        include=["documents"],
    )
    docs = res.get("documents") or []
    return docs[0] if docs else None


def fetch_rawi_bio(hadith_number):
    collection = get_collection()
    res = collection.get(
        where={"type": "rawi_bio"},
        include=["documents", "metadatas"],
    )
    for content, meta in zip(res["documents"], res["metadatas"]):
        nums = [n.strip() for n in str(meta.get("hadith_numbers", "")).split(",")]
        if str(hadith_number) in nums:
            return content
    return None


def fetch_hadith(hn):
    collection = get_collection()
    res = collection.get(
        where={"$and": [{"type": "hadith"}, {"hadith_number": int(hn)}]},
        include=["documents", "metadatas"],
    )
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    if not docs:
        return None, None
    return docs[0], metas[0]


def short_query_context(prompt, last_exchange):
    # سياق المحادثة للأسئلة القصيرة فقط — لا يغير البحث في الـ DB
    if last_exchange and len(prompt.split()) < 8:
        return f"سياق سابق:\nس: {last_exchange['q']}\nج: {last_exchange['a']}\n\n"
    return ""


def generate_events(question, context, history_prefix=""):
    """ أحداث: ("token", نص) | ("restart",) | ("fallback", موديل) | ("result", إجابة, موديل).

    لو انقطع البث بعد نزول مقاطع، يعيد المحاولة من جديد بعد إشارة restart
    (حتى لا يلتصق النص الجديد بالقديم)، مع مهلة قصيرة لتهدئة حد المعدل.
    """
    """مولد أحداث: ("fallback", model) | ("token", text) | ("result", answer, model).

    يجمع الرد كاملا داخليا (لا يعرض شيئا بنفسه) — العرض مسؤولية المستهلك.
    """
    import time

    client = get_llm_client()
    last_error = None
    attempt_no = 0
    for mi, model in enumerate(config.ANSWER_MODELS):
        for ai in range(2):
            try:
                if attempt_no > 0:
                    time.sleep(3)
                    yield ("restart",)
                attempt_no += 1
                stream = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": config.SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": f"{history_prefix}المقتطفات:\n{context}\n\nالسؤال: {question}",
                        },
                    ],
                    temperature=0,
                    max_tokens=512,
                    stream=True,
                )
                parts = []
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        parts.append(delta)
                        yield ("token", delta)
                yield ("result", "".join(parts).strip(), model)
                return
            except Exception as e:  # noqa: BLE001 - إعادة ثم الموديل البديل
                last_error = e
                if ai == 1 and mi + 1 < len(config.ANSWER_MODELS):
                    yield ("fallback", config.ANSWER_MODELS[mi + 1])
                continue
    raise RuntimeError(f"فشلت كل الموديلات. آخر خطأ: {last_error}")
