"""Part 2: request lists (CSV) -> review -> apply -> one draft email per provider -> send all.

Identity: a row's `request_id` is scoped to its ImportList. A Request keeps its first id as
`external_id` and every merged id in `aliases`.

Analysis (no side effects on requests):
- validate each row; the same id twice with different content is a blocking error
- exact duplicates (every meaningful field equal, id aside) merge automatically
- near duplicates are only suggested
- flags: vague (blocks sending), past due, no backup, shared owners, dependencies
- re-import: compare each row's CSV content with the last applied row for the same id.
  Unchanged rows do nothing. Requester edits made at review are kept on top of the CSV.
- rows scoped by the model, cached by content so unchanged rows never re-hit it

Apply = the requester confirming the reviewed checklists. New rows become confirmed requests
in ready_to_send with one draft email per provider; changed rows update in place and send one
consolidated change notice per provider; removed rows are flagged, never cancelled.
"""

from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock, storage
from ..config import get_settings
from ..db import session_scope
from ..llm import base as llm
from ..llm import prompts
from ..llm.schemas import DraftItem, RowScope
from ..models import (
    ChecklistVersion,
    Conversation,
    ConversationRequest,
    ImportBatch,
    ImportList,
    ImportRow,
    OutboundMessage,
    Provider,
    Request,
    RequestDependency,
    RequestOwner,
    ScopeCache,
    User,
)
from . import emails, hub, jobs, outbox, states
from .common import add_comment, add_flag, current_version, get_or_create_provider, next_version_number, request_label


class ImportError_(Exception):  # noqa: N801 - avoid shadowing the builtin ImportError
    pass


COLUMNS = ["request_id", "title", "instructions", "due_date", "owner_name", "owner_email", "backup_email"]
REQUIRED = ["request_id", "title", "instructions", "due_date", "owner_email"]
EMAIL_RE = re.compile(r"^[^@\s;,]+@[^@\s;,]+\.[^@\s;,]+$")
SCOPE_VERSION = "rowscope-v1"
NEAR_DUP_RATIO = 0.85
BLOCKING = {"vague", "scope_failed"}


# --------------------------------------------------------------------------- parsing


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _split(s: str | None) -> list[str]:
    return [p.strip() for p in (s or "").split(";") if p.strip()]


