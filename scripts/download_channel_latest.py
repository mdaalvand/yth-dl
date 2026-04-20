#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Tuple


def normalize_channel_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""

    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", value):
        url = f"https://www.youtube.com/channel/{value}"
    elif value.startswith("channel/"):
        url = f"https://www.youtube.com/{value}"
    elif value.startswith("/channel/") or value.startswith("/@"):
        url = f"https://www.youtube.com{value}"
    elif value.startswith("http://") or value.startswith("https://"):
        url = value
    elif value.startswith("@"):
        url = f"https://www.youtube.com/{value}"
    else:
        url = f"https://www.youtube.com/{value}"

    if not re.search(r"/(videos|shorts|streams|featured)(?:/|$)", url):
        url = url.rstrip("/") + "/videos"
    return url


def extract_video_id(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    return ""


def run_json(cmd: List[str]) -> Dict:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError("yt-dlp channel metadata extraction failed")
    return json.loads(proc.stdout)


def build_cmd(channel_url: str, scan_limit: int, cookies_exists: bool) -> List[str]:
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--dump-single-json",
        "--flat-playlist",
        "--playlist-end",
        str(scan_limit),
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
        cmd += ["--cookies", "cookies.txt"]
    cmd.append(channel_url)
    return cmd


def collect_latest(entries: List[Dict], count: int) -> List[Tuple[str, Dict]]:
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
        out.append((f"https://www.youtube.com/watch?v={vid}", item))
        if len(out) >= count:
            break
    return out


def main() -> int:
    channel_input = os.getenv("CHANNEL_INPUT", "").strip()
    channel_count = int((os.getenv("CHANNEL_COUNT", "5") or "5").strip())
    if not channel_input:
        print("CHANNEL_INPUT is required.")
        return 1

    channel_url = normalize_channel_url(channel_input)
    cookies_exists = os.path.isfile("cookies.txt")

    print(f"Reading channel videos: {channel_url}")
    channel_json = run_json(build_cmd(channel_url, channel_count * 4, cookies_exists))
    entries = channel_json.get("entries") or []
    selected = collect_latest(entries, channel_count)
    if not selected:
        print("No videos found for the channel.")
        return 1

    with open("channel_latest_videos.txt", "w", encoding="utf-8") as f:
        for url, _ in selected:
            f.write(url + "\n")

    with open("channel_latest_videos.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "channel_url": channel_url,
                "count": len(selected),
                "videos": [
                    {
                        "url": url,
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "uploader": item.get("uploader") or item.get("channel"),
                    }
                    for url, item in selected
                ],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open("channel_latest_videos.md", "w", encoding="utf-8") as f:
        f.write("# Latest Channel Videos\n\n")
        f.write(f"- Channel: {channel_url}\n")
        f.write(f"- Selected: {len(selected)}\n\n")
        for i, (url, item) in enumerate(selected, start=1):
            title = item.get("title") or "N/A"
            uploader = item.get("uploader") or item.get("channel") or "N/A"
            f.write(f"{i}. {title} | {uploader}\n")
            f.write(f"   - {url}\n")

    env = os.environ.copy()
    env["VIDEO_INPUTS"] = "\n".join(url for url, _ in selected)
    proc = subprocess.run(["python", "scripts/download_videos.py"], env=env)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
