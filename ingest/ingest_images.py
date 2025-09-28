"""Ingest images (PNG/JPG) by OCR -> chunks -> embeddings -> Azure AI Search.

Requirements:
  - Tesseract installed locally (macOS: `brew install tesseract`)
  - Pillow, pytesseract installed (in requirements.txt)
Environment:
  - IMAGE_DIR=./images (default) for source images
  - INDEX_CHUNKS (same as text ingest)
  - Azure OpenAI + Azure Search env vars (same as build_chunks.py)
"""
import os, uuid, re
from pathlib import Path
from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
import pytesseract
from PIL import Image

load_dotenv()
_ROOT = Path(__file__).resolve().parents[1]
_img_dir_str = os.getenv("IMAGE_DIR","./images")
IMAGE_DIR = Path(_img_dir_str)
if not IMAGE_DIR.is_absolute():
    IMAGE_DIR = _ROOT / _img_dir_str
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

SEARCH_ENDPOINT=os.getenv("SEARCH_ENDPOINT")
SEARCH_API_KEY=os.getenv("SEARCH_API_KEY")
INDEX_CHUNKS=os.getenv("INDEX_CHUNKS","ia-chunks")

AOAI_ENDPOINT=os.getenv("AZURE_OPENAI_ENDPOINT")
AOAI_KEY=os.getenv("AZURE_OPENAI_API_KEY")
AOAI_VER=os.getenv("AZURE_OPENAI_API_VERSION")
EMBED_DEPLOY=os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT")

if not (SEARCH_ENDPOINT and SEARCH_API_KEY and AOAI_ENDPOINT and AOAI_KEY):
    raise SystemExit("❌ Missing required env vars for search or openai.")

search = SearchClient(SEARCH_ENDPOINT, INDEX_CHUNKS, AzureKeyCredential(SEARCH_API_KEY))
aoai   = AzureOpenAI(azure_endpoint=AOAI_ENDPOINT, api_key=AOAI_KEY, api_version=AOAI_VER)

SUPPORTED = {".png",".jpg",".jpeg"}

def simple_chunks(text: str, max_len=1200, overlap=150):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, buf = [], ""
    for p in paras:
        if len(buf)+len(p)+1 <= max_len: buf = (buf+"\n\n"+p).strip()
        else:
            if buf: out.append(buf)
            keep = buf[-overlap:] if len(buf)>overlap else ""
            buf = (keep+"\n\n"+p).strip()
    if buf: out.append(buf)
    return out or ([text] if text.strip() else [])

def embed_batch(texts):
    resp = aoai.embeddings.create(model=EMBED_DEPLOY, input=texts)
    return [d.embedding for d in resp.data]

def ocr_image(path: Path) -> str:
    try:
        with Image.open(path) as img:
            txt = pytesseract.image_to_string(img, lang="kor+eng")
            return txt.strip()
    except Exception as e:
        print(f"⚠️ OCR failed {path}: {e}")
        return ""

def ingest_images():
    batch=[]
    count_files=0
    for img_path in IMAGE_DIR.iterdir():
        if img_path.suffix.lower() not in SUPPORTED: continue
        count_files +=1
        text = ocr_image(img_path)
        if not text:
            print(f"(skip empty OCR) {img_path.name}")
            continue
        parts = simple_chunks(text)
        vecs = embed_batch(parts)
        for t, v in zip(parts, vecs):
            batch.append({
                "id": str(uuid.uuid4()),
                "doc_id": img_path.stem,
                "title": img_path.name,
                "chunk": t,
                "contentVector": v,
                "source_uri": f"image://{img_path.name}",
            })
        if len(batch) >= 400:
            search.upload_documents(batch); batch.clear()
    if batch: search.upload_documents(batch)
    print(f"✅ image ingest complete (files scanned={count_files})")

if __name__ == "__main__":
    ingest_images()
