"""HTTP response helpers shared by the standard-library server."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote


def inline_filename_header(filename: str) -> str:
    """Build a Windows-safe inline filename header, including a UTF-8 name."""
    safe_name = Path(filename).name.replace('"', "_").replace("\r", "_").replace("\n", "_")
    fallback = safe_name.encode("ascii", "ignore").decode("ascii") or "exam"
    encoded = quote(safe_name, safe="")
    return f'inline; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'
