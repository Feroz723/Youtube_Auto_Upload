"""Google Sheets integration.

Responsibilities:
    - Read video metadata (title, description) from a tracking Google Sheet.
    - Lookup metadata by Video No column.
"""

from __future__ import annotations

import logging
from typing import Any

import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from src.config import get_google_sheet_id, get_google_sheet_worksheet

logger = logging.getLogger(__name__)

# ── Module-level cache for worksheet records ─────────────────────────────────
# Ensures the worksheet is loaded only once per process execution.
_WORKSHEET_CACHE: dict[tuple[str, str], list[list[str]]] = {}


def _get_worksheet_rows(creds: Credentials, sheet_id: str, worksheet_name: str) -> list[list[str]]:
    """Fetch all rows from the specified worksheet in a single API call (cached)."""
    cache_key = (sheet_id, worksheet_name)
    if cache_key in _WORKSHEET_CACHE:
        logger.debug("Reusing cached worksheet rows for '%s' -> '%s'.", sheet_id, worksheet_name)
        return _WORKSHEET_CACHE[cache_key]

    logger.info("Fetching worksheet rows from Google Sheet '%s' (tab: '%s')...", sheet_id, worksheet_name)
    try:
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(sheet_id)
        worksheet = spreadsheet.worksheet(worksheet_name)
        rows: list[list[str]] = worksheet.get_all_values()
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise RuntimeError(
            f"Google Sheet not found for ID '{sheet_id}'. "
            f"Verify GOOGLE_SHEET_ID and access permissions."
        ) from exc
    except gspread.exceptions.WorksheetNotFound as exc:
        raise RuntimeError(
            f"Worksheet tab '{worksheet_name}' not found in Google Sheet '{sheet_id}'. "
            f"Verify GOOGLE_SHEET_WORKSHEET."
        ) from exc
    except (gspread.exceptions.APIError, HttpError) as exc:
        raise RuntimeError(
            f"Failed to load Google Sheet '{sheet_id}' worksheet '{worksheet_name}': {exc}"
        ) from exc

    _WORKSHEET_CACHE[cache_key] = rows
    logger.info("Loaded %d row(s) from worksheet '%s'.", len(rows), worksheet_name)
    return rows


def clear_worksheet_cache() -> None:
    """Clear the in-memory worksheet cache."""
    _WORKSHEET_CACHE.clear()


def get_video_metadata(creds: Credentials, video_number: int) -> dict[str, str]:
    """Retrieve title and description for *video_number* from Google Sheets.

    Args:
        creds: Valid Google OAuth 2.0 credentials.
        video_number: Integer video number to lookup.

    Returns:
        A dictionary with ``"title"`` and ``"description"`` keys.

    Raises:
        ValueError: If video number is not found, or if title/description is empty.
        RuntimeError: If Sheet or Worksheet cannot be loaded.
    """
    sheet_id = get_google_sheet_id()
    worksheet_name = get_google_sheet_worksheet()

    rows = _get_worksheet_rows(creds, sheet_id, worksheet_name)

    if not rows or len(rows) < 2:
        raise ValueError(
            f"Google Sheet worksheet '{worksheet_name}' is empty or has no data rows."
        )

    # Header inspection (row 0)
    headers = [h.strip().lower() for h in rows[0]]

    # Locate column indices for Video No, Title, Description
    video_no_col_idx = -1
    title_col_idx = -1
    desc_col_idx = -1

    for idx, header in enumerate(headers):
        if header in ("video no", "video_no", "video number", "video #", "video_number", "video"):
            video_no_col_idx = idx
        elif header == "title":
            title_col_idx = idx
        elif header in ("description", "desc"):
            desc_col_idx = idx

    if video_no_col_idx == -1:
        raise ValueError(
            f"Required column 'Video No' not found in worksheet '{worksheet_name}'. "
            f"Found headers: {rows[0]}"
        )
    if title_col_idx == -1:
        raise ValueError(
            f"Required column 'Title' not found in worksheet '{worksheet_name}'. "
            f"Found headers: {rows[0]}"
        )
    if desc_col_idx == -1:
        raise ValueError(
            f"Required column 'Description' not found in worksheet '{worksheet_name}'. "
            f"Found headers: {rows[0]}"
        )

    # Search rows (rows[1:]) by Video No
    for row_idx, row in enumerate(rows[1:], start=2):
        if len(row) <= video_no_col_idx:
            continue

        raw_video_no = row[video_no_col_idx].strip()
        try:
            row_video_num = int(raw_video_no)
        except ValueError:
            continue

        if row_video_num == video_number:
            title = row[title_col_idx].strip() if len(row) > title_col_idx else ""
            description = row[desc_col_idx].strip() if len(row) > desc_col_idx else ""

            if not title:
                raise ValueError(
                    f"Title is empty for Video No {video_number} in row {row_idx} of worksheet '{worksheet_name}'."
                )
            if not description:
                raise ValueError(
                    f"Description is empty for Video No {video_number} in row {row_idx} of worksheet '{worksheet_name}'."
                )

            return {
                "title": title,
                "description": description,
            }

    raise ValueError(
        f"Video number {video_number} not found in Google Sheet '{sheet_id}' (worksheet '{worksheet_name}')."
    )
