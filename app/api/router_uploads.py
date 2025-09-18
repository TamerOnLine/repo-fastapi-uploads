# app/api/router_uploads.py
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.utils.storage import LocalStorage


router = APIRouter(prefix="/uploads", tags=["uploads"])


# ---------- Response Models ----------
class UploadResult(BaseModel):
    ok: bool = True
    rel_path: str = Field(..., description="Relative path under uploads/ (e.g., pdf/file.pdf)")
    size_bytes: int
    sha256: str | None = None
    mime: str | None = None


class FileItem(BaseModel):
    rel_path: str
    size_bytes: int


class ListResult(BaseModel):
    ok: bool = True
    files: list[FileItem] = []


# ---------- Helpers ----------
def _get_pdf_storage() -> LocalStorage:
    settings = get_settings()
    return LocalStorage(
        base_dir=settings.UPLOAD_DIR,
        subdir="pdf",
        max_mb=settings.UPLOAD_MAX_MB,
    )


# ---------- Endpoints ----------
@router.post(
    "/pdf",
    response_model=UploadResult,
    summary="Upload a PDF",
    description="Uploads a PDF into uploads/pdf/ with soft content-type check and size limits.",
    status_code=status.HTTP_201_CREATED,
)
async def upload_pdf(file: Annotated[UploadFile, File(...)]) -> UploadResult:
    # Soft check; real validation (magic header) should be handled in storage
    allowed_types = {"application/pdf", "application/x-pdf", "application/acrobat"}
    if file.content_type and file.content_type.lower() not in allowed_types:
        # Donâ€™t fail hard â€” some browsers send `application/octet-stream`
        pass

    storage = _get_pdf_storage()
    try:
        saved = await storage.save_pdf(file)  # Should return dict with rel_path/size_bytes/sha256/mime
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save PDF: {e}") from e

    return UploadResult(**saved)


@router.get(
    "/pdf",
    response_model=ListResult,
    summary="List uploaded PDFs",
)
def list_pdfs() -> ListResult:
    storage = _get_pdf_storage()
    files: list[FileItem] = []
    for rel_path, size in storage.iter_files():  # Expected to yield (rel_path, size_bytes)
        files.append(FileItem(rel_path=rel_path, size_bytes=size))
    return ListResult(files=files)


@router.get(
    "/pdf/{filename}",
    summary="Download a PDF by filename",
    responses={
        200: {"content": {"application/pdf": {}}},
        404: {"description": "File not found"},
    },
)
def get_pdf(filename: str):
    """
    Download a file from uploads/pdf/{filename}.
    Path traversal must be prevented by LocalStorage.resolve.
    """
    storage = _get_pdf_storage()
    try:
        abs_path: Path = storage.resolve(filename)  # Should sanitize input and keep path under base_dir/subdir
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not abs_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(abs_path),
        media_type="application/pdf",
        filename=abs_path.name,
    )
