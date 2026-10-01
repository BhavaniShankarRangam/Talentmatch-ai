"""Upload validation: extension allow-list, size limits, magic-byte checks and zip-bomb guards."""
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

ALLOWED_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_MAX_DOCX_UNCOMPRESSED = 60 * 1024 * 1024
_MAX_DOCX_ENTRIES = 3000


class UploadRejected(ValueError):
    pass


@dataclass
class ValidatedFile:
    filename: str
    ext: str
    content_type: str


def sanitize_filename(name: str) -> str:
    base = PurePath(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    return (base or "document")[:150]


def validate_upload(filename: str, data: bytes, max_bytes: int) -> ValidatedFile:
    clean = sanitize_filename(filename or "")
    ext = PurePath(clean).suffix.lower()
    if ext not in ALLOWED_TYPES:
        raise UploadRejected(f"Unsupported file type '{ext or 'none'}'. Upload PDF or DOCX.")
    if len(data) == 0:
        raise UploadRejected("File is empty.")
    if len(data) > max_bytes:
        raise UploadRejected(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    if ext == ".pdf" and not data.startswith(b"%PDF-"):
        raise UploadRejected("File content is not a PDF (missing %PDF header).")
    if ext == ".docx":
        if not data.startswith(b"PK\x03\x04"):
            raise UploadRejected("File content is not a DOCX document.")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                infos = zf.infolist()
                if len(infos) > _MAX_DOCX_ENTRIES:
                    raise UploadRejected("DOCX archive has too many entries.")
                if sum(i.file_size for i in infos) > _MAX_DOCX_UNCOMPRESSED:
                    raise UploadRejected("DOCX archive expands beyond the allowed size.")
                if "word/document.xml" not in zf.namelist():
                    raise UploadRejected("DOCX archive has no document body.")
        except zipfile.BadZipFile:
            raise UploadRejected("DOCX archive is corrupt.")
    return ValidatedFile(filename=clean, ext=ext, content_type=ALLOWED_TYPES[ext])