def parse_csv(data: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """-> (rows, file-level errors). Each row: normalized fields + `errors`."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError:
            return [], ["The file isn't a text CSV."]
    reader = csv.DictReader(io.StringIO(text))
    headers = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in headers]
    if missing:
        return [], [f"Missing column(s): {', '.join(missing)}. Expected: {', '.join(COLUMNS)}."]
    rows = []
    for n, raw in enumerate(reader, start=2):
        rec = {(k or "").strip().lower(): (v or "") for k, v in raw.items() if k}
        if not any(_norm(v) for v in rec.values()):
            continue
        errors: list[str] = []
        names, mails = _split(rec.get("owner_name")), [m.lower() for m in _split(rec.get("owner_email"))]
        if not mails:
            errors.append("no owner email")
        bad = [m for m in mails if not EMAIL_RE.match(m)]
        if bad:
            errors.append(f"invalid owner email: {', '.join(bad)}")
        if names and len(names) != len(mails):
            errors.append("owner_name and owner_email list a different number of people")
        owners = [{"email": m, "name": names[i] if i < len(names) else None} for i, m in enumerate(mails)]
        if len({o["email"] for o in owners}) != len(owners):
            errors.append("the same owner is listed twice")
        backup = _norm(rec.get("backup_email")).lower() or None
        if backup and not EMAIL_RE.match(backup):
            errors.append(f"invalid backup email: {backup}")
        due = None
        due_raw = _norm(rec.get("due_date"))
        if not due_raw:
            errors.append("no due date")
        else:
            try:
                due = date.fromisoformat(due_raw).isoformat()
            except ValueError:
                errors.append(f"due date '{due_raw}' isn't YYYY-MM-DD")
        for f in ("request_id", "title", "instructions"):
            if not _norm(rec.get(f)):
                errors.append(f"no {f.replace('_', ' ')}")
        rows.append(
            {
                "line": n,
                "request_id": _norm(rec.get("request_id")),
                "title": _norm(rec.get("title")),
                "instructions": _norm(rec.get("instructions")),
                "due_date": due,
                "owners": owners,
                "backup_email": backup,
                "errors": errors,
            }
        )
    if not rows:
        return [], ["The file has no rows."]
    return rows, []


def content_hash(row: dict[str, Any]) -> str:
    """Every meaningful field except the id. Dependencies are part of the instructions text."""
    key = {
        "title": row["title"].lower(),
        "instructions": row["instructions"].lower(),
        "due_date": row["due_date"],
        "owners": sorted(o["email"] for o in row["owners"]),
        "backup_email": row["backup_email"],
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()


def find_refs(text: str, known: set[str], self_id: str) -> list[str]:
    """Ids of other rows mentioned in the text (e.g. 'the R-05 report')."""
    out = []
    for m in re.finditer(r"\b([A-Za-z]{1,6}-\d{1,5})\b", text):
        ref = m.group(1).upper()
        if ref in known and ref != self_id.upper() and ref not in out:
            out.append(ref)
    return out


def effective(row: ImportRow) -> dict[str, Any]:
    """CSV values with the requester's review edits on top."""
    return {**{k: v for k, v in row.raw.items() if k != "_edits"}, **(row.raw.get("_edits") or {})}


def _flag(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "blocking": code in BLOCKING, **extra}


def _set_flag(row: ImportRow, flag: dict[str, Any]) -> None:
    row.flags = [f for f in (row.flags or []) if f["code"] != flag["code"]] + [flag]


def _drop_flag(row: ImportRow, code: str) -> None:
    row.flags = [f for f in (row.flags or []) if f["code"] != code]


# --------------------------------------------------------------------------- start


def start_import(s: Session, user: User, *, list_name: str, filename: str, data: bytes) -> ImportBatch:
    name = _norm(list_name) or "Request list"
    lst = s.scalars(select(ImportList).where(ImportList.workspace_id == user.workspace_id, ImportList.name == name)).first()
    if lst is None:
        lst = ImportList(workspace_id=user.workspace_id, requester_id=user.id, name=name, created_at=clock.now(s))
        s.add(lst)
        s.flush()
    for old in s.scalars(select(ImportBatch).where(ImportBatch.import_list_id == lst.id, ImportBatch.status.in_(["analyzing", "review"]))):
        old.status = "discarded"
    batch = ImportBatch(import_list_id=lst.id, filename=filename[:300], blob=storage.get_store().put(data), status="analyzing", created_at=clock.now(s))
    s.add(batch)
    s.flush()
    audit.log(s, actor="requester", actor_detail=user.email, action="import_uploaded", workspace_id=user.workspace_id, list=lst.name, batch=batch.id, filename=filename)
    jobs.enqueue(s, "import_analyze", f"import_analyze:{batch.id}", {"batch_id": batch.id, "user_id": user.id})
    return batch


def _list_requests(s: Session, lst: ImportList) -> list[Request]:
    return list(s.scalars(select(Request).where(Request.import_list_id == lst.id).order_by(Request.id)))


def _request_ids(r: Request) -> set[str]:
    return {i.upper() for i in [r.external_id or "", *(r.aliases or [])] if i}


def _last_applied_row(s: Session, request_id: int) -> ImportRow | None:
    return s.scalars(
        select(ImportRow)
        .join(ImportBatch, ImportBatch.id == ImportRow.batch_id)
        .where(ImportRow.request_id == request_id, ImportBatch.status == "applied", ImportRow.action.not_in(["removed", "error"]))
        .order_by(ImportRow.id.desc())
    ).first()


# --------------------------------------------------------------------------- analyze


@jobs.handler("import_analyze")
def analyze_job(payload: dict) -> None:
    bid = payload["batch_id"]
    with session_scope() as s:
        batch = s.get(ImportBatch, bid)
        if batch is None or batch.status != "analyzing":
            return
        analyze(s, batch)
        todo = _rows_to_scope(s, batch)
    _scope_rows(bid, todo)
    with session_scope() as s:
        batch = s.get(ImportBatch, bid)
        if batch is None or batch.status != "analyzing":
            return
        batch.status = "review"
        lst = s.get(ImportList, batch.import_list_id)
        assert lst is not None
        audit.log(s, actor="agent", action="import_analyzed", workspace_id=lst.workspace_id, batch=batch.id, rows=len(batch.rows), summary=summary(batch))
        audit.emit(s, lst.workspace_id, "import", None, {"batch_id": batch.id, "status": batch.status})


def analyze(s: Session, batch: ImportBatch) -> None:
    lst = s.get(ImportList, batch.import_list_id)
    assert lst is not None
    parsed, file_errors = parse_csv(storage.get_store().get(batch.blob))
    batch.rows.clear()
    s.flush()
    batch.errors = file_errors
    if file_errors:
        batch.status = "error"
        return
    today = clock.local_date(clock.now(s), get_settings().workspace_timezone)
    existing = _list_requests(s, lst)
    by_ext: dict[str, Request] = {}
    for r in existing:
        for i in _request_ids(r):
            by_ext[i] = r
    known = {p["request_id"].upper() for p in parsed if p["request_id"]} | set(by_ext)

    # the same id twice: identical content is a harmless repeat, different content is an error
    seen: dict[str, dict[str, Any]] = {}
    conflicting: set[str] = set()
    for p in parsed:
        rid = p["request_id"].upper()
        if not rid or p["errors"]:
            continue
        p["hash"] = content_hash(p)
        if rid in seen and seen[rid]["hash"] != p["hash"]:
            conflicting.add(rid)
        seen.setdefault(rid, p)

    first_by_hash: dict[str, str] = {}
    rows: list[ImportRow] = []
    for pos, p in enumerate(parsed):
        rid = p["request_id"].upper()
        raw = {k: p[k] for k in ("line", "request_id", "title", "instructions", "due_date", "owners", "backup_email")}
        raw["depends_on"] = find_refs(p["instructions"] + " " + p["title"], known, rid) if p["instructions"] else []
        row = ImportRow(position=pos, external_id=rid or f"(line {p['line']})", raw=raw, content_hash=p.get("hash") or "", action="new", flags=[], changes=[], scope={})
        rows.append(row)
        if p["errors"]:
            row.action = "error"
            _set_flag(row, _flag("invalid", "; ".join(p["errors"]), blocking=True))
            continue
        if rid in conflicting:
            row.action = "error"
            _set_flag(row, _flag("conflicting_id", f"{rid} appears more than once with different content. Exclude the wrong row.", blocking=True))
            continue
        if p["hash"] in first_by_hash:
            target = first_by_hash[p["hash"]]
            row.action = "duplicate"
            row.merged_into = target
            _set_flag(row, _flag("duplicate", f"Identical to {target}; merged into it." if target != rid else f"{rid} is repeated; the repeat is ignored."))
            continue
        first_by_hash[p["hash"]] = rid

        req = by_ext.get(rid)
        if req is not None:
            row.request_id = req.id
            prev = _last_applied_row(s, req.id)
            if prev is not None and prev.content_hash == p["hash"]:
                row.action = "unchanged"
                row.ownership_mode = prev.ownership_mode
                row.scope = prev.scope
                continue
            row.action = "changed"
            row.ownership_mode = req.ownership_mode
            row.changes = _diff(prev.raw if prev else _raw_from_request(s, req), raw)
            if req.state in states.TERMINAL:
                _set_flag(row, _flag("closed_request", f"{request_label(req)} is already {states.LABELS[req.state].lower()}; these changes won't be sent."))
            if not _scope_changed(row.changes) and prev is not None:
                row.scope = prev.scope
        _row_flags(row, raw, today)

    # near duplicates among rows that will create or change requests (suggested only)
    live = [r for r in rows if r.action in ("new", "changed")]
    for i, a in enumerate(live):
        for b in live[i + 1 :]:
            ea, eb = a.raw, b.raw
            same_owner = {o["email"] for o in ea["owners"]} & {o["email"] for o in eb["owners"]}
            ratio = difflib.SequenceMatcher(None, ea["instructions"].lower(), eb["instructions"].lower()).ratio()
            if same_owner and (ratio >= NEAR_DUP_RATIO or ea["title"].lower() == eb["title"].lower()):
                _set_flag(b, _flag("near_duplicate", f"Looks like {a.external_id} ({int(ratio * 100)}% similar instructions). Merge it if it's the same request.", other=a.external_id))

    # rows in the list that are gone from this file
    present = {r.external_id for r in rows}
    for req in existing:
        if req.state in states.TERMINAL or _request_ids(req) & present:
            continue
        rows.append(
            ImportRow(
                position=len(rows),
                external_id=req.external_id or str(req.id),
                raw={"request_id": req.external_id, "title": req.title},
                content_hash="",
                action="removed",
                request_id=req.id,
                flags=[_flag("removed", f"{request_label(req)} isn't in this file. It will be flagged, not cancelled. Cancel it from its page if it's no longer needed.")],
                changes=[],
                scope={},
            )
        )
    batch.rows.extend(rows)
    s.flush()


def _row_flags(row: ImportRow, raw: dict[str, Any], today: date) -> None:
    if raw["due_date"] and date.fromisoformat(raw["due_date"]) < today:
        _set_flag(row, _flag("past_due", f"The due date {raw['due_date']} has already passed. Change it here, or it'll be sent as overdue."))
    else:
        _drop_flag(row, "past_due")
    if not raw["backup_email"]:
        _set_flag(row, _flag("no_backup", "No backup owner: if this goes overdue, only you will be notified."))
    if len(raw["owners"]) > 1:
        who = " and ".join(o["name"] or o["email"] for o in raw["owners"])
        _set_flag(row, _flag("shared", f"Shared by {who}. By default either one can satisfy it; switch to 'both must respond' if each must send their own."))
    if raw["depends_on"]:
        _set_flag(row, _flag("depends_on", f"Refers to {', '.join(raw['depends_on'])}. Sent with that context, and completes only after it does.", refs=raw["depends_on"]))


def _raw_from_request(s: Session, req: Request) -> dict[str, Any]:
    return {
        "title": req.title,
        "instructions": req.instructions or "",
        "due_date": req.due_date.isoformat() if req.due_date else None,
        "owners": [{"email": o.provider.email, "name": o.provider.name} for o in req.owners],
        "backup_email": req.backup_email,
    }


def _diff(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for f in ("title", "instructions", "due_date", "backup_email"):
        if (old.get(f) or None) != (new.get(f) or None):
            out.append({"field": f, "old": old.get(f), "new": new.get(f)})
    oo = sorted(o["email"] for o in old.get("owners") or [])
    no = sorted(o["email"] for o in new.get("owners") or [])
    if oo != no:
        out.append({"field": "owners", "old": oo, "new": no})
    return out


def _scope_changed(changes: list[dict[str, Any]]) -> bool:
    return any(c["field"] in ("title", "instructions") for c in changes)


# --------------------------------------------------------------------------- scoping


def _rows_to_scope(s: Session, batch: ImportBatch) -> list[tuple[int, dict[str, Any]]]:
    out = []
    for r in batch.rows:
        if r.action == "new" or (r.action == "changed" and not r.scope):
            e = effective(r)
            out.append((r.id, {"request_id": e["request_id"], "title": e["title"], "instructions": e["instructions"], "due_date": e["due_date"], "depends_on": e["depends_on"]}))
    return out


def _cache_key(row: dict[str, Any]) -> str:
    cfg = get_settings()
    basis = json.dumps([SCOPE_VERSION, cfg.llm_provider, cfg.llm_strong_model, row["title"], row["instructions"], row["depends_on"]])
    return hashlib.sha256(basis.encode()).hexdigest()


def _scope_one(row: dict[str, Any], today: str, dep_titles: dict[str, str]) -> dict[str, Any]:
    key = _cache_key(row)
    with session_scope() as s:
        hit = s.get(ScopeCache, key)
        if hit is not None:
            return {**hit.result, "cached": True}
    deps = "".join(f"\n{d}: {dep_titles.get(d, '')}" for d in row["depends_on"])
    text = f"Row {row['request_id']}\nTitle: {row['title']}\nInstructions: {row['instructions']}" + (f"\nOther rows it refers to:{deps}" if deps else "")
    call = llm.LLMCall(
        step="scope_row",
        system=prompts.SCOPE_ROW.format(today=today),
        content=[{"type": "text", "text": text}],
        output=RowScope,
        tier="strong",
        context={"row": row},
    )
    result = llm.run(call, RowScope).model_dump()
    if result["vague"]:
        result["items"] = []
    with session_scope() as s:
        if s.get(ScopeCache, key) is None:
            s.add(ScopeCache(content_hash=key, result=result))
    return result


def _scope_rows(batch_id: int, todo: list[tuple[int, dict[str, Any]]]) -> None:
    if not todo:
        return
    with session_scope() as s:
        today = clock.local_date(clock.now(s), get_settings().workspace_timezone).isoformat()
        batch = s.get(ImportBatch, batch_id)
        assert batch is not None
        lst = s.get(ImportList, batch.import_list_id)
        assert lst is not None
        titles = {r.external_id: effective(r).get("title", "") for r in batch.rows}
        for req in _list_requests(s, lst):
            for i in _request_ids(req):
                titles.setdefault(i, req.title)

    def work(item: tuple[int, dict[str, Any]]) -> tuple[int, dict[str, Any] | None, str | None]:
        rid, row = item
        try:
            return rid, _scope_one(row, today, titles), None
        except llm.LLMError as e:
            return rid, None, str(e)

    workers = 1 if get_settings().llm_provider == "fake" else 6
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(work, todo))
    with session_scope() as s:
        for rid, scope, err in results:
            row = s.get(ImportRow, rid)
            if row is None:
                continue
            _apply_scope(row, scope, err)


def _apply_scope(row: ImportRow, scope: dict[str, Any] | None, err: str | None) -> None:
    if scope is None:
        row.scope = {}
        _set_flag(row, _flag("scope_failed", f"The agent couldn't draft a checklist for this row ({err}). Edit the items by hand or retry."))
        return
    _drop_flag(row, "scope_failed")
    row.scope = scope
    if scope.get("vague") or not scope.get("items"):
        _set_flag(row, _flag("vague", f"Too vague to send: {scope.get('vague_reason') or 'no clear deliverable'}. Rewrite the instructions or add checklist items."))
    else:
        _drop_flag(row, "vague")


@jobs.handler("import_rescope_row")
def rescope_job(payload: dict) -> None:
    with session_scope() as s:
        row = s.get(ImportRow, payload["row_id"])
        if row is None:
            return
        batch = s.get(ImportBatch, row.batch_id)
        if batch is None or batch.status != "review":
            return
        e = effective(row)
        todo = [(row.id, {"request_id": e["request_id"], "title": e["title"], "instructions": e["instructions"], "due_date": e["due_date"], "depends_on": e.get("depends_on") or []})]
        bid, ws = batch.id, s.get(ImportList, batch.import_list_id).workspace_id  # type: ignore[union-attr]
    _scope_rows(bid, todo)
    with session_scope() as s:
        audit.emit(s, ws, "import", None, {"batch_id": bid})


# --------------------------------------------------------------------------- review edits


def edit_row(s: Session, user: User, batch: ImportBatch, row: ImportRow, changes: dict[str, Any]) -> None:
    if batch.status != "review":
        raise ImportError_("this import is no longer in review")
    today = clock.local_date(clock.now(s), get_settings().workspace_timezone)
    edits = dict(row.raw.get("_edits") or {})
    rescope = False
    if "include" in changes:
        row.include = bool(changes["include"])
    if "ownership_mode" in changes:
        if changes["ownership_mode"] not in ("any", "all"):
            raise ImportError_("ownership_mode must be 'any' or 'all'")
        row.ownership_mode = changes["ownership_mode"]
    if changes.get("due_date"):
        try:
            edits["due_date"] = date.fromisoformat(changes["due_date"]).isoformat()
        except ValueError as e:
            raise ImportError_("due_date must be YYYY-MM-DD") from e
    if changes.get("instructions"):
        edits["instructions"] = _norm(changes["instructions"])
        rescope = True
    if "items" in changes:
        try:
            items = [DraftItem.model_validate(i).model_dump() for i in changes["items"]]
        except Exception as e:  # noqa: BLE001
            raise ImportError_(f"invalid items: {e}") from e
        row.scope = {**(row.scope or {}), "items": items, "vague": not items, "vague_reason": None if items else "no items", "edited": True}
        _apply_scope(row, row.scope, None)
    if "merge_into" in changes:
        target = (changes["merge_into"] or "").upper()
        if target:
            if target == row.external_id or not any(r.external_id == target and r.action in ("new", "changed", "unchanged") for r in batch.rows):
                raise ImportError_(f"can't merge into {target}")
            if row.action not in ("new",):
                raise ImportError_("only a new row can be merged into another")
            row.action, row.merged_into = "duplicate", target
            _drop_flag(row, "near_duplicate")
            _set_flag(row, _flag("duplicate", f"Merged into {target} by {user.name}."))
        elif row.action == "duplicate" and row.merged_into:
            row.action, row.merged_into = "new", None
            _drop_flag(row, "duplicate")
            rescope = rescope or not row.scope
    row.raw = {**row.raw, "_edits": edits}
    if row.action in ("new", "changed"):
        _row_flags(row, effective(row), today)
    s.flush()
    audit.log(s, actor="requester", actor_detail=user.email, action="import_row_edited", workspace_id=user.workspace_id, batch=batch.id, row=row.external_id, changes=sorted(changes))
    if rescope and row.action in ("new", "changed"):
        jobs.enqueue(s, "import_rescope_row", f"rescope:{row.id}:{hashlib.sha256(json.dumps(edits, sort_keys=True).encode()).hexdigest()[:12]}", {"row_id": row.id})


# --------------------------------------------------------------------------- apply


def _new_version(s: Session, req: Request, row: ImportRow, user: User, *, confirmed: bool, previous=None) -> ChecklistVersion:
    e = effective(row)
    first = e["owners"][0]
    now = clock.now(s)
    from .scoping import items_from_drafts

    v = ChecklistVersion(
        request_id=req.id,
        number=next_version_number(s, req),
        status="confirmed" if confirmed else "proposed",
        provider_email=first["email"],
        provider_name=first["name"],
        due_date=date.fromisoformat(e["due_date"]) if e["due_date"] else None,
        notes=list((row.scope or {}).get("assumptions") or []),
        created_by="import",
        created_at=now,
        confirmed_at=now if confirmed else None,
        confirmed_by=user.id if confirmed else None,
    )
    v.items = items_from_drafts([DraftItem.model_validate(i) for i in (row.scope or {}).get("items") or []], previous)
    s.add(v)
    s.flush()
    return v


def _sync_owners(s: Session, req: Request, owners: list[dict[str, Any]], sent: bool) -> list[str]:
    """Add new owners. Dropped owners are removed before sending; afterwards they're flagged."""
    notes = []
    wanted = {o["email"]: o for o in owners}
    have = {o.provider.email: o for o in req.owners}
    for email, o in wanted.items():
        if email not in have:
            p = get_or_create_provider(s, req.workspace_id, email, o.get("name"))
            req.owners.append(RequestOwner(provider_id=p.id))
            notes.append(f"added owner {email}")
    for email, ro in have.items():
        if email not in wanted:
            if sent:
                add_flag(req, "owner_removed", f"{email} is no longer listed as an owner in the import. They still have the request; follow up or cancel manually.")
            else:
                req.owners.remove(ro)
            notes.append(f"removed owner {email}")
    s.flush()
    return notes


def apply(s: Session, user: User, batch: ImportBatch) -> dict[str, Any]:
    if batch.status != "review":
        raise ImportError_(f"this import is {batch.status}")
    blocking = [r.external_id for r in batch.rows if r.include and r.action == "error"]
    if blocking:
        raise ImportError_(f"resolve or exclude the rows with errors first: {', '.join(blocking)}")
    lst = s.get(ImportList, batch.import_list_id)
    assert lst is not None
    now = clock.now(s)
    tz = get_settings().workspace_timezone
    today = clock.local_date(now, tz)
    by_ext: dict[str, Request] = {}
    for r in _list_requests(s, lst):
        for i in _request_ids(r):
            by_ext[i] = r
    created, updated, blocked, flagged = [], [], [], []
    change_lines: dict[int, list[str]] = {}
    touched: list[tuple[Request, ImportRow]] = []

    for row in batch.rows:
        if not row.include or row.action in ("unchanged", "error", "duplicate"):
            continue
        e = effective(row)
        if row.action == "removed":
            req = s.get(Request, row.request_id) if row.request_id else None
            already = req is not None and any(f.get("code") == "removed_from_list" for f in req.flags or [])
            if req is not None and req.state not in states.TERMINAL and not already:
                add_flag(req, "removed_from_list", f"Not in the import '{batch.filename}' ({today}). Still open; cancel it if it's no longer needed.")
                add_comment(s, req, author="system", kind="note", body=f"This item wasn't in the latest import of '{lst.name}'. It stays open until you cancel it.")
                flagged.append(req.id)
            continue
        is_blocked = any(f.get("blocking") for f in row.flags or [])
        if row.action == "new":
            req = Request(
                workspace_id=user.workspace_id,
                requester_id=user.id,
                title=e["title"][:300],
                state=states.SCOPING,
                origin="import",
                import_list_id=lst.id,
                external_id=row.external_id,
                aliases=[],
                instructions=e["instructions"],
                due_date=date.fromisoformat(e["due_date"]) if e["due_date"] else None,
                backup_email=e["backup_email"],
                ownership_mode=row.ownership_mode,
                flags=[],
                created_at=now,
                updated_at=now,
            )
            s.add(req)
            s.flush()
            for o in e["owners"]:
                p = get_or_create_provider(s, req.workspace_id, o["email"], o.get("name"))
                req.owners.append(RequestOwner(provider_id=p.id))
            for f in row.flags or []:
                if f["code"] in ("past_due", "no_backup", "shared"):
                    add_flag(req, f["code"], f["message"])
            add_comment(s, req, author="requester", user_id=user.id, body=f"{row.external_id} {e['title']}: {e['instructions']}", payload={"import_batch_id": batch.id})
            row.request_id = req.id
            by_ext[row.external_id] = req
            if is_blocked:
                v = _new_version(s, req, row, user, confirmed=False)
                add_flag(req, "vague", "Too vague to send. Clarify what's needed, then confirm the checklist.")
                add_comment(s, req, author="agent", kind="scope_proposal", body=(row.scope or {}).get("vague_reason") or "This row is too vague to send as is. What exactly do you need?", payload={"version_id": v.id, "questions": ["What exactly should the provider send?"], "assumptions": [], "ready": False})
                states.transition(s, req, states.WAITING_REQUESTER, actor="agent", reason="import row too vague")
                blocked.append(req.id)
            else:
                v = _new_version(s, req, row, user, confirmed=True)
                req.current_version_id = v.id
                add_comment(s, req, author="requester", user_id=user.id, kind="checklist_confirmed", body=f"Confirmed checklist v{v.number} at import review.", payload={"version_id": v.id})
                states.transition(s, req, states.READY_TO_SEND, actor="requester", reason="import applied", actor_detail=user.email)
                created.append(req.id)
            audit.log(s, actor="requester", actor_detail=user.email, action="import_row_created", workspace_id=req.workspace_id, request_id=req.id, row=row.external_id, blocked=is_blocked)
            touched.append((req, row))
        elif row.action == "changed":
            req = s.get(Request, row.request_id) if row.request_id else None
            if req is None or req.state in states.TERMINAL:
                continue
            sent = req.state in states.OPEN_WITH_PROVIDER
            lines: list[str] = []
            fields = {c["field"] for c in row.changes}
            if "due_date" in fields or "due_date" in (row.raw.get("_edits") or {}):
                new_due = date.fromisoformat(e["due_date"]) if e["due_date"] else None
                if new_due != req.due_date:
                    old = req.due_date
                    req.due_date = new_due
                    from .actions import reset_due_tracking

                    reset_due_tracking(s, req)
                    lines.append(f"New due date: {new_due:%b %-d, %Y}" + (f" (was {old:%b %-d, %Y})" if old else ""))
            if "backup_email" in fields:
                req.backup_email = e["backup_email"]
            if "owners" in fields:
                _sync_owners(s, req, e["owners"], sent)
            req.ownership_mode = row.ownership_mode
            if _scope_changed(row.changes):
                req.title = e["title"][:300]
                req.instructions = e["instructions"]
                if is_blocked:
                    add_flag(req, "vague", "The re-imported instructions are too vague; the previous checklist still applies.")
                else:
                    cur = current_version(s, req)
                    if cur is not None:
                        cur.status = "superseded"
                    v = _new_version(s, req, row, user, confirmed=True, previous=cur.items if cur else None)
                    req.current_version_id = v.id
                    add_comment(s, req, author="requester", user_id=user.id, kind="checklist_confirmed", body=f"Confirmed checklist v{v.number} from the re-import.", payload={"version_id": v.id})
                    lines.append(f"The request now reads: \"{e['instructions']}\"")
                    lines += [f"   {i + 1}. {it.description}" for i, it in enumerate(v.items)]
                    if sent:
                        from .checking import enqueue_check

                        enqueue_check(s, req, trigger=f"re-import v{v.number}", substantive=False)
            req.updated_at = now
            add_comment(s, req, author="system", kind="note", body="Updated from re-import: " + ", ".join(sorted(fields)) + ".")
            audit.log(s, actor="requester", actor_detail=user.email, action="import_row_updated", workspace_id=req.workspace_id, request_id=req.id, row=row.external_id, changes=row.changes)
            if sent and lines:
                change_lines[req.id] = lines
            updated.append(req.id)
            touched.append((req, row))

    # merged duplicates keep their ids as aliases
    for row in batch.rows:
        if row.include and row.action == "duplicate" and row.merged_into and row.merged_into != row.external_id:
            target = by_ext.get(row.merged_into)
            if target is not None and row.external_id not in (target.aliases or []):
                target.aliases = [*(target.aliases or []), row.external_id]
                row.request_id = target.id
                audit.log(s, actor="requester", actor_detail=user.email, action="import_row_merged", workspace_id=target.workspace_id, request_id=target.id, alias=row.external_id)

    # dependencies, resolved against the whole list
    for req, row in touched:
        want = {by_ext[d].id for d in effective(row).get("depends_on") or [] if d in by_ext and by_ext[d].id != req.id}
        have = {d.depends_on_id: d for d in s.scalars(select(RequestDependency).where(RequestDependency.request_id == req.id))}
        for dep in want - set(have):
            s.add(RequestDependency(request_id=req.id, depends_on_id=dep))
        for dep in set(have) - want:
            s.delete(have[dep])
    s.flush()

    if change_lines:
        from .followups import queue_change_notices

        queue_change_notices(s, change_lines, key=f"import:{batch.id}:changes")

    drafts = draft_batch_emails(s, user, batch)
    batch.status = "applied"
    batch.applied_at = now
    result = {"created": created, "updated": updated, "blocked": blocked, "flagged_removed": flagged, "drafts": [m.id for m in drafts], "change_notices": len(change_lines)}
    audit.log(s, actor="requester", actor_detail=user.email, action="import_applied", workspace_id=user.workspace_id, batch=batch.id, list=lst.name, **result)
    audit.emit(s, user.workspace_id, "import", None, {"batch_id": batch.id, "status": batch.status})
    return result


# --------------------------------------------------------------------------- batch emails


def _already_contacted(s: Session, provider: Provider, req: Request) -> bool:
    """Has this provider been sent (or is about to be sent) an email naming this request?"""
    msgs = s.scalars(
        select(OutboundMessage)
        .join(Conversation, Conversation.id == OutboundMessage.conversation_id)
        .join(ConversationRequest, ConversationRequest.conversation_id == Conversation.id)
        .where(Conversation.provider_id == provider.id, ConversationRequest.request_id == req.id, OutboundMessage.kind == "initial", OutboundMessage.status.in_(["queued", "sending", "sent", "uncertain"]))
    ).first()
    return msgs is not None


def _block_extra(s: Session, req: Request, provider: Provider) -> str | None:
    notes = []
    others = [o.provider for o in req.owners if o.provider_id != provider.id]
    if others:
        who = ", ".join(p.name or p.email for p in others)
        notes.append(f"shared with {who}: " + ("each of you needs to send your part" if req.ownership_mode == "all" else "either of you can send it"))
    from .common import dependencies

    deps = dependencies(s, req)
    if deps:
        notes.append("relates to " + "; ".join(request_label(d) for d in deps))
    return "; ".join(notes) or None


def draft_batch_emails(s: Session, user: User, batch: ImportBatch) -> list[OutboundMessage]:
    """One initial draft per provider covering every list request they haven't been sent yet."""
    lst = s.get(ImportList, batch.import_list_id)
    assert lst is not None
    per_provider: dict[int, list[Request]] = defaultdict(list)
    for req in _list_requests(s, lst):
        if req.state not in (states.READY_TO_SEND, *states.OPEN_WITH_PROVIDER) or req.current_version_id is None:
            continue
        for o in req.owners:
            if o.closed_at is None and not _already_contacted(s, o.provider, req):
                per_provider[o.provider_id].append(req)
    out = []
    for pid, reqs in sorted(per_provider.items()):
        provider = s.get(Provider, pid)
        assert provider is not None
        reqs.sort(key=lambda r: (r.due_date or date.max, r.external_id or ""))
        rids = {r.id for r in reqs}
        # an earlier unsent draft for this provider covering these requests is replaced
        for old in s.scalars(
            select(OutboundMessage)
            .join(Conversation, Conversation.id == OutboundMessage.conversation_id)
            .where(Conversation.provider_id == pid, OutboundMessage.kind == "initial", OutboundMessage.status == "draft")
        ):
            if set(old.request_ids or []) & rids:
                old.status = "cancelled"
                audit.log(s, actor="system", action="email_draft_replaced", workspace_id=old.workspace_id, message=old.id)
        import secrets

        conv = Conversation(workspace_id=provider.workspace_id, provider_id=pid, reply_token=secrets.token_urlsafe(12), subject=f"{lst.name}: " + emails.batch_subject(user, len(reqs)), created_at=clock.now(s))
        s.add(conv)
        s.flush()
        for r in reqs:
            conv.links.append(ConversationRequest(request_id=r.id, version_id=r.current_version_id))
        blocks = [emails.request_block(r, list(current_version(s, r).items), _block_extra(s, r, provider)) for r in reqs]  # type: ignore[union-attr]
        msg = outbox.queue_message(
            s,
            workspace_id=provider.workspace_id,
            kind="initial",
            idempotency_key=f"import:{batch.id}:p{pid}",
            to=[provider.email],
            subject=conv.subject,
            text=emails.initial_batch(blocks, user, provider.name, provider.email, hub.hub_url(hub.issue_token(s, provider))),
            from_name=emails.from_name(user),
            reply_to=outbox.reply_address(conv.reply_token),
            conversation=conv,
            request_id=reqs[0].id if len(reqs) == 1 else None,
            request_ids=[r.id for r in reqs],
            draft=True,
        )
        if msg is not None:
            out.append(msg)
    return out


def batch_drafts(s: Session, batch: ImportBatch) -> list[OutboundMessage]:
    return list(s.scalars(select(OutboundMessage).where(OutboundMessage.idempotency_key.like(f"import:{batch.id}:p%")).order_by(OutboundMessage.id)))


def send_all(s: Session, user: User, batch: ImportBatch, message_ids: list[int] | None = None) -> int:
    if batch.status != "applied":
        raise ImportError_("apply the import first")
    n = 0
    for msg in batch_drafts(s, batch):
        if msg.status != "draft" or (message_ids and msg.id not in message_ids):
            continue
        outbox.release(s, msg, actor_detail=user.email)
        n += 1
        for rid in msg.request_ids or []:
            req = s.get(Request, rid)
            if req is not None and req.state == states.READY_TO_SEND:
                states.transition(s, req, states.WAITING_PROVIDER, actor="requester", reason="import batch sent", actor_detail=user.email)
    audit.log(s, actor="requester", actor_detail=user.email, action="import_sent", workspace_id=user.workspace_id, batch=batch.id, messages=n)
    return n


# --------------------------------------------------------------------------- views


def summary(batch: ImportBatch) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for r in batch.rows:
        out[r.action] += 1
        if any(f.get("blocking") for f in r.flags or []) and r.action in ("new", "changed"):
            out["blocked"] += 1
    return dict(out)


def row_view(r: ImportRow) -> dict[str, Any]:
    e = effective(r)
    return {
        "id": r.id,
        "position": r.position,
        "external_id": r.external_id,
        "action": r.action,
        "merged_into": r.merged_into,
        "title": e.get("title"),
        "instructions": e.get("instructions"),
        "due_date": e.get("due_date"),
        "owners": e.get("owners") or [],
        "backup_email": e.get("backup_email"),
        "depends_on": e.get("depends_on") or [],
        "edits": r.raw.get("_edits") or {},
        "changes": r.changes,
        "flags": r.flags,
        "scope": r.scope,
        "ownership_mode": r.ownership_mode,
        "request_id": r.request_id,
        "include": r.include,
        "blocked": any(f.get("blocking") for f in r.flags or []),
    }


def batch_view(s: Session, batch: ImportBatch) -> dict[str, Any]:
    from ..api.serialize import iso, outbound

    lst = s.get(ImportList, batch.import_list_id)
    return {
        "id": batch.id,
        "list": {"id": lst.id, "name": lst.name} if lst else None,
        "filename": batch.filename,
        "status": batch.status,
        "errors": batch.errors,
        "created_at": iso(batch.created_at),
        "applied_at": iso(batch.applied_at),
        "summary": summary(batch),
        "rows": [row_view(r) for r in batch.rows],
        "drafts": [outbound(m) for m in batch_drafts(s, batch)],
    }
