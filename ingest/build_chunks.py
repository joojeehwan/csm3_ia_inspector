import os, uuid, re, unicodedata
from pathlib import Path
from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from pypdf import PdfReader
import importlib
try:
    from pdfminer.high_level import extract_text as _pdfminer_extract_text
    _HAS_PDFMINER = True
except Exception:
    _HAS_PDFMINER = False

load_dotenv()
SEARCH_ENDPOINT=os.getenv("SEARCH_ENDPOINT")
SEARCH_API_KEY=os.getenv("SEARCH_API_KEY")
INDEX_CHUNKS=os.getenv("INDEX_CHUNKS","ia-chunks")
INDEX_RAW=os.getenv("INDEX_RAW","ia-raw")
INGEST_MODE=os.getenv("INGEST_MODE","local")  # local | search_raw
# Resolve DATA_DIR relative to project root if it's a relative path
_ROOT = Path(__file__).resolve().parents[1]
_data_dir_str = os.getenv("DATA_DIR","./data")
DATA_DIR = Path(_data_dir_str)
if not DATA_DIR.is_absolute():
    DATA_DIR = _ROOT / _data_dir_str

AOAI_ENDPOINT=os.getenv("AZURE_OPENAI_ENDPOINT")
AOAI_KEY=os.getenv("AZURE_OPENAI_API_KEY")
AOAI_VER=os.getenv("AZURE_OPENAI_API_VERSION")
EMBED_DEPLOY=os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT")

search_chunks = SearchClient(SEARCH_ENDPOINT, INDEX_CHUNKS, AzureKeyCredential(SEARCH_API_KEY))
search_raw    = SearchClient(SEARCH_ENDPOINT, INDEX_RAW,   AzureKeyCredential(SEARCH_API_KEY))
aoai          = AzureOpenAI(azure_endpoint=AOAI_ENDPOINT, api_key=AOAI_KEY, api_version=AOAI_VER)

def clean_text(text: str) -> str:
    # Unicode normalize (fix ligatures like ﬂ → fl, normalize widths)
    t = unicodedata.normalize("NFKC", text)
    # Remove control characters except newlines and tabs
    t = "".join(ch for ch in t if (ch in "\n\t" or unicodedata.category(ch)[0] != "C"))
    # Replace non-breaking spaces and weird spaces with normal space
    t = t.replace("\xa0", " ").replace("\u200b", " ")
    # Collapse long runs of punctuation artifacts
    t = re.sub(r"[\uFFFD]+", " ", t)  # replacement char → space
    # Trim overly long repeated punctuation
    t = re.sub(r"([\-=_*#~])\1{3,}", r"\1\1", t)
    # Normalize whitespace inside lines
    t = re.sub(r"[ \t]+", " ", t)
    # De-hyphenate at line breaks: "exam-\nple" → "example"
    t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)
    # Convert single newlines (within paragraphs) to spaces, keep paragraph breaks
    t = re.sub(r"(?<!\n)\n(?!\n)", " ", t)
    return t


def simple_chunks(text: str, max_len=900, overlap=220):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, buf = [], ""
    for p in paras:
        if len(buf)+len(p)+1 <= max_len: buf = (buf+"\n\n"+p).strip()
        else:
            if buf: out.append(buf)
            keep = buf[-overlap:] if len(buf)>overlap else ""
            buf = (keep+"\n\n"+p).strip()
    if buf: out.append(buf)
    return out

from typing import List


def embed_batch(texts: List[str]) -> List[List[float]]:
    resp = aoai.embeddings.create(model=EMBED_DEPLOY, input=texts)
    return [d.embedding for d in resp.data]


def _quality_score(t: str) -> float:
    t2 = t.strip()
    if not t2:
        return 0.0
    # penalize replacement chars and very short content
    bad = t2.count("\uFFFD")
    letters = sum(ch.isalnum() for ch in t2)
    score = letters / max(len(t2), 1)
    if bad:
        score *= 1.0 / (1 + bad)
    # longer text gets slight bonus
    score *= min(len(t2) / 500.0, 1.0) * 0.2 + 0.8
    return score

