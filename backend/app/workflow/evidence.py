"""Evidence: store and extract files, render them for the checker, verify citations."""

from __future__ import annotations

import base64
import re
import unicodedata
from typing import Any

from sqlalchemy.orm import Session

from .. import audit, clock
from ..config import get_settings
from ..email.mime import parse_raw, strip_quoted
from ..extraction import ALLOWED, Rejected, Unreadable, detect, extract, find_injection_like
from ..models import EvidenceFile
from ..storage import get_store

MAX_TEXT_PER_FILE = 60_000
MAX_IMAGES_PER_CALL = 40
MAX_EML_DEPTH = 2


# --------------------------------------------------------------------------- storing


def store_file(
    session: Session,
    *,
    workspace_id: int,
    data: bytes,
    filename: str,
    declared_type: str | None,
    source: str,
    inbound_id: int | None = None,
    provider_id: int | None = None,
    parent: EvidenceFile | None = None,
    depth: int = 0,
) -> list[EvidenceFile]:
    """Validate, store and extract one file. Returns it plus any files nested inside an .eml."""
    s = get_settings()
    now = clock.now(session)
    ef = EvidenceFile(
        workspace_id=workspace_id,
        kind="file",
        filename=(filename or "attachment")[:300],
        content_type=declared_type,
        size=len(data),
        source=source,
        inbound_id=inbound_id,
        provider_id=provider_id,
        parent_file_id=parent.id if parent else None,
        created_at=now,
    )
    session.add(ef)
    out = [ef]
    if len(data) > s.upload_max_file_bytes:
        ef.accepted = False
        ef.rejection_reason = f"file is larger than {s.upload_max_file_bytes // (1024 * 1024)} MB"
        ef.extraction_status = "unreadable"
        ef.unreadable_reason = ef.rejection_reason
        session.flush()
        _log_file(session, ef)
        return out
    try:
        detected = detect(data, filename, declared_type)
    except Rejected as e:
        ef.accepted = False
        ef.rejection_reason = str(e)
        ef.extraction_status = "unreadable"
        ef.unreadable_reason = str(e)
        session.flush()
        _log_file(session, ef)
        return out
    ef.detected_type = detected
    ef.blob = get_store().put(data)
    session.flush()
    if detected == "eml":
        out += _store_eml(session, ef, data, depth)
    else:
        try:
            ef.extraction = extract(data, detected, filename, get_store().put)
            ef.extraction_status = "ok"
        except Unreadable as e:
            ef.extraction_status = "unreadable"
            ef.unreadable_reason = str(e)
        except Exception as e:  # noqa: BLE001 - parser crashed: unreadable, not a guess
            ef.extraction_status = "unreadable"
            ef.unreadable_reason = f"could not be processed ({type(e).__name__})"
    _flag_injection(ef)
    _log_file(session, ef)
    return out


def _store_eml(session: Session, ef: EvidenceFile, data: bytes, depth: int) -> list[EvidenceFile]:
    em = parse_raw(data)
    body = strip_quoted(em.text) or em.text
    ef.extraction = {
        "segments": [{"loc": {"type": "email"}, "label": "message", "text": f"From: {em.from_name} <{em.from_address}>\nSubject: {em.subject}\n\n{body}"}],
        "images": [],
        "meta": {"attachments": [a.filename for a in em.attachments]},
    }
    ef.extraction_status = "ok"
    out: list[EvidenceFile] = []
    if depth < MAX_EML_DEPTH:
        for a in em.attachments:
            out += store_file(
                session,
                workspace_id=ef.workspace_id,
                data=a.data,
                filename=a.filename,
                declared_type=a.content_type,
                source=ef.source,
                inbound_id=ef.inbound_id,
                provider_id=ef.provider_id,
                parent=ef,
                depth=depth + 1,
            )
    return out


def store_text(
    session: Session, *, workspace_id: int, text: str, label: str, source: str, inbound_id: int | None, provider_id: int | None
) -> EvidenceFile:
    loc_type = "email" if source == "email" else "upload_text"
    ef = EvidenceFile(
        workspace_id=workspace_id,
        kind="text",
        filename=label[:300],
        content_type="text/plain",
        size=len(text.encode()),
        source=source,
        inbound_id=inbound_id,
        provider_id=provider_id,
        extraction_status="ok",
        extraction={"segments": [{"loc": {"type": loc_type}, "label": "message", "text": text}], "images": [], "meta": {}},
        created_at=clock.now(session),
    )
    session.add(ef)
    session.flush()
    _flag_injection(ef, in_document=False)
    _log_file(session, ef)
    return ef


