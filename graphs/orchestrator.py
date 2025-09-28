import os
from typing import TypedDict, List, Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

from openai import AzureOpenAI
from retrivers.internal_search import hybrid_search
from retrivers.web_search import web_search
from rag.prompst import QA_PROMPT, IA_SUMMARY_PROMPT, WEB_QA_PROMPT


class State(TypedDict, total=False):
    question: str
    mode: str
    hits: List[Dict[str, Any]]
    snippets: str
    prompt: str
    answer: str
    error: Optional[str]


AOAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AOAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AOAI_VER = os.getenv("AZURE_OPENAI_API_VERSION")
CHAT_DEPLOY = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")

_client: Optional[AzureOpenAI] = None
_graph = None


def _get_client() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(azure_endpoint=AOAI_ENDPOINT, api_key=AOAI_KEY, api_version=AOAI_VER)
    return _client


def _format_snippets(hits: List[Dict[str, Any]]) -> str:
    rows = []
    for h in hits:
        title = h.get("title", "")
        page = h.get("page")
        uri = h.get("source_uri", "")
        chunk = (h.get("chunk", "")[:500]).replace("\n", " ")
        page_part = f" p.{page}" if page not in (None, "") else ""
        rows.append(f"- {title}{page_part}: {chunk} [src: {uri}]")
    return "\n".join(rows)


def _route(state: State) -> str:
    mode = state.get("mode", "qa")
    if mode == "web_qa":
        return "retrieve_web"
    # ia_summary도 내부 검색을 사용
    return "retrieve_internal"


def _retrieve_internal(state: State) -> State:
    hits = hybrid_search(state["question"], top=8)
    return {"hits": hits}


def _retrieve_web(state: State) -> State:
    hits = web_search(state["question"], top=8)
    return {"hits": hits}


def _make_prompt(state: State) -> State:
    mode = state.get("mode", "qa")
    hits = state.get("hits", [])
    snippets = _format_snippets(hits)
    if mode == "web_qa":
        prompt = WEB_QA_PROMPT.format(question=state["question"], snippets=snippets or "(근거 없음)")
    elif mode == "ia_summary":
        prompt = IA_SUMMARY_PROMPT.format(question=state["question"], snippets=snippets or "(근거 없음)")
    else:
        prompt = QA_PROMPT.format(question=state["question"], snippets=snippets or "(근거 없음)")
    return {"snippets": snippets, "prompt": prompt}


def _generate(state: State) -> State:
    client = _get_client()
    try:
        resp = client.chat.completions.create(
            model=CHAT_DEPLOY,
            messages=[
                {"role": "system", "content": "You are a helpful, factual assistant."},
                {"role": "user", "content": state["prompt"]},
            ],
            temperature=0.2,
        )
        answer = resp.choices[0].message.content
        return {"answer": answer}
    except Exception as e:  # pragma: no cover
        return {"error": str(e)}


def build_graph():
    try:
        from langgraph.graph import StateGraph, END  # type: ignore
    except Exception as e:
        raise RuntimeError(
            f"LangGraph를 사용할 수 없습니다. 패키지 설치 필요: pip install langgraph\n원인: {e}"
        )
    sg = StateGraph(State)
    sg.add_node("retrieve_internal", _retrieve_internal)
    sg.add_node("retrieve_web", _retrieve_web)
    sg.add_node("make_prompt", _make_prompt)
    sg.add_node("generate", _generate)

    sg.set_entry_point(_route)
    sg.add_edge("retrieve_internal", "make_prompt")
    sg.add_edge("retrieve_web", "make_prompt")
    sg.add_edge("make_prompt", "generate")
    sg.add_edge("generate", END)
    return sg.compile()


def run_query(mode: str, question: str):
    global _graph
    if _graph is None:
        _graph = build_graph()
    result: State = _graph.invoke({"mode": mode, "question": question})
    if result.get("error"):
        raise RuntimeError(result["error"])  # surface error to caller
    return result.get("answer", ""), result.get("hits", [])