def ingest_local():
    batch=[]
    # 1) PDF
    for pdf in DATA_DIR.glob("*.pdf"):
        reader = PdfReader(str(pdf))
        full_text = ""
        for i, page in enumerate(reader.pages, start=1):
            # First try PyPDF
            t = page.extract_text() or ""
            t = clean_text(t)
            sc = _quality_score(t)
            # If bad quality and pdfminer is available, try pdfminer per page
            if sc < 0.25 and _HAS_PDFMINER:
                try:
                    t2 = _pdfminer_extract_text(str(pdf), page_numbers=[i-1]) or ""
                    t2 = clean_text(t2)
                    if _quality_score(t2) > sc:
                        t = t2
                        sc = _quality_score(t2)
                except Exception:
                    pass
            full_text += f"\n\n[Page {i}]\n{t}"
        parts = simple_chunks(full_text, 1200, 150)
        if not parts: continue
        vecs = embed_batch(parts)
        for t, v in zip(parts, vecs):
            batch.append({
                "id": str(uuid.uuid4()),
                "doc_id": pdf.stem,
                "title": pdf.name,
                "chunk": t,
                "contentVector": v,
                "source_uri": f"local://{pdf.name}",
            })
        if len(batch) >= 500:
            search_chunks.upload_documents(batch); batch.clear()

    # 2) DOCX (python-docx)
    for docx_path in DATA_DIR.glob("*.docx"):
        try:
            docx_mod = importlib.import_module("docx")
            _Docx = getattr(docx_mod, "Document")
            doc = _Docx(str(docx_path))
            paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
            text = clean_text("\n\n".join(paras))
        except Exception as e:
            print(f"WARN: DOCX 읽기 실패: {docx_path.name} — {e}")
            continue
        parts = simple_chunks(text, 1200, 150)
        if not parts: continue
        vecs = embed_batch(parts)
        for t, v in zip(parts, vecs):
            batch.append({
                "id": str(uuid.uuid4()),
                "doc_id": docx_path.stem,
                "title": docx_path.name,
                "chunk": t,
                "contentVector": v,
                "source_uri": f"local://{docx_path.name}",
            })
        if len(batch) >= 500:
            search_chunks.upload_documents(batch); batch.clear()

    # 3) TXT
    for txt in DATA_DIR.glob("*.txt"):
        try:
            text = Path(txt).read_text(encoding="utf-8", errors="ignore")
            text = clean_text(text)
        except Exception as e:
            print(f"WARN: TXT 읽기 실패: {txt.name} — {e}")
            continue
        parts = simple_chunks(text, 1200, 150)
        if not parts: continue
        vecs = embed_batch(parts)
        for t, v in zip(parts, vecs):
            batch.append({
                "id": str(uuid.uuid4()),
                "doc_id": txt.stem,
                "title": txt.name,
                "chunk": t,
                "contentVector": v,
                "source_uri": f"local://{txt.name}",
            })
        if len(batch) >= 500:
            search_chunks.upload_documents(batch); batch.clear()

    if batch:
        search_chunks.upload_documents(batch)
    print("✅ local ingest (pdf/docx/txt) → ia-chunks complete")

def ingest_from_raw(limit=500):
    docs = search_raw.search(search_text="*", top=limit, select=["id","content","metadata_storage_name","metadata_storage_path","page"])
    batch=[]
    for d in docs:
        doc_id = d["id"]; title = d.get("metadata_storage_name",""); content = d.get("content","") or ""
        if not content.strip(): continue
        parts = simple_chunks(content, 1200, 150)
        vecs = embed_batch(parts)
        for t, v in zip(parts, vecs):
            batch.append({
                "id": str(uuid.uuid4()),
                "doc_id": doc_id, "title": title, "chunk": t,
                "contentVector": v, "source_uri": d.get("metadata_storage_path")
            })
        if len(batch) >= 500:
            search_chunks.upload_documents(batch); batch.clear()
    if batch: search_chunks.upload_documents(batch)
    print("✅ ia-raw → ia-chunks complete")

if __name__ == "__main__":
    if INGEST_MODE == "search_raw":
        ingest_from_raw()
    else:
        ingest_local()
