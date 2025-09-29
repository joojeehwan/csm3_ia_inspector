# IA Finder (한국어 안내)

Azure AI Search + Azure OpenAI를 이용해 사내 문서를 검색(RAG)하고, Chainlit UI로 제공하는 데모입니다.

## 필요한 Azure 리소스

- Azure OpenAI
  - 배포(Deployments):
    - Chat: `AZURE_OPENAI_CHAT_DEPLOYMENT` (예: gpt-4o-mini)
    - Embedding: `AZURE_OPENAI_EMBED_DEPLOYMENT` (예: text-embedding-3-large)
  - Endpoint, API Key, API Version
- Azure AI Search
  - 인덱스: `ia-chunks`(벡터+시맨틱), 선택 `ia-raw`
  - Endpoint, API Key
- 선택: Azure Blob Storage (PDF 업로드용)

## .env 설정

루트의 `.env.example`를 복사하여 `.env`를 만들고 값을 채우세요.

```
# Azure AI Search
SEARCH_ENDPOINT=https://<your-search>.search.windows.net
SEARCH_API_KEY=<admin-or-query-key>
INDEX_RAW=ia-raw
INDEX_CHUNKS=ia-chunks

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://<your-aoai>.openai.azure.com
AZURE_OPENAI_API_KEY=<your-aoai-key>
AZURE_OPENAI_API_VERSION=2024-02-01
AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-large
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini

# 선택: Bing Web Search (web_qa 모드)
BING_SEARCH_ENDPOINT=https://api.bing.microsoft.com/v7.0/search
BING_SEARCH_KEY=<your-bing-key>

# 데이터 적재(ingest) 경로
INGEST_MODE=local
DATA_DIR=./data
IMAGE_DIR=./images

# (히스토리 저장/사이드바용) Chainlit 지속 저장 + 인증
DATABASE_URL=sqlite+aiosqlite:///./chainlit.db
CHAINLIT_AUTH_SECRET=<chainlit-create-secret로-생성>
CHAINLIT_USERNAME=admin
CHAINLIT_PASSWORD=admin
```

> 히스토리 사이드바는 “지속 저장(Data Layer) + 인증”이 모두 활성화되어야 표시됩니다. 위 4개 항목(DATABASE_URL, CHAINLIT_AUTH_SECRET, CHAINLIT_USERNAME, CHAINLIT_PASSWORD)을 설정하세요.

## 의존성 설치

Git Bash(Windows) 또는 macOS/Linux 터미널에서:

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows(Git Bash)
# 또는: source .venv/bin/activate  # macOS/Linux
pip install -U pip
pip install -r requirements.txt
# (선택) LangGraph 오케스트레이션을 쓰려면
# pip install langgraph
```

## 검색 인덱스 생성

```bash
python infra/create_index.py
```

스키마는 `infra/search_index_chunks.json`에서 로드합니다.

## 문서 적재 (PDF 등)

`./data` 폴더에 PDF를 넣은 뒤 실행:

```bash
python ingest/build_chunks.py
```

- 이미 `ia-raw` 인덱스에 원문이 있다면 `.env`에서 `INGEST_MODE=search_raw`로 설정하세요.

### (선택) 이미지 OCR 적재

1) Tesseract 설치(macOS 예시)

```bash
brew install tesseract tesseract-lang
```

2) PNG/JPG를 `./images`에 두거나 `.env`의 `IMAGE_DIR`를 지정

3) 실행(동일한 `ingest/build_chunks.py`에 의해 OCR 텍스트도 청크/임베딩되어 `ia-chunks`로 들어갑니다. `source_uri`는 `image://` 접두 사용)

기본 언어는 `kor+eng`입니다. 언어팩 구성에 맞게 조정하세요.

## 앱 실행

```bash
# 일반 실행
chainlit run app.py -w

# Windows(Git Bash)에서 편하게 실행
bash dev_run.sh
```

Chainlit가 출력하는 URL로 접속 후, 설정에서 모드를 선택하세요:
- qa: 내부 문서 검색(Azure AI Search)
- web_qa: 웹 검색(Bing) + 인용
 - ia_summary: 내부 근거 요약/체크리스트

