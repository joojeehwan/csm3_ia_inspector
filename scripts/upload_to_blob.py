import os
from pathlib import Path
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()
conn = os.getenv("BLOB_CONNECTION_STRING")
container = os.getenv("BLOB_CONTAINER", "ia-source")
data_dir = Path(os.getenv("DATA_DIR","./data"))

if not conn:
    raise SystemExit("BLOB_CONNECTION_STRING not set in .env")

svc = BlobServiceClient.from_connection_string(conn)
client = svc.get_container_client(container)
client.create_container(exist_ok=True)

for p in data_dir.glob("*.pdf"):
    blob_name = p.name
    print(f"↑ uploading {p} → {container}/{blob_name}")
    with open(p, "rb") as f:
        client.upload_blob(name=blob_name, data=f, overwrite=True)
print("✅ upload complete")
