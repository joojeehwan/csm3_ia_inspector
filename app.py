import chainlit as cl
import os
from datetime import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv
from openai import AzureOpenAI
from retrivers.internal_search import hybrid_search
from retrivers.agents_web_qa import ask_via_agent, ask_via_agent_with_sources
from rag.prompst import QA_PROMPT, IA_SUMMARY_PROMPT
from pathlib import Path
from pypdf import PdfReader
import importlib
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from ingest.build_chunks import simple_chunks, embed_batch
from urllib.parse import urlparse

USE_LANGGRAPH = os.getenv("USE_LANGGRAPH", "false").lower() in ("1", "true", "yes")
_LG_AVAILABLE = False
if USE_LANGGRAPH:
    try:
        from graphs.orchestrator import run_query as lg_run_query
        _LG_AVAILABLE = True
    except Exception as _e:
        _LG_AVAILABLE = False

load_dotenv()

# --- Mode labels (UI) and internal codes ---
MODE_LABELS = {
    "qa": "IA 검색",
    "web_qa": "웹 검색",
    "ia_summary": "IA 요약",
}
REVERSE_MODE_LABELS = {v: k for k, v in MODE_LABELS.items()}

# --- Chainlit Data Persistence & Auth Setup ---
# Enable persistence with the community SQLAlchemy data layer using SQLite by default.
# Users can override via DATABASE_URL (e.g., postgres) per Chainlit docs.
from typing import Optional
try:
    from chainlit.data.sql_alchemy import SQLAlchemyDataLayer  # type: ignore
    _HAVE_SQLA = True
except Exception as _e:
    _HAVE_SQLA = False

if _HAVE_SQLA:
    @cl.data_layer
    def get_data_layer():
        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./chainlit.db")
        # Note: For Windows+relative path, file will be created next to app.
        print(f"[Chainlit] Data layer: SQLAlchemy enabled (conn={db_url})")
        return SQLAlchemyDataLayer(conninfo=db_url)
else:
    print("[Chainlit] Data layer: DISABLED (chainlit.data.sql_alchemy not available)")


# Minimal password auth to enable history sidebar (requires CHAINLIT_AUTH_SECRET env).
# Only register auth when CHAINLIT_AUTH_SECRET is present to avoid startup errors.
if os.getenv("CHAINLIT_AUTH_SECRET"):
    print("[Chainlit] Auth: SECRET present → authentication enabled")
    # Optional: auto-auth without user interaction (sidebar history without login)
    if os.getenv("DEV_AUTO_AUTH", "").lower() in ("1", "true", "yes"):
        print("[Chainlit] Auth: DEV_AUTO_AUTH enabled → auto header auth active")
        @cl.header_auth_callback
        def auto_header_auth(headers: Dict[str, Any]):  # type: ignore
            user_id = os.getenv("CHAINLIT_AUTO_USER", "guest")
            return cl.User(identifier=user_id, metadata={"provider": "auto"})

    @cl.password_auth_callback
    def auth_callback(username: str, password: str):
        u = os.getenv("CHAINLIT_USERNAME")
        p = os.getenv("CHAINLIT_PASSWORD")
        if u and p and (username == u) and (password == p):
            return cl.User(identifier=username, metadata={"provider": "password"})
        return None
else:
    # No auth configured. App remains public; chat history sidebar will be hidden.
    print("[Chainlit] Auth: SECRET missing → app is public, sidebar history hidden")


@cl.on_chat_resume
async def on_chat_resume(thread):
    await cl.Message(content="이전 대화를 불러왔습니다. 이어서 질문하세요.").send()

AOAI_ENDPOINT=os.getenv("AZURE_OPENAI_ENDPOINT")
AOAI_KEY=os.getenv("AZURE_OPENAI_API_KEY")
AOAI_VER=os.getenv("AZURE_OPENAI_API_VERSION")
CHAT_DEPLOY=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
client = AzureOpenAI(azure_endpoint=AOAI_ENDPOINT, api_key=AOAI_KEY, api_version=AOAI_VER)

