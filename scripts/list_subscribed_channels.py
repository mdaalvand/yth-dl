#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Dict, List


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
        "--no-playlist",
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


def to_upload_key(value: str) -> str:
    if not value:
        return ""
    raw = re.sub(r"\D", "", value)
    return raw[:8] if len(raw) >= 8 else ""


def channel_key(item: Dict) -> str:
    return (
        (item.get("channel_id") or "").strip()
        or (item.get("uploader_id") or "").strip()
        or (item.get("channel_url") or "").strip()
        or (item.get("uploader_url") or "").strip()
        or (item.get("uploader") or item.get("channel") or "").strip().lower()
    )


def normalize_channel_url(item: Dict) -> str:
    for key in ("channel_url", "uploader_url", "url", "webpage_url"):
        value = (item.get(key) or "").strip()
        if not value:
            continue
        if value.startswith("http://") or value.startswith("https://"):
            return value
        if value.startswith("@"):
            return f"https://www.youtube.com/{value}"
        if value.startswith("/"):
            return f"https://www.youtube.com{value}"
    cid = (item.get("channel_id") or "").strip()
    if cid:
        return f"https://www.youtube.com/channel/{cid}"
    return ""


def collect_channels(channels_feed: Dict, subscriptions_feed: Dict) -> List[Dict]:
    by_key: Dict[str, Dict] = {}

    channels_entries = channels_feed.get("entries") or []
    for item in channels_entries:
        base = {
            "channel_id": item.get("channel_id") or item.get("uploader_id"),
            "channel_name": item.get("channel") or item.get("uploader") or item.get("title"),
            "channel_url": normalize_channel_url(item),
            "latest_upload_date": "",
            "latest_video_title": "",
            "latest_video_url": "",
        }
        key = channel_key(base)
        if key:
            by_key[key] = base

    subs_entries = subscriptions_feed.get("entries") or []
    for item in subs_entries:
        base = {
            "channel_id": item.get("channel_id") or item.get("uploader_id"),
            "channel_name": item.get("channel") or item.get("uploader"),
            "channel_url": normalize_channel_url(item),
            "latest_upload_date": item.get("upload_date") or "",
            "latest_video_title": item.get("title") or "",
            "latest_video_url": item.get("webpage_url") or item.get("url") or "",
        }
        key = channel_key(base)
        if not key:
            continue

        if key not in by_key:
            by_key[key] = base
            continue

        current = by_key[key]
        if not current.get("channel_name") and base.get("channel_name"):
            current["channel_name"] = base["channel_name"]
        if not current.get("channel_url") and base.get("channel_url"):
            current["channel_url"] = base["channel_url"]

        if to_upload_key(base.get("latest_upload_date", "")) > to_upload_key(current.get("latest_upload_date", "")):
            current["latest_upload_date"] = base.get("latest_upload_date", "")
            current["latest_video_title"] = base.get("latest_video_title", "")
            current["latest_video_url"] = base.get("latest_video_url", "")

    return list(by_key.values())


def sort_channels(channels: List[Dict], sort_by: str) -> List[Dict]:
    if sort_by == "channel_name":
        return sorted(channels, key=lambda c: (c.get("channel_name") or "").lower())
    if sort_by == "channel_id":
        return sorted(channels, key=lambda c: (c.get("channel_id") or "").lower())
    return sorted(channels, key=lambda c: to_upload_key(c.get("latest_upload_date", "")), reverse=True)


def main() -> int:
    max_results = int((os.getenv("MAX_RESULTS", "100") or "100").strip())
    scan_limit = int((os.getenv("SCAN_LIMIT", "300") or "300").strip())
    sort_by = (os.getenv("SORT_BY", "latest_upload") or "latest_upload").strip()

    cookies_exists = os.path.isfile("cookies.txt")
    if not cookies_exists:
        print("cookies.txt is required for subscriptions data.")
        print("Set repository secret YT_COOKIES and rerun.")
        return 1

    channels_url = "https://www.youtube.com/feed/channels"
    subscriptions_url = "https://www.youtube.com/feed/subscriptions"

    print(f"Reading subscriptions channels from: {channels_url}")
    channels_feed = run_json(metadata_args(cookies_exists) + ["--playlist-end", str(scan_limit), channels_url])

    print(f"Reading subscriptions videos from: {subscriptions_url}")
    subscriptions_feed = run_json(metadata_args(cookies_exists) + ["--playlist-end", str(scan_limit), subscriptions_url])

    channels = collect_channels(channels_feed, subscriptions_feed)
    channels = sort_channels(channels, sort_by)[:max_results]

    if not channels:
        print("No subscribed channels found.")
        return 1

    payload = {
        "source_channels": channels_url,
        "source_subscriptions": subscriptions_url,
        "sort_by": sort_by,
        "count": len(channels),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "channels": channels,
    }

    with open("subscribed_channels.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    with open("subscribed_channels.txt", "w", encoding="utf-8") as f:
        for c in channels:
            name = c.get("channel_name") or "N/A"
            url = c.get("channel_url") or ""
            latest = c.get("latest_upload_date") or "N/A"
            f.write(f"{name} | {latest} | {url}\n")

    with open("subscribed_channels.md", "w", encoding="utf-8") as f:
        f.write("# Subscribed Channels\n\n")
        f.write(f"- Sort by: {sort_by}\n")
        f.write(f"- Selected: {len(channels)}\n\n")
        for i, c in enumerate(channels, start=1):
            name = c.get("channel_name") or "N/A"
            cid = c.get("channel_id") or "N/A"
            url = c.get("channel_url") or "N/A"
            latest = c.get("latest_upload_date") or "N/A"
            latest_title = c.get("latest_video_title") or "N/A"
            latest_video_url = c.get("latest_video_url") or "N/A"
            f.write(f"{i}. {name}\n")
            f.write(f"   - Channel ID: {cid}\n")
            f.write(f"   - Channel URL: {url}\n")
            f.write(f"   - Latest upload date: {latest}\n")
            f.write(f"   - Latest video: {latest_title}\n")
            f.write(f"   - Latest video URL: {latest_video_url}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
