import os
import time
from typing import Optional, List, Dict, Tuple
from dotenv import load_dotenv
from openai import AzureOpenAI
try:
    from azure.identity import DefaultAzureCredential
    from azure.ai.projects import AIProjectClient
    from azure.ai.agents.models import ListSortOrder
except Exception:  # Lazy import: only needed for services.ai endpoint
    DefaultAzureCredential = None  # type: ignore
    AIProjectClient = None  # type: ignore
    ListSortOrder = None  # type: ignore

load_dotenv()

# Prefer deployment-consistent names, fallback to legacy
AOAI_ENDPOINT = (
    os.getenv("AZURE_EXISTING_AIPROJECT_ENDPOINT")
    or os.getenv("AZURE_AGENT_ENDPOINT")
    or os.getenv("AZURE_OPENAI_ENDPOINT")
)
AOAI_KEY = os.getenv("AZURE_AGENT_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
AOAI_VER = os.getenv("AZURE_AGENT_API_VERSION") or os.getenv("AZURE_OPENAI_API_VERSION")
AGENT_ID = (
    os.getenv("AZURE_EXISTING_AGENT_ID")
    or os.getenv("AZURE_AGENT_ID")
)

_client: Optional[AzureOpenAI] = None
_ai_project_client = None  # type: ignore


def _is_services_ai_endpoint(url: str) -> bool:
    return "services.ai.azure.com" in (url or "")


def _get_client() -> AzureOpenAI:
    global _client
    if _client is None:
        if not (AOAI_ENDPOINT and AOAI_KEY and AOAI_VER):
            raise RuntimeError(
                "Agents 호출용 엔드포인트/키/버전이 필요합니다. AZURE_AGENT_ENDPOINT/API_KEY/API_VERSION 또는 AZURE_OPENAI_* 를 설정하세요."
            )
        if _is_services_ai_endpoint(AOAI_ENDPOINT):
            # For services.ai.azure.com, we won't use AzureOpenAI; we'll use AIProjectClient path elsewhere.
            raise RuntimeError(
                "현재 엔드포인트는 services.ai.azure.com입니다. 이 경우에는 Azure AI Agents 경로를 사용해야 합니다."
            )
        _client = AzureOpenAI(azure_endpoint=AOAI_ENDPOINT, api_key=AOAI_KEY, api_version=AOAI_VER)
    return _client


def _get_ai_project_client():
    global _ai_project_client
    if _ai_project_client is None:
        if not AOAI_ENDPOINT:
            raise RuntimeError("AZURE_AGENT_ENDPOINT 또는 AZURE_OPENAI_ENDPOINT가 필요합니다.")
        if not _is_services_ai_endpoint(AOAI_ENDPOINT):
            raise RuntimeError("AI Project 클라이언트는 services.ai.azure.com 엔드포인트에서만 사용됩니다.")
        if DefaultAzureCredential is None or AIProjectClient is None:
            raise RuntimeError("azure-identity, azure-ai-projects, azure-ai-agents 패키지를 설치하세요 (requirements.txt).")
        # Use DefaultAzureCredential. In App Service, prefer Managed Identity to avoid interactive login.
        # Locally, az login / VS Code Account also work.
        cred = DefaultAzureCredential(
            exclude_interactive_browser_credential=True,
            exclude_managed_identity_credential=False,
        )
        _ai_project_client = AIProjectClient(credential=cred, endpoint=AOAI_ENDPOINT)
    return _ai_project_client


def ask_via_agent_with_sources(question: str, timeout_sec: int = 90) -> Tuple[str, List[Dict[str, str]]]:
    """Call Azure OpenAI Assistants (Agents) with an agent that has Bing Search connection attached.

    Env required:
    - AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION
    - AZURE_AGENT_ID (assistant/agent id, e.g., 'asst_...')
    """
    if not AGENT_ID:
        raise RuntimeError("AZURE_AGENT_ID가 설정되지 않았습니다. 에이전트 화면의 Agent ID를 .env에 설정하세요.")

    # Route depending on endpoint type
    if _is_services_ai_endpoint(AOAI_ENDPOINT):
        # Use Azure AI Agents path (services.ai.azure.com)
        try:
            project = _get_ai_project_client()
            agent = project.agents.get_agent(AGENT_ID)
            thread = project.agents.threads.create()
            project.agents.messages.create(thread_id=thread.id, role="user", content=question)
            run = project.agents.runs.create_and_process(thread_id=thread.id, agent_id=agent.id)
            if run.status == "failed":
                err = getattr(run, "last_error", None)
                raise RuntimeError(f"Agents run 실패: {err}")
            messages = project.agents.messages.list(thread_id=thread.id, order=ListSortOrder.ASCENDING)
            # Extract last assistant message text + citations
            answer = ""
            sources: List[Dict[str, str]] = []
            for m in messages:
                if getattr(m, "role", "") == "assistant" and getattr(m, "text_messages", None):
                    tm = m.text_messages[-1]
                    # text
                    try:
                        answer = tm.text.value or answer
                    except Exception:
                        pass
                    # citations (best-effort: look for common attrs)
                    try:
                        cits = getattr(tm, "citations", None) or []
                        for c in cits:
                            url = getattr(c, "url", None) or getattr(c, "source_url", None) or getattr(c, "href", None)
                            title = getattr(c, "title", None) or getattr(c, "source", None) or "(출처)"
                            snippet = getattr(c, "snippet", None) or getattr(c, "quote", None) or ""
                            if url:
                                sources.append({"url": url, "title": str(title), "snippet": str(snippet)})
                    except Exception:
                        pass
            return (answer or "(응답 없음)", sources)
        except Exception as e:
            raise RuntimeError(
                "Azure AI Agents 호출 실패: 로그인/권한 또는 엔드포인트(project) URL을 확인하세요. VS Code/CLI 로그인과 프로젝트 접근 권한이 필요합니다."
            ) from e
    else:
        # Use Azure OpenAI Assistants path (openai SDK)
        client = _get_client()
        try:
            thread = client.beta.threads.create()
            # Validate agent exists and is accessible
            try:
                client.beta.assistants.retrieve(assistant_id=AGENT_ID)
            except Exception as re:
                raise RuntimeError(
                    "에이전트를 찾을 수 없습니다(404/401). 확인: 1) AZURE_OPENAI_ENDPOINT가 에이전트가 있는 리소스인지, 2) AZURE_AGENT_API_VERSION이 Assistants 지원버전인지, 3) AZURE_AGENT_ID 정확성, 4) 키 권한."
                ) from re
            client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=question,
            )
            run = client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=AGENT_ID,
            )

            # Poll until completed or timeout
            started = time.time()
            status = run.status
            while status in ("queued", "in_progress", "requires_action"):
                if time.time() - started > timeout_sec:
                    raise TimeoutError("Agents run 대기 시간 초과")
                time.sleep(0.8)
                run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
                status = run.status

            if status != "completed":
                last_error = getattr(run, "last_error", None)
                raise RuntimeError(f"Agents run 실패: status={status} error={last_error}")

            msgs = client.beta.threads.messages.list(thread_id=thread.id, order="desc", limit=10)
            answer_parts: List[str] = []
            sources: List[Dict[str, str]] = []
            for m in getattr(msgs, "data", []):
                if getattr(m, "role", "") == "assistant":
                    for c in getattr(m, "content", []) or []:
                        t = getattr(c, "text", None) or (c.get("text") if isinstance(c, dict) else None)
                        if t:
                            value = getattr(t, "value", None) or (t.get("value") if isinstance(t, dict) else None)
                            if value:
                                answer_parts.append(value)
                            # Try to parse annotations for citations
                            ann = getattr(t, "annotations", None) or (t.get("annotations") if isinstance(t, dict) else None) or []
                            try:
                                for a in ann:
                                    url = getattr(a, "url", None) or getattr(a, "source", None) or (a.get("url") if isinstance(a, dict) else None)
                                    title = getattr(a, "title", None) or (a.get("title") if isinstance(a, dict) else None) or "(출처)"
                                    quote = getattr(a, "quote", None) or (a.get("quote") if isinstance(a, dict) else None) or ""
                                    if url:
                                        sources.append({"url": url, "title": str(title), "snippet": str(quote)})
                            except Exception:
                                pass
                    break
            return ("\n\n".join(answer_parts) or "(응답 메시지를 찾지 못했습니다)", sources)
        except Exception as e:
            raise RuntimeError(f"Azure OpenAI Assistants 호출 실패: {e}")


def ask_via_agent(question: str, timeout_sec: int = 90) -> str:
    """Backward-compatible wrapper returning only text."""
    text, _ = ask_via_agent_with_sources(question, timeout_sec)
    return text
