"""Decide what a file really is from its bytes, and reject what we won't process.

The extension and declared content type are hints only. Office containers are opened and
inspected: macro-enabled files are rejected, and zip expansion is bounded.
"""

from __future__ import annotations

import io
import re
import zipfile

ALLOWED = {"pdf", "xlsx", "xls", "csv", "png", "jpeg", "heic", "docx", "eml"}

MAX_ZIP_ENTRIES = 5000
MAX_ZIP_UNCOMPRESSED = 300 * 1024 * 1024
MAX_ZIP_RATIO = 250


class Rejected(Exception):
    pass


def _check_zip(data: bytes) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise Rejected("corrupt Office/zip container") from e
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise Rejected("archive has too many entries")
    total = sum(i.file_size for i in infos)
    if total > MAX_ZIP_UNCOMPRESSED or (len(data) and total / max(len(data), 1) > MAX_ZIP_RATIO):
        raise Rejected("archive expands too much (possible zip bomb)")
    names = {i.filename for i in infos}
    lowered = {n.lower() for n in names}
    if any(n.endswith("vbaproject.bin") or "/vba" in n for n in lowered):
        raise Rejected("macro-enabled Office files are not accepted")
    if "[Content_Types].xml" in names:
        ct = zf.read("[Content_Types].xml")[:200_000].decode("utf-8", "replace").lower()
        if "macroenabled" in ct or "vbaproject" in ct:
            raise Rejected("macro-enabled Office files are not accepted")
    if "xl/workbook.xml" in names:
        return "xlsx"
    if "word/document.xml" in names:
        return "docx"
    raise Rejected("zip archives other than .xlsx/.docx are not accepted")


def _check_ole(data: bytes) -> str:
    import olefile

    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        raise Rejected("corrupt legacy Office file") from e
    streams = ["/".join(p) for p in ole.listdir(streams=True, storages=True)]
    lowered = [s.lower() for s in streams]
    if any("_vba_project" in s or s.startswith("macros") or "/vba" in s or s == "vba" for s in lowered):
        raise Rejected("macro-enabled Office files are not accepted")
    if any(s in ("workbook", "book") for s in lowered):
        return "xls"
    if any(s == "encryptedpackage" for s in lowered):
        return "encrypted_office"
    raise Rejected("legacy Office documents other than .xls are not accepted")


_HEADER_LINE = re.compile(rb"^[A-Za-z][A-Za-z0-9-]*:[ \t]", re.M)


def detect(data: bytes, filename: str, declared: str | None) -> str:
    """Return one of ALLOWED (or 'encrypted_office'); raise Rejected otherwise."""
    if not data:
        raise Rejected("empty file")
    head = data[:2048]
    name = filename.lower()
    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc", b"heim", b"heis"):
        return "heic"
    if head.startswith(b"PK\x03\x04"):
        return _check_zip(data)
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return _check_ole(data)
    if head.startswith((b"GIF8", b"MZ", b"\x7fELF")):
        raise Rejected("file type not accepted")
    is_texty = b"\x00" not in head
    if is_texty and (name.endswith(".eml") or (declared or "").lower() == "message/rfc822"):
        if len(_HEADER_LINE.findall(head)) >= 2:
            return "eml"
    if is_texty and (name.endswith(".csv") or (declared or "").lower() in ("text/csv", "application/csv")):
        try:
            data[:200_000].decode("utf-8")
        except UnicodeDecodeError:
            data[:200_000].decode("latin-1")
        return "csv"
    raise Rejected("file type not accepted (allowed: PDF, XLSX, XLS, CSV, PNG, JPG, HEIC, DOCX, EML)")
