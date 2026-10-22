"""Upload validation and safe storage for images and documents.

Files are sniffed by content (not just extension), renamed to generated ids,
kept inside one configured directory, and never executed or served by raw path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import AppConfig
from app.models.schemas import AttachmentInfo
from app.utils.validation import new_id, safe_filename

logger = logging.getLogger("companion.attachments")

IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
DOCUMENT_TYPES = {"application/pdf": ".pdf", "text/plain": ".txt"}

GEMINI_MIME_TYPES = set(IMAGE_TYPES) | set(DOCUMENT_TYPES)


class AttachmentError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class StoredAttachment:
    info: AttachmentInfo
    stored_name: str
    path: Path


def sniff_mime(header: bytes, declared: str) -> str | None:
    """Return the real mime type when the magic bytes look supported."""
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"%PDF-"):
        return "application/pdf"

    # Plain text: only accept it when it was declared text and decodes cleanly.
    if declared.startswith("text/") or declared in {"application/json", "text/markdown"}:
        sample = header[:4096]
        if b"\x00" in sample:
            return None
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return "text/plain"
    return None


class AttachmentService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.uploads_dir = config.uploads_dir
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    def save(self, filename: str, declared_mime: str, data: bytes) -> StoredAttachment:
        if not data:
            raise AttachmentError("That file is empty.")
        if len(data) > self.config.max_upload_bytes:
            raise AttachmentError(
                f"File is larger than the {self.config.max_upload_mb} MB limit.", status=413
            )

        mime = sniff_mime(data[:8192], declared_mime or "")
        if mime is None:
            supported = "JPEG, PNG, WebP images, PDF and plain text files."
            raise AttachmentError(f"Unsupported file type. Supported: {supported}")

        display = safe_filename(filename or "file")
        ext = IMAGE_TYPES.get(mime) or DOCUMENT_TYPES.get(mime) or ""
        att_id = new_id("a_")
        stored_name = f"{att_id}{ext}"
        target = (self.uploads_dir / stored_name).resolve()
        if self.uploads_dir.resolve() not in target.parents:
            raise AttachmentError("Invalid storage path.", status=500)

        target.write_bytes(data)
        info = AttachmentInfo(id=att_id, filename=display, mime=mime, size=len(data))
        return StoredAttachment(info=info, stored_name=stored_name, path=target)

    def resolve(self, stored_name: str) -> Path:
        """Map a stored filename to a path, rejecting traversal attempts."""
        clean = Path(stored_name).name
        if clean != stored_name or not stored_name:
            raise AttachmentError("Invalid attachment path.", status=400)
        path = (self.uploads_dir / clean).resolve()
        if self.uploads_dir.resolve() not in path.parents:
            raise AttachmentError("Invalid attachment path.", status=400)
        if not path.is_file():
            raise AttachmentError("Attachment file not found.", status=404)
        return path

    def load_bytes(self, stored_name: str, limit: int | None = None) -> bytes:
        path = self.resolve(stored_name)
        data = path.read_bytes()
        max_bytes = limit or self.config.max_upload_bytes
        if len(data) > max_bytes:
            raise AttachmentError("Attachment is too large to process.", status=413)
        return data

    def delete(self, stored_name: str) -> None:
        try:
            self.resolve(stored_name).unlink(missing_ok=True)
        except AttachmentError:
            return

    def gemini_part(self, mime: str, data: bytes) -> dict:
        """A google-genai inline_data part for this attachment."""
        if mime not in GEMINI_MIME_TYPES:
            raise AttachmentError(f"Cannot send {mime} to the model.")
        return {"inline_data": {"mime_type": mime, "data": data}}

    def cleanup_orphans(self, keep_names: set[str]) -> int:
        """Delete stored files that no database record references."""
        removed = 0
        for path in self.uploads_dir.glob("*"):
            if path.is_file() and path.name not in keep_names:
                try:
                    path.unlink()
                    removed += 1
                except OSError:  # pragma: no cover
                    logger.warning("Could not remove orphan %s", path.name)
        return removed
