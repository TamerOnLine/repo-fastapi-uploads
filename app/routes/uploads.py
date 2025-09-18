from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from app.core.config import get_settings
from app.utils.storage import LocalStorage

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/pdf")
async def upload_pdf(file: UploadFile = File(...)):
    # تحقق من نوع المحتوى اختياريًا (soft check)
    if file.content_type not in {"application/pdf", "application/x-pdf", "application/acrobat"}:
        # سنعتمد الفحص الحقيقي على ترويسة %PDF- داخل التخزين
        pass

    settings = get_settings()  # يوفّر UPLOAD_DIR و UPLOAD_MAX_MB وغيرها 
    storage = LocalStorage(
        base_dir=settings.UPLOAD_DIR,
        subdir="pdf",
        max_mb=settings.UPLOAD_MAX_MB,
    )
    try:
        saved = await storage.save_pdf(file)
        return {"ok": True, **saved}
    except HTTPException as e:
        # نعيد كود وخطأ واضح
        raise e
