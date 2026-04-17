# YouTube Workflow Hub

Automate YouTube download and YouTube search with GitHub Actions.

## Features

1. Download workflow from YouTube URLs or video IDs
2. Select target quality (default: `480p`) and auto-pick the closest available stream
3. Optional subtitle embedding (default: `true`)
4. Optional chapter embedding (default: `true`)
5. Upload downloaded files to GitHub Releases
6. Separate search workflow that publishes rich result details in a Release
7. Home recommendations workflow (personalized using your YouTube cookies)
8. Local command/script to download latest videos from a channel

## Workflow: Download Videos

File: `.github/workflows/download-youtube.yml`

### Inputs

1. `video_inputs` (required): one or more YouTube URLs or video IDs (comma, space, or newline separated)
2. `quality` (optional): max output quality (default: `480`)
3. `embed_subtitles` (optional): embed subtitles into video (default: `true`)
4. `embed_chapters` (optional): embed chapters into video (default: `true`)
5. `subtitle_langs` (optional): subtitle language filter for `yt-dlp --sub-langs` (default: `fa.*,en.*,fa,en`)
6. `release_name` (optional): custom release title

## Workflow: Search Videos

File: `.github/workflows/search-youtube.yml`

### Inputs

1. `query` (required): search keyword(s)
2. `max_results` (optional): number of results (default: `10`)
3. `sort_by` (optional): how to sort results in release notes
4. `release_name` (optional): custom release title

### Search Output in Release Notes

1. Video title
2. Channel name and channel ID
3. Duration
4. View count
5. Like count (if provided by YouTube/yt-dlp)
6. Upload date
7. Live status
8. Direct video URL
9. Summary stats (total and average views)

## Workflow: Download Home Recommended Videos (20)

File: `.github/workflows/download-youtube-suggested.yml`

### Inputs

1. `max_results` (optional): number of recommended videos (default: `20`)
2. `quality` (optional): target quality (default: `480`)
3. `embed_subtitles` (optional): embed subtitles into videos (default: `true`)
4. `embed_chapters` (optional): embed chapters into videos (default: `true`)
5. `subtitle_langs` (optional): subtitle language filter (default: `fa.*,en.*,fa,en`)
6. `release_name` (optional): custom release title

### Important

1. This workflow reads your personalized recommendations from `https://www.youtube.com/feed/recommended`.
2. `YT_COOKIES` secret is required. Without cookies, personalized home feed cannot be fetched.

## Local Command: Download Latest Channel Videos

Script: `scripts/download_channel_latest.py`

Example:

```bash
cd /path/to/youtube-workflow-hub
CHANNEL_INPUT="https://www.youtube.com/@MrBeast" \
CHANNEL_COUNT="5" \
QUALITY="480" \
EMBED_SUBTITLES="true" \
EMBED_CHAPTERS="true" \
SUBTITLE_LANGS="fa.*,en.*,fa,en" \
python scripts/download_channel_latest.py
```

You can also use a handle directly:

```bash
CHANNEL_INPUT="@MrBeast" CHANNEL_COUNT="3" python scripts/download_channel_latest.py
```

`CHANNEL_INPUT` supports channel URLs and `@handle`. The script resolves `/videos` automatically.

## Quick Start

1. Push this project to your GitHub repository.
2. Open the `Actions` tab.
3. Run a workflow using `Run workflow`.
4. Check output files and notes in the `Releases` section.

## Technical Notes

1. All download/search flows use `yt-dlp`.
2. `ffmpeg` is used for subtitle/chapter embedding.
3. `node` is installed and passed as JS runtime for more reliable YouTube extraction.
4. Download logic is handled in `scripts/download_videos.py` for cleaner retries and error handling.
5. The downloader picks the closest quality (`--format-sort res:<quality>`) instead of forcing one strict format ID.
6. For `HTTP 429`, the downloader sleeps and retries with backoff (`15s`, `30s`, `45s`, `60s` by default).
7. If subtitle requests keep getting 429 after retries, it retries the same video without subtitles so the whole workflow does not fail.
8. Home recommendation selection is handled in `scripts/download_suggested_videos.py`.
9. Latest channel selection is handled in `scripts/download_channel_latest.py`.

## Bot Check / "Sign in to confirm you’re not a bot"

On GitHub-hosted runners, YouTube may block anonymous requests for some videos/queries.  
If that happens, provide YouTube cookies through a repository secret:

1. Go to `Repository Settings > Secrets and variables > Actions`.
2. Create a new secret named `YT_COOKIES`.
3. Paste your full `cookies.txt` content (Netscape format) as the secret value.
4. Re-run the workflow.

## How to Obtain `cookies.txt` (Recommended)

1. Sign in to YouTube in your browser.
2. Install a trusted cookies export extension that can export in Netscape format (for example: `Get cookies.txt LOCALLY`).
3. Open `youtube.com`.
4. Export cookies for YouTube domains (`youtube.com`, `.youtube.com`, and often `.google.com`).
5. Save/export as `cookies.txt`.
6. Open the file, copy all content, and put it into the `YT_COOKIES` GitHub secret.

## Security Best Practices for Cookies

1. Treat `cookies.txt` like a password.
2. Never commit cookies to git.
3. Store cookies only in GitHub Secrets (`YT_COOKIES`).
4. Rotate/re-export cookies if they stop working or if you suspect leakage.
5. Use a dedicated Google account for automation if possible.
