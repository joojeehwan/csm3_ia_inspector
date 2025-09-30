import chainlit as cl
import os
import re
from datetime import datetime, timedelta
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
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.identity import DefaultAzureCredential

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


def _uploads_page_size() -> int:
    # Page size for uploads list; defaults to 10
    return _env_int("UPLOADS_PAGE_SIZE", 10)


async def _send_uploads_list(page: int = 0):
    uploads = cl.user_session.get("uploads", [])
    if not uploads:
        await cl.Message(content="업로드 이력이 없습니다.").send();
        return
    n = len(uploads)
    ps = _uploads_page_size()
    # Newest first: build reversed indices
    rev_indices = list(range(n - 1, -1, -1))
    total_pages = max(1, (n + ps - 1) // ps)
    page = max(0, min(page, total_pages - 1))
    start = page * ps
    end = min(len(rev_indices), start + ps)
    view_indices = rev_indices[start:end]

    # Header
    lines = [f"업로드 문서 목록 (총 {n}개) — 페이지 {page+1}/{total_pages}"]
    for disp_i, idx in enumerate(view_indices, start=1):
        u = uploads[idx]
        # Use page-local numbering like "1)" to avoid Markdown auto-lists
        lines.append(f" {disp_i}) {u.get('title')} — {u.get('ts','')}")
    lines.append("")
    lines.append("상세 보기: 가장 최신 3 개 항목만 버튼으로 제공됩니다.")

    # Detail actions for latest 3 overall
    actions = []
    latest_count = min(3, n)
    for k in range(latest_count):
        latest_idx = n - 1 - k
        title = uploads[latest_idx].get("title") or f"업로드 {latest_idx+1}"
        actions.append(cl.Action(name="show_upload", value=str(latest_idx), description=f"최근 {k+1}번: {title}"))

    # Pagination actions
    if page > 0:
        actions.append(cl.Action(name="uploads_page_prev", value=str(page-1), description="이전 페이지"))
    if page < total_pages - 1:
        actions.append(cl.Action(name="uploads_page_next", value=str(page+1), description="다음 페이지"))

    # Remember page in session
    cl.user_session.set("uploads_page", page)
    await cl.Message(content="\n".join(lines), actions=actions).send()

def _preview_text(text: str, n: int = None) -> str:
    if n is None:
        n = SNIPPET_PREVIEW_CHARS
    if not text:
        return ""
    return text if len(text) <= n else (text[:n] + "…")

def _strip_inline_source_markers(text: str) -> str:
    """Remove inline citation tokens like 【3:0†source】 that can appear in agent answers."""
    if not text:
        return text
    try:
        cleaned = re.sub(r"【[^】]*?source】", "", text, flags=re.IGNORECASE)
        # Collapse excessive spaces/newlines
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()
    except Exception:
        return text

"""In-chat history panel features removed for a cleaner UI."""

def _format_snippets(hits):
    rows = []
    for h in hits:
        title = h.get("title", "")
        chunk = (_preview_text(h.get("chunk", ""), 500)).replace("\n", " ")
        # Keep prompt context clean: exclude raw source refs and page indicators
        if title:
            rows.append(f"- {title}: {chunk}")
        else:
            rows.append(f"- {chunk}")
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


def _highlight(text: str, query: str) -> str:
    if not text or not query:
        return text or ""
    try:
        # naive token highlight on words >= 2 chars
        toks = [t for t in set(query.replace("\n"," ").split()) if len(t) >= 2]
        out = text
        for t in sorted(toks, key=len, reverse=True):
            out = re.sub(re.escape(t), f"**{t}**", out, flags=re.IGNORECASE)
        return out
    except Exception:
        return text

def _query_tokens(q: str) -> List[str]:
    if not q:
        return []
    try:
        # Extract words and Korean blocks; drop very short tokens
        toks = re.findall(r"[\w가-힣]+", q, flags=re.IGNORECASE)
        toks = [t.lower() for t in toks if len(t) >= 2 and not t.startswith('/')]
        # de-dup while preserving length-based relevance
        return sorted(set(toks), key=len, reverse=True)
    except Exception:
        return [t for t in (q or '').split() if len(t) >= 2]

def _is_relevant_hits(hits: List[dict], query: str, k: int = 3) -> bool:
    """Heuristic guard: require token overlap in at least 2 of the top-k hits.
    Returns True if >= 2 hits contain any query token.
    """
    toks = _query_tokens(query)
    if not toks:
        return False
    k = max(1, k)
    match_hits = 0
    for h in hits[:k]:
        title = (h.get('title') or '').lower()
        chunk = (h.get('chunk') or '').lower()
        blob = f"{title}\n{chunk}"
        if any(t in blob for t in toks):
            match_hits += 1
    return match_hits >= 2 or (match_hits >= 1 and k == 1)


def _group_hits_by_doc(hits: List[dict]) -> List[dict]:
    groups: Dict[str, dict] = {}
    order: List[str] = []
    for h in hits:
        key = h.get("doc_id") or (h.get("source_uri") or h.get("title") or os.urandom(4).hex())
        if key not in groups:
            groups[key] = {"title": h.get("title") or "(제목없음)", "source_uri": h.get("source_uri",""), "items": []}
            order.append(key)
        groups[key]["items"].append(h)
    return [groups[k] for k in order]


def _hits_table_markdown(hits: List[dict], max_rows: int = 5, preview_chars: int = 140, query: str = ""):
    # Group by document; show one line per doc with first snippet preview
    groups = _group_hits_by_doc(hits)
    rows = ["| # | 제목 | 출처 | 미리보기 |", "|:-:|:--|:--|:--|"]
    action_map = []
    for i, g in enumerate(groups[:max_rows], start=1):
        title = (g.get("title") or "(제목없음)").replace("|"," ")
        src = _format_source_for_table(g.get("source_uri",""))
        first = g.get("items", [{}])[0]
        preview = _preview_text(first.get("chunk",""), preview_chars).replace("\n"," ")
        preview = _highlight(preview, query)
        rows.append(f"| {i} | {title} | {src} | {preview} |")
        action_map.append((f"전체 보기 #{i}", str(first.get("id") or os.urandom(8).hex())))
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
            lines.append(f"  {i}. {h.get('title','')} — {h.get('source_uri','')}")
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


# ===== Azure Blob helpers =====
def _get_blob_container_client():
    """Create a Blob container client using either connection string or MSI.

    Env options:
    - BLOB_CONNECTION_STRING + BLOB_CONTAINER (default: ia-source)
    - or STORAGE_ACCOUNT_URL (e.g., https://<account>.blob.core.windows.net) + BLOB_CONTAINER with DefaultAzureCredential
    Returns (client, container_url) or (None, None) if not configured.
    """
    try:
        container = os.getenv("BLOB_CONTAINER", "ia-source")
        conn = os.getenv("BLOB_CONNECTION_STRING")
        if conn:
            svc = BlobServiceClient.from_connection_string(conn)
            client = svc.get_container_client(container)
            try:
                client.create_container()
            except Exception:
                pass
            return client, client.url
        # MSI / Workload identity path
        acct_url = os.getenv("STORAGE_ACCOUNT_URL")  # https://<acct>.blob.core.windows.net
        if acct_url:
            cred = DefaultAzureCredential(exclude_interactive_browser_credential=True)
            svc = BlobServiceClient(account_url=acct_url, credential=cred)
            client = svc.get_container_client(container)
            try:
                client.create_container()
            except Exception:
                pass
            return client, client.url
    except Exception:
        return None, None
    return None, None


def _upload_to_blob(local_path: str, dest_name: str) -> str | None:
    """Upload a local file to the configured Blob container. Returns https://… URL or None on failure."""
    client, container_url = _get_blob_container_client()
    if not client:
        return None
    try:
        with open(local_path, "rb") as f:
            client.upload_blob(name=dest_name, data=f, overwrite=True)
        # Try to build a temporary read-only SAS URL so private containers can still be opened
        try:
            sas_url = _build_blob_sas_url(client, dest_name)
            if sas_url:
                return sas_url
            # If SAS cannot be built, avoid exposing non-SAS URL
            return None
        except Exception:
            # Any error building SAS: do not return plain URL
            return None
    except Exception:
        return None


def _build_blob_sas_url(container_client, blob_name: str) -> str | None:
    """Create a read-only SAS URL for the given blob.
    Prefers account key from connection string; if not available, uses user delegation key with MSI.
    Expiry defaults to 1 hour and can be tuned via BLOB_SAS_TTL_MIN (minutes).
    """
    try:
        # Determine expiry
        ttl_min = 60
        try:
            ttl_min = int(os.getenv("BLOB_SAS_TTL_MIN", "60") or 60)
        except Exception:
            ttl_min = 60
        expiry = datetime.utcnow() + timedelta(minutes=max(5, ttl_min))

        # Service/client basics
        container_name = container_client.container_name  # type: ignore[attr-defined]
        base_url = container_client.url.rstrip("/")

        # Try account-key SAS path (connection string)
        account_name = getattr(container_client, "account_name", None)
        account_key = None
        # Preferred: read from env connection string directly (always available if that path used)
        conn_str = os.getenv("BLOB_CONNECTION_STRING")
        if conn_str and "AccountKey=" in conn_str:
            try:
                parts = dict([tuple(p.split("=", 1)) for p in conn_str.split(";") if "=" in p])
                account_name = parts.get("AccountName", account_name)
                account_key = parts.get("AccountKey")
            except Exception:
                account_key = None
        # Fallback attempt: introspect service client credential
        service_client = None
        if not account_key:
            try:
                service_client = container_client._get_service_client()  # type: ignore[attr-defined]
                account_key = getattr(getattr(service_client, "credential", None), "account_key", None)
            except Exception:
                service_client = None
        if account_name and account_key:
            sas = generate_blob_sas(
                account_name=account_name,
                container_name=container_name,
                blob_name=blob_name,
                permission=BlobSasPermissions(read=True),
                expiry=expiry,
            )
            return f"{base_url}/{blob_name}?{sas}"

        # If no account key (MSI path), use user delegation key
        try:
            if service_client is None:
                service_client = container_client._get_service_client()  # type: ignore[attr-defined]
        except Exception:
            # Fallback: reconstruct from account URL (container URL is like https://acct.blob.core.windows.net/container)
            m = re.match(r"^(https://[^/]+)/", base_url + "/")
            account_url = m.group(1) if m else None
            if not account_url:
                return None
            service_client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential(exclude_interactive_browser_credential=True))

        udk = service_client.get_user_delegation_key(starts_on=datetime.utcnow() - timedelta(minutes=1), expires_on=expiry)
        sas = generate_blob_sas(
            account_name=service_client.account_name,
            container_name=container_name,
            blob_name=blob_name,
            permission=BlobSasPermissions(read=True),
            expiry=expiry,
            user_delegation_key=udk
        )
        return f"{base_url}/{blob_name}?{sas}"
    except Exception:
        return None


