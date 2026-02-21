import json
from pathlib import Path

NEWS_DATA_DIR = Path("D:/Gemini CLI/News")
SEEN_ARTICLES_FILE = NEWS_DATA_DIR / "seen_articles.json"

def main(n: int = 31):
    if not SEEN_ARTICLES_FILE.exists():
        print("Seen articles file not found.")
        return

    with open(SEEN_ARTICLES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    seen = data.get('seen', {})
    print(f"Total seen articles before: {len(seen)}")

    # Sort by timestamp descending, remove the N most recent
    sorted_items = sorted(seen.items(), key=lambda x: x[1], reverse=True)
    
    to_remove = sorted_items[:n]
    to_keep = sorted_items[n:]

    print(f"\nRemoving {len(to_remove)} most recent articles:")
    for link, ts in to_remove:
        print(f"  - {ts}: {link[:80]}")

    data['seen'] = dict(to_keep)

    with open(SEEN_ARTICLES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    print(f"\nRemoved: {len(to_remove)}")
    print(f"Remaining: {len(to_keep)}")

if __name__ == "__main__":
    main()
