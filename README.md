# IA Finder

RAG demo that searches internal documents using Azure AI Search + Azure OpenAI, exposed via Chainlit UI.

## Required Azure resources

- Azure OpenAI
  - Deployments:
    - Chat: `AZURE_OPENAI_CHAT_DEPLOYMENT` (e.g., gpt-4o-mini)
    - Embedding: `AZURE_OPENAI_EMBED_DEPLOYMENT` (e.g., text-embedding-3-large)
  - Endpoint + API key + API version
- Azure AI Search
  - Index: `ia-chunks` (vector + semantic), optional `ia-raw`
  - Endpoint + API key
- Optional: Azure Blob Storage (for uploading PDFs)

## Configure .env

Copy `.env` and fill values:

```
# Azure AI Search
SEARCH_ENDPOINT=https://<your-search>.search.windows.net
SEARCH_API_KEY=<admin-or-query-key>
INDEX_RAW=ia-raw
INDEX_CHUNKS=ia-chunks

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://<your-aoai>.openai.azure.com
## Deploy to Azure Web App (Container)
AZURE_OPENAI_API_KEY=<your-aoai-key>
AZURE_OPENAI_API_VERSION=2024-02-01
AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-large
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini

# Optional Blob
BLOB_CONNECTION_STRING=DefaultEndpointsProtocol=...;AccountName=...;AccountKey=...
BLOB_CONTAINER=ia-source

# Optional: Bing Web Search (for web_qa mode)
BING_SEARCH_ENDPOINT=https://api.bing.microsoft.com/v7.0/search
BING_SEARCH_KEY=<your-bing-key>

# Ingest mode: local | search_raw
INGEST_MODE=local
DATA_DIR=./data
IMAGE_DIR=./images  # (optional) image OCR source directory
```

## Install dependencies

```zsh
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
# (선택) LangGraph 오케스트레이션을 쓰려면
# pip install langgraph
```

## Create the search index

```zsh
python infra/create_index.py
```

Index schema comes from `infra/search_index_chunks.json`.

## Ingest documents

Place PDFs under `./data`. Then run:

```zsh
python ingest/build_chunks.py
```

- If you already have a `ia-raw` index with raw text, set `INGEST_MODE=search_raw` in `.env`.

### (Optional) Ingest images via OCR

1. Install Tesseract (macOS):
```zsh
brew install tesseract tesseract-lang
```
2. Put PNG/JPG files in `./images` (or set `IMAGE_DIR` in `.env`).
3. Run:
```zsh
4. The OCR text is chunked & embedded same as PDFs and merged into the `ia-chunks` index with `source_uri` prefix `image://`.

Languages: script calls pytesseract with `lang="kor+eng"`; adjust if language packs differ.

## Run the app

```zsh
chainlit run app.py -w
```

Open the URL shown by Chainlit. Pick a mode in the settings:
- qa: internal docs via Azure AI Search
- web_qa: online web search (Bing) with citations
- ia_summary: summarize internal snippets into checklist/risks

선택 사항: LangGraph 오케스트레이션 사용
- LangGraph 설치 후 `.env`에 `USE_LANGGRAPH=true`를 설정하면 검색→프롬프트→생성 단계를 LangGraph 그래프로 실행합니다.

## Upload PDFs to Blob (optional)

```zsh
python scripts/upload_to_blob.py
```

Requires `BLOB_CONNECTION_STRING` and `BLOB_CONTAINER` in `.env`.

## New: Sidebar controls & Upload workflow

- Sidebar controls: Mode, TopK, OData filter, "결과 후 로그 패널 표시"
- Quick commands:
  - /upload: Upload PDF/DOCX/TXT → chunk → embed → index → summarize → keywords → similar docs → checklist
  - /uploads: Show uploaded documents in this session
  - /dashboard: Show quick analytics (counts, completion rate, top hashtags)
  - /history, /show N: Show search history and details

Actions in upload card:
- 업로드 상세 보기, 체크리스트 토글, 해당 문서만 검색 필터 적용/해제

Note: Upload history is stored per session (not persisted). For persistence, wire to SQLite/Azure Table.

## Deploy to Azure Web App (Container)

1) Build and push image to ACR (or use GitHub Container Registry). Example names:
- Image: <yourregistry>.azurecr.io/ia-finder:latest

2) Create Azure Web App for Containers
- Runtime stack: Docker
- Configure container image and registry credentials
- Configure App Settings (environment variables):
  - SEARCH_ENDPOINT, SEARCH_API_KEY, INDEX_CHUNKS
  - AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION, AZURE_OPENAI_CHAT_DEPLOYMENT, AZURE_OPENAI_EMBED_DEPLOYMENT
  - (Optional) BING_SEARCH_KEY, BING_SEARCH_ENDPOINT
  - (Optional) USE_LANGGRAPH=true

3) Exposed port
- The container listens on $PORT (provided by Web App). No extra config required.

## Deploy to Azure Web App (built-in Python, no Docker)

1) Create Web App (Linux) with Python runtime
2) Deploy this repo (e.g., via Zip Deploy)
3) In Configuration > General settings:
- Startup Command:
  ./startup.sh
4) In Configuration > Application settings: add the same environment variables as above.
5) Limitations: System packages like Tesseract may not be available; OCR features may not work without custom container.
