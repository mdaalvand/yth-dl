#!/usr/bin/env python3
import os
import re
import shlex
import subprocess
import sys
import time
import json
from dataclasses import dataclass
from typing import List, Dict


@dataclass
class RunResult:
    ok: bool
    output: str
    saw_429: bool
    subtitle_429: bool
    timed_out: bool


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


def run_command(args: List[str], command_timeout_seconds: int) -> RunResult:
    print(f"\n$ {' '.join(shlex.quote(x) for x in args)}")
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=command_timeout_seconds)
        output = f"{proc.stdout}\n{proc.stderr}".strip()
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        output = f"{stdout}\n{stderr}\nERROR: command timed out after {command_timeout_seconds}s".strip()
        timed_out = True

    if output:
        print(output)

    saw_429 = ("HTTP Error 429" in output) or ("Too Many Requests" in output)
    subtitle_429 = saw_429 and (
        "Unable to download video subtitles" in output or "Downloading subtitles" in output
    )
    return RunResult(
        ok=(not timed_out) and proc.returncode == 0 if not timed_out else False,
        output=output,
        saw_429=saw_429,
        subtitle_429=subtitle_429,
        timed_out=timed_out,
    )


def run_with_429_retry(
    args: List[str], max_attempts: int, base_sleep: int, command_timeout_seconds: int
) -> RunResult:
    last = RunResult(ok=False, output="", saw_429=False, subtitle_429=False, timed_out=False)
    for attempt in range(1, max_attempts + 1):
        print(f"\nAttempt {attempt}/{max_attempts}")
        result = run_command(args, command_timeout_seconds)
        if result.ok:
            return result

        last = result
        if not result.saw_429 and not result.timed_out:
            return result

        if attempt < max_attempts:
            sleep_seconds = min(base_sleep * attempt, 180)
            if result.timed_out:
                print(f"Timeout detected. Sleeping {sleep_seconds}s before retry...")
            else:
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
    command_timeout_seconds = int(os.getenv("PER_VIDEO_TIMEOUT_SECONDS", "900").strip() or "900")
    continue_on_error = env_bool("CONTINUE_ON_ERROR", True)

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

    failures: List[Dict[str, str]] = []
    success_count = 0

    for idx, url in enumerate(urls, start=1):
        print(f"\n=== ({idx}/{len(urls)}) Downloading: {url}")

        full_cmd = common_args + chapter_args + subtitle_args + [url]
        result = run_with_429_retry(full_cmd, max_429_retries, retry_base_sleep, command_timeout_seconds)

        if result.ok:
            success_count += 1
            continue

        # If subtitle downloads are rate-limited, keep the video workflow successful
        # by falling back to no-subtitles after controlled retries.
        if embed_subtitles and result.subtitle_429:
            print("\nSubtitle download kept hitting 429. Retrying without subtitles...")
            no_sub_cmd = common_args + chapter_args + [url]
            no_sub_result = run_with_429_retry(
                no_sub_cmd, max_429_retries, retry_base_sleep, command_timeout_seconds
            )
            if no_sub_result.ok:
                print("Downloaded successfully without subtitles due to subtitle 429 limits.")
                success_count += 1
                continue
            result = no_sub_result

        print("\nDownload failed.")
        short_reason = "unknown_error"
        for line in reversed((result.output or "").splitlines()):
            line = line.strip()
            if line.startswith("ERROR:"):
                short_reason = line
                break
        failures.append({"url": url, "reason": short_reason})
        if not continue_on_error:
            return 1
        print("Skipping failed video and continuing with next item...")

    with open("downloads_failed.json", "w", encoding="utf-8") as f:
        json.dump({"failed_count": len(failures), "failed": failures}, f, ensure_ascii=False, indent=2)

    with open("downloads_failed.txt", "w", encoding="utf-8") as f:
        for item in failures:
            f.write(f"{item['url']} | {item['reason']}\n")

    print("\nDownload run finished.")
    print(f"Successful videos: {success_count}")
    print(f"Failed videos: {len(failures)}")
    if success_count == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
