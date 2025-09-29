Used 1 reference
I'll quickly read app.py and chainlit.md to list all user-facing features and commands accurately, so I can tailor precise test inputs and acceptance criteria for each.

Read app.py

Completed (4/5) 재배포 가이드 제공

좋아요—현재 app.py 기준으로 노출된 모든 기능을 커버하는 “입력 예시 + 기대 결과”를 모아서 드릴게요. 체계적으로 스모크 테스트부터 고급까지 빠르게 돌릴 수 있게 구성했습니다.

A. 공통 사전 세팅
사이드바 설정 체크: 모드(mode), Top K(top_k), OData 필터(filter), 결과 후 로그 표시(show_log)
필수 환경 변수 설정: Search/AOAI 키 등
기본 가정: LangGraph 비활성(기본 false). Bing 키가 있으면 web_qa 모드가 노출됩니다.
B. 스모크 테스트 5분 코스
기본 QA 동작
입력: “이 앱은 어떤 문서를 검색하나요?”
기대: 답변 1개 + “근거” 섹션에 최대 5개의 근거 메시지
성공 기준: 에러 없이 답변/근거 표출, 히스토리에 1건 기록
히스토리 확인
입력: “/history”
기대: “세션 히스토리 (최근 5개)” 목록과 “/show N” 안내
로그 보기
입력: “/show 1”
기대: “#[1] [qa] 질문…” 형태의 로그 카드와, 검색 히트 요약
대시보드 빈 상태
입력: “/dashboard”
기대: 업로드 문서 수 0, 청크 수 0, 체크리스트 완료율 0%, 상위 키워드 없음
업로드 UX 시작
입력: “/upload”
기대: 파일 선택 요청(AskFileMessage). 실테스트는 아래 업로드 섹션에서 진행
C. 모드/설정 관련 테스트
모드 전환
동작: 사이드바 mode=“ia_summary”, top_k=5로 변경
입력: “/history” 또는 임의 질문
기대: 설정 변경 알림 메시지(“설정이 업데이트되었습니다…”), 이후 질의 시 요약형 답변
로그 패널 자동 표시
동작: show_log=True로 변경
입력: “회사 내부 정책 변경점 요약해줘”
기대: 답변 후 자동으로 로그 카드가 추가 출력
OData 필터 적용
동작: filter="system eq 'kb' and year ge 2023"
입력: “최근 보안 가이드 요약”
기대: 답변 + 근거가 해당 필터의 문서 범위에서만 나옴
D. 업로드/인덱싱 플로우
파일 업로드
입력: “/upload” → 샘플 PDF 또는 TXT 업로드 (예: 1~2페이지 텍스트)
기대:
“📤 N개 파일 처리 중…” 메시지
파일별 처리 결과 카드: doc_id, 청크 수, 요약, 해시태그, 유사 문서(있으면), 체크리스트(최대 10개)
“show_upload”와 “show_history” 액션 버튼
세션의 uploads 배열에 레코드가 저장됨
업로드 목록
입력: “/uploads”
기대: “업로드 문서 목록”과 최근 업로드 날짜(ts). “최근 업로드 보기” 액션 노출
업로드 상세
액션: “show_upload” 클릭 (value: last 또는 인덱스)
기대: 상세 카드(요약/키워드/유사 문서/체크리스트)
체크리스트 토글
액션: 상세 카드의 “toggle_check” 액션 클릭 (value: “0:1” 같은 형식)
기대: “체크리스트 1번 항목을 완료/미완료로 표시” 알림, 재호출 시 상태 토글
문서 한정 검색
액션: 상세 카드의 “use_filter” 클릭
기대: “이제 검색은 해당 문서(doc_id=…)로 제한됩니다.”
이후 질문: “이 문서의 핵심 포인트 알려줘”
기대: 해당 문서 근거 위주로 답변/근거가 제한
필터 해제
액션: “clear_filter” 클릭
기대: “검색 필터가 해제되었습니다.”
E. 내부 검색 QA 시나리오
모드: qa, top_k=8
입력 예시:
“회사 정보보호 정책의 비밀번호 규칙은?”
“2024년 변경된 휴가 정책 핵심만 정리해줘”
“클라우드 비용 절감을 위해 권장하는 3가지 액션은?”
기대: 정책/문서에서 발췌한 답변 + 근거(제목, p.번호, source_uri)
에러/엣지

검색 결과 없음: “(근거 없음)” 기반 답변이 생성되며 근거가 비어있을 수 있음
필터 구문 오류: hybrid_search 쿼리에서 예외 발생 시 메시지로 표출될 수 있으니, 올바른 OData 문법 사용
F. IA 요약 모드(ia_summary)
모드: ia_summary, top_k=5
입력 예시:
“최근 보안 감사 보고서 핵심 요약해줘”
“워크플로우 자동화 관련 내부문서 요약”
기대: 요약 중심 답변 + 근거
G. 웹 검색 모드(web_qa, Bing Key 필요)
전제: BING_SEARCH_KEY 설정됨 → 모드 선택에 web_qa 노출
모드: web_qa, top_k=5
입력 예시:
“Azure App Service에서 Python 앱 스타트업 커맨드 설정 방법?”
“text-embedding-3-large 특징 간단 요약”
기대: 웹 검색 결과 근거를 바탕으로 한 답변 + 출처 링크 포함 근거
H. LangGraph 경로(옵션)
전제: USE_LANGGRAPH=true, orchestrator.py 정상
입력: 일반 질문
기대: LangGraph 경로에서 answer/hits를 반환하여 답변 및 근거 카드 출력
실패 시: “LangGraph 실행 오류… 일반 모드로 재시도합니다.” 안내 후 기본 경로로 처리
I. 에러/복구 시나리오
Search/AOAI 자격증명 누락
기대: 초기 질의 시 예외 메시지, Log Stream에서 인증 오류 확인
조치: 포털 App Settings 갱신 후 Restart
PDF 텍스트 추출 실패
케이스: 스캔 PDF(텍스트 미검출)
기대: “파일 읽기 실패: …” 메시지 또는 요약/키워드 생성 실패 대체 처리
조치: OCR 파이프라인(pytesseract) 도입 고려
업로드 후 유사 문서 없음
기대: “유사 문서” 섹션 미표시 또는 빈 섹션
정상: 코퍼스에 유사항목이 없는 경우
J. 간단 “합격 기준” 체크리스트
질의→답변→근거까지 3회 이상 정상 동작
/history, /show N, /dashboard, /uploads, /upload 모두 정상 응답
업로드 1건 이상에서 요약/키워드/체크리스트 생성
checklist 토글 액션 정상
use_filter/clear_filter 액션 후 검색 범위 변화 확인
web_qa 모드(있다면)에서 외부 검색 근거 포함
에러 발생 시 사용자 메시지로 안내되고 앱이 중단되지 않음
필요하시면 위 테스트를 한 번에 돌릴 수 있는 “테스트 스크립트 카드”를 Chainlit 초기 메시지에 추가하는 작은 개선도 해드릴 수 있어요. 또는 smoke_test.py에 API 레벨 스모크테스트(간단한 함수 호출 모킹 기반)를 넣는 방법도 있습니다. 어떤 방식으로 자동화하고 싶으신지 알려주세요!
