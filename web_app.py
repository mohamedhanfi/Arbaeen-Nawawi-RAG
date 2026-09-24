"""واجهة ويب (Streamlit) للأسئلة والأجوبة على كتاب الأربعين النووية.

التشغيل:
    streamlit run web_app.py
    أو: run_web.bat
"""

import html as ihtml
import json as _json
import os
import re
from pathlib import Path

import streamlit as st
from streamlit.components.v1 import html as components_html

BASE = Path(__file__).resolve().parent

EMB_MODEL = "omarelshehy/Arabic-Retrieval-v1.0"
ANSWER_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nex-agi/nex-n2.5-mini:free",
]
# حد أدنى للتشابه (0-1) — تحدده calibrate_threshold.py
SIM_THRESHOLD = 0.35
TASHKEEL = "".join(chr(c) for c in list(range(0x064B, 0x0660)) + [0x0670])

SYSTEM_PROMPT = """أنت مساعد يجيب عن أسئلة حول كتاب الأربعين النووية.
القواعد الصارمة:
1. أجب من المقتطفات المعطاة فقط، ولا تستخدم معلومات من خارجها.
2. اذكر أرقام الأحاديث التي اعتمدت عليها في إجابتك.
3. إذا لم تجد الإجابة في المقتطفات فقل: لا أعلم بناء على المصادر المتاحة.
4. لا تضف أحاديث أو تفاصيل غير موجودة في المقتطفات.
5. أجب بالعربية وباختصار مفيد."""


def normalize_ar(text):
    text = text.translate(str.maketrans("", "", TASHKEEL))
    return re.sub(r"\s+", " ", text).strip()


def l2_to_similarity(d):
    # مجموعة ChromaDB بالمسافة الافتراضية l2 (مربعة) على متجهات normalized:
    # cosine = 1 - d/2
    return max(0.0, 1.0 - float(d) / 2.0)


@st.cache_resource(show_spinner="تحميل موديل التضمين...")
def get_embedding_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMB_MODEL, device="cpu")


@st.cache_resource(show_spinner="الاتصال بقاعدة البيانات...")
def get_collection():
    import chromadb

    client = chromadb.PersistentClient(path=str(BASE / "chroma_db"))
    return client.get_collection(name="arbaeen_nawawi_small")


@st.cache_resource(show_spinner="تجهيز عميل التوليد...")
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


@st.cache_data(show_spinner=False)
def fetch_sharh(hadith_number):
    collection = get_collection()
    res = collection.get(
        where={"$and": [{"type": "sharh"}, {"hadith_number": hadith_number}]},
        include=["documents"],
    )
    docs = res.get("documents") or []
    return docs[0] if docs else None


@st.cache_data(show_spinner=False)
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


def generate_answer(question, context, history_prefix=""):
    client = get_llm_client()
    last_error = None
    for model in ANSWER_MODELS:
        for _ in range(2):
            try:
                stream = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": f"{history_prefix}المقتطفات:\n{context}\n\nالسؤال: {question}",
                        },
                    ],
                    temperature=0,
                    max_tokens=512,
                    stream=True,
                )

                def _chunks():
                    for chunk in stream:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            yield delta

                return st.write_stream(_chunks()).strip(), model
            except Exception as e:  # noqa: BLE001 - إعادة ثم الموديل البديل
                last_error = e
                continue
    raise RuntimeError(f"فشلت كل الموديلات. آخر خطأ: {last_error}")

def load_css():
    try:
        css = (BASE / "style.css").read_text(encoding="utf-8")
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    except OSError:
        pass


def copy_button(text):
    payload = _json.dumps(text)
    components_html(
        "<button onclick='navigator.clipboard.writeText(" + payload + ").then(()=>{this.innerText=\"تم النسخ\"})' "
        "style='border:1px solid #c9a227;border-radius:10px;padding:0.4rem 0.9rem;"
        "background:transparent;cursor:pointer;font-family:inherit;'>"
        "📋 نسخ الإجابة</button>",
        height=48,
    )


