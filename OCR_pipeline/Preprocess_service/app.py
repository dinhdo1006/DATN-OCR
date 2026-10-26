from fastapi import FastAPI, UploadFile, File, HTTPException # Thêm HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from fastapi.concurrency import run_in_threadpool
import os, shutil, zipfile, uuid
from pathlib import Path
from pdf2image.exceptions import PDFPageCountError, PDFSyntaxError
from preprocess import process_scan_pdf

app = FastAPI()

UPLOAD_DIR = "/data/input"
OUTPUT_DIR = "/data/output"

@app.post("/process")
async def process(file: UploadFile = File(...)):

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF allowed")

    safe_name = Path(file.filename).name
    if not safe_name.isascii():
        # Mã tài liệu trả về trong header X-Document-Id, header HTTP không chứa được ký tự có dấu
        raise HTTPException(status_code=422, detail="Tên tệp phải không dấu (chỉ chữ cái, chữ số, _ . -)")
    unique_name = f"{uuid.uuid4()}_{safe_name}"
    pdf_path = os.path.join(UPLOAD_DIR, unique_name)

    with open(pdf_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    await file.close()

    # Mỗi yêu cầu một thư mục ảnh riêng: hai yêu cầu đồng thời không ghi đè page_N.png của nhau
    work_dir = os.path.join(OUTPUT_DIR, unique_name)
    os.makedirs(work_dir, exist_ok=True)

    def cleanup():
        shutil.rmtree(work_dir, ignore_errors=True)
        try:
            os.remove(pdf_path)
        except OSError:
            pass

    try:
        images = await run_in_threadpool(process_scan_pdf, pdf_path, work_dir)
    except (PDFPageCountError, PDFSyntaxError) as e:
        # PDF hỏng / có mật khẩu: lỗi của dữ liệu đầu vào (4xx) để NiFi không thử lại vô ích
        reason = (str(e).strip().splitlines() or [""])[0][:150]
        cleanup()
        raise HTTPException(status_code=422, detail=f"Không đọc được PDF (tệp hỏng hoặc có mật khẩu): {reason}")
    except Exception as e:
        cleanup()
        raise HTTPException(status_code=500, detail=str(e))

    if not images:
        cleanup()
        raise HTTPException(status_code=422, detail="PDF không có trang nào")

    try:
        total_pages = len(images)  # 🔥 QUAN TRỌNG

        zip_path = os.path.join(work_dir, f"{unique_name}.zip")

        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for img_path in images:
                zipf.write(img_path, os.path.basename(img_path))

        # 🔥 TRẢ HEADER
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=os.path.basename(zip_path),
            headers={
                "X-Total-Pages": str(total_pages),
                "X-Document-Id": safe_name.replace(".pdf", "")
            },
            # Xóa ảnh tạm và PDF sau khi đã gửi xong ZIP
            background=BackgroundTask(cleanup)
        )

    except Exception as e:
        cleanup()
        raise HTTPException(status_code=500, detail=str(e))