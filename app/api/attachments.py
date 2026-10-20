"""Attachment upload, download and removal endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.models.schemas import AttachmentInfo
from app.services.attachment_service import AttachmentError

logger = logging.getLogger("gethu.api.attachments")

router = APIRouter(prefix="/api/attachments", tags=["attachments"])


def _service(request: Request):
    return request.app.state.attachment_service


def _repo(request: Request):
    return request.app.state.repo


@router.post("", response_model=AttachmentInfo, status_code=201)
async def upload_attachment(request: Request, file: UploadFile = File(...)) -> AttachmentInfo:
    service = _service(request)
    # Read one byte past the limit so oversized files fail fast without loading
    # an unbounded amount of data into memory.
    limit = service.config.max_upload_bytes
    data = await file.read(limit + 1)
    try:
        stored = service.save(file.filename or "file", file.content_type or "", data)
    except AttachmentError as err:
        raise HTTPException(status_code=err.status, detail=err.message) from err

    _repo(request).add_attachment_record(
        attachment_id=stored.info.id,
        conversation_id=None,
        filename=stored.info.filename,
        stored_name=stored.stored_name,
        mime=stored.info.mime,
        size=stored.info.size,
    )
    logger.info(
        "Stored attachment %s (%s, %d bytes)", stored.info.id, stored.info.mime, stored.info.size
    )
    return stored.info


@router.get("/{attachment_id}")
async def download_attachment(attachment_id: str, request: Request) -> FileResponse:
    service = _service(request)
    record = _repo(request).get_attachment_record(attachment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    try:
        path = service.resolve(record["stored_name"])
    except AttachmentError as err:
        raise HTTPException(status_code=err.status, detail=err.message) from err
    return FileResponse(path, media_type=record["mime"], filename=record["filename"])


@router.delete("/{attachment_id}", status_code=204)
async def delete_attachment(attachment_id: str, request: Request) -> None:
    service = _service(request)
    record = _repo(request).get_attachment_record(attachment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    service.delete(record["stored_name"])
    _repo(request).delete_attachment_record(attachment_id)
