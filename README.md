# YouTube Workflow Hub

Automate YouTube download and YouTube search with GitHub Actions.

## Features

1. Download workflow from YouTube URLs or video IDs
2. Select target quality (default: `480p`) and auto-pick the closest available stream
3. Optional subtitle embedding (default: `true`)
4. Optional chapter embedding (default: `true`)
5. Upload downloaded files to GitHub Releases
6. Separate search workflow that publishes rich result details in a Release

## Workflow: Download Videos

File: `.github/workflows/download-youtube.yml`

### Inputs

1. `video_inputs` (required): one or more YouTube URLs or video IDs (comma, space, or newline separated)
2. `quality` (optional): max output quality (default: `480`)
3. `embed_subtitles` (optional): embed subtitles into video (default: `true`)
4. `embed_chapters` (optional): embed chapters into video (default: `true`)
5. `release_name` (optional): custom release title

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

## Quick Start

1. Push this project to your GitHub repository.
2. Open the `Actions` tab.
3. Run either workflow using `Run workflow`.
4. Check output files and notes in the `Releases` section.

## Technical Notes

1. Both workflows use `yt-dlp`.
2. `ffmpeg` is used for subtitle/chapter embedding.
3. `node` is installed and passed as JS runtime for more reliable YouTube extraction.
4. The download workflow prints available formats first, then selects the closest quality instead of forcing a single strict format.

## Bot Check / "Sign in to confirm you’re not a bot"

On GitHub-hosted runners, YouTube may block anonymous requests for some videos/queries.  
If that happens, provide YouTube cookies through a repository secret:

1. Go to `Repository Settings > Secrets and variables > Actions`.
2. Create a new secret named `YT_COOKIES`.
3. Paste your full `cookies.txt` content (Netscape format) as the secret value.
4. Re-run the workflow.

## How to Obtain `cookies.txt` (Recommended)

1. Sign in to YouTube in your browser.
2. Install a trusted cookies export extension that can export in Netscape format. [EditThisCookie (V3)
](https://chromewebstore.google.com/detail/editthiscookie-v3/ojfebgpkimhlhcblbalbfjblapadhbol)
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
