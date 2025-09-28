import os
import requests
from dotenv import load_dotenv

load_dotenv()

BING_SEARCH_ENDPOINT = os.getenv("BING_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search")
BING_SEARCH_KEY = os.getenv("BING_SEARCH_KEY")

def web_search(query: str, top: int = 5):
    if not BING_SEARCH_KEY:
        raise RuntimeError("BING_SEARCH_KEY is not set in .env")
    params = {
        "q": query,
        "count": top,
        "mkt": "ko-KR",
        "textDecorations": "false",
        "textFormat": "Raw",
    }
    headers = {"Ocp-Apim-Subscription-Key": BING_SEARCH_KEY}
    resp = requests.get(BING_SEARCH_ENDPOINT, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    values = data.get("webPages", {}).get("value", [])
    hits = []
    for v in values[:top]:
        hits.append({
            "title": v.get("name", ""),
            "chunk": v.get("snippet", ""),
            "source_uri": v.get("url", ""),
            "page": None,
        })
    return hits