def _flag_injection(ef: EvidenceFile, in_document: bool = True) -> None:
    hits = []
    for seg in (ef.extraction or {}).get("segments", []):
        for h in find_injection_like(seg["text"], in_document=in_document):
            hits.append({"code": "instruction_like", "location": seg["label"], "quote": h})
    if hits:
        ef.flags = [*(ef.flags or []), *hits]


def _log_file(session: Session, ef: EvidenceFile) -> None:
    audit.log(
        session,
        actor="provider",
        action="file_received" if ef.kind == "file" else "answer_received",
        workspace_id=ef.workspace_id,
        file=ef.id,
        filename=ef.filename,
        source=ef.source,
        accepted=ef.accepted,
        status=ef.extraction_status,
        reason=ef.unreadable_reason,
        flags=len(ef.flags or []),
    )


# --------------------------------------------------------------------------- rendering for the model


def eid(ef: EvidenceFile) -> str:
    return f"E{ef.id}"


def _attr(s: str) -> str:
    return s.replace('"', "'").replace("<", "(").replace(">", ")")


def _neutralize(text: str) -> str:
    # keep provider text from closing our delimiters
    return re.sub(r"</?\s*(evidence|segment|untrusted|provider_message)", lambda m: m.group(0).replace("<", "‹"), text, flags=re.I)


