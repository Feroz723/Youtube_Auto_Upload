"""Entry point for the daily YouTube Short upload pipeline.

The pipeline is **stateless** — Google Drive is the single source of truth.
Every file still in the "Videos" folder is pending upload.  The runner picks
the file with the smallest numeric suffix, uploads it, then moves it to the
"Uploaded" sub-folder so it is never processed again.

The upload flow is split into six sequential stages, each receiving and
returning an :class:`~src.state.UploadContext`.  If any stage fails the
pipeline stops immediately and logs which stage failed.

Usage::

    python -m src.main               # normal upload pipeline
    python -m src.main --dry-run     # dry-run mode (discover, download, metadata, validate, clean up)
    python -m src.main --drive-test  # read-only Drive validation
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from google.oauth2.credentials import Credentials

from src.config import get_drive_videos_folder_id, setup_logging, validate_config
from src.drive import download_video, list_video_files, move_to_uploaded
from src.sheets import get_video_metadata
from src.state import UploadContext
from src.utils import extract_video_number, get_credentials
from src.youtube import upload_short

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
_SEPARATOR = "-----------------------------------"
_DRIVE_TEST_PREVIEW_LIMIT = 10

# Stage function signature: (creds, ctx) -> ctx
StageFunc = Callable[[Credentials, UploadContext], UploadContext]


# ── Pipeline stages ─────────────────────────────────────────────────────────

def stage_discover(creds: Credentials,
                   ctx: UploadContext) -> UploadContext:
    """Stage 1 — Discover the next video from Google Drive.

    Populates ``drive_file_id``, ``filename``, and ``video_number``.
    """
    pending = list_video_files(creds)

    if not pending:
        raise RuntimeError(
            "No video files found in the Drive 'Videos' folder. "
            "Upload new files and retry."
        )

    next_file = pending[0]  # already sorted by video number

    ctx.drive_file_id = next_file["id"]
    ctx.filename = next_file["name"]
    ctx.video_number = extract_video_number(next_file["name"])

    logger.info("Next upload: %s (video #%d)", ctx.filename, ctx.video_number)
    logger.info("Drive File ID: %s", ctx.drive_file_id)
    return ctx


def stage_download(creds: Credentials,
                   ctx: UploadContext) -> UploadContext:
    """Stage 3 — Download the video file from Google Drive.

    Populates ``local_file_path``.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="yt_upload_"))
    destination = tmp_dir / ctx.filename

    download_video(creds, ctx.drive_file_id, destination)
    ctx.local_file_path = destination

    if destination.exists():
        size_mb = destination.stat().st_size / (1024 * 1024)
        logger.info("Local file path: %s (%.2f MB)", destination, size_mb)
    return ctx


def stage_metadata(creds: Credentials,
                   ctx: UploadContext) -> UploadContext:
    """Stage 4 — Read video metadata from Google Sheets.

    Populates ``title`` and ``description``.
    """
    metadata = get_video_metadata(creds, ctx.video_number)
    ctx.title = metadata["title"]
    ctx.description = metadata["description"]

    logger.info("Metadata loaded successfully.")
    logger.info("Title: %s", ctx.title)
    logger.info("Description length: %d characters", len(ctx.description))
    return ctx


def stage_upload(creds: Credentials,
                 ctx: UploadContext) -> UploadContext:
    """Stage 5 — Upload the video to YouTube as a Short.

    Requires ``local_file_path``, ``title``, and ``description`` to be set.
    Populates ``youtube_video_id`` and ``youtube_url``.
    """
    result = upload_short(creds, ctx)
    ctx.youtube_video_id = result["video_id"]
    ctx.youtube_url = result["url"]

    logger.info("Uploaded Video ID: %s", ctx.youtube_video_id)
    logger.info("Uploaded Watch URL: %s", ctx.youtube_url)
    return ctx


def stage_move(creds: Credentials,
               ctx: UploadContext) -> UploadContext:
    """Stage 6 — Move the source file to the "Uploaded" folder on Drive.

    This stage MUST only run after a successful YouTube upload.
    """
    move_to_uploaded(creds, ctx.drive_file_id)
    logger.info("Drive file %s moved to Uploaded folder.", ctx.drive_file_id)
    return ctx


# ── Pipeline runner ──────────────────────────────────────────────────────────

_FULL_STAGES: list[tuple[str, StageFunc]] = [
    ("Discover", stage_discover),
    ("Download", stage_download),
    ("Metadata", stage_metadata),
    ("Upload",   stage_upload),
    ("Move",     stage_move),
]

_DRY_RUN_STAGES: list[tuple[str, StageFunc]] = [
    ("Discover", stage_discover),
    ("Download", stage_download),
    ("Metadata", stage_metadata),
]


