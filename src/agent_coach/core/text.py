"""Pure text and source helpers for Agent Core orchestration."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, MutableSequence


def query_terms(value: object) -> set[str]:
    """Normalize a retrieval query for conservative near-duplicate checks."""

    return {
        token
        for token in re.findall(r"[\w]+", str(value or "").casefold(), flags=re.UNICODE)
        if len(token) > 2
    }


def source_identity(source: Mapping[str, object]) -> str:
    """Return a stable, non-sensitive identity for a source-like mapping."""

    node_id = str(source.get("node_id") or "").strip()
    if node_id:
        return f"node:{node_id}"
    path = str(
        source.get("relative_path")
        or source.get("file_name")
        or source.get("file")
        or source.get("url")
        or ""
    ).strip().casefold()
    text = " ".join(str(source.get("text") or "").casefold().split())[:180]
    position = ":".join(
        str(source.get(key) or "") for key in ("page", "line_start", "line_end")
    )
    return f"source:{path}|{position}|{text}"


def merge_sources(
    target: MutableSequence[dict[str, object]],
    incoming: Iterable[object],
    *,
    max_sources: int,
) -> None:
    """Merge source-like mappings while preserving richer later fields."""

    known = {source_identity(source): index for index, source in enumerate(target)}
    for raw in incoming:
        if not isinstance(raw, dict):
            continue
        source = dict(raw)
        if not source.get("file_name") and source.get("file"):
            source["file_name"] = source["file"]
        identity = source_identity(source)
        if identity in known:
            current = target[known[identity]]
            current.update(
                {
                    key: value
                    for key, value in source.items()
                    if value not in (None, "", [], {})
                }
            )
            continue
        if len(target) >= max_sources:
            continue
        known[identity] = len(target)
        target.append(source)
