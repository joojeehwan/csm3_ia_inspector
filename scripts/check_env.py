import os
from dotenv import load_dotenv

REQUIRED = [
    "SEARCH_ENDPOINT",
    "SEARCH_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_EMBED_DEPLOYMENT",
    "AZURE_OPENAI_CHAT_DEPLOYMENT",
]

if __name__ == "__main__":
    load_dotenv()
    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        print("❌ Missing in .env:")
        for k in missing:
            print(" -", k)
        raise SystemExit(1)
    # Optional: Bing Search for web_qa mode
    if not os.getenv("BING_SEARCH_KEY"):
        print("ℹ️  Note: BING_SEARCH_KEY not set. 'web_qa' mode will be disabled.")
    else:
        print("✅ Bing Search available for web_qa mode.")
    print("✅ All required env vars are set.")
