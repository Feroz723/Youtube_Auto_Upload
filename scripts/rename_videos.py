"""Standalone utility for batch renaming MP4 video files.

Renames all MP4 files in a specified folder to the zero-padded format::

    funny_cartoon_001.mp4
    funny_cartoon_002.mp4
    ...
    funny_cartoon_527.mp4

Usage::

    python scripts/rename_videos.py "E:\\Funny Cartoons"
    python scripts/rename_videos.py "E:\\Funny Cartoons" --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from pathlib import Path

# ── Ensure UTF-8 Console Output on Windows ───────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Default Prefix & Extension ───────────────────────────────────────────────
_DEFAULT_PREFIX = "funny_cartoon"
_EXTENSION = ".mp4"


def _safe_print(text: str) -> None:
    """Print text safely across legacy OS console encodings."""
    try:
        print(text)
    except UnicodeEncodeError:
        safe_text = text.replace("↓", "->").replace("→", "->")
        print(safe_text)


def natural_sort_key(path: Path) -> list[int | str]:
    """Generate a key for natural/numerical sorting.

    Splits the stem into text and numeric components so that
    'funny_cartoon_2.mp4' comes before 'funny_cartoon_10.mp4'.
    """
    stem = path.stem
    parts = re.split(r"(\d+)", stem)
    key: list[int | str] = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part.lower())
    return key


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="rename_videos",
        description="Batch rename MP4 files to funny_cartoon_NNN.mp4 format.",
    )
    parser.add_argument(
        "folder",
        type=str,
        help="Path to the folder containing MP4 files to rename.",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default=_DEFAULT_PREFIX,
        help=f"Filename prefix (default: '{_DEFAULT_PREFIX}').",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview renaming mapping without changing any files on disk.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of files to rename (e.g. --limit 99).",
    )
    return parser.parse_args(argv)


def rename_videos(folder_path: str | Path, prefix: str = _DEFAULT_PREFIX, dry_run: bool = False, limit: int | None = None) -> int:
    """Batch rename MP4 files in *folder_path* to *prefix*_NNN.mp4 format using a safe two-pass algorithm.

    Args:
        folder_path: Path to target directory.
        prefix: Filename prefix (e.g. 'funny_cartoon').
        dry_run: If True, preview renaming without modifying disk.
        limit: Optional maximum number of files to process.

    Returns:
        0 on success, 1 on error.
    """
    target_dir = Path(folder_path).resolve()

    # ── 1. Validation ────────────────────────────────────────────────────
    if not target_dir.exists():
        _safe_print(f"Error: Folder does not exist: {target_dir}")
        return 1

    if not target_dir.is_dir():
        _safe_print(f"Error: Target path is not a directory: {target_dir}")
        return 1

    # ── 2. Discover MP4 files ───────────────────────────────────────────
    all_files = [p for p in target_dir.iterdir() if p.is_file() and p.suffix.lower() == _EXTENSION]

    if not all_files:
        _safe_print(f"No MP4 files found in '{target_dir}'. Nothing to do.")
        return 0

    _safe_print(f"{len(all_files)} files found\n")

    # ── 3. Natural Sort & Limit ──────────────────────────────────────────
    sorted_files = sorted(all_files, key=natural_sort_key)
    if limit is not None and limit > 0:
        sorted_files = sorted_files[:limit]
        _safe_print(f"Processing first {len(sorted_files)} file(s) (--limit {limit}).\n")

    # ── 4. Calculate target names ────────────────────────────────────────
    renames: list[tuple[Path, Path]] = []
    renamed_count = 0
    skipped_count = 0
    failed_count = 0

    for idx, old_path in enumerate(sorted_files, start=1):
        new_filename = f"{prefix}_{idx:03d}{_EXTENSION}"
        new_path = target_dir / new_filename

        if old_path == new_path:
            skipped_count += 1
            continue

        renames.append((old_path, new_path))

    if not renames:
        _safe_print("All MP4 files are already correctly named.\n")
        _safe_print("Finished.")
        _safe_print(f"0 renamed\n{skipped_count} skipped\n0 failed")
        return 0

    # ── 5. Preview (Dry Run) ──────────────────────────────────────────────
    if dry_run:
        _safe_print("Renamed (dry-run):")
        for old_path, new_path in renames:
            _safe_print(f"{old_path.name}\n↓\n{new_path.name}\n")
        _safe_print("Finished.")
        _safe_print(f"{len(renames)} renamed")
        _safe_print(f"{skipped_count} skipped")
        _safe_print("0 failed")
        return 0

    # ── 6. Safe Two-Pass Execution ───────────────────────────────────────
    # Pass 1: Rename all source files to temporary unique filenames
    temp_map: list[tuple[Path, Path, str]] = []  # (temp_path, final_path, original_name)
    session_id = uuid.uuid4().hex[:8]

    try:
        # Pass 1: Old -> Temp
        for old_path, final_path in renames:
            temp_name = f"_temp_{session_id}_{old_path.name}"
            temp_path = target_dir / temp_name
            old_path.rename(temp_path)
            temp_map.append((temp_path, final_path, old_path.name))

        # Pass 2: Temp -> Final
        _safe_print("Renamed:")
        for temp_path, final_path, original_name in temp_map:
            temp_path.rename(final_path)
            renamed_count += 1
            _safe_print(f"{original_name}\n→\n{final_path.name}\n")

    except Exception as exc:
        _safe_print(f"Error during rename operation: {exc}")
        failed_count += 1
        # Emergency rollback for remaining temp files
        for temp_path, _, original_name in temp_map:
            if temp_path.exists():
                try:
                    temp_path.rename(target_dir / original_name)
                except Exception:
                    pass
        return 1

    _safe_print("Finished.")
    _safe_print(f"{renamed_count} renamed")
    _safe_print(f"{skipped_count} skipped")
    _safe_print(f"{failed_count} failed")
    return 0


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    args = parse_args(argv)
    code = rename_videos(folder_path=args.folder, prefix=args.prefix, dry_run=args.dry_run, limit=args.limit)
    sys.exit(code)


if __name__ == "__main__":
    main()
