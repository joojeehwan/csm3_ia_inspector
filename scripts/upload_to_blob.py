import os
from pathlib import Path
from datetime import datetime
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()
conn = os.getenv("BLOB_CONNECTION_STRING")
container = os.getenv("BLOB_CONTAINER", "ia-source")

# Default to repo-root /data to align with gen_sample_pdfs.py output
ROOT = Path(__file__).resolve().parents[1]
data_dir = ROOT / os.getenv("DATA_DIR", "data")

if not conn:
    raise SystemExit("BLOB_CONNECTION_STRING not set in .env")

svc = BlobServiceClient.from_connection_string(conn)
client = svc.get_container_client(container)
try:
    client.create_container()
except Exception:
    # likely already exists or insufficient perms; proceed if exists
    pass

pdfs = sorted(data_dir.glob("*.pdf"))
if not pdfs:
    print(f"⚠️  no PDFs found under: {data_dir}")
    print("Hint: run 'python scripts/gen_sample_pdfs.py' to create test PDFs.")
else:
    for p in pdfs:
        blob_name = p.name
        print(f"↑ uploading {p} → {container}/{blob_name}")
        with open(p, "rb") as f:
            client.upload_blob(name=blob_name, data=f, overwrite=True)
    print(f"✅ upload complete: {len(pdfs)} file(s)")
