## 🎤 데모 스크립트(8~12분)

아래 시나리오대로 진행하면 핵심 기능을 자연스럽게 데모할 수 있습니다.

### 0) 사전 체크(1분)

- .env 확인: SEARCH_*, AZURE_OPENAI_*, INDEX_CHUNKS 필수
- 선택:
	- 웹검색: AZURE_AGENT_ID 또는 AZURE_EXISTING_AGENT_ID
	- Blob: BLOB_CONNECTION_STRING, BLOB_CONTAINER
	- 히스토리: CHAINLIT_AUTH_SECRET, DATABASE_URL
- 앱 실행
	- PowerShell:

```powershell
python -m chainlit run app.py -w
```

- 브라우저 열고 설정 패널 확인

말하기 포인트: “내부 문서 RAG + 요약 + 보안형 원본열람(SAS) + 웹검색(옵션) 지원합니다.”

### 1) 명령어 소개(20초)

- 입력: `/` 또는 `/help`
- 기대 결과: 사용 가능한 명령 목록 노출
- 말하기 포인트: “/업로드, /uploads, /history, /보기 N, /기록시각화, /help 지원합니다.”

### 2) 파일 업로드 → Blob 저장/SAS 링크(1.5분)

- 입력: `/업로드` → 파일 선택(PDF/DOCX/TXT 1~2개)
- 기대 결과:
	- “✅ 업로드 완료” 카드
	- doc_id/청크 수/요약/키워드
	- 원본 파일: [열기](…?sv=…) 링크(SAS 포함)
- 검증: 시크릿 창에서도 링크 열림(퍼블릭 차단이어도 OK)
- 말하기 포인트: “원본은 Blob에 저장되고, SAS로 시간 제한 접근만 허용합니다. 문서별 고유 파일명으로 누적됩니다.”
- 문제 시: ?sv 없음/403 → 스토리지 권한·환경변수 확인, 미지원 확장자/25MB 초과 → 안내 확인

### 3) 업로드 목록/페이지네이션(40초)

- 입력: `/업로드목록`
- 기대 결과:
	- “업로드 문서 목록 (총 N개) — 페이지 x/y”
	- 항목 리스트 후 한 줄 띄우고 “상세 보기: 가장 최신 3 개 …”
	- 최신 3개 액션 버튼
- 액션: “다음 페이지/이전 페이지” 버튼
- 말하기 포인트: “최근 문서에 빠르게 접근, 페이지네이션으로 정리.”

### 4) QA 모드 — 내부 RAG + 근거 표(1.5분)

- 설정: 모드=QA
- 질문 예시(인덱스에 맞게 1개):
	- "신입사원 온보딩 관련 내용 문서 찾아줘”
- 기대 결과: 답변 + “근거 (상위 5)” 표
- 말하기 포인트: “근거 표로 투명성, 출처 즉시 확인.”

### 5) 저연관/오프토픽 가드(30초)

- 입력: “강아지에 대한 문서 찾아줘”
- 기대 결과: “질문과 근거의 관련성이 낮습니다.” 가이드만 출력, 근거 표 없음
- 말하기 포인트: “환각 방지 위해 저연관이면 근거/답변 숨김.”

### 6) IA 요약 모드 — 요약만 출력(1분)

- 설정: 모드=IA 요약
- 입력 예시: “신입 개발자 온보딩 매뉴얼 요약해줘"
- 기대 결과: “요약” 본문만 출력, 각 문단 끝 [근거: 문서/페이지/URI] 1~2개
- 말하기 포인트: “요약만 요청하도록 프롬프트 정제.”

### 7) 웹 검색 모드(옵션, 1분)

- 설정: 모드=웹 검색(에이전트 설정 필요)
- 입력 예시: “최근 azure ai 관련 기사 찾아줘”
- 기대 결과: 최신 정보 답변 + 출처 카드(제목/URL/요약/파비콘)
- 말하기 포인트: “App Service 관리 ID 권한으로 로그인 없이 동작.”
- 미설정 시: 에이전트 필요 안내 메시지

### 8) 히스토리/상세/시각화(50초)

- 입력: `/기록` → 최근 5개, `/보기 2` → 2번 상세, `/기록시각화` → 차트(미설치면 안내)
- 말하기 포인트: “요청-응답-근거가 세션 히스토리로 남아 재검토 용이.”

### 9) OData 필터/TopK(40초)

