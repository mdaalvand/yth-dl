#!/usr/bin/env python3
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List


@dataclass
class RunResult:
    ok: bool
    output: str
    saw_429: bool
    subtitle_429: bool


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def parse_video_inputs(raw: str) -> List[str]:
    parts = [p.strip() for p in re.split(r"[\s,]+", raw or "") if p.strip()]
    urls = []
    for item in parts:
        if item.startswith("http://") or item.startswith("https://"):
            urls.append(item)
        else:
            urls.append(f"https://www.youtube.com/watch?v={item}")
    return urls


def run_command(args: List[str]) -> RunResult:
    print(f"\n$ {' '.join(shlex.quote(x) for x in args)}")
    proc = subprocess.run(args, capture_output=True, text=True)
    output = f"{proc.stdout}\n{proc.stderr}".strip()
    if output:
        print(output)

    saw_429 = ("HTTP Error 429" in output) or ("Too Many Requests" in output)
    subtitle_429 = saw_429 and (
        "Unable to download video subtitles" in output or "Downloading subtitles" in output
    )
    return RunResult(ok=proc.returncode == 0, output=output, saw_429=saw_429, subtitle_429=subtitle_429)


def run_with_429_retry(args: List[str], max_attempts: int, base_sleep: int) -> RunResult:
    last = RunResult(ok=False, output="", saw_429=False, subtitle_429=False)
    for attempt in range(1, max_attempts + 1):
        print(f"\nAttempt {attempt}/{max_attempts}")
        result = run_command(args)
        if result.ok:
            return result

        last = result
        if not result.saw_429:
            return result

        if attempt < max_attempts:
            sleep_seconds = min(base_sleep * attempt, 180)
            print(f"429 detected. Sleeping {sleep_seconds}s before retry...")
            time.sleep(sleep_seconds)

    return last


def main() -> int:
    video_inputs = os.getenv("VIDEO_INPUTS", "")
    quality = os.getenv("QUALITY", "480").strip()
    embed_subtitles = env_bool("EMBED_SUBTITLES", True)
    embed_chapters = env_bool("EMBED_CHAPTERS", True)
    subtitle_langs = os.getenv("SUBTITLE_LANGS", "fa.*,en.*,fa,en").strip()
    max_429_retries = int(os.getenv("MAX_429_RETRIES", "4").strip() or "4")
    retry_base_sleep = int(os.getenv("RETRY_BASE_SLEEP_SECONDS", "15").strip() or "15")

    urls = parse_video_inputs(video_inputs)
    if not urls:
        print("No valid video input found.")
        return 1

    os.makedirs("downloads", exist_ok=True)
    cookies_exists = os.path.isfile("cookies.txt")

    common_args = [
        "yt-dlp",
        "--no-playlist",
        "--restrict-filenames",
        "--merge-output-format",
        "mp4",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
        "--extractor-args",
        "youtube:player_client=web,tv",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "--retry-sleep",
        "2",
        "--sleep-requests",
        "1",
        "--sleep-interval",
        "1",
        "--max-sleep-interval",
        "5",
        "--concurrent-fragments",
        "1",
        "--format",
        "bv*+ba/b",
        "--format-sort",
        f"res:{quality}",
        "--paths",
        "downloads",
        "--output",
        "%(title).180B-%(id)s.%(ext)s",
    ]

    if cookies_exists:
        common_args += ["--cookies", "cookies.txt"]

    chapter_args: List[str] = []
    if embed_chapters:
        chapter_args = ["--add-metadata", "--embed-chapters"]

    subtitle_args: List[str] = []
    if embed_subtitles:
        subtitle_args = ["--write-subs", "--write-auto-subs", "--sub-langs", subtitle_langs, "--embed-subs"]

    for idx, url in enumerate(urls, start=1):
        print(f"\n=== ({idx}/{len(urls)}) Downloading: {url}")

        full_cmd = common_args + chapter_args + subtitle_args + [url]
        result = run_with_429_retry(full_cmd, max_429_retries, retry_base_sleep)

        if result.ok:
            continue

        # If subtitle downloads are rate-limited, keep the video workflow successful
        # by falling back to no-subtitles after controlled retries.
        if embed_subtitles and result.subtitle_429:
            print("\nSubtitle download kept hitting 429. Retrying without subtitles...")
            no_sub_cmd = common_args + chapter_args + [url]
            no_sub_result = run_with_429_retry(no_sub_cmd, max_429_retries, retry_base_sleep)
            if no_sub_result.ok:
                print("Downloaded successfully without subtitles due to subtitle 429 limits.")
                continue
            result = no_sub_result

        print("\nDownload failed.")
        return 1

    print("\nAll downloads finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

