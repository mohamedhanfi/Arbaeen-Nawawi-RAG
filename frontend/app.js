// واجهة الشات — كل دور (turn) كائن واحد يرسم فقاعة واحدة متكاملة.
const PRESETS = [
  "ما هي مراتب الدين؟",
  "ما حكم الغضب في الإسلام؟",
  "ما هي أركان الإسلام؟",
  "حديث الاستقامة",
  "حديث لا ضرر ولا ضرار",
  "ما حكم من أحدث في الدين ما ليس منه؟",
];
const LS_KEY = "arbaeen-chat-v1";
const API = "/api/ask";

const chatEl = document.getElementById("chat");
const startEl = document.getElementById("start-screen");
const presetsEl = document.getElementById("presets");
const formEl = document.getElementById("composer");
const inputEl = document.getElementById("input");

let turns = loadTurns();
let uidCounter = turns.reduce((m, t) => Math.max(m, t.uid || 0), 0);
let stickBottom = true;

// ---------- أدوات ----------
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function inlineMd(s) {
  return s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function md(src) {
  // ماركدون مصغّر آمن: عناوين + قوائم + فقرات (بعد الهروب أولا)
  const lines = escapeHtml(src).split("\n");
  let html = "", inList = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (const raw of lines) {
    const line = raw.trim();
    let m;
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) {
      closeList();
      const l = m[1].length + 2;
      html += `<h${l}>${inlineMd(m[2])}</h${l}>`;
    } else if ((m = line.match(/^([-*]|\d+[.)])\s+(.*)$/))) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inlineMd(m[2])}</li>`;
    } else if (line === "") {
      closeList();
    } else {
      closeList();
      html += `<p>${inlineMd(line)}</p>`;
    }
  }
  closeList();
  return html;
}

function save() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(turns)); } catch (e) { /* مساحة ممتلئة؟ نتجاهل */ }
}

function loadTurns() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch (e) {
    return [];
  }
}

function maybeScroll() {
  if (stickBottom) window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

window.addEventListener("scroll", () => {
  const nearBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 120;
  stickBottom = nearBottom;
}, { passive: true });

// ---------- رسم دور واحد ----------
function badgesHtml(t) {
  const m = t.meta || {};
  let h = `<span class="badge">حديث رقم ${escapeHtml(m.hadith_number ?? "?")}</span>`;
  if (m.narrator) h += `<span class="badge">الراوي: ${escapeHtml(m.narrator)}</span>`;
  if (m.pages) h += `<span class="badge">الصفحات: ${escapeHtml(String(m.pages))}</span>`;
  if (t.score != null) h += `<span class="badge">التطابق: ${t.score}%</span>`;
  return `<div class="badges">${h}</div>`;
}

function openCls(open, key) {
  return open[key] ? "open" : "";
}

function badgesHtml(t) {
  const m = t.meta || {};
  let h = `<span class="badge">حديث رقم ${escapeHtml(m.hn ?? "?")}</span>`;
  if (m.title) h += `<span class="badge">${escapeHtml(m.title)}</span>`;
  if (m.narrator) h += `<span class="badge">الراوي: ${escapeHtml(m.narrator)}</span>`;
  if (m.pages) h += `<span class="badge">الصفحات: ${escapeHtml(String(m.pages))}</span>`;
  if (t.score != null) h += `<span class="badge">التطابق: ${t.score}%</span>`;
  return `<div class="badges">${h}</div>`;
}

function renderTurn(turn) {
  let node = document.getElementById("turn-" + turn.uid);
  if (!node) {
    node = document.createElement("div");
    node.id = "turn-" + turn.uid;
    node.className = "msg assistant";
    chatEl.appendChild(node);
  }
  if (turn.blocked) {
    node.innerHTML = `<div class="bubble"><div class="warning-box">${escapeHtml(turn.blocked)}</div></div>`;
    return;
  }
  if (!turn.done) {
    node.innerHTML = `<div class="bubble"><span class="status-dot"></span>${escapeHtml(turn.statusText || "جاري...")}<div class="answer-stream"></div></div>`;
    return;
  }
  const t = turn;
  const fb = t.feedback;
  const warnHtml = t.warning ? `<div class="warning-box">${escapeHtml(t.warning)}</div>` : "";
  node.innerHTML = `<div class="bubble">
    ${warnHtml}
    <div class="answer">${md(t.answer || "")}</div>
    ${badgesHtml(t)}
    <div class="matn-box">${escapeHtml(t.matn || "").replace(/\n/g, "<br>")}</div>
    <div class="chips-row">
      <button data-act="toggle" data-k="sharh" data-uid="${t.uid}">الشرح ${t.open.sharh ? "▲" : "▼"}</button>
      <button data-act="toggle" data-k="bio" data-uid="${t.uid}">الراوي ${t.open.bio ? "▲" : "▼"}</button>
      <button data-act="toggle" data-k="related" data-uid="${t.uid}">ذات صلة ${t.open.related ? "▲" : "▼"}</button>
    </div>
    <div class="collapsible ${openCls(t.open, "sharh")}"><div class="inner"><div class="sharh-text">${escapeHtml(t.sharh || "لا يوجد شرح مسجل.")}</div></div></div>
    <div class="collapsible ${openCls(t.open, "bio")}"><div class="inner"><div class="sharh-text">${escapeHtml(t.bio || "لا توجد معلومات مسجلة.")}</div></div></div>
    <div class="collapsible ${openCls(t.open, "related")}"><div class="inner">${(t.related || []).map((r) =>
      `<button class="mini-card" data-act="open-related" data-uid="${t.uid}" data-hn="${r.hn}">${escapeHtml("حديث " + r.hn + ": " + r.title)}<small>التطابق: ${r.pct != null ? r.pct + "%" : "—"}</small></button>
       <div class="mini-snippet">${escapeHtml(r.snippet)}...</div>`).join("") || "<p>لا توجد أحاديث ذات صلة.</p>"}</div></div>
    <div class="chips-row">
      <button class="fb ${fb === "up" ? "active" : ""}" data-act="fb" data-v="up" data-uid="${t.uid}">👍</button>
      <button class="fb ${fb === "down" ? "active" : ""}" data-act="fb" data-v="down" data-uid="${t.uid}">👎</button>
      <button data-act="copy" data-uid="${t.uid}">نسخ الإجابة</button>
    </div>
    ${fb ? `<div class="thanks">شكرًا! تم تسجيل رأيك.</div>` : ""}
  </div>`;
}

function renderQuestion(text) {
  const node = document.createElement("div");
  node.className = "msg user";
  const b = document.createElement("div");
  b.className = "bubble";
  b.textContent = text;
  node.appendChild(b);
  chatEl.appendChild(node);
}

// ---------- الأحداث (تفويض واحد) ----------
chatEl.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const uid = Number(btn.dataset.uid);
  const turn = turns.find((t) => t.uid === uid);
  const act = btn.dataset.act;
  if (act === "toggle" && turn) {
    const k = btn.dataset.k;
    turn.open[k] = !turn.open[k];
    save();
    renderTurn(turn);
  } else if (act === "fb" && turn) {
    turn.feedback = btn.dataset.v;
    save();
    renderTurn(turn);
  } else if (act === "copy" && turn) {
    navigator.clipboard.writeText(turn.answer || "").then(() => {
      btn.textContent = "تم النسخ";
      setTimeout(() => { btn.textContent = "نسخ الإجابة"; }, 1500);
    }).catch(() => {});
  } else if (act === "open-related") {
    askQuestion("حدثني عن الحديث رقم " + btn.dataset.hn);
  }
});

// ---------- الإرسال والبث ----------
function lastExchange() {
  const done = [...turns].reverse().find((t) => t.done && !t.blocked && t.answer);
  return done ? { q: done.question, a: done.answer } : null;
}

async function askQuestion(question) {
  question = (question || "").trim();
  if (!question) return;
  renderQuestion(question);
  const prev = lastExchange();
  const turn = {
    uid: ++uidCounter, question, statusText: "جاري البحث...",
    answer: "", done: false, blocked: null,
    open: { sharh: false, bio: false, related: false },
    feedback: null,
  };
  turns.push(turn);
  save();
  renderTurn(turn);
  maybeScroll();
  startEl.style.display = "none";

  let answerEl = null;
  try {
    const resp = await fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        last_q: prev ? prev.q : null,
        last_a: prev ? prev.a : null,
      }),
    });
    if (!resp.ok || !resp.body) throw new Error("http-" + resp.status);
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    const findAnswer = () => {
      const node = document.getElementById("turn-" + turn.uid);
      return node ? node.querySelector(".answer-stream") : null;
    };
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const blocks = buf.split("\n\n");
      buf = blocks.pop();
      for (const b of blocks) {
        let ev = null, data = null;
        for (const line of b.split("\n")) {
          if (line.startsWith("event:")) ev = line.slice(6).trim();
          else if (line.startsWith("data:")) data = JSON.parse(line.slice(5));
        }
        if (ev === "status") {
          const map = { search: "جاري البحث...", generate: "جاري الصياغة...", fallback: "جاري تجربة مصدر بديل..." };
          turn.statusText = map[data.phase] || "جاري...";
          renderTurn(turn);
        } else if (ev === "restart") {
          turn.answer = "";
          if (answerEl) answerEl.textContent = "";
        } else if (ev === "token") {
          turn.answer += data.text;
          if (!answerEl) answerEl = findAnswer();
          if (answerEl) {
            answerEl.textContent += data.text;
            maybeScroll();
          }
        } else if (ev === "done") {
          if (data.blocked) {
            turn.blocked = data.message;
          } else {
            Object.assign(turn, {
              done: true, answer: data.answer, model: data.model,
              score: data.score ?? null,
              meta: data.top, matn: data.top.matn,
              related: data.related, sharh: data.sharh, bio: data.bio,
              warning: data.warning || null,
            });
          }
          save();
          renderTurn(turn);
        } else if (ev === "error") {
          turn.blocked = data.message;
          save();
          renderTurn(turn);
        }
      }
    }
  } catch (err) {
    turn.blocked = "عذرًا، حدث خطأ أثناء معالجة سؤالك. تحقق من الاتصال ثم حاول مجددًا.";
    save();
    renderTurn(turn);
  }
  maybeScroll();
}

// ---------- بدء التشغيل ----------
PRESETS.forEach((q) => {
  const b = document.createElement("button");
  b.textContent = q;
  b.onclick = () => askQuestion(q);
  presetsEl.appendChild(b);
});

turns.forEach((t) => {
  if (t.question) {
    renderQuestion(t.question);
    if (t.done || t.blocked) renderTurn(t);
    else { t.blocked = "انقطع الاتصال أثناء التوليد — أعد إرسال السؤال."; renderTurn(t); }
  }
});
if (turns.length) startEl.style.display = "none";

formEl.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = inputEl.value.trim();
  if (!q) return;
  inputEl.value = "";
  inputEl.style.height = "auto";
  askQuestion(q);
});

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    formEl.requestSubmit();
  }
});

inputEl.addEventListener("input", () => {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
});
