#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Dict, List, Tuple


def run_json(cmd: List[str]) -> Dict:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError("yt-dlp metadata extraction failed")
    return json.loads(proc.stdout)


def metadata_args(cookies_exists: bool) -> List[str]:
    args = [
        "yt-dlp",
        "--skip-download",
        "--dump-single-json",
        "--flat-playlist",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
        "--extractor-args",
        "youtube:player_client=web,tv",
        "--retries",
        "10",
    ]
    if cookies_exists:
        args += ["--cookies", "cookies.txt"]
    return args


def extract_video_id(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    return ""


def to_upload_key(value: str) -> str:
    if not value:
        return ""
    raw = re.sub(r"\D", "", value)
    return raw[:8] if len(raw) >= 8 else ""


def to_int(value) -> int:
    if value is None:
        return 0
    raw = re.sub(r"[^\d-]", "", str(value))
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def yyyymmdd_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def missed_by_days(upload_date: str, missed_after_days: int) -> bool:
    key = to_upload_key(upload_date)
    if not key:
        return True
    today = datetime.strptime(yyyymmdd_utc(), "%Y%m%d")
    published = datetime.strptime(key, "%Y%m%d")
    age_days = (today - published).days
    return age_days >= missed_after_days


def sort_videos(videos: List[Dict], sort_by: str) -> List[Dict]:
    if sort_by == "view_count":
        return sorted(videos, key=lambda v: to_int(v.get("view_count")), reverse=True)
    if sort_by == "channel_name":
        return sorted(videos, key=lambda v: (v.get("uploader") or v.get("channel") or "").lower())
    return sorted(videos, key=lambda v: to_upload_key(v.get("upload_date", "")), reverse=True)


def collect_missed(subscriptions_feed: Dict, max_results: int, missed_after_days: int) -> List[Tuple[str, Dict]]:
    entries = subscriptions_feed.get("entries") or []
    out: List[Tuple[str, Dict]] = []
    seen = set()

    for item in entries:
        vid = (
            extract_video_id(item.get("id", ""))
            or extract_video_id(item.get("url", ""))
            or extract_video_id(item.get("webpage_url", ""))
        )
        if not vid or vid in seen:
            continue
        seen.add(vid)

        upload_date = item.get("upload_date") or ""
        if not missed_by_days(upload_date, missed_after_days):
            continue

        url = item.get("webpage_url") or item.get("url") or f"https://www.youtube.com/watch?v={vid}"
        out.append((url, item))
        if len(out) >= max_results:
            break

    return out


def main() -> int:
    max_results = int((os.getenv("MAX_RESULTS", "50") or "50").strip())
    scan_limit = int((os.getenv("SCAN_LIMIT", "300") or "300").strip())
    missed_after_days = int((os.getenv("MISSED_AFTER_DAYS", "1") or "1").strip())
    sort_by = (os.getenv("SORT_BY", "upload_date") or "upload_date").strip()

    cookies_exists = os.path.isfile("cookies.txt")
    if not cookies_exists:
        print("cookies.txt is required for subscriptions data.")
        print("Set repository secret YT_COOKIES and rerun.")
        return 1

    subscriptions_url = "https://www.youtube.com/feed/subscriptions"
    print(f"Reading subscriptions feed: {subscriptions_url}")
    feed = run_json(metadata_args(cookies_exists) + ["--playlist-end", str(scan_limit), subscriptions_url])

    missed = collect_missed(feed, max_results=max_results, missed_after_days=missed_after_days)
    videos = []
    for url, item in missed:
        videos.append(
            {
                "url": url,
                "id": item.get("id") or extract_video_id(url),
                "title": item.get("title"),
                "uploader": item.get("uploader") or item.get("channel"),
                "channel_id": item.get("channel_id"),
                "upload_date": item.get("upload_date"),
                "duration": item.get("duration"),
                "view_count": item.get("view_count"),
            }
        )

    videos = sort_videos(videos, sort_by)
    if not videos:
        print("No missed videos found with current threshold.")

    payload = {
        "source": subscriptions_url,
        "count": len(videos),
        "sort_by": sort_by,
        "missed_after_days": missed_after_days,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "videos": videos,
    }

    with open("missed_subscription_videos.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    with open("missed_subscription_videos.txt", "w", encoding="utf-8") as f:
        if videos:
            for v in videos:
                title = v.get("title") or "N/A"
                uploader = v.get("uploader") or "N/A"
                upload_date = v.get("upload_date") or "N/A"
                f.write(f"{title} | {uploader} | {upload_date} | {v['url']}\n")
        else:
            f.write("no_missed_videos\n")

    with open("missed_subscription_videos.md", "w", encoding="utf-8") as f:
        f.write("# Missed Subscription Videos\n\n")
        f.write(f"- Source: {subscriptions_url}\n")
        f.write(f"- Missed threshold (days): {missed_after_days}\n")
        f.write(f"- Sort by: {sort_by}\n")
        f.write(f"- Selected: {len(videos)}\n\n")

        if not videos:
            f.write("- No missed videos found with current threshold.\n")
        else:
            for i, v in enumerate(videos, start=1):
                title = v.get("title") or "N/A"
                uploader = v.get("uploader") or "N/A"
                upload_date = v.get("upload_date") or "N/A"
                duration = v.get("duration")
                view_count = v.get("view_count")
                views_text = f"{view_count:,}" if isinstance(view_count, int) else "N/A"
                f.write(f"{i}. {title}\n")
                f.write(f"   - Channel: {uploader}\n")
                f.write(f"   - Upload date: {upload_date}\n")
                f.write(f"   - Duration: {duration if duration is not None else 'N/A'}\n")
                f.write(f"   - Views: {views_text}\n")
                f.write(f"   - URL: {v['url']}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