# ===== IA history visualization helpers =====
def _hist_build_df(history: list):
    import pandas as pd  # type: ignore
    from urllib.parse import urlparse as _u
    rows = []
    for e in history:
        try:
            ts = e.get("ts")
            ts_dt = pd.to_datetime(ts, errors="coerce")
            mode = e.get("mode") or "-"
            q = (e.get("question") or "").strip()
            filt = e.get("filter") or None
            hits = e.get("hits") or []
            domains = []
            doc_titles = []
            doc_keys = []
            for h in hits:
                uri = h.get("source_uri") or ""
                try:
                    if uri.startswith("upload://"):
                        dom = "upload"
                    else:
                        dom = _u(uri).netloc or "-"
                except Exception:
                    dom = "-"
                domains.append(dom)
                # document key/title
                title = (h.get("title") or "").strip()
                key = uri or title or "-"
                if title:
                    doc_titles.append(title)
                else:
                    doc_titles.append(key)
                doc_keys.append(key)
            rows.append({
                "ts": ts_dt,
                "date": ts_dt.date() if pd.notnull(ts_dt) else None,
                "mode": mode,
                "question": q,
                "filter": filt,
                "hit_count": len(hits),
                "domains": ",".join(sorted(set(domains))) if domains else "-",
                "doc_titles": "|".join(sorted(set(doc_titles))) if doc_titles else "-",
                "doc_keys": "|".join(sorted(set(doc_keys))) if doc_keys else "-",
            })
        except Exception:
            continue
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.dropna(subset=["ts"]).sort_values("ts")
    return df


