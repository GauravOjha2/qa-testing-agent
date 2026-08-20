"""Small, dependency-free helpers for reading already-rendered page state."""

from __future__ import annotations

from typing import Any


def read_meta_description(page: Any) -> str:
    """Return a description if it exists now, without waiting for hydration."""
    try:
        value = page.evaluate("""() =>
            document.querySelector('meta[name="description"]')?.content || ''
        """)
        return value if isinstance(value, str) else ""
    except Exception:
        return ""