def short_query_context(prompt):
    # سياق المحادثة للأسئلة القصيرة فقط — لا يغير البحث في الـ DB
    last = st.session_state.get("last_exchange")
    if last and len(prompt.split()) < 8:
        return f"سياق سابق:\nس: {last['q']}\nج: {last['a']}\n\n"
    return ""


def verify_mentions(answer, valid_numbers):
    # يكتشف الأرقام المشرقية أيضا (ملاحظة: الصيغ اللفظية مثل الثاني لا تكتشف)
    conv = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    nums = re.findall(r"حديث\s*(?:رقم\s*)?([0-9٠-٩]+)", answer)
    mentioned = {int(n.translate(conv)) for n in nums}
    return mentioned - set(valid_numbers)


def render_badges(meta, pct):
    return (
        "<div class='badges'>"
        f"<span class='badge'>حديث رقم {meta.get('hadith_number')}</span>"
        f"<span class='badge'>الراوي: {ihtml.escape(str(meta.get('narrator', '')), quote=False)}</span>"
        f"<span class='badge'>الصفحات: {ihtml.escape(str(meta.get('pages')), quote=False)}</span>"
        f"<span class='badge'>التطابق: {pct}%</span>"
        "</div>"
    )


def render_matn(doc):
    return f"<div class='matn-box'>{ihtml.escape(doc, quote=False).replace(chr(10), '<br>')}</div>"


