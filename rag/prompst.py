QA_PROMPT = """아래 근거들을 '사실 기반'으로 통합해 답하세요.
- 추정 금지, 각 문단 끝에 [src: ...] 표기
질문: {question}
근거:
{snippets}
"""

IA_SUMMARY_PROMPT = """아래 근거를 바탕으로 '요약/재사용 체크리스트/리스크'를 간결히 작성하세요.
각 항목 끝에 [근거: 문서/페이지/URI] 2~3개 표기.
요약 대상: {question}
근거:
{snippets}
"""

WEB_QA_PROMPT = """
아래 웹 검색 근거를 바탕으로 최신 정보를 사실 기반으로 답하세요.
- 추정/과장 금지, 각 문단 끝에 [src: URL] 표기
질문: {question}
근거:
{snippets}
"""
