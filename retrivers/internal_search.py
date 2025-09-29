import os
from typing import List, Optional
from dotenv import load_dotenv
from openai import AzureOpenAI
from openai import NotFoundError
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
try:
    # Newer SDKs (11.4.0b8+) use RawVectorQuery and vector_queries + k
    from azure.search.documents.models import RawVectorQuery as _VectorQuery
    _USE_NEW_VECTOR_API = True
except ImportError:  # fallback for older SDKs
    from azure.search.documents.models import QueryVector as _VectorQuery
    _USE_NEW_VECTOR_API = False

load_dotenv()
SEARCH_ENDPOINT=os.getenv("SEARCH_ENDPOINT")
SEARCH_API_KEY=os.getenv("SEARCH_API_KEY")
INDEX_CHUNKS=os.getenv("INDEX_CHUNKS","ia-chunks")

AOAI_ENDPOINT=os.getenv("AZURE_OPENAI_ENDPOINT")
AOAI_KEY=os.getenv("AZURE_OPENAI_API_KEY")
AOAI_VER=os.getenv("AZURE_OPENAI_API_VERSION")
EMBED_DEPLOY=os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT")

search = SearchClient(SEARCH_ENDPOINT, INDEX_CHUNKS, AzureKeyCredential(SEARCH_API_KEY))
aoai   = AzureOpenAI(azure_endpoint=AOAI_ENDPOINT, api_key=AOAI_KEY, api_version=AOAI_VER)

def _embed(q: str) -> List[float]:
    try:
        return aoai.embeddings.create(model=EMBED_DEPLOY, input=q).data[0].embedding
    except NotFoundError as e:
        # Provide a clearer, actionable message
        msg = (
            "Azure OpenAI Embedding deployment not found.\n"
            f"- Endpoint: {AOAI_ENDPOINT}\n"
            f"- API version: {AOAI_VER}\n"
            f"- EMBED_DEPLOY (deployment name): {EMBED_DEPLOY}\n"
            "확인하세요: Azure Portal > Azure OpenAI 리소스 > Deployments 에서 임베딩 모델 배포명이 위와 정확히 일치하는지, \n"
            "그리고 이 리소스의 엔드포인트가 .env 의 AZURE_OPENAI_ENDPOINT 와 동일한지."
        )
        raise RuntimeError(msg) from e

def hybrid_search(query: str, top: int = 8, filter: Optional[str] = None):
    emb = _embed(query)
    if _USE_NEW_VECTOR_API:
        vec = _VectorQuery(vector=emb, k=top, fields="contentVector")
        try:
            res = search.search(
                search_text=query,
                vector_queries=[vec],
                top=top,
                filter=filter,
                query_type="semantic",
                semantic_configuration_name="default",
                search_fields=["title","chunk"],
                select=["id","doc_id","title","chunk","source_uri","page","dept","system","year"],
            )
        except Exception:
            # Fallback when semantic ranker/config is not available
            res = search.search(
                search_text=query,
                vector_queries=[vec],
                top=top,
                filter=filter,
                query_type="simple",
                search_fields=["title","chunk"],
                select=["id","doc_id","title","chunk","source_uri","page","dept","system","year"],
            )
    else:
        vec = _VectorQuery(value=emb, k_nearest_neighbors=top, fields="contentVector")
        try:
            res = search.search(
                search_text=query,
                vectors=[vec],
                top=top,
                filter=filter,
                query_type="semantic",
                semantic_configuration_name="default",
                search_fields=["title","chunk"],
                select=["id","doc_id","title","chunk","source_uri","page","dept","system","year"],
            )
        except Exception:
            res = search.search(
                search_text=query,
                vectors=[vec],
                top=top,
                filter=filter,
                query_type="simple",
                search_fields=["title","chunk"],
                select=["id","doc_id","title","chunk","source_uri","page","dept","system","year"],
            )
    return [r for r in res]
