import json
from pathlib import Path
from datetime import datetime

NEWS_DATA_DIR = Path("D:/Gemini CLI/News")
SEEN_ARTICLES_FILE = NEWS_DATA_DIR / "seen_articles.json"

def main():
    if not SEEN_ARTICLES_FILE.exists():
        print("Seen articles file not found.")
        return

    with open(SEEN_ARTICLES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    seen = data.get('seen', {})
    print(f"Total seen articles before: {len(seen)}")

    # Remove articles seen on or after Feb 7, 2026
    cutoff_date = "2026-02-07"
    
    new_seen = {}
    removed_count = 0
    
    for link, timestamp in seen.items():
        if timestamp.startswith(cutoff_date) or timestamp > "2026-02-07":
            removed_count += 1
            # print(f"Removing: {link} (Seen: {timestamp})")
        else:
            new_seen[link] = timestamp

    data['seen'] = new_seen
    
    with open(SEEN_ARTICLES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    print(f"Removed {removed_count} articles marked as seen on/after {cutoff_date}")
    print(f"Remaining seen articles: {len(new_seen)}")

if __name__ == "__main__":
    main()
