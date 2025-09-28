import json, os, sys, re
from pathlib import Path
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv

API_VERSION = "2024-07-01"

# Load env
load_dotenv()
endpoint = os.getenv("SEARCH_ENDPOINT", "").strip()
key      = os.getenv("SEARCH_API_KEY", "").strip()
index_def_path = Path(__file__).with_name("search_index_chunks.json")

def fail(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)

if not endpoint or not key:
    fail("SEARCH_ENDPOINT / SEARCH_API_KEY not set in .env")

# Basic endpoint validation + helpful hints
if endpoint.lower().startswith("hhttp") or endpoint.lower().startswith("hhttps"):
    fail(f"Malformed SEARCH_ENDPOINT (starts with 'hhttp'/'hhttps'): {endpoint}")

if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
    # Allow shorthand like '<name>.search.windows.net'
    endpoint = "https://" + endpoint

parsed = urlparse(endpoint)
if not parsed.scheme or not parsed.netloc:
    fail(f"Invalid SEARCH_ENDPOINT URL: {endpoint}")

if not re.search(r"\.search\.windows\.net$", parsed.netloc):
    print(f"WARN: SEARCH_ENDPOINT host looks unusual: {parsed.netloc}")

headers = {
    "api-key": key,
    "Content-Type": "application/json",
}

# Read index schema JSON
def load_index_schema(p: Path) -> dict:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

schema = load_index_schema(index_def_path)
index_name = schema.get("name", "ia-chunks")

base = endpoint.rstrip("/")
index_url = f"{base}/indexes/{index_name}?api-version={API_VERSION}"

# Delete if exists (ignore 404)
del_resp = requests.delete(index_url, headers=headers)
if del_resp.status_code in (200, 204):
    print(f"Deleted existing index: {index_name}")
elif del_resp.status_code != 404:
    print(f"WARN: delete index returned {del_resp.status_code}: {del_resp.text}")

# Create index with full JSON schema so vector/semantic settings are honored
put_resp = requests.put(index_url, headers=headers, data=json.dumps(schema))
if put_resp.ok:
    print(f"✅ Created index: {index_name}")
else:
    fail(f"Failed to create index [{put_resp.status_code}]: {put_resp.text}")