# Search client for upserting uploaded chunks
SEARCH_ENDPOINT=os.getenv("SEARCH_ENDPOINT")
SEARCH_API_KEY=os.getenv("SEARCH_API_KEY")
INDEX_CHUNKS=os.getenv("INDEX_CHUNKS","ia-chunks")
_search_chunks = SearchClient(SEARCH_ENDPOINT, INDEX_CHUNKS, AzureKeyCredential(SEARCH_API_KEY))

# UI snippet preview length (configurable via env)
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except Exception:
        return default

SNIPPET_PREVIEW_CHARS = _env_int("SNIPPET_PREVIEW_CHARS", 400)

def _preview_text(text: str, n: int = None) -> str:
    if n is None:
        n = SNIPPET_PREVIEW_CHARS
    if not text:
        return ""
    return text if len(text) <= n else (text[:n] + "…")

"""In-chat history panel features removed for a cleaner UI."""

def _format_snippets(hits):
    rows = []
    for h in hits:
        title = h.get("title", "")
        page = h.get("page")
        uri = h.get("source_uri", "")
        chunk = (_preview_text(h.get("chunk", ""), 500)).replace("\n", " ")
        page_part = f" p.{page}" if page not in (None, "") else ""
        rows.append(f"- {title}{page_part}: {chunk} [src: {uri}]")
    return "\n".join(rows)


def _sanitize_hits_for_log(hits):
    out=[]
    for h in hits:
        out.append({
            "title": h.get("title",""),
            "page": h.get("page"),
            "source_uri": h.get("source_uri",""),
        })
    return out


def _format_source_for_table(uri: str) -> str:
    if not uri:
        return "-"
    try:
        if uri.startswith("upload://"):
            return uri.replace("upload://", "📄 ")
        u = urlparse(uri)
        dom = u.netloc or uri
        return f"{dom} · [열기]({uri})"
    except Exception:
        return uri


def _hits_table_markdown(hits: List[dict], max_rows: int = 5, preview_chars: int = 140):
    rows = ["| # | 제목 | p. | 출처 | 미리보기 |", "|:-:|:--|:-:|:--|:--|"]
    action_map = []  # list of (label, rid)
    for i, h in enumerate(hits[:max_rows], start=1):
        title = (h.get("title") or "(제목없음)").replace("|", " ")
        page = h.get("page")
        rid = str(h.get("id") or os.urandom(8).hex())
        src = _format_source_for_table(h.get("source_uri", ""))
        preview = _preview_text(h.get("chunk", ""), preview_chars).replace("\n", " ")
        rows.append(f"| {i} | {title} | {page or '-'} | {src} | {preview} |")
        action_map.append((f"전체 보기 #{i}", rid))
    return "\n".join(rows), action_map


def _render_log_entry(idx: int, entry: dict) -> str:
    lines = [f"#{idx+1} [{entry.get('mode','qa')}] {entry.get('question','')}"]
    f = entry.get("filter")
    if f:
        lines.append(f"- 필터: {f}")
    lines.append(f"- 시간: {entry.get('ts','')}")
    hits = entry.get("hits", [])
    if not hits:
        lines.append("(근거 없음)")
    else:
        for i, h in enumerate(hits[:10], start=1):
            page_part = f" p.{h.get('page')}" if h.get('page') not in (None, "") else ""
            lines.append(f"  {i}. {h.get('title','')} {page_part} — {h.get('source_uri','')}")
    return "\n".join(lines)


def _read_pdf(path: str) -> str:
    reader = PdfReader(path)
    texts = []
    for i, page in enumerate(reader.pages, start=1):
        t = page.extract_text() or ""
        texts.append(f"[Page {i}]\n{t}")
    return "\n\n".join(texts)


def _read_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _read_docx(path: str) -> str:
    try:
        docx_mod = importlib.import_module("docx")
        _Docx = getattr(docx_mod, "Document")
    except Exception:
        raise RuntimeError("DOCX 지원을 위해 'python-docx' 패키지를 설치하세요 (requirements.txt).")
    doc = _Docx(path)
    paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    return "\n\n".join(paras)