- 설정: OData 필터 = `upload'`, TopK=5
- 입력: “업로드한 문서 중 ‘RAG 아키텍처’ 관련 핵심만 알려줘”
- 기대 결과: 업로드 문서에 한정된 결과 표시
- 말하기 포인트: “업무/문서 타입/기간 등 필터로 품질 향상.”

### 10) 마무리(20초)

- 포인트 요약: “SAS 원본열람 · 근거 표 · 저연관 차단 · 요약만 · (옵션) 웹 검색/히스토리/시각화/필터링”

### 추가 팁

- 데모 전 /업로드로 1~2개 문서 사전 업로드
- 웹 검색은 변수 많으니 사전 점검 또는 옵션 처리
- 시간이 부족하면 7), 9)는 생략 가능

## 📄 IA Inspector: AI 기반 문서 검색·요약 시스템

Azure AI Search + Azure OpenAI로 내부 문서를 검색(RAG)하고, Chainlit UI로 질의·요약·출처 표시를 제공하는 경량 데모입니다. 업로드 원본은 Azure Blob에 보관되고, 비공개 스토리지에서도 SAS 링크로 열람 가능합니다. 오프토픽일 땐 근거를 숨겨 환각을 줄입니다.

---

## 🚀 주요 기능

- ✅ 문서 업로드(PDF, DOCX, TXT) → 청크/임베딩/색인
- 🔎 RAG 검색 답변(출처 표 포함) + IA 요약 모드
- 🌐 (선택) 웹 검색 모드: Azure OpenAI Agents 기반 출처 인용
- 🔐 Blob 저장소(SAS 링크) 원본 열람, 퍼블릭 차단 환경 지원
- 🛡️ 환각 방지: 무검색/저연관 시 답변·근거 표시 억제 가이드 출력
- 🧭 업로드 목록 페이지네이션 + 최신 3건 빠른 상세 보기 버튼
- 🧱 Chainlit 데이터 레이어·인증(선택)로 세션 히스토리 보관

---

## 📁 프로젝트 구조

```bash
.
├── app.py                     # Chainlit 엔트리; 업로드·검색·요약·가드·SAS 처리
├── rag/
│   └── prompst.py            # QA/요약/웹QA 프롬프트(요약 전용으로 수정됨)
├── retrivers/
│   ├── internal_search.py    # Azure AI Search 하이브리드 검색
│   └── web_search.py         # (옵션) Bing Web Search 클라이언트
├── graphs/
│   └── orchestrator.py       # (옵션) LangGraph 오케스트레이션
├── ingest/
│   ├── build_chunks.py       # 로컬/검색 원문에서 청크 생성·색인
│   └── ingest_images.py      # (옵션) 이미지 OCR ingest
├── infra/
│   ├── create_index.py       # 인덱스 생성 스크립트
│   └── search_index_chunks.json  # 인덱스 스키마
├── scripts/
│   ├── check_env.py          # 필수 .env 점검
│   ├── gen_sample_pdfs.py    # 샘플 PDF 생성
│   └── upload_to_blob.py     # 샘플 파일 Blob 업로드(타임스탬프 prefix)
├── startup.sh                # App Service에서 $PORT로 Chainlit 실행
├── requirements.txt          # 의존성
└── README.md
```

---

## 📦 폴더별 기능 · 적용 기술

아래는 각 폴더/파일이 담당하는 역할과 적용된 기술 스택입니다. 기존 기술 상세(아래 "🧠 기술 상세")는 유지하며, 구조 이해를 돕기 위해 기능 중심 설명을 추가했습니다.

### 루트
- `app.py`
	- 기능: Chainlit 엔트리. 업로드(읽기→청크→색인), 검색/요약, 근거 표, 저연관 가드, Azure Blob 업로드+SAS 링크 생성, 세션 히스토리/시각화 명령 처리.
	- 기술: Chainlit UI, Azure OpenAI Chat Completions, Azure AI Search(하이브리드), Azure Blob Storage(SAS: AccountKey 또는 MSI User Delegation), pandas/plotly(옵션, 기록 시각화), OData 필터.
- `requirements.txt`
	- 기능: 의존성 고정(Chainlit, Azure SDK, OpenAI SDK, pypdf, python-docx, pandas/plotly 등).
- `startup.sh`
	- 기능: App Service에서 `$PORT`로 Chainlit 실행.
- `README.md`
	- 기능: 사용/설치/배포/데모 안내 및 기술 상세.

### rag/
- `prompst.py`
	- 기능: QA/요약(IA Summary) 프롬프트 템플릿. 요약 모드는 “요약만” 출력하도록 조정.
	- 기술: 프롬프트 엔지니어링(근거 스니펫 삽입, 오프토픽 억제 정책과 연계).

