#!/usr/bin/env python3
import json
import os
import random
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


def run_json_lines(cmd: List[str]) -> List[Dict]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError("yt-dlp metadata extraction failed")
    out: List[Dict] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def metadata_args(cookies_exists: bool, single_json: bool = True) -> List[str]:
    args = [
        "yt-dlp",
        "--skip-download",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
        "--extractor-args",
        "youtube:player_client=web,tv",
        "--retries",
        "10",
    ]
    if single_json:
        args.append("--dump-single-json")
    if cookies_exists:
        args += ["--cookies", "cookies.txt"]
    return args


def to_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def to_upload_key(value: str) -> str:
    if not value:
        return ""
    raw = re.sub(r"\D", "", value)
    if len(raw) >= 8:
        return raw[:8]
    return ""


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


def collect_fallback_recommendations(home_json: Dict, max_results: int) -> List[Tuple[str, Dict]]:
    found_ids: List[str] = []
    seen = set()

    def visit(value):
        if len(found_ids) >= max_results:
            return
        if isinstance(value, dict):
            for key in ("id", "url", "webpage_url", "original_url"):
                vid = extract_video_id(str(value.get(key, "")))
                if vid and vid not in seen:
                    seen.add(vid)
                    found_ids.append(vid)
                    if len(found_ids) >= max_results:
                        return
            for v in value.values():
                visit(v)
                if len(found_ids) >= max_results:
                    return
            return
        if isinstance(value, list):
            for item in value:
                visit(item)
                if len(found_ids) >= max_results:
                    return
            return
        if isinstance(value, str):
            vid = extract_video_id(value)
            if vid and vid not in seen:
                seen.add(vid)
                found_ids.append(vid)

    visit(home_json)
    return [(f"https://www.youtube.com/watch?v={vid}", {}) for vid in found_ids[:max_results]]


def enrich_video_metadata(candidates: List[Tuple[str, Dict]], cookies_exists: bool) -> Dict[str, Dict]:
    urls = [url for url, _ in candidates]
    if not urls:
        return {}

    details: Dict[str, Dict] = {}
    for i in range(0, len(urls), 20):
        chunk = urls[i : i + 20]
        cmd = metadata_args(cookies_exists, single_json=False) + ["--dump-json"] + chunk
        for item in run_json_lines(cmd):
            vid = extract_video_id(item.get("id", "")) or extract_video_id(item.get("webpage_url", ""))
            if not vid:
                continue
            details[vid] = item
    return details


def sort_candidates(candidates: List[Tuple[str, Dict]], sort_by: str) -> List[Tuple[str, Dict]]:
    if sort_by == "view_count":
        return sorted(candidates, key=lambda x: to_int(x[1].get("view_count"), 0), reverse=True)
    if sort_by == "upload_date":
        return sorted(candidates, key=lambda x: to_upload_key(x[1].get("upload_date", "")), reverse=True)
    if sort_by == "duration":
        return sorted(candidates, key=lambda x: to_int(x[1].get("duration"), 0), reverse=True)
    if sort_by == "title":
        return sorted(candidates, key=lambda x: (x[1].get("title") or "").lower())
    return candidates


def pick_candidates(candidates: List[Tuple[str, Dict]], max_results: int, selection_mode: str) -> List[Tuple[str, Dict]]:
    if len(candidates) <= max_results:
        return candidates

    if selection_mode == "random":
        # Keep randomness while biasing toward highest-ranked candidates.
        pool_size = min(len(candidates), max_results * 3)
        pool = candidates[:pool_size]
        random.shuffle(pool)
        return pool[:max_results]

    if selection_mode == "mixed":
        top_n = max_results // 2
        picked = candidates[:top_n]
        remaining = candidates[top_n:]
        random.shuffle(remaining)
        picked.extend(remaining[: max_results - len(picked)])
        return picked

    return candidates[:max_results]


def merge_item(base_item: Dict, detail_item: Dict) -> Dict:
    merged = dict(base_item)
    for key in ("title", "uploader", "channel", "duration", "view_count", "upload_date", "webpage_url", "id"):
        value = detail_item.get(key)
        if value not in (None, "", []):
            merged[key] = value
    return merged


def main() -> int:
    max_results = int((os.getenv("MAX_RESULTS", "20") or "20").strip())
    sort_by = (os.getenv("RECOMMENDED_SORT_BY", "feed_order") or "feed_order").strip()
    selection_mode = (os.getenv("RECOMMENDED_SELECTION_MODE", "sorted") or "sorted").strip()
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
    candidates = collect_home_recommendations(home_json, max_results * 5)
    if not candidates:
        print("No direct entries found in home feed. Trying fallback extraction...")
        candidates = collect_fallback_recommendations(home_json, max_results * 5)
    if not candidates:
        debug = {
            "reason": "no_candidates",
            "top_level_keys": sorted(list(home_json.keys())) if isinstance(home_json, dict) else [],
            "entries_count": len(home_json.get("entries") or []) if isinstance(home_json, dict) else 0,
            "home_url": home_url,
        }
        with open("recommended_debug_summary.json", "w", encoding="utf-8") as f:
            json.dump(debug, f, ensure_ascii=False, indent=2)
        print("No recommended videos found in home feed after fallback extraction.")
        return 1

    details_by_id = enrich_video_metadata(candidates, cookies_exists)
    enriched: List[Tuple[str, Dict]] = []
    for url, item in candidates:
        vid = extract_video_id(url)
        detail_item = details_by_id.get(vid, {})
        merged = merge_item(item, detail_item)
        merged["id"] = vid
        merged["webpage_url"] = merged.get("webpage_url") or url
        enriched.append((url, merged))

    sorted_candidates = sort_candidates(enriched, sort_by)
    recommended = pick_candidates(sorted_candidates, max_results, selection_mode)
    if not recommended:
        print("No videos were selected after sorting/filtering.")
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
                "sort_by": sort_by,
                "selection_mode": selection_mode,
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "recommended": [
                    {
                        "url": url,
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "uploader": item.get("uploader") or item.get("channel"),
                        "duration": item.get("duration"),
                        "view_count": item.get("view_count"),
                        "upload_date": item.get("upload_date"),
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
        f.write(f"- Sort by: {sort_by}\n")
        f.write(f"- Selection mode: {selection_mode}\n")
        f.write(f"- Selected: {len(recommended)}\n\n")
        for idx, (url, item) in enumerate(recommended, start=1):
            title = item.get("title") or "N/A"
            uploader = item.get("uploader") or item.get("channel") or "N/A"
            upload_date = item.get("upload_date") or "N/A"
            view_count = item.get("view_count")
            views_text = f"{view_count:,}" if isinstance(view_count, int) else "N/A"
            f.write(f"{idx}. {title} | {uploader}\n")
            f.write(f"   - Upload date: {upload_date} | Views: {views_text}\n")
            f.write(f"   - {url}\n")

    env = os.environ.copy()
    env["VIDEO_INPUTS"] = "\n".join(url for url, _ in recommended)
    proc = subprocess.run(["python", "scripts/download_videos.py"], env=env)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