def _run_pipeline(dry_run: bool = False) -> None:
    """Run the staged upload pipeline with total duration tracking and strict cleanup."""
    workflow_t0 = time.monotonic()

    logger.info(_SEPARATOR)
    if dry_run:
        logger.info("YouTube Auto Upload (DRY RUN MODE)")
    else:
        logger.info("YouTube Auto Upload")
    logger.info(_SEPARATOR)

    # ── 1. Startup Configuration Validation ──────────────────────────────
    try:
        validate_config()
    except EnvironmentError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    # ── 2. Authenticate ──────────────────────────────────────────────────
    try:
        t0 = time.monotonic()
        creds = get_credentials()
        auth_ms = (time.monotonic() - t0) * 1000
        logger.info("Authentication successful (%.0f ms).", auth_ms)
    except (FileNotFoundError, EnvironmentError) as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.error("Authentication failed: %s", exc)
        sys.exit(1)

    # ── 3. Seed context ──────────────────────────────────────────────────
    ctx = UploadContext(drive_file_id="", filename="", video_number=0)
    stages = _DRY_RUN_STAGES if dry_run else _FULL_STAGES

    # ── 4. Execute stages sequentially with cleanup in finally ──────────
    try:
        for name, stage_fn in stages:
            logger.info("[Stage: %s] Starting.", name)
            t0 = time.monotonic()

            try:
                ctx = stage_fn(creds, ctx)
            except Exception as exc:
                elapsed_ms = (time.monotonic() - t0) * 1000
                logger.error(
                    "[Stage: %s] FAILED after %.0f ms — %s: %s",
                    name, elapsed_ms, type(exc).__name__, exc,
                )
                sys.exit(1)

            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.info("[Stage: %s] Completed in %.0f ms.", name, elapsed_ms)

    finally:
        # ── 5. Guaranteed temporary file cleanup ─────────────────────────
        if ctx.local_file_path:
            tmp_path = ctx.local_file_path
            tmp_dir = tmp_path.parent
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
                    logger.info("Cleaned up downloaded file: %s", tmp_path.name)
                if tmp_dir.exists() and tmp_dir.name.startswith("yt_upload_"):
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    logger.debug("Removed temporary directory: %s", tmp_dir)
            except Exception as cleanup_err:
                logger.warning("Failed to clean up temporary file %s: %s", tmp_path, cleanup_err)

    total_duration_sec = time.monotonic() - workflow_t0

    logger.info(_SEPARATOR)
    if dry_run:
        logger.info("Dry run completed successfully. All validations passed.")
    else:
        logger.info("Pipeline finished successfully.")
    logger.info("Total workflow duration: %.2f seconds", total_duration_sec)
    logger.info(_SEPARATOR)


# ── Drive test mode ──────────────────────────────────────────────────────────

def _run_drive_test() -> None:
    """Validate the Google Drive connection without modifying anything."""
    logger.info(_SEPARATOR)
    logger.info("Drive Test Mode (read-only)")
    logger.info(_SEPARATOR)

    try:
        validate_config(required_vars=["GOOGLE_DRIVE_VIDEOS_FOLDER_ID"])

        # ── Authenticate ─────────────────────────────────────────────
        t0 = time.monotonic()
        creds = get_credentials()
        auth_ms = (time.monotonic() - t0) * 1000
        logger.info("Authentication successful (%.0f ms).", auth_ms)

        # ── Resolve folder ID ────────────────────────────────────────
        folder_id = get_drive_videos_folder_id()
        logger.info("Connected to Google Drive.")
        logger.info("Videos folder ID: %s", folder_id)

        # ── List files ───────────────────────────────────────────────
        t0 = time.monotonic()
        videos = list_video_files(creds)
        list_ms = (time.monotonic() - t0) * 1000

    except FileNotFoundError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except EnvironmentError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except RuntimeError as exc:
        logger.error("Drive error: %s", exc)
        logger.error(
            "Check that the folder ID is correct and the OAuth account "
            "has access to it."
        )
        sys.exit(1)

    # ── Report results ───────────────────────────────────────────────
    total = len(videos)
    logger.info("Discovered %d file(s) in %.0f ms.", total, list_ms)

    if total == 0:
        logger.warning(
            "No matching MP4 files found. Make sure the folder contains "
            "files named funny_cartoon_NNN.mp4."
        )
        return

    logger.info("")
    logger.info("Found %d video(s).", total)
    logger.info("")

    shown = min(total, _DRIVE_TEST_PREVIEW_LIMIT)
    for i, video in enumerate(videos[:shown], start=1):
        logger.info("  %d. %s", i, video["name"])

    if total > shown:
        logger.info("  ... and %d more.", total - shown)

    logger.info("")
    logger.info("Drive test passed.")


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="youtube-auto-upload",
        description="Automatically upload one YouTube Short per day.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Validation mode: discover video, download, read metadata, and "
            "validate all pipeline steps without uploading to YouTube or moving files. "
            "Temporary files are cleaned up automatically."
        ),
    )
    parser.add_argument(
        "--drive-test",
        action="store_true",
        help=(
            "Read-only test mode: authenticate, list videos in the "
            "Drive 'Videos' folder, and print results. Nothing is "
            "downloaded, moved, or uploaded."
        ),
    )
    return parser.parse_args(argv)


# ── Entry point ──────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    """Parse arguments and dispatch to the appropriate mode."""
    setup_logging()
    args = _parse_args(argv)

    if args.drive_test:
        _run_drive_test()
    else:
        _run_pipeline(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())  # type: ignore[arg-type]