def render_result(res, live=False):
    top = res["top"]
    st.markdown("✨ **الإجابة:**")
    st.markdown(res["answer"])
    if live:
        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if st.button("👍", key="fb_up_live"):
                st.session_state.feedback = "up"
        with c2:
            if st.button("👎", key="fb_down_live"):
                st.session_state.feedback = "down"
        with c3:
            copy_button(res["answer"])
        if st.session_state.get("feedback"):
            st.caption("شكرًا! تم تسجيل رأيك.")
    tab1, tab2, tab3 = st.tabs(["📜 الحديث", "📖 الشرح", "👤 الراوي"])
    with tab1:
        st.markdown(render_badges(top["meta"], top["pct"]), unsafe_allow_html=True)
        st.markdown(render_matn(top["doc"]), unsafe_allow_html=True)
    with tab2:
        if res.get("sharh"):
            st.markdown(
                f"<div class='sharh-text'>{ihtml.escape(res['sharh'], quote=False)}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.info("لا يوجد شرح مسجل.")
    with tab3:
        if res.get("bio"):
            st.markdown(
                f"<div class='sharh-text'>{ihtml.escape(res['bio'], quote=False)}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.info("لا توجد معلومات مسجلة.")
    if res.get("related"):
        with st.expander("🔗 أحاديث ذات صلة"):
            for r in res["related"]:
                st.markdown(f"**حديث {r['hn']}: {r['title']}** — التطابق: {r['pct']}%")
                st.caption(r["snippet"] + "...")
    st.caption(f"الموديل: {res['model']}")


# ---------- الواجهة ----------
# ---------- الواجهة ----------
st.set_page_config(page_title="الأربعين النووية", page_icon="🕌", layout="centered")
load_css()

st.markdown(
    "<div class='banner fade-in'><h1>🕌 الأربعين النووية</h1>"
    "<p>اسأل بأي صياغة — نعرض الحديث الأنسب كاملًا مع شرحه وراويه</p></div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("عن المشروع")
    st.write("42 حديثًا من الأربعين النووية للإمام النووي، مع الشرح وتراجم الرواة — 116 وثيقة مفهرسة.")
    st.divider()
    if st.button("🗑️ مسح المحادثة", key="clear_chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.feedback = None
        st.rerun()
    st.divider()
    st.caption("التوليد: nemotron-3-ultra (مع بديل احتياطي)")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "preset" not in st.session_state:
    st.session_state.preset = None
if "feedback" not in st.session_state:
    st.session_state.feedback = None
if "last_exchange" not in st.session_state:
    st.session_state.last_exchange = None

PRESETS = [
    "ما هي مراتب الدين؟",
    "ما حكم الغضب في الإسلام؟",
    "ما هي أركان الإسلام؟",
    "حديث الاستقامة",
    "حديث لا ضرر ولا ضرار",
    "ما حكم من أحدث في الدين ما ليس منه؟",
]

if not st.session_state.messages:
    st.subheader("جرّب سؤالًا جاهزًا 👇")
    cols = st.columns(2)
    for i, q in enumerate(PRESETS):
        with cols[i % 2]:
            if st.button(q, key=f"preset_card_{i}", use_container_width=True):
                st.session_state.preset = q

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if isinstance(msg["content"], dict):
            render_result(msg["content"])
        else:
            st.markdown(msg["content"], unsafe_allow_html=True)

prompt = st.chat_input("اكتب سؤالك هنا...")
if st.session_state.preset:
    prompt, st.session_state.preset = st.session_state.preset, None

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        with st.chat_message("assistant"):
            with st.status("جاري البحث والتوليد...", expanded=False) as status:
                st.write("🔍 البحث عن الأحاديث الأنسب...")
                results = retrieve(prompt, top_k=3)
                metas = results["metadatas"][0]
                docs = results["documents"][0]
                dists = results["distances"][0]

                best_sim = l2_to_similarity(dists[0])
                if best_sim < SIM_THRESHOLD:
                    status.update(label="لا توجد نتائج مناسبة", state="complete", expanded=False)
                    st.warning("لم أجد حديثًا مناسبًا لسؤالك، جرّب صياغة أخرى.")
                else:
                    context = "\n\n".join(
                        f"[حديث رقم {m.get('hadith_number')} — {m.get('title')}]\n{d[:1000]}"
                        for m, d in zip(metas, docs)
                    )
                    st.write("✍️ توليد الإجابة...")
                    prefix = short_query_context(prompt)
                    answer, model = generate_answer(prompt, context, prefix)

                    top_meta, top_doc = metas[0], docs[0]
                    top_pct = round(best_sim * 100)
                    res = {
                        "question": prompt,
                        "answer": answer,
                        "model": model,
                        "score": top_pct,
                        "top": {"meta": top_meta, "doc": top_doc, "pct": top_pct},
                        "related": [
                            {
                                "hn": m.get("hadith_number"),
                                "title": m.get("title"),
                                "pct": round(l2_to_similarity(dd) * 100),
                                "snippet": d[:300].strip(),
                            }
                            for m, d, dd in zip(metas[1:], docs[1:], dists[1:])
                        ],
                        "sharh": fetch_sharh(top_meta.get("hadith_number")),
                        "bio": fetch_rawi_bio(top_meta.get("hadith_number")),
                    }
                    render_result(res, live=True)
                    st.session_state.messages.append({"role": "assistant", "content": res})
                    st.session_state.last_exchange = {"q": prompt, "a": answer}

                    foreign = verify_mentions(answer, {m.get("hadith_number") for m in metas})
                    if foreign:
                        st.warning("تنبيه: الإجابة ذكرت حديثًا خارج النتائج المعروضة.")

                    status.update(label="اكتمل ✅", state="complete", expanded=False)

    except Exception as exc:  # noqa: BLE001 - لا نظهر traceback للمستخدم
        st.error("عذرًا، حدث خطأ أثناء معالجة سؤالك. تحقق من الاتصال والمفاتيح ثم حاول مجددًا.")
        st.caption(f"تفاصيل تقنية: {type(exc).__name__}")

st.markdown(
    "<div class='disclaimer'>الإجابات للاسترشاد من نص الكتاب وليست فتوى، ويُرجع لأهل العلم في المسائل الشرعية.</div>",
    unsafe_allow_html=True,
)