### retrivers/
- `internal_search.py`
	- 기능: Azure AI Search 하이브리드 검색 호출, 결과 정규화.
	- 기술: `azure-search-documents` SDK, 키워드+벡터 결합, OData 필터 지원.
- `web_search.py` (옵션)
	- 기능: Bing Web Search v7 클라이언트(직접 호출 스크립트용). 현재 앱은 Agents 경로를 기본 사용.
	- 기술: REST 호출(requests), Cognitive Services/Bing Search API.
- `agents_web_qa.py`
	- 기능: Azure OpenAI Agents(services.ai/Foundry) 기반 웹 검색 Q&A. 출처(URL/요약/파비콘) 목록 반환.
	- 기술: `azure-ai-projects`, `azure-ai-agents`, MSI/Key 인증, Bing 연결(에이전트 리소스).

### graphs/
- `orchestrator.py` (옵션)
	- 기능: LangGraph로 검색→가드→프롬프트→생성 파이프라인 오케스트레이션.
	- 기술: LangGraph 노드 구성, 단계별 책임 분리. `USE_LANGGRAPH=true`일 때 사용.

### ingest/
- `build_chunks.py`
	- 기능: PDF/DOCX/TXT에서 텍스트 추출→청크 분할→임베딩→Search 인덱스 업로드.
	- 기술: `pypdf`, `python-docx`, OpenAI Embeddings(배치), Azure AI Search 업서트.
- `ingest_images.py` (옵션)
	- 기능: 이미지 OCR 파이프라인(샘플/확장용). 기본 앱 경로에서는 사용하지 않음.

### infra/
- `create_index.py`
	- 기능: `search_index_chunks.json` 스키마로 Azure AI Search 인덱스 생성.
	- 기술: `azure-search-documents` 관리 API.
- `search_index_chunks.json`
	- 기능: 하이브리드 검색용 인덱스 스키마(텍스트/필드/벡터 포함).

### scripts/
- `check_env.py`
	- 기능: 필수 환경 변수 점검(개발 편의 스크립트).
- `gen_sample_pdfs.py`
	- 기능: 데모용 샘플 PDF 생성.
- `upload_to_blob.py`
	- 기능: 로컬 파일을 Azure Blob에 업로드(SAS는 앱에서 생성; 스크립트는 경로/누적 업로드 중심).
- `smoke_test.py` (옵션)
	- 기능: 간단한 연쇄 실행으로 개발 환경 스모크 테스트.

### 기타
- `chainlit.md`
	- 기능: Chainlit 환영 화면 텍스트(비워두면 환영 화면 미표시).
- `.vscode/`
	- 기능: VS Code 배포 설정(App Service) 등.
- `data/` (로컬)
	- 기능: 인덱싱 대상 데이터 디렉터리(개발 시 편의).

---

## ⚙️ 환경 변수(.env)

```env
# Azure AI Search
SEARCH_ENDPOINT=https://<your-search>.search.windows.net
SEARCH_API_KEY=<admin-or-query-key>
INDEX_CHUNKS=ia-chunks
INDEX_RAW=ia-raw

# Azure OpenAI (필수)
AZURE_OPENAI_ENDPOINT=https://<your-aoai>.openai.azure.com
AZURE_OPENAI_API_KEY=<your-aoai-key>
AZURE_OPENAI_API_VERSION=2024-02-01
AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-large
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini

# (선택) 웹 검색: Azure OpenAI Agents
# Agents 리소스 또는 동일 AOAI 리소스 사용 가능
AZURE_AGENT_ENDPOINT=https://<your-aoai-or-agents>.openai.azure.com
AZURE_AGENT_API_KEY=<your-key>
AZURE_AGENT_API_VERSION=2024-02-01
AZURE_AGENT_ID=asst_...
# 이미 존재하는 에이전트 ID를 쓸 경우
# AZURE_EXISTING_AGENT_ID=asst_...

# 데이터/옵션
DATA_DIR=./data
USE_LANGGRAPH=true

# 업로드 원본 저장(둘 중 하나 경로 사용)
BLOB_CONNECTION_STRING=DefaultEndpointsProtocol=...;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net
BLOB_CONTAINER=ia-source

```

> 히스토리 사이드바는 “지속 저장(Data Layer) + 인증”이 모두 활성화되어야 표시됩니다.

---

## 🧩 설치

