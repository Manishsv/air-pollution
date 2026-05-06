from __future__ import annotations

from typing import Any, Iterable, Sequence


def paginate_items(items: Sequence[Any], *, limit: int, offset: int) -> dict[str, Any]:
    total = len(items)
    o = max(0, int(offset))
    l = max(1, int(limit))
    sliced = list(items[o : o + l])
    count = len(sliced)
    next_offset = o + count
    has_more = next_offset < total
    return {
        "items": sliced,
        "count": count,
        "total": total,
        "limit": l,
        "offset": o,
        "next_offset": next_offset,
        "has_more": bool(has_more),
    }

