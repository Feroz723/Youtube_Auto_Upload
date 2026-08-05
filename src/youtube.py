"""YouTube Data API v3 integration.

Responsibilities:
    - Search for duplicate video uploads within the last 7 days.
    - Upload video files as YouTube Shorts with resumable uploads.
    - Handle exponential backoff for transient upload failures.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

from src.config import YOUTUBE_CATEGORY_ID, YOUTUBE_PRIVACY_STATUS
from src.state import UploadContext

logger = logging.getLogger(__name__)


class DuplicateUploadError(Exception):
    """Raised when a video with the exact same title was uploaded in the last 7 days."""


def upload_short(creds: Credentials, context: UploadContext) -> dict[str, str]:
    """Upload a video to YouTube as a Short.

    Args:
        creds: Valid Google OAuth 2.0 credentials.
        context: The current UploadContext containing title, description, and file path.

    Returns:
        A dictionary containing ``"video_id"`` and ``"url"`` keys.

    Raises:
        ValueError: If title, description, or local_file_path is missing.
        FileNotFoundError: If the local file does not exist.
        DuplicateUploadError: If the video was already uploaded within the last 7 days.
        RuntimeError: If the upload fails after 3 attempts or encounters a non-retryable error.
    """
    if not context.title:
        raise ValueError("Cannot upload to YouTube: context.title is empty.")
    if not context.description:
        raise ValueError("Cannot upload to YouTube: context.description is empty.")
    if not context.local_file_path:
        raise ValueError("Cannot upload to YouTube: context.local_file_path is missing.")
    if not context.local_file_path.exists():
        raise FileNotFoundError(f"Local video file not found: {context.local_file_path}")

    service = build("youtube", "v3", credentials=creds)

    # ── 1. Check for duplicate upload (Idempotency) ──────────────────────
    _check_duplicate_upload(service, context.title)

    # ── 2. Prepare upload payload ────────────────────────────────────────
    body = {
        "snippet": {
            "title": context.title,
            "description": context.description,
            "categoryId": YOUTUBE_CATEGORY_ID,
        },
        "status": {
            "privacyStatus": YOUTUBE_PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False,
        },
    }

    # ── 3. Upload video with retries ──────────────────────────────────────
    logger.info("Uploading %s to YouTube...", context.filename)
    video_id = _execute_resumable_upload(service, body, context.local_file_path, context.filename)
    watch_url = f"https://youtu.be/{video_id}"

    logger.info("Upload complete.")
    logger.info("Video ID: %s", video_id)
    logger.info("Watch URL: %s", watch_url)

    return {
        "video_id": video_id,
        "url": watch_url,
    }


def _check_duplicate_upload(service: Any, title: str) -> None:
    """Search channel for videos uploaded within the last 7 days with matching title.

    Raises:
        DuplicateUploadError: If an exact title match is found within 7 days.
    """
    logger.debug("Checking for recent duplicate uploads matching title '%s'...", title)
    try:
        response = (
            service.search()
            .list(
                forMine=True,
                type="video",
                part="snippet",
                order="date",
                maxResults=50,
            )
            .execute()
        )
    except HttpError as exc:
        logger.warning("Could not search YouTube channel for duplicate videos: %s", exc)
        return

    items = response.get("items", [])
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)

    for item in items:
        snippet = item.get("snippet", {})
        video_title = snippet.get("title", "")
        published_at_str = snippet.get("publishedAt", "")

        if video_title == title and published_at_str:
            try:
                pub_dt = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                if pub_dt >= cutoff:
                    existing_id = item.get("id", {}).get("videoId", "unknown")
                    raise DuplicateUploadError(
                        f"Duplicate upload detected: video '{title}' was already "
                        f"uploaded to YouTube within the last 7 days (Video ID: {existing_id})."
                    )
            except ValueError:
                continue


def _execute_resumable_upload(
    service: Any,
    body: dict[str, Any],
    local_file_path: Path,
    filename: str,
) -> str:
    """Perform a resumable YouTube video upload with retry logic for transient errors.

    Retries up to 3 times using exponential backoff.
    HTTP 400, 401, and 403 errors are treated as permanent failures and fail fast.
    """
    max_attempts = 3
    attempt = 0

    while attempt < max_attempts:
        attempt += 1
        if attempt > 1:
            logger.info("Retry attempt %d/%d for %s...", attempt, max_attempts, filename)

        try:
            media = MediaFileUpload(
                str(local_file_path),
                mimetype="video/mp4",
                chunksize=1024 * 1024,
                resumable=True,
            )
            request = service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress_pct = int(status.progress() * 100)
                    logger.info("Progress: %d%%", progress_pct)

            video_id = response.get("id")
            if not video_id:
                raise RuntimeError("YouTube API did not return a valid video ID.")
            return str(video_id)

        except HttpError as exc:
            status_code = exc.resp.status if hasattr(exc, "resp") and exc.resp else 0

            # Permanent client/auth/permission errors must NOT be retried
            if status_code in (400, 401, 403):
                logger.error("Non-retryable YouTube API error (HTTP %d): %s", status_code, exc)
                raise RuntimeError(
                    f"YouTube upload failed with non-retryable HTTP {status_code}: {exc}"
                ) from exc

            if attempt < max_attempts:
                backoff_sec = 2 ** (attempt - 1)
                logger.warning(
                    "YouTube upload attempt %d failed with HTTP %d (%s). Retrying in %ds...",
                    attempt, status_code, exc, backoff_sec
                )
                time.sleep(backoff_sec)
            else:
                raise RuntimeError(
                    f"YouTube upload failed after {max_attempts} attempts: {exc}"
                ) from exc
        except (DuplicateUploadError, ValueError, FileNotFoundError):
            raise
        except Exception as exc:
            if attempt < max_attempts:
                backoff_sec = 2 ** (attempt - 1)
                logger.warning(
                    "YouTube upload attempt %d failed (%s). Retrying in %ds...",
                    attempt, exc, backoff_sec
                )
                time.sleep(backoff_sec)
            else:
                raise RuntimeError(
                    f"YouTube upload failed after {max_attempts} attempts: {exc}"
                ) from exc

    raise RuntimeError(f"YouTube upload failed after {max_attempts} attempts.")
