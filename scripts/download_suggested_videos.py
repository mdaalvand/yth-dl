#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Tuple


def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return f"https://www.youtube.com/watch?v={raw}"


def extract_video_id(url: str) -> str:
    m = re.search(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else ""


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


def collect_related(source_info: Dict, source_id: str, max_results: int) -> List[Tuple[str, Dict]]:
    related_items = source_info.get("related_videos") or []
    out: List[Tuple[str, Dict]] = []
    seen = set()
    for item in related_items:
        vid = item.get("id") or extract_video_id(item.get("url", ""))
        if not vid or vid == source_id or vid in seen:
            continue
        seen.add(vid)
        out.append((f"https://www.youtube.com/watch?v={vid}", item))
        if len(out) >= max_results:
            break
    return out


def fallback_search(
    source_info: Dict, source_id: str, max_results: int, existing: List[Tuple[str, Dict]], cookies_exists: bool
) -> List[Tuple[str, Dict]]:
    needed = max_results - len(existing)
    if needed <= 0:
        return existing

    title = source_info.get("title") or ""
    uploader = source_info.get("uploader") or source_info.get("channel") or ""
    query = f"{title} {uploader}".strip() or source_id

    search_cmd = metadata_args(cookies_exists) + [f"ytsearch{needed * 2}:{query}"]
    search_json = run_json(search_cmd)
    entries = search_json.get("entries") or []

    seen_ids = {extract_video_id(url) for url, _ in existing}
    seen_ids.add(source_id)

    for item in entries:
        vid = item.get("id") or extract_video_id(item.get("url", ""))
        if not vid or vid in seen_ids:
            continue
        seen_ids.add(vid)
        existing.append((f"https://www.youtube.com/watch?v={vid}", item))
        if len(existing) >= max_results:
            break

    return existing


def main() -> int:
    source_input = os.getenv("SOURCE_VIDEO", "").strip()
    max_results = int((os.getenv("MAX_RESULTS", "20") or "20").strip())
    if not source_input:
        print("SOURCE_VIDEO is required.")
        return 1

    source_url = normalize_url(source_input)
    source_id = extract_video_id(source_url)
    cookies_exists = os.path.isfile("cookies.txt")

    print(f"Source video: {source_url}")
    source_info = run_json(metadata_args(cookies_exists) + [source_url])

    suggested = collect_related(source_info, source_id, max_results)
    if len(suggested) < max_results:
        suggested = fallback_search(source_info, source_id, max_results, suggested, cookies_exists)

    suggested = suggested[:max_results]
    if not suggested:
        print("No suggested videos found.")
        return 1

    os.makedirs("downloads", exist_ok=True)
    with open("suggested_videos.txt", "w", encoding="utf-8") as f:
        for url, _ in suggested:
            f.write(url + "\n")

    with open("suggested_videos.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "source_video": source_url,
                "count": len(suggested),
                "suggested": [
                    {
                        "url": url,
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "uploader": item.get("uploader") or item.get("channel"),
                        "duration": item.get("duration"),
                        "view_count": item.get("view_count"),
                    }
                    for url, item in suggested
                ],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open("suggested_videos.md", "w", encoding="utf-8") as f:
        f.write("# Suggested Videos\n\n")
        f.write(f"- Source: {source_url}\n")
        f.write(f"- Selected: {len(suggested)}\n\n")
        for idx, (url, item) in enumerate(suggested, start=1):
            title = item.get("title") or "N/A"
            uploader = item.get("uploader") or item.get("channel") or "N/A"
            f.write(f"{idx}. {title} | {uploader}\n")
            f.write(f"   - {url}\n")

    env = os.environ.copy()
    env["VIDEO_INPUTS"] = "\n".join(url for url, _ in suggested)
    proc = subprocess.run(["python", "scripts/download_videos.py"], env=env)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())

