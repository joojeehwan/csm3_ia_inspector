import chainlit as cl
import os
from datetime import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv
from openai import AzureOpenAI
from retrivers.internal_search import hybrid_search
from retrivers.web_search import web_search
from rag.prompst import QA_PROMPT, IA_SUMMARY_PROMPT, WEB_QA_PROMPT
from pathlib import Path
from pypdf import PdfReader
import importlib
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from ingest.build_chunks import simple_chunks, embed_batch

USE_LANGGRAPH = os.getenv("USE_LANGGRAPH", "false").lower() in ("1", "true", "yes")
_LG_AVAILABLE = False
if USE_LANGGRAPH:
    try:
        from graphs.orchestrator import run_query as lg_run_query
        _LG_AVAILABLE = True
    except Exception as _e:
        _LG_AVAILABLE = False

load_dotenv()

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

def _format_snippets(hits):
    rows=[]
    for h in hits:
        title = h.get("title","")
        page  = h.get("page")
        uri   = h.get("source_uri","")
        chunk = (h["chunk"][:500]).replace("\n"," ")
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


def _render_log_entry(idx: int, entry: dict) -> str:
    lines = [f"#{idx+1} [{entry.get('mode','qa')}] {entry.get('question','')}"]
    f = entry.get("filter")
    if f:
        lines.append(f"- filter: {f}")
    lines.append(f"- time: {entry.get('ts','')}")
    hits = entry.get("hits", [])
    if not hits:
        lines.append("(no hits)")
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
    modes = ["qa", "ia_summary"]
    if os.getenv("BING_SEARCH_KEY"):
        modes.insert(1, "web_qa")
    settings = await cl.ChatSettings(inputs=[
        Select(id="mode", label="모드", values=modes, initial_index=0),
        Slider(id="top_k", label="Top K", min=3, max=20, step=1, initial=8),
        TextInput(id="filter", label="OData 필터(선택)", placeholder="예) system eq 'kb' and year ge 2023"),
        Switch(id="show_log", label="결과 후 로그 패널 표시", initial=False),
    ]).send()
    cl.user_session.set("settings", settings)
    cl.user_session.set("history", [])
    cl.user_session.set("uploads", [])
    cl.user_session.set("forced_filter", None)
    await cl.Message(content=(
        "왼쪽 사이드바에서 모드/TopK/필터를 조정하세요.\n"
        "- /history : 최근 검색 목록\n- /show N : N번째 검색 로그\n"
        "- /upload : 문서 업로드 및 분석\n- /uploads : 업로드 목록\n- /dashboard : 간단 통계\n"
        "질문을 입력하면 검색→요약까지 실행합니다."
    )).send()

@cl.on_settings_update
async def on_settings_update(s):
    cl.user_session.set("settings", s)
    mode = s.get("mode"); tk = s.get("top_k"); filt = s.get("filter"); show_log = s.get("show_log")
    await cl.Message(content=f"설정이 업데이트되었습니다. 모드={mode}, TopK={tk}, 필터={filt or '-'}, 로그표시={bool(show_log)} (세션 한정)").send()

