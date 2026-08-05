# youtube-auto-upload (v1.0.0)

> Automated, stateless pipeline that uploads one YouTube Short every day using Google Drive, Google Sheets, and GitHub Actions.

---

## 📐 Architecture Overview

```
                          ┌────────────────────────┐
                          │   Google Drive         │
                          │   ("Videos" Folder)    │
                          └───────────┬────────────┘
                                      │
                                      ▼ 1. Discover lowest NNN file
                          ┌────────────────────────┐
                          │   UploadContext        │
                          │   (drive_file_id,      │
                          │    filename, NNN)      │
                          └───────────┬────────────┘
                                      │
                                      ▼ 2. Download MP4 to temp dir
                          ┌────────────────────────┐
                          │   Local Video File     │
                          └───────────┬────────────┘
                                      │
                                      ▼ 3. Fetch Title & Description by NNN
                          ┌────────────────────────┐
                          │   Google Sheets        │
                          │   (Metadata Lookup)    │
                          └───────────┬────────────┘
                                      │
                                      ▼ 4. Upload Short (Public, Category 24)
                          ┌────────────────────────┐
                          │   YouTube Data API v3  │
                          └───────────┬────────────┘
                                      │
                                      ▼ 5. Move file to "Uploaded" folder
                          ┌────────────────────────┐
                          │   Google Drive         │
                          │   ("Uploaded" Folder)  │
                          └────────────────────────┘
```

The pipeline is **fully stateless** and treats **Google Drive as the single source of truth**:
- **No local database or state file** is needed.
- Each run finds the video with the smallest numeric suffix (`funny_cartoon_001.mp4`).
- Once successfully uploaded to YouTube, the video is moved out of the `Videos` folder into `Uploaded`.

---

## 🛠️ Folder & Codebase Structure

```
youtube-auto-upload/
│
├── .github/
│   └── workflows/
│       └── daily_upload.yml   # Production GitHub Actions workflow (cron + dispatch)
│
├── src/
│   ├── __init__.py            # Package declaration (v1.0.0)
│   ├── config.py              # Environment configuration & startup validation
│   ├── drive.py               # Google Drive: list, download & atomic move
│   ├── sheets.py              # Google Sheets: cached metadata lookup & validation
│   ├── youtube.py             # YouTube API: 7-day duplicate check & resumable upload
│   ├── state.py               # UploadContext dataclass (threaded pipeline state)
│   ├── utils.py               # OAuth 2.0 auth flow & filename parsing
│   └── main.py                # Pipeline orchestrator with dry-run & test modes
│
├── credentials.json           # OAuth 2.0 Desktop credentials (git-ignored)
├── token.json                 # Saved OAuth access/refresh token (git-ignored)
├── .env.example               # Template for environment variables
├── requirements.txt           # Pinned production dependencies
├── .gitignore
└── README.md                  # Project documentation
```

---

## ⚙️ Environment Variables

| Environment Variable | Required | Description |
| --- | --- | --- |
| `GOOGLE_DRIVE_VIDEOS_FOLDER_ID` | ✅ | Folder ID for pending `.mp4` video files |
| `GOOGLE_DRIVE_UPLOADED_FOLDER_ID` | ✅ | Folder ID for completed uploads |
| `GOOGLE_SHEET_ID` | ✅ | Spreadsheet ID containing video metadata |
| `GOOGLE_SHEET_WORKSHEET` | ✅ | Worksheet tab name (e.g. `Sheet1` or `Videos`) |
| `YOUTUBE_CATEGORY_ID` | ❌ | YouTube Category ID (default: `24` — Entertainment) |
| `LOG_LEVEL` | ❌ | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## 🔑 Google Cloud & OAuth Setup

