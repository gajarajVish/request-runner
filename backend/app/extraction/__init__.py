"""Turn evidence files into located text segments (and page images for vision).

Extraction output (stored on EvidenceFile.extraction):

    {"segments": [{"loc": {...}, "label": "p.2", "text": "..."}],
     "images":   [{"loc": {...}, "label": "p.3 (image)", "blob": "<sha>", "media_type": "image/png", "why": "..."}],
     "meta": {...}}

`loc` is what citations point at: {"type": "pdf", "page": 2}, {"type": "sheet", "sheet": "Sep",
"range": "A1:F40"}, {"type": "docx", "paragraph": 7}, {"type": "docx", "table": 1, "row": 3},
{"type": "email"}, {"type": "image"}. Files that can't be read raise Unreadable with a reason
the requester and provider can act on.
"""

from __future__ import annotations

from .core import Unreadable, extract, find_injection_like  # noqa: F401
from .validate import ALLOWED, Rejected, detect  # noqa: F401
