"""Centralised configuration loaded from environment variables.

A ``.env`` file in the project root is loaded automatically via
*python-dotenv* so the same code works both locally and inside
GitHub Actions (where secrets are injected as env vars).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ── Load .env ────────────────────────────────────────────────────────────────
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


# ── Helper ───────────────────────────────────────────────────────────────────
def _require(name: str) -> str:
    """Return an environment variable or raise with a clear message."""
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set. "
            f"See .env.example for reference."
        )
    return value


# ── Google Drive ─────────────────────────────────────────────────────────────
def get_drive_videos_folder_id() -> str:
    """Return the Drive folder ID for pending videos ("Videos" folder)."""
    return _require("GOOGLE_DRIVE_VIDEOS_FOLDER_ID")


def get_drive_uploaded_folder_id() -> str:
    """Return the Drive folder ID for completed uploads ("Uploaded" folder)."""
    return _require("GOOGLE_DRIVE_UPLOADED_FOLDER_ID")


# ── Google Sheets ────────────────────────────────────────────────────────────
def get_google_sheet_id() -> str:
    """Return the Google Sheet ID."""
    return _require("GOOGLE_SHEET_ID")


def get_google_sheet_worksheet() -> str:
    """Return the Google Sheet worksheet name."""
    return _require("GOOGLE_SHEET_WORKSHEET")


def get_sheets_spreadsheet_id() -> str:
    """Alias for get_google_sheet_id for backward compatibility."""
    return get_google_sheet_id()


# ── YouTube ──────────────────────────────────────────────────────────────────
YOUTUBE_CATEGORY_ID: str = os.getenv("YOUTUBE_CATEGORY_ID", "24")
YOUTUBE_PRIVACY_STATUS: str = os.getenv("YOUTUBE_PRIVACY_STATUS", "public").lower()

# ── Application ──────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()


# ── Startup Configuration Validation ─────────────────────────────────────────
def validate_config(required_vars: list[str] | None = None) -> dict[str, str]:
    """Validate required environment variables on startup.

    Args:
        required_vars: Optional list of variable names to check. Defaults to all required variables.

    Returns:
        A dictionary of validated configuration parameters.

    Raises:
        EnvironmentError: If one or more required variables are missing.
    """
    if required_vars is None:
        required_vars = [
            "GOOGLE_DRIVE_VIDEOS_FOLDER_ID",
            "GOOGLE_DRIVE_UPLOADED_FOLDER_ID",
            "GOOGLE_SHEET_ID",
            "GOOGLE_SHEET_WORKSHEET",
        ]

    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        msg = (
            f"Configuration validation failed. The following required environment "
            f"variables are missing:\n" + "\n".join(f"  - {v}" for v in missing) +
            "\nPlease check your .env file or GitHub Secrets configuration."
        )
        logger.error(msg)
        raise EnvironmentError(msg)

    config_summary = {var: os.getenv(var, "") for var in required_vars}
    logger.debug("Configuration validated successfully.")
    return config_summary


# ── Logging setup ────────────────────────────────────────────────────────────
def setup_logging() -> None:
    """Configure the root logger with a uniform format."""
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
