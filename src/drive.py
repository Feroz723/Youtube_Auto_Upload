"""Google Drive integration.

Responsibilities:
    - List MP4 video files in the configured "Videos" folder.
    - Download a video file by its Drive file ID.
    - Move uploaded videos from "Videos" to "Uploaded" folder.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials

from src.config import get_drive_videos_folder_id, get_drive_uploaded_folder_id
from src.utils import extract_video_number

logger = logging.getLogger(__name__)


# ── Types ────────────────────────────────────────────────────────────────────
VideoFile = dict[str, str]  # {"id": "...", "name": "funny_cartoon_001.mp4"}


# ── Public API ───────────────────────────────────────────────────────────────

def list_video_files(creds: Credentials) -> list[VideoFile]:
    """List MP4 video files in the Drive "Videos" folder.

    Files are returned **sorted by video number** (ascending), not
    alphabetically.  Only files matching the ``funny_cartoon_NNN.mp4``
    naming convention are included.

    Args:
        creds: Valid Google OAuth 2.0 credentials.

    Returns:
        A list of dicts, each containing ``id`` and ``name`` keys.

    Raises:
        RuntimeError: If the API call fails or the folder is inaccessible.
    """
    folder_id = get_drive_videos_folder_id()
    service = build("drive", "v3", credentials=creds)

    try:
        results: list[VideoFile] = []
        page_token: str | None = None

        while True:
            response: dict[str, Any] = (
                service.files()
                .list(
                    q=(
                        f"'{folder_id}' in parents "
                        "and mimeType='video/mp4' "
                        "and trashed=false"
                    ),
                    fields="nextPageToken, files(id, name)",
                    pageSize=1000,
                    pageToken=page_token,
                )
                .execute()
            )

            files = response.get("files", [])
            results.extend(
                {"id": f["id"], "name": f["name"]}
                for f in files
            )

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    except HttpError as exc:
        raise RuntimeError(
            f"Failed to list files in Drive folder '{folder_id}': {exc}"
        ) from exc

    # Filter to valid filenames and sort by video number
    valid_files = _filter_and_sort(results)

    logger.info("Found %d video(s) in Drive.", len(valid_files))
    return valid_files


def download_video(creds: Credentials, file_id: str,
                   destination: Path) -> Path:
    """Download a video file from Google Drive.

    Args:
        creds:       Valid Google OAuth 2.0 credentials.
        file_id:     The Drive file ID of the video to download.
        destination: Local path where the file should be saved.

    Returns:
        The *destination* path (for convenience in chaining).

    Raises:
        RuntimeError: If the download fails.
    """
    service = build("drive", "v3", credentials=creds)

    try:
        request = service.files().get_media(fileId=file_id)

        destination.parent.mkdir(parents=True, exist_ok=True)

        with io.FileIO(str(destination), "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    logger.debug(
                        "Download progress: %d%%",
                        int(status.progress() * 100),
                    )

    except HttpError as exc:
        raise RuntimeError(
            f"Failed to download file '{file_id}': {exc}"
        ) from exc

    size_bytes = destination.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    logger.info("Downloaded %s (%.2f MB / %d bytes).", destination.name, size_mb, size_bytes)
    return destination


def move_to_uploaded(creds: Credentials, file_id: str) -> None:
    """Move a video file from "Videos" to "Uploaded" folder on Drive.

    This is an atomic metadata update (no re-upload) — the file's parent is
    changed from the Videos folder to the Uploaded folder.

    Args:
        creds:   Valid Google OAuth 2.0 credentials.
        file_id: The Drive file ID of the video to move.

    Raises:
        RuntimeError: If the move operation fails.
    """
    videos_folder = get_drive_videos_folder_id()
    uploaded_folder = get_drive_uploaded_folder_id()
    service = build("drive", "v3", credentials=creds)

    try:
        service.files().update(
            fileId=file_id,
            addParents=uploaded_folder,
            removeParents=videos_folder,
            fields="id, parents",
        ).execute()
    except HttpError as exc:
        raise RuntimeError(
            f"Failed to move file '{file_id}' to Uploaded folder: {exc}"
        ) from exc

    logger.info("Moved file '%s' to Uploaded folder.", file_id)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _filter_and_sort(files: list[VideoFile]) -> list[VideoFile]:
    """Keep only validly-named files and sort by video number."""
    valid: list[tuple[int, VideoFile]] = []
    for f in files:
        try:
            num = extract_video_number(f["name"])
            valid.append((num, f))
        except ValueError:
            logger.warning(
                "Skipping file with unexpected name: '%s'", f["name"]
            )
    valid.sort(key=lambda pair: pair[0])
    return [f for _, f in valid]