### Step 1: Enable Google APIs
In your [Google Cloud Console](https://console.cloud.google.com/), select your project and enable:
1. **Google Drive API**
2. **Google Sheets API**
3. **YouTube Data API v3**

### Step 2: Create OAuth 2.0 Desktop Credentials
1. Go to **APIs & Services → Credentials**.
2. Click **Create Credentials → OAuth client ID**.
3. Choose **Desktop app**.
4. Download the client secret JSON file and save it as `credentials.json` in the root directory.

### Step 3: Initial Authorization (`token.json`)
Run the pipeline locally to complete the one-time browser authentication flow:
```bash
python -m src.main --dry-run
```
This opens your browser to grant permissions. Once approved, `token.json` will be generated in the root directory.

---

## 📊 Google Sheets Setup

The tracking sheet must have a header row with the following column names:

| Video No | Title | Description |
| --- | --- | --- |
| 1 | Episode 1: The Adventure Begins | Welcome to the series! #shorts #cartoon |
| 2 | Episode 2: The Lost Key | Can they find the key? Watch now! #shorts |

- **`Video No`**: Integer matching the numeric suffix in the filename (`funny_cartoon_001.mp4` → `1`).
- **`Title`**: Non-empty video title for YouTube.
- **`Description`**: Non-empty video description for YouTube.

---

## 🔐 GitHub Secrets Configuration

Add these **Repository Secrets** under **Settings → Secrets and variables → Actions**:

| Secret Name | Content / Value |
| --- | --- |
| `CREDENTIALS_JSON_B64` | Base64-encoded `credentials.json` (`base64 -w 0 credentials.json`) |
| `TOKEN_JSON_B64` | Base64-encoded `token.json` (`base64 -w 0 token.json`) |
| `GOOGLE_DRIVE_VIDEOS_FOLDER_ID` | Drive ID for pending videos |
| `GOOGLE_DRIVE_UPLOADED_FOLDER_ID` | Drive ID for finished videos |
| `GOOGLE_SHEET_ID` | Google Spreadsheet ID |
| `GOOGLE_SHEET_WORKSHEET` | Sheet tab name (e.g. `Sheet1`) |

---

## 🚀 Execution Modes

### 1. Production Pipeline Execution
Runs all 6 stages (Discover → Context → Download → Metadata → Upload → Move → Cleanup):
```bash
python -m src.main
```

### 2. Dry-Run Mode (`--dry-run`)
Executes discovery, download, metadata lookup, and validation. **Skips YouTube upload and Drive file move**. Guarantees temporary file cleanup:
```bash
python -m src.main --dry-run
```

### 3. Read-Only Drive Test (`--drive-test`)
Tests OAuth credentials and lists pending files in the Drive `Videos` folder without downloading anything:
```bash
python -m src.main --drive-test
```

---

## 🤖 GitHub Actions Workflow

The workflow (`.github/workflows/daily_upload.yml`):
- Runs automatically on a daily schedule (**10:00 UTC**).
- Supports manual triggering via `workflow_dispatch` with a `dry_run` checkbox option.
- Restores `credentials.json` and `token.json` at runtime and **deletes them in an `always()` cleanup step**.
- Features pip dependency caching and a 30-minute execution timeout.

---

## 🛠️ Batch Rename Utility

Use the standalone helper script `scripts/rename_videos.py` to prepare local video files before uploading them to Google Drive.

It renames all `.mp4` files in a target folder sequentially into the `funny_cartoon_001.mp4` naming convention using a **safe two-pass algorithm** that prevents filename collisions.

### Usage

```bash
# Rename videos in a local directory
python scripts/rename_videos.py "E:\Funny Cartoons"

# Dry-run mode (preview proposed renames without modifying disk)
python scripts/rename_videos.py "E:\Funny Cartoons" --dry-run
```

### Features

- **Natural Sorting**: Sorts files numerically (e.g. `video_1.mp4`, `video_2.mp4`, `video_10.mp4`).
- **Two-Pass Collision Protection**: Renames files to temporary unique identifiers before applying final filenames so no files are ever overwritten.
- **Selective Filtering**: Processes `.mp4` files only and skips non-video files (`.txt`, `.jpg`, etc.).
- **Cross-Platform**: Operates identically on Windows, macOS, and Linux.

---

## ❓ Troubleshooting & FAQ

### Q: Why does the pipeline raise `DuplicateUploadError`?
A: To prevent duplicate uploads during workflow retries, the pipeline checks your YouTube channel before uploading. If a video with the exact same title was uploaded in the last 7 days, it aborts safely.

### Q: What happens if YouTube API quota is exceeded?
A: `videos.insert` consumes ~1,600 API quota units out of the default 10,000 daily quota. If quota is exhausted, YouTube returns HTTP `403`, which fails fast without retrying until the daily quota resets.

### Q: Are temporary files cleaned up if an error occurs?
A: Yes. `stage_download` creates temporary video files inside a dedicated directory. `main.py` uses a `finally` block to guarantee local temp files are deleted even on failure.

---

## 📄 License

MIT License