"""Date range helper removed (no time filters)."""


async def _hist_render_dashboard(df, title_suffix=""):
    import pandas as pd  # type: ignore
    import plotly.express as px  # type: ignore
    dff = df.copy()
    title = f"📜 IA 검색 히스토리 리포트 {title_suffix}"
    await cl.Message(content=title).send()
    # Top documents (by appearance in hits)
    if not dff.empty and (dff["doc_titles"] != "-").any():
        doc_rows = []
        for ds in dff["doc_titles"].fillna(""):
            for t in str(ds).split("|"):
                t = t.strip()
                if t:
                    doc_rows.append(t)
        if doc_rows:
            ddf = pd.DataFrame({"document": doc_rows})
            dtop = ddf["document"].value_counts().head(15).reset_index()
            dtop.columns = ["document", "count"]
            fig_docs = px.bar(dtop, x="document", y="count", title="자주 참조된 문서 Top 15")
            await cl.Message(elements=[cl.Plotly(name="Top 문서", figure=fig_docs)], content="").send()

    # Main topics: frequent terms from questions
    if not dff.empty:
        terms = []
        for q in dff["question"].fillna(""):
            for t in str(q).split():
                t = t.strip()
                if len(t) >= 2 and not t.startswith("/"):
                    terms.append(t.lower())
        if terms:
            tdf = pd.DataFrame({"term": terms})
            ttop = tdf["term"].value_counts().head(20).reset_index()
            ttop.columns = ["term", "count"]
            fig_terms = px.bar(ttop, x="term", y="count", title="주된 키워드 Top 20")
            await cl.Message(elements=[cl.Plotly(name="Top 키워드", figure=fig_terms)], content="").send()

    # Raw 로그 표 제거됨

    # CSV 다운로드 제거됨

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
    # Tuned chunk size/overlap for better precision
    parts = simple_chunks(text, 900, 220)
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
    # Minimal intro message without panel references
    await cl.Message(content=(
        "질문을 입력하면 검색과 요약을 수행합니다.\n"
        "- /업로드 : 문서 업로드 및 분석\n- /업로드목록 : 업로드 목록\n"
        "- /기록시각화 : IA 검색 히스토리 시각화\n"
        "- /기록 : 최근 검색 목록\n- /보기 N : N번째 검색 로그"
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
        "/": "help",
        "/도움말": "help",
        "/업로드": "upload",
        "/업로드목록": "uploads",
        "/기록": "history",
        "/보기": "show",
    # CSV viz removed
    "/기록시각화": "viz_history",
    }
    en_map = {
        "/help": "help",
        "/upload": "upload",
        "/uploads": "uploads",
        "/history": "history",
    "/show": "show",
    # CSV viz removed
    "/viz-history": "viz_history",
    "/history-viz": "viz_history",
    }
    return ko_map.get(head) or en_map.get(head) or ""

def _help_text() -> str:
    return (
        "사용 가능한 명령:\n"
        "- /업로드 : 문서 업로드 및 분석\n"
        "- /업로드목록 : 업로드 목록\n"
        "- /기록 : 최근 검색 목록\n"
        "- /보기 N : N번째 검색 로그 보기 (예: /보기 2)\n"
        "- /기록시각화 : IA 검색 히스토리 시각화\n"
    )

@cl.on_message
async def on_message(msg: cl.Message):
    # quick commands to inspect history (Korean aliases supported)
    cmd = _normalize_command(msg.content)
    if cmd == "help":
        await cl.Message(content=_help_text()).send(); return
    # IA search history visualization
    if cmd == "viz_history":
        history = cl.user_session.get("history", [])
        if not history:
            await cl.Message(content="시각화할 히스토리가 없습니다.").send(); return
        try:
            import pandas as pd  # type: ignore
            import plotly.express as px  # type: ignore
        except Exception as e:
            await cl.Message(content=f"시각화 라이브러리 누락: {e}. requirements.txt 설치 후 다시 시도하세요.").send(); return
        df = _hist_build_df(history)
        cl.user_session.set("hist_df", df)
        await _hist_render_dashboard(df, title_suffix="")
        return
    # If it looks like a slash command but unknown, don't search
    if (msg.content or "").strip().startswith("/") and not cmd:
        await cl.Message(content=_help_text()).send()
        return
    if cmd == "history":
        hist_list = cl.user_session.get("history", [])
        if not hist_list:
            await cl.Message(content="히스토리가 비어있습니다.").send()
        else:
            parts = ["세션 히스토리 (최근 5개):"]
            for i, e in list(enumerate(hist_list))[-5:]:
                parts.append(f" - {i+1}) [{e.get('mode')}] {e.get('question')}")
            parts.append("\n자세히 보려면 '/보기 N' 을 입력하세요 (예: /보기 2)")
            await cl.Message(content="\n".join(parts)).send()
        return
    if cmd == "uploads":
        await _send_uploads_list(page=cl.user_session.get("uploads_page", 0) or 0)
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
            # Upload original file to Blob if configured; fall back to upload:// pseudo URI
            blob_url = None
            try:
                safe_name = f"uploads/{doc_id}{ext}"
                blob_url = _upload_to_blob(path, safe_name)
            except Exception:
                blob_url = None
            source_uri = blob_url or f"upload://{name}"
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


            # save upload record
            uploads = cl.user_session.get("uploads", [])
            rec = {
                "doc_id": doc_id,
                "title": name,
                "chunks": n_chunks,
                "summary": sk.get("summary",""),
                "hashtags": sk.get("hashtags", []),
                "similar": sim_safe,
                "blob_url": blob_url,
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
            if blob_url:
                lines.append(f"\n원본 파일: [열기]({blob_url})")
            if rec["similar"]:
                lines.append("\n유사 문서:")
                for i, h in enumerate(rec["similar"][:5], start=1):
                    lines.append(f"  {i}. {h.get('title','')} — {h.get('source_uri','')}")
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
            # Guard: if no hits, or hits irrelevant, avoid answering
            if not hits:
                await cl.Message(content="📭 관련 근거를 찾지 못했습니다.\n- 검색어를 바꾸거나 필터를 조정해 보세요.").send()
                # log empty and return
                history = cl.user_session.get("history", [])
                history.append({
                    "mode": MODE_LABELS.get(mode, mode),
                    "question": msg.content,
                    "filter": filter_str,
                    "hits": [],
                    "ts": datetime.utcnow().isoformat(timespec='seconds') + 'Z'
                })
                cl.user_session.set("history", history)
                if show_log:
                    await cl.Message(content=_render_log_entry(len(history)-1, history[-1])).send()
                return
            _relevant = _is_relevant_hits(hits, msg.content)
            if not _relevant:
                tips = [
                    "질문과 근거의 관련성이 낮습니다.",
                    "- 질문에 문서의 핵심 키워드나 용어를 더 포함해 보세요.",
                    "- 다른 표현(동의어)로도 시도해 보세요.",
                ]
                # 오프토픽: 근거 표시는 하지 않습니다.
                await cl.Message(content="\n".join(tips)).send()
            else:
                await cl.Message(content=answer).send()
                if hits:
                    # cache last hits for full-view actions
                    last_hits_map = {}
                    for h in hits:
                        rid = h.get("id") or os.urandom(8).hex()
                        last_hits_map[str(rid)] = h
                    cl.user_session.set("last_hits_map", last_hits_map)

                    md, actions = _hits_table_markdown(hits, query=msg.content)
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
            answer = _strip_inline_source_markers(answer)
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
            return
        # Build prompt only when hits exist AND look relevant
        if not _is_relevant_hits(hits, msg.content):
            # 오프토픽: LLM 호출도, 근거 표시도 하지 않음. 가이드만 출력.
            tips = [
                "질문과 근거의 관련성이 낮습니다.",
                "- 질문에 문서의 핵심 키워드나 용어를 더 포함해 보세요.",
                "- 다른 표현(동의어)로도 시도해 보세요.",
            ]
            await cl.Message(content="\n".join(tips)).send()
            # save to history and return
            history = cl.user_session.get("history", [])
            history.append({
                "mode": MODE_LABELS.get(mode, mode),
                "question": msg.content,
                "filter": filter_str,
                "hits": _sanitize_hits_for_log(hits),
                "ts": datetime.utcnow().isoformat(timespec='seconds') + 'Z'
            })
            cl.user_session.set("history", history)
            if show_log:
                await cl.Message(content=_render_log_entry(len(history)-1, history[-1])).send()
            return
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
        md, actions = _hits_table_markdown(hits, query=msg.content)
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
    if u.get("blob_url"):
        lines.append(f"\n원본 파일: [열기]({u.get('blob_url')})")
    if u.get("similar"):
        lines.append("\n유사 문서:")
        for i, h in enumerate(u["similar"][:5], start=1):
            lines.append(f"  {i}. {h.get('title','')} — {h.get('source_uri','')}")
    await cl.Message(
        content="\n".join(lines)
    ).send()


"""Document-limit actions removed."""


@cl.action_callback("uploads_page_prev")
async def uploads_page_prev(action):
    try:
        page = int(action.value)
    except Exception:
        page = max(0, (cl.user_session.get("uploads_page", 0) or 0) - 1)
    await _send_uploads_list(page=page)


@cl.action_callback("uploads_page_next")
async def uploads_page_next(action):
    try:
        page = int(action.value)
    except Exception:
        page = (cl.user_session.get("uploads_page", 0) or 0) + 1
    await _send_uploads_list(page=page)
