"""Shared utility helpers.

Responsibilities:
    - Extract video numbers from filenames.
    - OAuth 2.0 authentication (Desktop Application flow).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CREDENTIALS_FILE = _PROJECT_ROOT / "credentials.json"
_TOKEN_FILE = _PROJECT_ROOT / "token.json"

# ── OAuth scopes ─────────────────────────────────────────────────────────────
# Drive: full file access (list, download, move).
# Sheets & YouTube scopes will be added here when those modules are
# implemented — requesting all scopes upfront avoids re-authorization later.
SCOPES: list[str] = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

# ── Filename pattern ─────────────────────────────────────────────────────────
# Matches filenames like: funny_cartoon_001.mp4, funny_cartoon_527.mp4
_VIDEO_PATTERN = re.compile(r"^funny_cartoon_(\d+)\.mp4$")


# ── Authentication ───────────────────────────────────────────────────────────

def get_credentials() -> Credentials:
    """Return valid Google OAuth 2.0 credentials.

    Workflow:

    1. If ``token.json`` exists, load it and reuse the saved credentials.
    2. If the access token is expired but a refresh token is available,
       silently refresh it and re-save ``token.json``.
    3. If no ``token.json`` exists, launch the Desktop OAuth flow (opens a
       browser), obtain tokens, and save them to ``token.json``.

    On GitHub Actions the browser flow cannot run, so ``token.json`` must be
    generated locally first and committed to the repo (or injected as a
    secret).

    Returns:
        A :class:`~google.oauth2.credentials.Credentials` object with a
        valid access token.

    Raises:
        FileNotFoundError: If ``credentials.json`` is missing and no
            ``token.json`` is available.
        google.auth.exceptions.RefreshError: If the refresh token has been
            revoked or is otherwise invalid.
    """
    creds: Credentials | None = None

    # ── 1. Try to load existing token ────────────────────────────────────
    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), SCOPES)
        logger.info("Loaded existing token from token.json.")

    # ── 2. Refresh or re-authorize ───────────────────────────────────────
    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        logger.info("Access token expired — refreshing.")
        creds.refresh(Request())
        _save_token(creds)
        return creds

    # ── 3. Full OAuth flow (local only) ──────────────────────────────────
    if not _CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"OAuth credentials file not found: {_CREDENTIALS_FILE}\n"
            f"Download it from Google Cloud Console → APIs & Services → "
            f"Credentials → OAuth 2.0 Client IDs → Download JSON, and save "
            f"it as 'credentials.json' in the project root."
        )

    logger.info("No valid token found — starting OAuth browser flow.")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(_CREDENTIALS_FILE), SCOPES
    )
    creds = flow.run_local_server(port=0)
    _save_token(creds)
    logger.info("Authorization successful — token saved to token.json.")
    return creds


# ── Filename parsing ─────────────────────────────────────────────────────────

def extract_video_number(filename: str) -> int:
    """Extract the numeric suffix from a video filename.

    Args:
        filename: A filename matching ``funny_cartoon_NNN.mp4``.

    Returns:
        The video number as an integer (leading zeros stripped).

    Raises:
        ValueError: If *filename* does not match the expected pattern.

    Examples:
        >>> extract_video_number("funny_cartoon_001.mp4")
        1
        >>> extract_video_number("funny_cartoon_527.mp4")
        527
    """
    match = _VIDEO_PATTERN.match(filename)
    if not match:
        raise ValueError(
            f"Invalid filename format: '{filename}'. "
            f"Expected pattern: funny_cartoon_NNN.mp4"
        )
    return int(match.group(1))


# ── Internal helpers ─────────────────────────────────────────────────────────

def _save_token(creds: Credentials) -> None:
    """Persist credentials to ``token.json``."""
    _TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    logger.debug("Token written to %s", _TOKEN_FILE)