async def _summarize_and_keywords(text: str) -> Dict[str, Any]:
    sample = text[:6000]  # token 보호를 위해 길이 제한
    sum_prompt = (
        "다음 문서를 한국어로 5문장 이내로 요약하고, 주요 주제 3가지를 불릿으로 제시하세요.\n\n" + sample
    )
    kw_prompt = (
        "다음 문서의 핵심 키워드 8개만 콤마로 나열해 주세요 (짧고 보편적인 형태).\n\n" + sample
    )
    s_resp = client.chat.completions.create(
        model=CHAT_DEPLOY,
        messages=[{"role":"system","content":"You are a concise summarizer."},{"role":"user","content":sum_prompt}],
        temperature=0.2
    )
    summary = s_resp.choices[0].message.content
    k_resp = client.chat.completions.create(
        model=CHAT_DEPLOY,
        messages=[{"role":"system","content":"Extract keywords."},{"role":"user","content":kw_prompt}],
        temperature=0
    )
    kws_raw = k_resp.choices[0].message.content
    # normalize keywords → hashtags
    parts = [p.strip().lstrip("-•").strip() for p in (kws_raw or "").replace("\n", ",").split(",")]
    parts = [p for p in parts if p]
    hashtags = sorted({("#"+p.replace(" ", "")).lower() for p in parts})[:12]
    return {"summary": summary, "hashtags": hashtags}


def _recommend_similar(doc_id: str, top: int = 5):
    try:
        return hybrid_search("이 문서와 유사한 내용", top=top, filter=f"doc_id ne '{doc_id}'")
    except Exception:
        return []


def _upsert_chunks(doc_id: str, title: str, source_uri: str, text: str, system: str = "upload") -> int:
    parts = simple_chunks(text, 1200, 150)
    if not parts:
        return 0
    vecs = embed_batch(parts)
    year = datetime.utcnow().year
    batch = []
    for t, v in zip(parts, vecs):
        batch.append({
            "id": os.urandom(8).hex(),
            "doc_id": doc_id,
            "title": title,
            "chunk": t,
            "contentVector": v,
            "source_uri": source_uri,
            "system": system,
            "year": year,
        })
    _search_chunks.upload_documents(batch)
    return len(batch)

@cl.on_chat_start
async def start():
    from chainlit.input_widget import Select, Slider, TextInput, Switch
    # Display labels in UI
    modes = [MODE_LABELS["qa"], MODE_LABELS["ia_summary"]]
    # Expose 웹 검색 only when an Azure OpenAI Agent ID is configured
    if os.getenv("AZURE_EXISTING_AGENT_ID") or os.getenv("AZURE_AGENT_ID"):
        modes.insert(1, MODE_LABELS["web_qa"])
    settings = await cl.ChatSettings(inputs=[
        Select(id="mode", label="모드", values=modes, initial_index=0),
        Slider(id="top_k", label="상위 K", min=3, max=20, step=1, initial=8),
        TextInput(id="filter", label="OData 필터(선택)", placeholder="예) system eq 'kb' and year ge 2023"),
        Switch(id="show_log", label="결과 후 로그 보기", initial=False),
    ]).send()
    cl.user_session.set("settings", settings)
    cl.user_session.set("history", [])
    cl.user_session.set("uploads", [])
    # Initialize forced filter (used by use_filter/clear_filter actions)
    cl.user_session.set("forced_filter", None)
    # Minimal intro message without panel references
    await cl.Message(content=(
        "질문을 입력하면 검색과 요약을 수행합니다.\n"
        "- /업로드 : 문서 업로드 및 분석\n- /업로드목록 : 업로드 목록\n"
        "- /기록 : 최근 검색 목록\n- /보기 N : N번째 검색 로그\n- /대시보드 : 간단 통계"
    )).send()