def render(files: list[EvidenceFile], describe: dict[int, str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Content blocks for the checker. Returns (blocks, notes about truncation/limits)."""
    blocks: list[dict[str, Any]] = []
    notes: list[str] = []
    text_parts: list[str] = []
    images_used = 0

    def flush_text() -> None:
        if text_parts:
            blocks.append({"type": "text", "text": "\n".join(text_parts)})
            text_parts.clear()

    for ef in files:
        head = f'<evidence id="{eid(ef)}" file="{_attr(ef.filename)}" kind="{ "provider_message" if ef.kind == "text" else (ef.detected_type or "unknown")}" source="{_attr(describe.get(ef.id, ef.source))}"'
        if not ef.accepted or ef.extraction_status != "ok":
            text_parts.append(f'{head} status="unreadable" reason="{_attr(ef.unreadable_reason or ef.rejection_reason or "unknown")}" />')
            continue
        text_parts.append(f"{head}>")
        used = 0
        for seg in ef.extraction.get("segments", []):
            t = seg["text"]
            if used + len(t) > MAX_TEXT_PER_FILE:
                t = t[: max(0, MAX_TEXT_PER_FILE - used)]
                notes.append(f"{ef.filename}: text truncated at {MAX_TEXT_PER_FILE} characters")
            used += len(t)
            text_parts.append(f'<segment loc="{_attr(seg["label"])}">\n{_neutralize(t)}\n</segment>')
            if used >= MAX_TEXT_PER_FILE:
                break
        imgs = ef.extraction.get("images", [])
        if imgs:
            text_parts.append(f"(page images for {eid(ef)} follow)")
        text_parts.append("</evidence>")
        for img in imgs:
            if images_used >= MAX_IMAGES_PER_CALL:
                notes.append(f"{ef.filename}: image {img['label']} not shown (image limit)")
                continue
            flush_text()
            blocks.append({"type": "text", "text": f'<evidence_image id="{eid(ef)}" loc="{_attr(img["label"])}" why="{_attr(img["why"])}">'})
            data = get_store().get(img["blob"])
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": img["media_type"], "data": base64.standard_b64encode(data).decode()}})
            images_used += 1
    flush_text()
    return blocks, notes


# --------------------------------------------------------------------------- citation verification

_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " ", "•": " "})


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").translate(_TRANS)
    return re.sub(r"\s+", " ", s).strip().lower()


def _contains(hay: str, quote: str) -> bool:
    h = norm(hay)
    parts = [norm(p) for p in re.split(r"\.\.\.|…", quote) if norm(p)]
    if not parts:
        return False
    pos = 0
    for p in parts:
        i = h.find(p, pos)
        if i < 0:
            return False
        pos = i + len(p)
    return True


_CELL = re.compile(r"^([A-Z]+)(\d+)$")


def _col_num(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _in_range(coord: str, rng: str | None) -> bool:
    if not rng:
        return True
    rng = rng.replace("$", "").upper().strip()
    a, _, b = rng.partition(":")
    b = b or a
    ma, mb, mc = _CELL.match(a), _CELL.match(b), _CELL.match(coord)
    if not (ma and mb and mc):
        return True
    c1, r1, c2, r2 = _col_num(ma[1]), int(ma[2]), _col_num(mb[1]), int(mb[2])
    c, r = _col_num(mc[1]), int(mc[2])
    return min(c1, c2) <= c <= max(c1, c2) and min(r1, r2) <= r <= max(r1, r2)


def verify_citation(cit: dict[str, Any], files: dict[str, EvidenceFile]) -> dict[str, Any]:
    out = {
        "evidence_id": cit.get("evidence_id"),
        "file_id": None,
        "filename": None,
        "location": "",
        "quote": cit.get("quote"),
        "visual": bool(cit.get("visual")),
        "verified": False,
        "problem": None,
        "note": cit.get("note"),
        "image_blob": None,
    }
    ef = files.get(str(cit.get("evidence_id") or "").strip())
    if ef is None:
        out["problem"] = "cites evidence that was not provided"
        return out
    out["file_id"], out["filename"] = ef.id, ef.filename
    segs = (ef.extraction or {}).get("segments", [])
    imgs = (ef.extraction or {}).get("images", [])
    quote = (cit.get("quote") or "").strip()
    dtype = ef.detected_type if ef.kind == "file" else "text"

    if dtype == "pdf":
        page = cit.get("page")
        candidates = [s for s in segs if s["loc"].get("page") == page] if page else segs
        if quote:
            hits = [s for s in candidates if _contains(s["text"], quote)]
            if not hits and page:  # model got the page wrong: accept if the quote is on exactly one page
                hits = [s for s in segs if _contains(s["text"], quote)]
                if hits:
                    out["note"] = ((out["note"] or "") + f" (quote found on {hits[0]['label']}, not p.{page})").strip()
            if hits:
                out["verified"] = True
                out["location"] = hits[0]["label"]
                return out
        if out["visual"]:
            img = next((i for i in imgs if not page or i["loc"].get("page") == page), None)
            if img:
                out["location"] = img["label"]
                out["image_blob"] = img["blob"]
                return out
            out["problem"] = "visual citation, but no page image exists for that location"
            return out
        out["location"] = f"p.{page}" if page else ""
        out["problem"] = "quote not found at the cited location" if quote else "no quote given"
        return out

    if dtype in ("xlsx", "xls", "csv"):
        sheet = (cit.get("sheet") or "").strip().lower()
        rng = cit.get("cell_range")
        sheets = [s for s in segs if not sheet or s["loc"].get("sheet", "").lower() == sheet] or (segs if len(segs) == 1 else [])
        for sg in sheets:
            cells = sg.get("cells", {})
            in_range = [v for k, v in cells.items() if _in_range(k, rng)]
            joined = " | ".join(in_range)
            frags = [f for f in re.split(r"\s*\|\s*", quote) if f.strip()] if quote else []
            ok = bool(quote) and (_contains(joined, quote) or (frags and all(any(_contains(v, f) for v in in_range) for f in frags)))
            if ok:
                out["verified"] = True
                out["location"] = f"sheet '{sg['loc']['sheet']}'" + (f" {rng}" if rng else "")
                return out
        out["location"] = f"sheet '{cit.get('sheet')}' {rng or ''}".strip()
        out["problem"] = "quote not found in the cited cells" if quote else "no quote given"
        return out

    if dtype == "docx":
        para, table, row = cit.get("paragraph"), cit.get("table"), cit.get("row")
        if para:
            cands = [s for s in segs if s["loc"].get("paragraph") == para]
        elif table:
            cands = [s for s in segs if s["loc"].get("table") == table and (not row or s["loc"].get("row") == row)]
        else:
            cands = segs
        hit = next((s for s in cands if quote and _contains(s["text"], quote)), None)
        if hit:
            out["verified"], out["location"] = True, hit["label"]
            return out
        out["problem"] = "quote not found at the cited location" if quote else "no quote given"
        return out

    if dtype in ("png", "jpeg", "heic"):
        out["location"] = "image"
        if imgs:
            out["image_blob"] = imgs[0]["blob"]
        if not out["visual"]:
            out["visual"] = True  # anything cited from an image is visual evidence
        return out

    # provider message text or .eml body
    hit = next((s for s in segs if quote and _contains(s["text"], quote)), None)
    out["location"] = "message"
    if hit:
        out["verified"] = True
        return out
    out["problem"] = "quote not found in the message" if quote else "no quote given"
    return out


def supports(c: dict[str, Any]) -> bool:
    """A citation counts as support if its text was verified, or it is labeled visual evidence."""
    return bool(c.get("verified") or (c.get("visual") and not c.get("problem")))


ALLOWED_TYPES = ALLOWED
