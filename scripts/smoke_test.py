"""
Minimal end-to-end smoke test (robust to CWD):
- Ensures project root on sys.path and as CWD
- Checks env
- Creates/refreshes Search index
- Ingests local PDFs (if any) into ia-chunks
- Runs one sample query via retriever
"""
import os
import sys
import subprocess
from pathlib import Path
from dotenv import load_dotenv

# Resolve project root (two levels up from this file)
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[1]

# Ensure imports work regardless of where we run from
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

load_dotenv()

print("[1/4] Checking env…")
# Run as a subprocess to avoid import path issues
subprocess.run([sys.executable, "scripts/check_env.py"], check=True)

print("[2/4] Creating search index…")
subprocess.run([sys.executable, "infra/create_index.py"], check=True)

print("[3/4] Ingesting local PDFs (if any)…")
subprocess.run([sys.executable, "ingest/build_chunks.py"], check=True)

print("[4/4] Querying retriever…")
from retrivers.internal_search import hybrid_search
hits = hybrid_search("테스트", top=3)
print("Hits:")
for h in hits:
    print("-", h.get("title"), h.get("page"), str(h.get("chunk",""))[:80])

print("✅ Smoke test complete")
