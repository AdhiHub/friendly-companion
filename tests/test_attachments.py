"""Attachment safety: sniffing, size limits, path traversal, storage."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from app.services.attachment_service import AttachmentError, AttachmentService, sniff_mime


def upload(client: TestClient, name: str, data: bytes, content_type: str):
    return client.post(
        "/api/attachments",
        files={"file": (name, data, content_type)},
    )


def test_sniff_detects_real_types():
    assert sniff_mime(b"\xff\xd8\xff\xe0rest", "application/octet-stream") == "image/jpeg"
    assert sniff_mime(b"\x89PNG\r\n\x1a\nrest", "text/plain") == "image/png"
    assert sniff_mime(b"RIFF\x00\x00\x00\x00WEBP", "") == "image/webp"
    assert sniff_mime(b"%PDF-1.7 rest", "application/x-pdf") == "application/pdf"
    assert sniff_mime("hello world".encode(), "text/plain") == "text/plain"


def test_sniff_rejects_mismatched_or_binary_content():
    # Declared text but contains NUL bytes → binary, not text.
    assert sniff_mime(b"abc\x00def", "text/plain") is None
    # Declared image but wrong magic bytes.
    assert sniff_mime(b"not really an image", "image/jpeg") is None
    # Unknown binary.
    assert sniff_mime(b"\x00\x01\x02\x03", "application/octet-stream") is None


def test_upload_png_and_pdf(client: TestClient, png_bytes, pdf_bytes):
    png = upload(client, "photo.png", png_bytes, "image/png")
    assert png.status_code == 201
    info = png.json()
    assert info["mime"] == "image/jpeg" or info["mime"] == "image/png"
    assert info["filename"] == "photo.png"
    assert info["size"] == len(png_bytes)

    pdf = upload(client, "notes.pdf", pdf_bytes, "application/pdf")
    assert pdf.status_code == 201
    assert pdf.json()["mime"] == "application/pdf"


def test_upload_rejects_unsupported_type(client: TestClient):
    response = upload(client, "virus.exe", b"MZ\x90\x00", "application/x-msdownload")
    assert response.status_code == 400
    assert "Supported" in response.json()["detail"] or "Unsupported" in response.json()["detail"]


def test_upload_rejects_extension_spoofing(client: TestClient):
    # .png name, but content is an executable → sniffing wins over the extension.
    response = upload(client, "totally-an-image.png", b"MZ\x90\x00\x03", "image/png")
    assert response.status_code == 400


def test_upload_rejects_oversized_file(config: AppConfig, png_bytes):
    small = AppConfig(
        api_key="k",
        max_upload_mb=1,
        data_dir=config.data_dir,
        uploads_dir=config.uploads_dir,
    )
    app = create_app(small)
    with TestClient(app) as client:
        big = b"\x89PNG\r\n\x1a\n" + b"0" * (2 * 1024 * 1024)
        response = upload(client, "big.png", big, "image/png")
        assert response.status_code == 413
        _ = png_bytes


def test_upload_rejects_empty_file(client: TestClient):
    assert upload(client, "empty.txt", b"", "text/plain").status_code == 400


def test_download_and_delete_roundtrip(client: TestClient, png_bytes):
    info = upload(client, "pic.png", png_bytes, "image/png").json()
    fetched = client.get(f"/api/attachments/{info['id']}")
    assert fetched.status_code == 200
    assert fetched.content == png_bytes

    assert client.delete(f"/api/attachments/{info['id']}").status_code == 204
    assert client.get(f"/api/attachments/{info['id']}").status_code == 404
    assert client.delete(f"/api/attachments/{info['id']}").status_code == 404


def test_unknown_attachment_404(client: TestClient):
    assert client.get("/api/attachments/a_does_not_exist").status_code == 404


def test_resolve_blocks_path_traversal(config: AppConfig):
    service = AttachmentService(config)
    outside = config.data_dir.parent / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    for attempt in ("../secret.txt", "..%2Fsecret.txt", "/etc/passwd", "a/b.txt"):
        try:
            service.resolve(attempt)
        except AttachmentError as err:
            assert err.status in (400, 404)
        else:
            raise AssertionError(f"traversal accepted: {attempt}")
    assert outside.exists()


def test_stored_files_use_generated_names(client: TestClient, png_bytes):
    info = upload(client, "../../../evil.png", png_bytes, "image/png").json()
    assert info["filename"] == "evil.png"  # display name sanitised
    uploads = list(Path(client.app.state.config.uploads_dir).glob("*"))
    assert all(part.name.startswith("a_") for part in uploads)


def test_attachment_flows_into_chat(client: TestClient, fake_gemini, png_bytes, read_sse):
    info = upload(client, "scene.png", png_bytes, "image/png").json()
    with client.stream(
        "POST",
        "/api/chat",
        json={"message": "what is in this image?", "attachment_ids": [info["id"]]},
    ) as response:
        events = read_sse("".join(response.iter_text()))
    assert [n for n, _ in events][-1] == "done"

    detail = client.get(f"/api/conversations/{[d for n, d in events if n == 'meta'][0]['conversation_id']}")
    messages = detail.json()["messages"]
    assert messages[0]["attachments"][0]["filename"] == "scene.png"

    # Model received the actual bytes inline.
    parts = fake_gemini.calls[0]["contents"][-1]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/png"
    assert parts[-1]["text"] == "what is in this image?"


def test_missing_attachment_id_fails_gracefully(client: TestClient):
    response = client.post("/api/chat", json={"message": "hi", "attachment_ids": ["a_ghost"]})
    assert response.status_code == 404
    assert "attachment" in response.json()["detail"].lower()