Windows PowerShell 기준:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate
pip install -U pip
pip install -r requirements.txt
```

---

## 🏗️ 인덱스 생성 · 데이터 적재

```powershell
python infra/create_index.py           # 인덱스 생성 (스키마: infra/search_index_chunks.json)
python ingest/build_chunks.py          # ./data의 PDF/DOCX/TXT를 청크·색인
```

샘플 데이터:

```powershell
python scripts/gen_sample_pdfs.py      # 예제 PDF 생성
python scripts/upload_to_blob.py       # Blob에 예제 업로드(누적 prefix)
```

---

## ▶ 실행

```powershell
python -m chainlit run app.py -w
```

접속 후 설정에서 모드를 선택하세요.
- qa: 내부 문서 RAG 검색
- ia_summary: 내부 근거 요약(요약만 출력)
- web_qa: Azure OpenAI Agents 기반 웹 검색(에이전트 ID 필요)

슬래시 명령
- /업로드, /uploads, /history, /보기 N, /기록시각화, /help(또는 /)

---

## ☁ 배포(App Service)

컨테이너 또는 내장 Python 모두 지원합니다.

공통 설정
- 앱 설정(환경 변수): 위 .env 항목 반영
- WebSockets: On (Chainlit 실시간 업데이트)
- Startup: 컨테이너는 플랫폼 전달 `$PORT`로 리슨. 내장 Python은 `./startup.sh` 사용

권한(웹 검색/스토리지)
- 웹 검색(Agents): App Service 관리 ID(MSI)를 Azure AI Project(services.ai)에 Contributor로 추가하면 로그인 없이 동작
- Blob SAS(MSI 경로): 스토리지에 ‘Storage Blob Data Contributor’ 부여 필요

---

## 🧩 VS Code 확장(추천)

Azure 배포/운영을 VS Code에서 편하게 하기 위한 확장 목록입니다.

- Azure Tools (Extension Pack) — ms-vscode.vscode-azureextensionpack
	- App Service, Storage, Resources, Account 등 주요 Azure 확장을 일괄 설치
- Azure App Service — ms-azuretools.vscode-azureappservice
	- “Deploy to Web App…”, 구성 편집, 로그 스트리밍, SSH/콘솔 등
- Azure Storage — ms-azuretools.vscode-azurestorage
	- Blob 컨테이너 탐색/업로드, SAS 생성, 파일 브라우저
- Azure Resources — ms-azuretools.vscode-azureresourcegroups
	- 구독/리소스 그룹/리소스 트리 보기 및 빠른 액션
- Azure Account — ms-vscode.azure-account
	- VS Code에서 Azure 로그인/구독 선택
- Azure Developer CLI (azd) — ms-azuretools.vscode-azd (선택)
	- IaC+앱 통합 배포 파이프라인 구성 시 유용

개발 일반
- Python — ms-python.python, Pylance — ms-python.vscode-pylance
- Docker — ms-azuretools.vscode-docker (컨테이너 빌드/실행/퍼블리시)

---

## 🛠️ 트러블슈팅

- chainlit 명령을 찾을 수 없음 → `python -m chainlit run app.py -w`
- 웹 검색이 안 보임 → AZURE_AGENT_ID(AZURE_EXISTING_AGENT_ID) 환경 변수 설정
- Blob 링크 403 → SAS 파라미터(?sv=…) 존재 확인, 스토리지 권한 확인
- 히스토리 미표시 → CHAINLIT_AUTH_SECRET, DATABASE_URL, 사용자 계정 설정 확인

---

## 📌 비고

- 요약 프롬프트는 ‘요약만’ 출력하도록 조정됨(`rag/prompst.py`)
- 오프토픽/저연관 시 근거 표 생략으로 환각 최소화
- 업로드 목록은 최신순, 페이지네이션 + 최신 3개 빠른 상세 버튼 제공

---

## 🧠 기술 상세: LangGraph · 검색/리랭킹

### LangGraph 오케스트레이션(USE_LANGGRAPH=true)

- 실행 경로: `graphs/orchestrator.py`
- 단계:
	1) 검색: Azure AI Search로 하이브리드 검색 수행(키워드+벡터)
	2) 관련성 판단: `_is_relevant_hits`로 오프토픽/저연관 차단(LLM 호출·근거 표시 억제)
	3) 프롬프트 구성: 모드에 따라 QA/요약 프롬프트로 스니펫 주입
	4) 생성: Azure OpenAI Chat 호출, 답변 생성
	5) 근거: 관련성 충분할 때만 상위 히트 표 렌더링

장점: 흐름과 가드가 분리되어 유지보수 용이, 단계별 로깅/교체가 쉬움.

### Azure AI Search: 하이브리드 검색과 리랭킹

- 색인: `infra/search_index_chunks.json` 스키마 기반, 벡터(임베딩) + 텍스트/필드
- 검색 클라이언트: `SearchClient(SEARCH_ENDPOINT, INDEX_CHUNKS, AzureKeyCredential(…))`
- 하이브리드: 질의어를 임베딩해 벡터 유사도 + 키워드 매칭 병합
- (선택) 시맨틱 세팅/랭커 활성화 시 의미기반 리랭킹 적용 가능(리소스/요금제 요건)
- 필터링: OData(예: `system eq 'upload' and year ge 2023`)로 문서·연도 등 제한
- TopK/스니펫: 설정 패널에서 K 조정, 표는 상위 5개까지 출력

본 앱의 가드라인:
- 무검색/저연관 시 LLM 호출·근거 표시 생략 → 환각 최소화
- 요약 모드에서는 “요약만” 출력하도록 프롬프트 정제

---

## 🔭 향후 확장 로드맵

### 1) Chainlit UI 개선(버튼 중심)
- 상단 고정 퀵 액션 버튼
	- 예: “📎 업로드”, “📜 히스토리”, “📈 기록 시각화”, “🧹 초기화”
	- 구현 포인트: 초기 안내 메시지에 `cl.Action` 버튼을 추가하고 `@cl.action_callback`으로 라우팅.
- 모드/TopK/필터 프리셋 버튼
	- 예: “모드=QA/요약/웹검색”, “TopK=5/8/12”, “system='upload' 필터 토글”
	- 구현 포인트: 세션의 `settings` 값을 업데이트하고 `on_settings_update`를 재호출.
- 근거 행별 액션(선택적 재도입)
	- 예: “🔎 전체 보기”, “📄 스니펫 더보기”
	- 구현 포인트: 기존 `last_hits_map` 세션 캐시를 활용해 id→히트 매핑. 저연관 시엔 버튼을 노출하지 않음.
- 업로드 카드 내 버튼
	- 예: “📂 업로드 상세 보기”, “🔗 원본 열기”, “🧩 유사문서 다시보기”
	- 구현 포인트: 이미 존재하는 `show_upload` 콜백 확장.

권장 수락 기준(예)
- 퀵 액션 클릭 시 동일 기능의 슬래시 명령과 동등하게 동작한다.
- 저연관/무검색 상황에서는 근거 관련 버튼이 노출되지 않는다.
- 프리셋 버튼 클릭 시 설정 패널 값과 세션 상태가 일관된다.

### 2) 업로드 UX 고도화
- 드래그&드롭, 진행률 표시, 대용량 파일 분할 업로드(청크 업로드)
- 파일 유형별 전처리(스캔 PDF OCR, 이미지 EXIF/텍스트 추출)
- 바이러스 스캔/금지 확장자 정책(보안 강화)

### 3) 검색 품질/안정성
- 시맨틱 리랭커/랭킹 프로파일 실험(리소스/요금제 요건 검토)
- 문서/도메인 다변량 가중치(최근성/작성자/태그 등) 튜닝
- 캐시(쿼리 토큰+필터 키 기반)로 반복 질의 가속화

### 4) 관리/감사 및 가시성
- 감사 로그(질의/근거/요약) 익명화 저장, CSV/Parquet 내보내기
- Azure Application Insights/Log Analytics 연계(성능/오류/사용량)
- 프롬프트/추론 트레이싱 도입(선택)

### 5) 보안/권한
- App Service Easy Auth와 역할 기반 접근(RBAC) 연동
- MSI 전용 운영 경로 확립(키 무노출), Blob/AI Project 최소 권한
- 업로드 격리(사용자/테넌트별 컨테이너/프리픽스)

### 6) 배포·운영
- CI/CD(예: GitHub Actions): 린트/테스트/빌드/배포 파이프라인
- 로드 테스트(Azure Load Testing)와 기본 SLO 모니터링
- 환경 분리(.env.dev/.env.prod) 및 시크릿 관리(Repo Secrets/App Settings)

### 7) 도메인 기능 확장
- 문서 메타데이터 추출/정규화(작성일/저자/카테고리/태그)
- 지식 그래프/연결 분석(참조/종속 관계 시각화)
- 멀티언어(i18n)와 모바일 최적화 레이아웃

참고: UI 버튼 도입은 현재 구조(슬래시 명령 및 `@cl.action_callback`)와 잘 호환되며, 먼저 퀵 액션 3~4개만 도입해도 체감 효율이 큽니다.
