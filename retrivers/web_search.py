import os
import requests
from dotenv import load_dotenv

load_dotenv()

# Allow overriding endpoint (e.g., Cognitive Services multi-service):
#   https://<resource>.cognitiveservices.azure.com/bing/v7.0/search
BING_SEARCH_ENDPOINT = (os.getenv("BING_SEARCH_ENDPOINT") or "https://api.bing.microsoft.com/v7.0/search").strip()
# Subscription key for Bing Web Search v7
BING_SEARCH_KEY = (os.getenv("BING_SEARCH_KEY") or "").strip()
# Optional region header for certain Azure configurations
BING_SEARCH_REGION = (os.getenv("BING_SEARCH_REGION") or "").strip()

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
    if BING_SEARCH_REGION:
        headers["Ocp-Apim-Subscription-Region"] = BING_SEARCH_REGION
    resp = requests.get(BING_SEARCH_ENDPOINT, params=params, headers=headers, timeout=15)
    # Provide clearer guidance on common misconfigs
    if resp.status_code == 401:
        raise RuntimeError(
            "Bing Search 401 Unauthorized. Check that your BING_SEARCH_KEY is a valid Bing Search v7 key and the endpoint matches your resource. "
            "For Azure Cognitive Services multi-service, set BING_SEARCH_ENDPOINT to https://<resource>.cognitiveservices.azure.com/bing/v7.0/search."
        )
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