@cl.on_message
async def on_message(msg: cl.Message):
    # quick commands to inspect history
    if msg.content.strip().lower() == "/history":
        history = cl.user_session.get("history", [])
        if not history:
            await cl.Message(content="히스토리가 비어있습니다.").send()
        else:
            parts = ["세션 히스토리 (최근 5개):"]
            for i, e in list(enumerate(history))[-5:]:
                parts.append(f" - {i+1}) [{e.get('mode')}] {e.get('question')}")
            parts.append("\n자세히 보려면 '/show N' 을 입력하세요 (예: /show 2)")
            await cl.Message(content="\n".join(parts)).send()
        return
    if msg.content.strip().lower() == "/dashboard":
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
    if msg.content.strip().lower() == "/uploads":
        uploads = cl.user_session.get("uploads", [])
        if not uploads:
            await cl.Message(content="업로드 이력이 없습니다.").send(); return
        lines = ["업로드 문서 목록:"]
        for i, u in enumerate(uploads, start=1):
            lines.append(f" {i}. {u.get('title')} — {u.get('ts','')}")
        lines.append("\n문서 상세는 'show_upload' 액션을 사용하세요.")
        await cl.Message(
            content="\n".join(lines),
            actions=[cl.Action(name="show_upload", value="last", description="최근 업로드 보기")]
        ).send()
        return
    if msg.content.strip().lower() == "/upload":
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
                "checklist": checklist,
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
            if checklist:
                done = sum(1 for c in checklist if c.get("done"))
                lines.append(f"\n체크리스트 ({done}/{len(checklist)} 완료):")
                for i, c in enumerate(checklist, start=1):
                    lines.append(f"  [{'x' if c.get('done') else ' '}] {i}. {c.get('text')}")
            idx = len(uploads) - 1
            await cl.Message(
                content="\n".join(lines),
                actions=[
                    cl.Action(name="show_upload", value=str(idx), description="업로드 상세 보기"),
                    cl.Action(name="show_history", value="all", description="세션 히스토리 보기"),
                ],
            ).send()
        return
    if msg.content.strip().lower().startswith("/show"):
        try:
            idx = int(msg.content.strip().split()[1]) - 1
        except Exception:
            await cl.Message(content="형식: /show N").send(); return
        history = cl.user_session.get("history", [])
        if 0 <= idx < len(history):
            await cl.Message(content=_render_log_entry(idx, history[idx])).send()
        else:
            await cl.Message(content="해당 번호의 히스토리가 없습니다.").send()
        return
    settings = cl.user_session.get("settings", {})
    mode = settings.get("mode", "qa")
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
    await cl.Message(content=f"🔎 검색 중… ({mode})").send()

    if _LG_AVAILABLE:
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
                await cl.Message(content="**근거 스니펫**").send()
                for h in hits[:5]:
                    await cl.Message(
                        content=f"**{h.get('title','(제목없음)')}** · {('p.'+str(h.get('page')) if h.get('page') else '')}\n\n{h.get('chunk','')[:300]}\n\n{h.get('source_uri','')}"
                    ).send()
            # log history and provide quick actions
            history = cl.user_session.get("history", [])
            history.append({
                "mode": mode,
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
        try:
            hits = web_search(msg.content, top=top_k)
        except Exception as e:
            await cl.Message(content=f"웹 검색을 사용할 수 없습니다: {e}").send()
            return
        snippets = _format_snippets(hits)
        prompt = WEB_QA_PROMPT.format(question=msg.content, snippets=snippets or "(근거 없음)")
    else:
        hits = hybrid_search(msg.content, top=top_k, filter=filter_str)
        snippets = _format_snippets(hits)
        prompt = (IA_SUMMARY_PROMPT if mode=="ia_summary" else QA_PROMPT).format(
            question=msg.content, snippets=snippets or "(근거 없음)"
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
        await cl.Message(content="**근거 스니펫**").send()
        for h in hits[:5]:
            page_part = ("p."+str(h.get('page')) if h.get('page') else "")
            await cl.Message(
                content=f"**{h.get('title','(제목없음)')}** · {page_part}\n\n{h['chunk'][:300]}\n\n{h.get('source_uri','')}"
            ).send()

    # save to history and provide actions
    history = cl.user_session.get("history", [])
    history.append({
        "mode": mode,
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
    parts.append("\n자세히 보려면 '/show N' 을 입력하세요 (예: /show 2)")
    await cl.Message(content="\n".join(parts)).send()


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
            cl.Action(name="toggle_check", value=f"{idx}:1", description="1번 항목 토글"),
            cl.Action(name="use_filter", value=u.get("doc_id"), description="이 문서만 검색 필터 적용"),
            cl.Action(name="clear_filter", value="", description="검색 필터 해제"),
        ],
    ).send()


@cl.action_callback("toggle_check")
async def toggle_check(action):
    uploads = cl.user_session.get("uploads", [])
    if not uploads:
        await cl.Message(content="업로드 이력이 없습니다.").send(); return
    try:
        idx_str, item_str = (action.value or "").split(":", 1)
        uidx = int(idx_str); item_idx = int(item_str) - 1
    except Exception:
        await cl.Message(content="형식: idx:item (예: 0:2)").send(); return
    if not (0 <= uidx < len(uploads)):
        await cl.Message(content="업로드 인덱스 범위를 벗어났습니다.").send(); return
    ck = uploads[uidx].get("checklist", [])
    if not (0 <= item_idx < len(ck)):
        await cl.Message(content="체크리스트 항목 번호가 잘못되었습니다.").send(); return
    ck[item_idx]["done"] = not ck[item_idx].get("done")
    cl.user_session.set("uploads", uploads)
    await cl.Message(content=f"체크리스트 {item_idx+1}번 항목을 {'완료' if ck[item_idx]['done'] else '미완료'}로 표시했습니다.").send()


@cl.action_callback("use_filter")
async def use_filter(action):
    doc_id = action.value
    cl.user_session.set("forced_filter", f"doc_id eq '{doc_id}'")
    await cl.Message(content=f"이제 검색은 해당 문서(doc_id={doc_id})로 제한됩니다.").send()


@cl.action_callback("clear_filter")
async def clear_filter(action):
    cl.user_session.set("forced_filter", None)
    await cl.Message(content="검색 필터가 해제되었습니다.").send()
