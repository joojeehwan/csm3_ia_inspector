# VS Code로 Azure Web App (Non-Docker) 배포 가이드

이 문서는 `startup.sh`를 사용하는 Non-Docker 방식으로, VS Code에서 바로 Azure Web App에 이 프로젝트를 배포하는 가장 쉬운 방법을 정리했습니다. `02.streamlit_deployment.md`와 유사한 난이도로 따라 할 수 있게 구성했습니다.

## 1. 준비물 (Prerequisites)
- Azure 구독(Subscription)
- VS Code
- VS Code 확장
  - Azure Account
  - Azure App Service
- 로컬에서 이 레포가 열려 있고, 커밋/푸시 준비 완료 상태
- .env 값 준비 (예: 키/엔드포인트). 실제 배포 시 포털의 App Settings에 입력합니다.

## 2. 프로젝트 체크리스트
- `startup.sh`: Web App이 제공하는 `$PORT`로 Chainlit을 실행하도록 구성되어 있습니다.
- `requirements.txt`: 런타임 필요한 패키지 목록 포함.
- `app.py`: Chainlit 엔트리 파일.
- `.env.example`: 배포 시 App Settings로 옮길 키 목록 레퍼런스.
- Azure 리소스들: Azure OpenAI, Azure AI Search, (선택) Bing Web Search

## 3. VS Code에서 Azure 로그인
1) VS Code 좌측 Activity Bar에서 Azure 아이콘 클릭
2) "Sign in to Azure" 진행 → 브라우저에서 로그인 완료
3) 오른쪽 하단 팝업 또는 Azure 패널에서 로그인/구독 인식 확인

## 4. 새로운 Web App 만들기 (Linux/Python)
1) Azure 패널 > App Service > + Create New Web App…
2) 입력 및 선택 제안
   - App name: `ia-finder-<임의문자>` (전역 유일)
   - Runtime stack: Python 3.11 (권장)
   - OS: Linux
   - Region: 가까운 리전
   - App Service plan: B1(테스트), S1(상시 운영)
3) 생성이 완료되면 App Service 목록에 새 앱이 나타납니다.

## 5. App Settings 설정 (.env 반영)
배포 전에 환경 변수(키/엔드포인트)를 Web App에 등록합니다.

방법 A) VS Code에서 포털 열기
- 새로 만든 Web App를 우클릭 → Open in Portal
- Settings > Environment variables(App settings)
- 다음 키/값 추가 (모두 문자열):
  - SEARCH_ENDPOINT = https://<your-search>.search.windows.net
  - SEARCH_API_KEY = <your-search-key>
  - INDEX_CHUNKS = ia-chunks
  - INDEX_RAW = ia-raw
  - AZURE_OPENAI_ENDPOINT = https://<your-aoai>.openai.azure.com
  - AZURE_OPENAI_API_KEY = <your-aoai-key>
  - AZURE_OPENAI_API_VERSION = 2024-02-01
  - AZURE_OPENAI_EMBED_DEPLOYMENT = text-embedding-3-large
  - AZURE_OPENAI_CHAT_DEPLOYMENT = gpt-4o-mini
  - (선택) BING_SEARCH_ENDPOINT = https://api.bing.microsoft.com/v7.0/search
  - (선택) BING_SEARCH_KEY = <your-bing-key>
  - INGEST_MODE = local
  - DATA_DIR = ./data
  - IMAGE_DIR = ./images
  - USE_LANGGRAPH = false

추가로 General settings에서 다음 권장 설정을 확인합니다.
- Stack: Python 3.11
- Web sockets: On (Chainlit 실시간 업데이트에 유리)
- Always On: On (S1 이상에서 권장)

## 6. Startup Command 설정
- 포털 > Web App > Configuration > General settings > Startup Command에 다음 값 입력
```
./startup.sh
```
- 저장 후 자동 재시작을 기다립니다.

## 7. VS Code에서 바로 배포(Deploy)
1) VS Code Explorer에서 이 폴더를 선택한 상태로, Azure 패널 > App Service에서 생성한 Web App를 우클릭
2) "Deploy to Web App…" 선택 → 현재 폴더(레포 루트)를 배포 소스로 선택
3) 기존 컨텐츠 덮어쓰기 확인 → Yes
4) 배포가 완료되면 VS Code가 브라우저로 앱 URL을 열어줍니다. (https://<appname>.azurewebsites.net)

배포 시 서버가 자동으로 `pip install -r requirements.txt`를 수행하고, `startup.sh`로 Chainlit을 `$PORT`에서 실행합니다.

## 8. 동작 확인
- 브라우저에서 앱 URL 접속
- 첫 화면 로딩 확인, 사이드바(Mode/TopK/Filter/Show Log) 표시 확인
- 간단한 질문을 해보고, 검색/요약이 동작하는지 확인

## 9. 로그 보기 & 문제 해결
- VS Code Azure 패널에서 해당 Web App 우클릭 → "Start Streaming Logs"로 실시간 로그 확인 가능
- 일반 이슈 가이드
  - 500/Crash: 환경 변수 누락 여부 확인 (App Settings 재확인)
  - ModuleNotFoundError: `requirements.txt`에 누락된 패키지 없는지 확인
  - 403/401: Azure AI Search/Azure OpenAI 키 또는 엔드포인트 확인
  - 포트 관련 에러: `startup.sh`가 `$PORT`를 사용하므로 별도 포트 하드코딩 금지
  - WebSocket 이슈: Web sockets 옵션 On 확인

## 10. 비용/플랜 팁
- 테스트: Linux B1(저렴), Always On은 제한적
- 운영: S1 이상 권장(Always On 사용, 더 안정)

## 11. 자주 묻는 질문(FAQ)
- Q: 도커 없이 가능한가요?  
  A: 네, 이 가이드는 Non-Docker 경로로 VS Code에서 바로 배포합니다.
- Q: Python 버전은?  
  A: 3.11 권장(로컬 3.9~3.12 호환). App Service Runtime은 3.11로 설정하세요.
- Q: .env 파일은 올리나요?  
  A: 아니요. 포털의 App Settings에 키를 등록하세요. `.env`는 git에 올리지 않습니다.

---
이제 VS Code만으로 바로 배포/업데이트가 가능합니다. 문제가 생기면 로그 스트림을 먼저 확인하고, 환경 변수와 런타임 설정(Startup Command, Python 버전)을 다시 점검하세요.
