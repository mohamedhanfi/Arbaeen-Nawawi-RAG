"""نقطة دخول الـ backend: FastAPI يقدّم API_Position والواجهة معًا (StaticFiles)."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from . import rag

BASE = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # تحميل ثقيل مرة واحدة عند الإقلاع (موديل + DB + فهرس BM25)
    rag.get_embedding_model()
    rag.get_collection()
    rag.get_bm25_index()
    print("backend ready: model + chroma + bm25 loaded", flush=True)
    yield


app = FastAPI(title="Arbaeen Nawawi RAG")


class AskRequest(BaseModel):
    question: str
    last_q: str | None = None
    last_a: str | None = None


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/ask")
def ask(req: AskRequest):
    question = (req.question or "").strip()
    last = {"q": req.last_q, "a": req.last_a} if req.last_q else None

    def event_gen():
        try:
            if not question:
                yield _sse("error", {"message": "السؤال فارغ."})
                return

            yield _sse("status", {"phase": "search"})

            direct_hn = rag.resolve_direct_reference(question)
            direct_pack = None
            if direct_hn is not None:
                _doc0, _meta0 = rag.fetch_hadith(direct_hn)
                if _doc0 is not None:
                    # مرجع صريح: يجاوز البحث الدلالي والعتبة
                    direct_pack = ([_meta0], [_doc0], [None])

            if direct_pack is None:
                results = rag.retrieve(question, top_k=5)
                metas = results["metadatas"][0]
                docs = results["documents"][0]
                dists = results["distances"][0]
            else:
                metas, docs, dists = direct_pack

            best_sim = (
                rag.l2_to_similarity(dists[0])
                if dists[0] is not None
                else 1.0
            )
            if best_sim < config.SIM_THRESHOLD:
                yield _sse("done", {
                    "blocked": True,
                    "message": "لم أجد حديثًا مناسبًا لسؤالك، جرّب صياغة أخرى.",
                })
                return

            if direct_pack is not None:
                triplets = [(metas[0], docs[0], dists[0])]
            else:
                triplets = rag.fuse_ranking(question, metas, docs, dists)
                metas = [t[0] for t in triplets]
                docs = [t[1] for t in triplets]
                dists = [t[2] for t in triplets]
                top_score = (
                    round(rag.l2_to_similarity(dists[0]) * 100)
                    if dists[0] is not None else None
                )

            context = "\n\n".join(
                f"[حديث رقم {m.get('hadith_number')} — {m.get('title')}]\n{rag.smart_truncate(d)}"
                for m, d in zip(metas, docs)
            )
            prefix = ""
            if last and len(question.split()) < 8:
                prefix = (
                    f"سياق سابق:\nس: {last['q']}\nج: {last['a']}\n\n"
                )

            yield _sse("status", {"phase": "generate"})

            top_meta = metas[0]
            hn = top_meta.get("hadith_number")
            answer_parts = []
            model_used = None
            for kind, *rest in rag.generate_events(question, context, prefix):
                if kind == "token":
                    answer_parts.append(rest[0])
                    yield _sse("token", {"text": rest[0]})
                elif kind == "restart":
                    answer_parts = []
                    yield _sse("restart", {})
                elif kind == "fallback":
                    yield _sse("status", {"phase": "fallback", "model": rest[0]})
                elif kind == "result":
                    model_used = rest[1]
            answer = "".join(answer_parts).strip()

            valid = {m.get("hadith_number") for m in metas}
            foreign = rag.verify_mentions(answer, valid)

            yield _sse("done", {
                "blocked": False,
                "answer": answer,
                "model": model_used,
                "score": top_score,
                "top": {
                    "hn": hn,
                    "title": top_meta.get("title"),
                    "narrator": top_meta.get("narrator", ""),
                    "pages": top_meta.get("pages"),
                    "matn": docs[0],
                    "score": (
                        round(rag.l2_to_similarity(dists[0]) * 100)
                        if dists[0] is not None else None
                    ),
                },
                "related": [
                    {
                        "hn": m.get("hadith_number"),
                        "title": m.get("title"),
                        "pct": (
                            round(rag.l2_to_similarity(dd) * 100)
                            if dd is not None else None
                        ),
                        "snippet": rag.smart_truncate(d, 300),
                    }
                    for m, d, dd in zip(metas[1:], docs[1:], dists[1:])
                ],
                "sharh": rag.fetch_sharh(hn),
                "bio": rag.fetch_rawi_bio(hn),
                "warning": (
                    "تنبيه: الإجابة ذكرت حديثًا خارج النتائج المعروضة."
                    if foreign else None
                ),
            })
        except Exception:
            partial = "".join(locals().get("answer_parts", [])).strip()
            _metas = locals().get("metas") or []
            if partial and _metas:
                try:
                    _m0 = _metas[0]
                    _hn = _m0.get("hadith_number")
                    _docs = locals().get("docs") or [""]
                    yield _sse("done", {
                        "blocked": False,
                        "partial": True,
                        "answer": partial,
                        "model": None,
                        "score": None,
                        "top": {
                            "hn": _hn,
                            "title": _m0.get("title"),
                            "narrator": _m0.get("narrator", ""),
                            "pages": _m0.get("pages"),
                            "matn": _docs[0] if _docs else "",
                        },
                        "related": [],
                        "sharh": rag.fetch_sharh(_hn),
                        "bio": rag.fetch_rawi_bio(_hn),
                        "warning": "اكتملت الإجابة جزئيًا بسبب انقطاع المصدر.",
                    })
                    return
                except Exception:
                    pass
            yield _sse("error", {
                "message": "عذرًا، حدث خطأ أثناء معالجة سؤالك. تحقق من الاتصال ثم حاول مجددًا.",
            })

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# الواجهة تُقدَّم من نفس العملية والبورت (لا CORS)
app.mount("/", StaticFiles(directory=str(BASE / "frontend"), html=True), name="frontend")