@cl.on_settings_update
async def on_settings_update(s):
    cl.user_session.set("settings", s)
    mode_label = s.get("mode"); tk = s.get("top_k"); filt = s.get("filter"); show_log = s.get("show_log")
    # Keep the computed internal mode in session for convenience
    cl.user_session.set("mode_internal", REVERSE_MODE_LABELS.get(mode_label, "qa"))
    await cl.Message(content=f"설정이 업데이트되었습니다. 모드={mode_label}, 상위K={tk}, 필터={filt or '-'}, 로그표시={bool(show_log)} (세션 한정)").send()


def _normalize_command(text: str) -> str:
    t = (text or "").strip()
    if not t.startswith("/"):
        return ""
    head = t.split()[0].lower()
    ko_map = {
        "/업로드": "upload",
        "/업로드목록": "uploads",
        "/기록": "history",
        "/보기": "show",
        "/대시보드": "dashboard",
        "/통계": "dashboard",
    }
    en_map = {
        "/upload": "upload",
        "/uploads": "uploads",
        "/history": "history",
        "/show": "show",
        "/dashboard": "dashboard",
    }
    return ko_map.get(head) or en_map.get(head) or ""

@cl.on_message
async def on_message(msg: cl.Message):
    # quick commands to inspect history (Korean aliases supported)
    cmd = _normalize_command(msg.content)
    if cmd == "history":
        history = cl.user_session.get("history", [])
        if not history:
            await cl.Message(content="히스토리가 비어있습니다.").send()
        else:
            parts = ["세션 히스토리 (최근 5개):"]
            for i, e in list(enumerate(history))[-5:]:
                parts.append(f" - {i+1}) [{e.get('mode')}] {e.get('question')}")
            parts.append("\n자세히 보려면 '/보기 N' 을 입력하세요 (예: /보기 2)")
            await cl.Message(content="\n".join(parts)).send()
        return
    if cmd == "dashboard":
        uploads = cl.user_session.get("uploads", [])
        n_docs = len(uploads)
        n_chunks = sum(u.get("chunks", 0) for u in uploads)
        all_tags = []
        for u in uploads:
            all_tags.extend(u.get("hashtags", []))
        tag_counts = {}
        for t in all_tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ck_total = sum(len(u.get("checklist", [])) for u in uploads)
        ck_done = sum(sum(1 for c in u.get("checklist", []) if c.get("done")) for u in uploads)
        rate = (ck_done / ck_total * 100) if ck_total else 0
        lines = [
            "📊 분석 대시보드",
            f"- 업로드 문서 수: {n_docs}",
            f"- 인덱싱된 청크 수: {n_chunks}",
            f"- 체크리스트 완료율: {ck_done}/{ck_total} ({rate:.0f}%)",
        ]
        if top_tags:
            lines.append("- 상위 키워드: " + ", ".join([f"{k}×{v}" for k, v in top_tags]))
        await cl.Message(content="\n".join(lines)).send()
        return
    if cmd == "uploads":
        uploads = cl.user_session.get("uploads", [])
        if not uploads:
            await cl.Message(content="업로드 이력이 없습니다.").send(); return
        lines = ["업로드 문서 목록:"]
        for i, u in enumerate(uploads, start=1):
            lines.append(f" {i}. {u.get('title')} — {u.get('ts','')}")
        lines.append("\n문서 상세는 아래 버튼을 사용하세요.")
        await cl.Message(
            content="\n".join(lines),
            actions=[cl.Action(name="show_upload", value="last", description="최근 업로드 보기")]
        ).send()
        return
    if cmd == "upload":
        files = await cl.AskFileMessage(
            content="분석할 파일을 업로드하세요 (PDF, DOCX, TXT)",
            accept=["application/pdf","text/plain","application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
            max_size_mb=25,
            max_files=5
        ).send()
        if not files:
            await cl.Message(content="파일이 선택되지 않았습니다.").send(); return
        await cl.Message(content=f"📤 {len(files)}개 파일 처리 중…").send()
        for f in files:
            path = f.path; name = f.name
            ext = Path(name).suffix.lower()
            try:
                if ext == ".pdf":
                    text = _read_pdf(path)
                elif ext == ".txt":
                    text = _read_txt(path)
                elif ext == ".docx":
                    text = _read_docx(path)
                else:
                    await cl.Message(content=f"지원하지 않는 형식: {name}").send(); continue
            except Exception as e:
                await cl.Message(content=f"파일 읽기 실패: {name} — {e}").send(); continue

            doc_id = Path(name).stem + "-" + os.urandom(3).hex()
            source_uri = f"upload://{name}"
            try:
                n_chunks = _upsert_chunks(doc_id, name, source_uri, text, system="upload")
            except Exception as e:
                await cl.Message(content=f"인덱싱 실패: {name} — {e}").send(); continue

            # summarize & keywords
            try:
                sk = await _summarize_and_keywords(text)
            except Exception as e:
                sk = {"summary": "(요약 실패)", "hashtags": []}

            # similar docs (best effort)
            sim = _recommend_similar(doc_id, top=5)
            sim_safe = _sanitize_hits_for_log(sim)

            # basic checklist from summary
            checklist: List[Dict[str, Any]] = []
            ck_prompt = (
                "다음 문서를 기반으로 검토해야 할 체크리스트 항목 6개를 간단한 한 줄로 제안해 주세요. 각 항목은 하이픈(-)으로 시작하세요.\n\n"
                + (sk.get("summary") or text[:1000])
            )
            try:
                ck_resp = client.chat.completions.create(
                    model=CHAT_DEPLOY,
                    messages=[{"role":"system","content":"Generate checklist."},{"role":"user","content":ck_prompt}],
                    temperature=0.1
                )
                ck_text = ck_resp.choices[0].message.content
                for line in (ck_text or "").splitlines():
                    t = line.strip().lstrip("-•").strip()
                    if t:
                        checklist.append({"text": t, "done": False})
                checklist = checklist[:10]
            except Exception:
                pass

            # save upload record
            uploads = cl.user_session.get("uploads", [])
            rec = {
                "doc_id": doc_id,
                "title": name,
                "chunks": n_chunks,
                "summary": sk.get("summary",""),
                "hashtags": sk.get("hashtags", []),
                "similar": sim_safe,
                # "checklist": checklist,
                "ts": datetime.utcnow().isoformat(timespec='seconds') + 'Z'
            }
            uploads.append(rec)
            cl.user_session.set("uploads", uploads)

            # Render card
            lines = [
                f"✅ 업로드 완료: {name}",
                f"- doc_id: {doc_id}",
                f"- 청크 수: {n_chunks}",
                "",
                "요약:",
                (rec["summary"][:1200] + ("…" if len(rec["summary"])>1200 else "")),
                "",
                "키워드:",
                (" ".join(rec["hashtags"]) or "(없음)"),
            ]
            if rec["similar"]:
                lines.append("\n유사 문서:")
                for i, h in enumerate(rec["similar"][:5], start=1):
                    page_part = f" p.{h.get('page')}" if h.get('page') not in (None, "") else ""
                    lines.append(f"  {i}. {h.get('title','')} {page_part} — {h.get('source_uri','')}")
            idx = len(uploads) - 1
            await cl.Message(
                content="\n".join(lines),
                actions=[
                    cl.Action(name="show_upload", value=str(idx), description="업로드 상세 보기"),
                    cl.Action(name="show_history", value="all", description="세션 히스토리 보기"),
                ],
            ).send()
        return
    if cmd == "show":
        try:
            idx = int(msg.content.strip().split()[1]) - 1
        except Exception:
            await cl.Message(content="형식: /보기 N").send(); return
        history = cl.user_session.get("history", [])
        if 0 <= idx < len(history):
            await cl.Message(content=_render_log_entry(idx, history[idx])).send()
        else:
            await cl.Message(content="해당 번호의 히스토리가 없습니다.").send()
        return
    settings = cl.user_session.get("settings", {})
    mode_label = settings.get("mode", MODE_LABELS["qa"])  # UI label
    mode = REVERSE_MODE_LABELS.get(mode_label, "qa")        # internal code
    try:
        top_k = int(settings.get("top_k", 8) or 8)
    except Exception:
        top_k = 8
    filter_parts = []
    if settings.get("filter"):
        filter_parts.append(settings.get("filter"))
    forced = cl.user_session.get("forced_filter")
    if forced:
        filter_parts.append(forced)
    filter_str = " and ".join([f"({p})" for p in filter_parts]) or None
    show_log = bool(settings.get("show_log", False))
    await cl.Message(content=f"🔎 검색 중… ({mode_label})").send()

    if _LG_AVAILABLE and mode != "web_qa":
        try:
            answer, hits = lg_run_query(mode, msg.content)
        except Exception as e:
            await cl.Message(content=f"LangGraph 실행 오류: {e}\n일반 모드로 재시도합니다.").send()
            # fall back to non-LangGraph path
            _lg = False
        else:
            _lg = True
        if _LG_AVAILABLE and '_lg' in locals() and _lg:
            await cl.Message(content=answer).send()
            if hits:
                # cache last hits for full-view actions
                last_hits_map = {}
                for h in hits:
                    rid = h.get("id") or os.urandom(8).hex()
                    last_hits_map[str(rid)] = h
                cl.user_session.set("last_hits_map", last_hits_map)

                md, actions = _hits_table_markdown(hits)
                await cl.Message(content="**근거 (상위 5)**\n\n" + md).send()
                # Cache for snippet opens
                last_hits_map = {}
                for h in hits[:5]:
                    rid = str(h.get("id") or os.urandom(8).hex())
                    last_hits_map[rid] = h
                cl.user_session.set("last_hits_map", last_hits_map)
                # Snippet action buttons removed per request – table only
            # log history and provide quick actions
            history = cl.user_session.get("history", [])
            history.append({
                "mode": MODE_LABELS.get(mode, mode),
                "question": msg.content,
                "filter": filter_str,
                "hits": _sanitize_hits_for_log(hits),
                "ts": datetime.utcnow().isoformat(timespec='seconds') + 'Z'
            })
            cl.user_session.set("history", history)
            idx = len(history) - 1
            if show_log:
                await cl.Message(content=_render_log_entry(idx, history[idx])).send()
            else:
                await cl.Message(
                    content="로그 액션",
                    actions=[
                        cl.Action(name="show_log", value=str(idx), description="이번 검색 로그 보기"),
                        cl.Action(name="show_history", value="all", description="세션 히스토리 보기"),
                    ],
                ).send()
            return

    if mode == "web_qa":
        # Use Azure OpenAI Agents path (agent must have Bing Search connection)
        if not (os.getenv("AZURE_EXISTING_AGENT_ID") or os.getenv("AZURE_AGENT_ID")):
            await cl.Message(content=(
                "웹 검색 모드는 Azure OpenAI 에이전트가 필요합니다.\n"
                "Azure AI Foundry(services.ai) 프로젝트에서 에이전트를 만들고 Bing Search 연결을 추가한 뒤, \n"
                ".env에 AZURE_AGENT_ID=asst_...를 설정하세요. App Service에서는 시스템 할당 관리 ID(MSI)를 활성화하고 프로젝트에 권한을 부여하면 로그인 없이 동작합니다."
            )).send()
            return
        try:
            answer, sources = ask_via_agent_with_sources(msg.content)
            await cl.Message(content=answer).send()
            hits = []
            if sources:
                await cl.Message(content="**출처**").send()
                for s in sources[:6]:
                    title = s.get("title") or "(출처)"
                    url = s.get("url") or ""
                    snip = s.get("snippet") or ""
                    preview = _preview_text(snip, 300)
                    domain = ""
                    favicon = ""
                    try:
                        if url:
                            u = urlparse(url)
                            domain = u.netloc
                            # Try site favicon
                            favicon = f"{u.scheme}://{u.netloc}/favicon.ico"
                    except Exception:
                        pass
                    # Card-like markdown: favicon + title link + snippet + domain + open link
                    lines = []
                    if favicon:
                        lines.append(f"![icon]({favicon}) ")
                    lines.append(f"**[{title}]({url})**")
                    if domain:
                        lines.append(f"\n_{domain}_")
                    if preview:
                        lines.append(f"\n{preview}")
                    lines.append(f"\n[🔗 링크 열기]({url})")
                    await cl.Message(content="".join(lines)).send()
            history = cl.user_session.get("history", [])
            history.append({
                "mode": MODE_LABELS.get(mode, mode),
                "question": msg.content,
                "filter": None,
                "hits": _sanitize_hits_for_log(hits),
                "ts": datetime.utcnow().isoformat(timespec='seconds') + 'Z'
            })
            cl.user_session.set("history", history)
            idx = len(history) - 1
            if show_log:
                await cl.Message(content=_render_log_entry(idx, history[idx])).send()
            else:
                await cl.Message(
                    content="로그 보기",
                    actions=[
                        cl.Action(name="show_log", value=str(idx), description="이번 검색 로그 보기"),
                        cl.Action(name="show_history", value="all", description="세션 히스토리 보기"),
                    ],
                ).send()
            return
        except Exception as e:
            await cl.Message(content=f"에이전트(웹 검색) 호출 실패: {e}").send()
            return
    else:
        hits = hybrid_search(msg.content, top=top_k, filter=filter_str)
        # If no hits, avoid hallucination by not calling the LLM
        if not hits:
            msg_lines = [
                "📭 관련 근거를 찾지 못했습니다.",
                "- 검색어를 바꾸거나 필터를 조정해 보세요.",
            ]
            if cl.user_session.get("forced_filter"):
                msg_lines.append("- 현재 문서 한정 필터가 적용되어 있습니다. '문서 한정 해제' 버튼으로 해제하세요.")
            await cl.Message(content="\n".join(msg_lines)).send()

            # save to history with empty hits
            history = cl.user_session.get("history", [])
            history.append({
                "mode": MODE_LABELS.get(mode, mode),
                "question": msg.content,
                "filter": filter_str,
                "hits": [],
                "ts": datetime.utcnow().isoformat(timespec='seconds') + 'Z'
            })
            cl.user_session.set("history", history)
            idx = len(history) - 1
            if show_log:
                await cl.Message(content=_render_log_entry(idx, history[idx])).send()
            else:
                await cl.Message(
                    content="로그 보기",
                    actions=[
                        cl.Action(name="show_log", value=str(idx), description="이번 검색 로그 보기"),
                        cl.Action(name="show_history", value="all", description="세션 히스토리 보기"),
                    ],
                ).send()
            return
        # Build prompt only when hits exist
        snippets = _format_snippets(hits)
        prompt = (IA_SUMMARY_PROMPT if mode=="ia_summary" else QA_PROMPT).format(
            question=msg.content, snippets=snippets
        )

    resp = client.chat.completions.create(
        model=CHAT_DEPLOY,
        messages=[
            {"role":"system","content":"You are a helpful, factual assistant."},
            {"role":"user","content": prompt}
        ],
        temperature=0.2
    )
    answer = resp.choices[0].message.content
    await cl.Message(content=answer).send()

    if hits:
        # cache and compact evidence rendering
        md, actions = _hits_table_markdown(hits)
        await cl.Message(content="**근거 (상위 5)**\n\n" + md).send()
        last_hits_map = {}
        for h in hits[:5]:
            rid = str(h.get("id") or os.urandom(8).hex())
            last_hits_map[rid] = h
        cl.user_session.set("last_hits_map", last_hits_map)
    # Snippet action buttons removed per request – table only

    # save to history and provide actions
    history = cl.user_session.get("history", [])
    history.append({
        "mode": MODE_LABELS.get(mode, mode),
        "question": msg.content,
        "filter": filter_str,
        "hits": _sanitize_hits_for_log(hits),
        "ts": datetime.utcnow().isoformat(timespec='seconds') + 'Z'
    })
    cl.user_session.set("history", history)
    idx = len(history) - 1
    if show_log:
        await cl.Message(content=_render_log_entry(idx, history[idx])).send()
    else:
        await cl.Message(
            content="로그 보기",
            actions=[
                cl.Action(name="show_log", value=str(idx), description="이번 검색 로그 보기"),
                cl.Action(name="show_history", value="all", description="세션 히스토리 보기"),
            ],
        ).send()
    # No in-chat panel refresh (feature removed)


@cl.action_callback("show_log")
async def show_log(action):
    history = cl.user_session.get("history", [])
    try:
        idx = int(action.value)
    except Exception:
        idx = len(history) - 1
    if 0 <= idx < len(history):
        await cl.Message(content=_render_log_entry(idx, history[idx])).send()
    else:
        await cl.Message(content="히스토리가 비어있습니다.").send()


@cl.action_callback("show_history")
async def show_history(action):
    history = cl.user_session.get("history", [])
    if not history:
        await cl.Message(content="히스토리가 비어있습니다.").send(); return
    parts = ["세션 히스토리 (최근 5개):"]
    for i, e in list(enumerate(history))[-5:]:
        parts.append(f" - {i+1}) [{e.get('mode')}] {e.get('question')}")
    parts.append("\n자세히 보려면 '/보기 N' 을 입력하세요 (예: /보기 2)")
    await cl.Message(content="\n".join(parts)).send()


# Removed: toggle_history_panel, replay_query (no panel)


@cl.action_callback("show_upload")
async def show_upload(action):
    uploads = cl.user_session.get("uploads", [])
    if not uploads:
        await cl.Message(content="업로드 이력이 없습니다.").send(); return
    if action.value == "last":
        idx = len(uploads) - 1
    else:
        try:
            idx = int(action.value)
        except Exception:
            idx = len(uploads) - 1
    if not (0 <= idx < len(uploads)):
        await cl.Message(content="해당 업로드를 찾을 수 없습니다.").send(); return
    u = uploads[idx]
    # render
    lines = [
        f"📄 업로드 상세: {u.get('title')}",
        f"- doc_id: {u.get('doc_id')}",
        f"- 청크 수: {u.get('chunks')}",
        "",
        "요약:",
        (u.get("summary", "")[:1500] + ("…" if len(u.get("summary",""))>1500 else "")),
        "",
        "키워드:",
        (" ".join(u.get("hashtags", [])) or "(없음)"),
    ]
    if u.get("similar"):
        lines.append("\n유사 문서:")
        for i, h in enumerate(u["similar"][:5], start=1):
            page_part = f" p.{h.get('page')}" if h.get('page') not in (None, "") else ""
            lines.append(f"  {i}. {h.get('title','')} {page_part} — {h.get('source_uri','')}")
    ck = u.get("checklist", [])
    if ck:
        done = sum(1 for c in ck if c.get("done"))
        lines.append(f"\n체크리스트 ({done}/{len(ck)} 완료):")
        for i, c in enumerate(ck, start=1):
            lines.append(f"  [{'x' if c.get('done') else ' '}] {i}. {c.get('text')}")
    await cl.Message(
        content="\n".join(lines),
    actions=[
        cl.Action(name="use_filter", value=u.get("doc_id",""), description="이 문서로 검색 한정"),
        cl.Action(name="clear_filter", value="", description="문서 한정 해제"),
    ],
    ).send()


@cl.action_callback("use_filter")
async def use_filter(action):
    doc_id = str(action.value or "").strip()
    if not doc_id:
        await cl.Message(content="doc_id가 비어있습니다.").send(); return
    filt = f"doc_id eq '{doc_id}'"
    cl.user_session.set("forced_filter", filt)
    await cl.Message(content=f"필터 적용됨: {filt}").send()


@cl.action_callback("clear_filter")
async def clear_filter(action):
    cl.user_session.set("forced_filter", None)
    await cl.Message(content="문서 한정 필터가 해제되었습니다.").send()
