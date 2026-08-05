"""Pipeline context — the single data object passed through every stage.

``UploadContext`` is created once at the start of the pipeline and threaded
through each stage.  Stages populate the fields they own and leave the rest
untouched, so there is a single source of truth for every piece of data and
no values are duplicated.

Fields that are not yet available are set to ``None`` and filled in by the
stage responsible for them (see the table below).

=================  ==================  ======================
Field              Populated by        Contains
=================  ==================  ======================
drive_file_id      Stage 1 (Discover)  Google Drive file ID
filename           Stage 1 (Discover)  e.g. funny_cartoon_001.mp4
video_number       Stage 1 (Discover)  Extracted integer (1)
local_file_path    Stage 3 (Download)  Temp path on disk
title              Stage 4 (Metadata)  Video title from Sheet
description        Stage 4 (Metadata)  Video description from Sheet
=================  ==================  ======================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class UploadContext:
    """Mutable context object threaded through every pipeline stage.

    Required fields are set at construction (Stage 1).  Optional fields
    start as ``None`` and are populated by later stages.
    """

    # ── Stage 1: Discover ────────────────────────────────────────────────
    drive_file_id: str
    filename: str
    video_number: int

    # ── Stage 3: Download ────────────────────────────────────────────────
    local_file_path: Path | None = field(default=None)

    # ── Stage 4: Metadata (Sheets) ───────────────────────────────────────
    title: str | None = field(default=None)
    description: str | None = field(default=None)

    # ── Stage 5: Upload (YouTube) ────────────────────────────────────────
    youtube_video_id: str | None = field(default=None)
    youtube_url: str | None = field(default=None)
