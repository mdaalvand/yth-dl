#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone


def sec_to_hms(seconds):
    if not isinstance(seconds, int) or seconds < 0:
        return "N/A"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def fmt_num(value):
    if value is None:
        return "N/A"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "N/A"


def sort_entries(entries, sort_by):
    if sort_by == "view_count":
        return sorted(entries, key=lambda e: (e.get("view_count") or 0), reverse=True)
    if sort_by == "upload_date":
        return sorted(entries, key=lambda e: (e.get("upload_date") or ""), reverse=True)
    if sort_by == "duration":
        return sorted(entries, key=lambda e: (e.get("duration") or 0), reverse=True)
    return entries


def main():
    query = os.environ.get("QUERY", "").strip()
    max_results = os.environ.get("MAX_RESULTS", "").strip()
    sort_by = os.environ.get("SORT_BY", "relevance").strip()

    with open("search_raw.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("entries", [])
    entries = sort_entries(entries, sort_by)

    with open("search_results.json", "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    total_views = sum((e.get("view_count") or 0) for e in entries)
    avg_views = int(total_views / len(entries)) if entries else 0

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# YouTube Search Results",
        "",
        f"- Query: `{query}`",
        f"- Requested count: `{max_results}`",
        f"- Returned count: `{len(entries)}`",
        f"- Sort: `{sort_by}`",
        f"- Generated at: `{now}`",
        "",
        "## Summary",
        f"- Total views (sum): `{fmt_num(total_views)}`",
        f"- Average views: `{fmt_num(avg_views)}`",
        "",
        "## Results",
    ]

    if not entries:
        lines.append("- No result found.")
    else:
        for i, e in enumerate(entries, 1):
            title = e.get("title") or "N/A"
            uploader = e.get("uploader") or e.get("channel") or "N/A"
            channel_id = e.get("channel_id") or "N/A"
            duration = sec_to_hms(e.get("duration"))
            view_count = fmt_num(e.get("view_count"))
            like_count = fmt_num(e.get("like_count"))
            upload_date = e.get("upload_date") or "N/A"
            live_status = e.get("live_status") or "N/A"
            webpage_url = e.get("webpage_url") or "N/A"

            lines.extend(
                [
                    f"### {i}. {title}",
                    f"- Channel: `{uploader}`",
                    f"- Channel ID: `{channel_id}`",
                    f"- Duration: `{duration}`",
                    f"- Views: `{view_count}`",
                    f"- Likes: `{like_count}`",
                    f"- Upload date: `{upload_date}`",
                    f"- Live status: `{live_status}`",
                    f"- URL: {webpage_url}",
                    "",
                ]
            )

    with open("release_notes.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines).strip() + "\n")


if __name__ == "__main__":
    main()

