#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
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


def extract_video_id(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    return ""


def collect_home_recommendations(home_json: Dict, max_results: int) -> List[Tuple[str, Dict]]:
    entries = home_json.get("entries") or []
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
        if len(out) >= max_results:
            break
    return out


def main() -> int:
    max_results = int((os.getenv("MAX_RESULTS", "20") or "20").strip())
    cookies_exists = os.path.isfile("cookies.txt")
    if not cookies_exists:
        print("cookies.txt is required for personalized home recommendations.")
        print("Set repository secret YT_COOKIES and rerun.")
        return 1

    home_url = "https://www.youtube.com/feed/recommended"
    print(f"Reading personalized home feed: {home_url}")
    home_cmd = metadata_args(cookies_exists) + [
        "--flat-playlist",
        "--playlist-end",
        str(max_results * 4),
        home_url,
    ]
    home_json = run_json(home_cmd)
    recommended = collect_home_recommendations(home_json, max_results)
    if not recommended:
        print("No recommended videos found in home feed.")
        return 1

    os.makedirs("downloads", exist_ok=True)
    with open("recommended_videos.txt", "w", encoding="utf-8") as f:
        for url, _ in recommended:
            f.write(url + "\n")

    with open("recommended_videos.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "source": home_url,
                "count": len(recommended),
                "recommended": [
                    {
                        "url": url,
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "uploader": item.get("uploader") or item.get("channel"),
                        "duration": item.get("duration"),
                        "view_count": item.get("view_count"),
                    }
                    for url, item in recommended
                ],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open("recommended_videos.md", "w", encoding="utf-8") as f:
        f.write("# Home Recommended Videos\n\n")
        f.write(f"- Source: {home_url}\n")
        f.write(f"- Selected: {len(recommended)}\n\n")
        for idx, (url, item) in enumerate(recommended, start=1):
            title = item.get("title") or "N/A"
            uploader = item.get("uploader") or item.get("channel") or "N/A"
            f.write(f"{idx}. {title} | {uploader}\n")
            f.write(f"   - {url}\n")

    env = os.environ.copy()
    env["VIDEO_INPUTS"] = "\n".join(url for url, _ in recommended)
    proc = subprocess.run(["python", "scripts/download_videos.py"], env=env)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
