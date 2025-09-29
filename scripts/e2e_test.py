"""
End-to-end test script:
- Ensures project root CWD
- (Re)create index
- Ingest local data (pdf/docx/txt)
- Run a set of queries (qa, ia_summary)
- Apply/clear filter based on one uploaded doc (if exists)
- Optionally validate LangGraph path if USE_LANGGRAPH=true
"""
import os
import sys
from pathlib import Path
import subprocess
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
load_dotenv()

PY = sys.executable

print("[1/6] Create/refresh index…")
subprocess.run([PY, "infra/create_index.py"], check=True)

print("[2/6] Ingest local data (pdf/docx/txt)…")
subprocess.run([PY, "ingest/build_chunks.py"], check=True)

print("[3/6] Run QA queries…")
from retrivers.internal_search import hybrid_search

queries_file = Path("scripts/test_queries.txt")
queries = [q.strip() for q in queries_file.read_text(encoding="utf-8").splitlines() if q.strip()]

for q in queries:
    hits = hybrid_search(q, top=5)
    print(f"Q: {q}")
    if not hits:
        print("  - no hits")
    else:
        for h in hits[:3]:
            print("  -", h.get("title"), h.get("page"), str(h.get("chunk",""))[:120].replace("\n"," "))

print("[4/6] Prepare Chainlit simulation (settings)…")
# Simulate core prompt formatting used by app for QA and IA_SUMMARY
from rag.prompst import QA_PROMPT, IA_SUMMARY_PROMPT

def _format_snippets(hits):
    rows=[]
    for h in hits[:5]:
        title=h.get("title","")
        page=h.get("page")
        uri=h.get("source_uri","")
        chunk=(str(h.get("chunk",""))[:300]).replace("\n"," ")
        page_part=f" p.{page}" if page not in (None,"") else ""
        rows.append(f"- {title}{page_part}: {chunk} [src: {uri}]")
    return "\n".join(rows)

if queries:
    q = queries[0]
    hits = hybrid_search(q, top=5)
    print("QA_PROMPT preview:\n", QA_PROMPT.format(question=q, snippets=_format_snippets(hits) or "(근거 없음)")[:600])
    print("IA_SUMMARY_PROMPT preview:\n", IA_SUMMARY_PROMPT.format(question=q, snippets=_format_snippets(hits) or "(근거 없음)")[:600])

print("[5/6] Filter smoke (if any uploads)")
# We don't have app session here; just demonstrate OData filter behavior by doc_id if any hit contains doc_id
if queries:
    q = queries[0]
    hits = hybrid_search(q, top=5)
    doc_id = None
    for h in hits:
        if h.get("doc_id"):
            doc_id = h["doc_id"]; break
    if doc_id:
        fhits = hybrid_search(q, top=5, filter=f"doc_id eq '{doc_id}'")
        print(f"Filtered by doc_id={doc_id} → {len(list(fhits))} hits")
    else:
        print("No doc_id found in hits to demonstrate filter.")

print("[6/6] Done. E2E test finished.")
