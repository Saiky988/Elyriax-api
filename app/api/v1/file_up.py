import asyncio
import io
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import zipfile
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
import httpx

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = BASE_DIR / "data" / "file_database.json"

MODRINTH_USER_AGENT = "Sayraa-srx/mc-fixlag-autobuild/1.0.0 (sayraa.srx@gmail.com)"

def read_file_db() -> Dict[str, Any]:
    if not DB_FILE.exists():
        return {}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def write_file_db(data: Dict[str, Any]):
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def generate_file_id(length: int = 8) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-"
    return "".join(secrets.choice(chars) for _ in range(length))

def resolve_actual_file_path(file_info: Dict[str, Any]) -> Optional[Path]:
    filename = file_info.get("filename") or Path(file_info.get("path", "")).name
    # Check in uploads dir
    candidate = UPLOAD_DIR / filename
    if candidate.exists():
        return candidate
    # Check original path if exists
    orig = Path(file_info.get("path", ""))
    if orig.exists():
        return orig
    return None

@router.post("/v1/file/upload")
async def upload_file_endpoint(file: UploadFile = File(...)):
    if not file or not file.filename:
        return JSONResponse(status_code=400, content={"error": "Vui lòng chọn file để upload!"})

    try:
        dest_path = UPLOAD_DIR / file.filename
        content = await file.read()
        with open(dest_path, "wb") as f:
            f.write(content)

        file_id = generate_file_id(8)
        db = read_file_db()
        db[file_id] = {
            "originalName": file.filename,
            "filename": file.filename,
            "path": str(dest_path),
            "uploadedAt": datetime.now(timezone.utc).isoformat(),
        }
        write_file_db(db)

        download_link = f"https://sayraa.xyz/d/{file_id}"
        return {
            "success": True,
            "message": "Upload file thành công!",
            "fileId": file_id,
            "originalName": file.filename,
            "downloadUrl": download_link,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Đã xảy ra lỗi khi xử lý file: {e}"})

@router.get("/v1/file/download/{file_id}")
@router.get("/d/{file_id}")
async def download_file_endpoint(file_id: str):
    db = read_file_db()
    file_info = db.get(file_id)
    if not file_info:
        return HTMLResponse("<h1>File không tồn tại hoặc đã bị xóa!</h1>", status_code=404)

    actual_path = resolve_actual_file_path(file_info)
    if not actual_path or not actual_path.exists():
        return HTMLResponse("<h1>File vật lý không tìm thấy trên server!</h1>", status_code=404)

    return FileResponse(
        path=actual_path,
        filename=file_info.get("originalName", actual_path.name),
        media_type="application/octet-stream",
    )

@router.post("/v1/mc/auto-build")
async def mc_auto_build(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    version = body.get("version")
    loader = body.get("loader")
    mods = body.get("mods")

    if not version or not loader or not mods or not isinstance(mods, dict) or len(mods) == 0:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing or misformatted data fields (version, loader, mods{})."},
        )

    loader_capitalized = loader.capitalize()
    zip_file_name = f"[{version}] {loader_capitalized} - Sayraa.zip"
    zip_file_path = UPLOAD_DIR / zip_file_name

    valid_files = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for mod_name, mod_id in mods.items():
            try:
                res = await client.get(
                    f"https://api.modrinth.com/v2/project/{mod_id}/version",
                    headers={"User-Agent": MODRINTH_USER_AGENT},
                )
                versions = res.json()

                matched = None
                for v in versions:
                    if version in v.get("game_versions", []) and loader.lower() in [l.lower() for l in v.get("loaders", [])]:
                        if v.get("version_type") == "release":
                            matched = v
                            break
                        if matched is None:
                            matched = v

                if matched and matched.get("files"):
                    files = matched["files"]
                    primary = next((f for f in files if f.get("primary")), files[0])
                    valid_files.append({"name": mod_name, "filename": primary["filename"], "url": primary["url"]})
            except Exception:
                pass

        if not valid_files:
            return JSONResponse(
                status_code=404,
                content={"error": "No mod files compatible with the selected version and loader were found!"},
            )

        with zipfile.ZipFile(zip_file_path, "w", zipfile.ZIP_DEFLATED) as zip_f:
            for file_info in valid_files:
                try:
                    f_res = await client.get(file_info["url"], headers={"User-Agent": MODRINTH_USER_AGENT})
                    if f_res.status_code == 200:
                        zip_f.writestr(file_info["filename"], f_res.content)
                except Exception:
                    pass

    file_id = generate_file_id(8)
    db = read_file_db()
    db[file_id] = {
        "originalName": zip_file_name,
        "filename": zip_file_name,
        "path": str(zip_file_path),
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
    }
    write_file_db(db)

    download_link = f"https://sayraa.xyz/d/{file_id}"
    return {
        "success": True,
        "message": f"Automatically build mod collection [{version}] successfully!",
        "fileId": file_id,
        "zipName": zip_file_name,
        "downloadUrl": download_link,
        "totalModsPacked": len(valid_files),
    }