선택 사항: LangGraph 오케스트레이션
- `.env`에 `USE_LANGGRAPH=true` 설정 시, 검색→프롬프트→생성 단계를 LangGraph로 실행합니다.

## 업로드/사이드바 워크플로

- 사이드바 컨트롤: 모드, TopK, OData 필터, “결과 후 로그 패널 표시”
- 퀵 명령어:
  - `/upload`: PDF/DOCX/TXT 업로드 → 청크 → 임베딩 → 인덱스 → 요약 → 키워드 → 유사문서 → 체크리스트
  - `/uploads`: 현재 세션 업로드 목록
  - `/dashboard`: 간단 통계(개수/완료율/상위 해시태그)
  - `/history`, `/show N`: 검색 히스토리와 상세

업로드 카드 액션:
- 업로드 상세 보기, 체크리스트 토글, 해당 문서만 검색 필터 적용/해제

### 대화 히스토리(사이드바) 활성화

- 히스토리 사이드바 표시 조건:
  1) 데이터 레이어 활성화(DATABASE_URL 설정)
  2) 인증 활성화(체인릿 시크릿 + 인증 콜백)
- 본 프로젝트는 기본으로 SQLite(SQLAlchemy 데이터 레이어)와 패스워드 인증을 연결해 두었습니다.
  - .env에 `CHAINLIT_AUTH_SECRET`, `CHAINLIT_USERNAME`, `CHAINLIT_PASSWORD`를 설정하면 로그인 후 히스토리를 볼 수 있습니다.
  - 이전 대화 재개 시 화면 상단에 안내 메시지가 표시됩니다.

## (선택) Blob 업로드

```bash
python scripts/upload_to_blob.py
```

`.env`에 `BLOB_CONNECTION_STRING`, `BLOB_CONTAINER`가 필요합니다.

## Azure Web App(컨테이너) 배포

1) 이미지를 ACR(또는 GHCR)에 빌드/푸시
- 예: `<yourregistry>.azurecr.io/ia-finder:latest`

2) Web App for Containers 생성
- 런타임: Docker
- 컨테이너 이미지/레지스트리 자격 구성
- 앱 설정(환경 변수):
  - SEARCH_ENDPOINT, SEARCH_API_KEY, INDEX_CHUNKS
  - AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION, AZURE_OPENAI_CHAT_DEPLOYMENT, AZURE_OPENAI_EMBED_DEPLOYMENT
  - (선택) BING_SEARCH_KEY, BING_SEARCH_ENDPOINT
  - (선택) USE_LANGGRAPH=true
  - (히스토리 사용 시) DATABASE_URL, CHAINLIT_AUTH_SECRET (+ 필요 시 사용자 인증 방식)

3) 포트
- 컨테이너는 플랫폼에서 제공하는 `$PORT`로 리슨합니다.

## Azure Web App(내장 Python, Docker 미사용)

1) Linux Web App(Python) 생성
2) 리포지토리 배포(Zip Deploy 등)
3) 구성 > 일반 설정:
- Startup Command: `./startup.sh`
4) 구성 > 애플리케이션 설정: 위와 같은 환경 변수 추가
5) 주의: Tesseract 같은 시스템 패키지는 기본 환경에 없을 수 있어 OCR 기능은 컨테이너 사용을 권장합니다.

## 트러블슈팅

- chainlit 명령을 찾을 수 없음: `python -m chainlit run app.py -w`를 사용하거나, 가상환경이 활성화되었는지 확인하세요.
- 포트 충돌: `dev_run.sh`가 자동으로 점유 프로세스를 종료합니다. 수동으로는 Windows `netstat -ano | grep :8000` 확인 후 `taskkill` 실행.
- 인증 화면이 안 뜨거나 히스토리가 안 보임: `.env`의 `CHAINLIT_AUTH_SECRET`과 사용자 계정/비밀번호가 설정되었는지, `DATABASE_URL`이 존재하는지 확인하세요.
