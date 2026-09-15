import asyncio
import json
import logging
import os
import secrets
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.core.config import settings

logger = logging.getLogger("FileUp")
router = APIRouter()

# Root project directory
BASE_DIR = Path(__file__).resolve().parents[3]
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = BASE_DIR / "data" / "file_database.json"

LEGACY_UPLOAD_DIR = BASE_DIR / "app" / "uploads"
LEGACY_DB_FILE = BASE_DIR / "app" / "data" / "file_database.json"

MODRINTH_USER_AGENT = "Sayraa-srx/mc-fixlag-autobuild/1.0.0 (sayraa.srx@gmail.com)"


def read_file_db() -> Dict[str, Any]:
    db = {}
    if DB_FILE.exists():
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                db.update(json.load(f))
        except Exception:
            pass
    # Fallback to legacy path if any files were recorded there
    if LEGACY_DB_FILE.exists():
        try:
            with open(LEGACY_DB_FILE, "r", encoding="utf-8") as f:
                legacy_data = json.load(f)
                for k, v in legacy_data.items():
                    if k not in db:
                        db[k] = v
        except Exception:
            pass
    return db


def write_file_db(data: Dict[str, Any]):
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_file_id(length: int = 8) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-"
    return "".join(secrets.choice(chars) for _ in range(length))


def resolve_actual_file_path(file_info: Dict[str, Any]) -> Optional[Path]:
    filename = file_info.get("filename") or Path(file_info.get("path", "")).name
    # 1. Primary uploads directory
    candidate = UPLOAD_DIR / filename
    if candidate.exists():
        return candidate
    # 2. Legacy uploads directory
    legacy_candidate = LEGACY_UPLOAD_DIR / filename
    if legacy_candidate.exists():
        return legacy_candidate
    # 3. Direct path recorded in DB
    orig = Path(file_info.get("path", ""))
    if orig.exists():
        return orig
    return None


def get_version_prefix(version: str) -> str:
    parts = version.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}."
    return version


async def _match_mod_version(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    mod_name: str,
    mod_id: str,
    version: str,
    loader: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    prefix = get_version_prefix(version)
    target_loaders = [loader.lower()]
    if loader.lower() == "fabric":
        target_loaders.append("quilt")

    async with sem:
        try:
            res = await client.get(
                f"https://api.modrinth.com/v2/project/{mod_id}/version",
                headers={"User-Agent": MODRINTH_USER_AGENT},
                timeout=20.0,
            )
            if res.status_code != 200:
                return None, {"name": mod_name, "reason": f"Modrinth HTTP {res.status_code}"}

            versions = res.json()
            matched = None

            # 1. Exact game version match
            for v in versions:
                v_loaders = [l.lower() for l in v.get("loaders", [])]
                if any(tl in v_loaders for tl in target_loaders):
                    if version in v.get("game_versions", []):
                        if v.get("version_type") == "release":
                            matched = v
                            break
                        if matched is None:
                            matched = v

            # 2. Smart fallback: closest version in same minor series (e.g. 1.21.x)
            if not matched:
                for v in versions:
                    v_loaders = [l.lower() for l in v.get("loaders", [])]
                    if any(tl in v_loaders for tl in target_loaders):
                        if any(gv.startswith(prefix) for gv in v.get("game_versions", [])):
                            if v.get("version_type") == "release":
                                matched = v
                                break
                            if matched is None:
                                matched = v

            if matched and matched.get("files"):
                files = matched["files"]
                primary = next((f for f in files if f.get("primary")), files[0])
                return {
                    "name": mod_name,
                    "filename": primary["filename"],
                    "url": primary["url"],
                    "version_number": matched.get("version_number", ""),
                }, None

            return None, {"name": mod_name, "reason": f"No compatible version found for {version} or {prefix}*"}
        except Exception as e:
            return None, {"name": mod_name, "reason": str(e)}


async def _download_mod_file(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    item: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    async with sem:
        try:
            res = await client.get(
                item["url"],
                headers={"User-Agent": MODRINTH_USER_AGENT},
                timeout=60.0,
            )
            if res.status_code == 200:
                return {
                    "filename": item["filename"],
                    "content": res.content,
                    "name": item["name"],
                }
            return None
        except Exception as e:
            logger.warning(f"Failed to download mod {item['name']}: {e}")
            return None


@router.post("/v1/file/upload")
@router.post("/api/v1/file/upload")
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

        download_link = f"{settings.BASE_URL}/d/{file_id}"
        return {
            "success": True,
            "message": "Upload file thành công!",
            "fileId": file_id,
            "originalName": file.filename,
            "downloadUrl": download_link,
            "directUrl": f"{settings.BASE_URL}/v1/file/download/{file_id}",
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Đã xảy ra lỗi khi xử lý file: {e}"})


@router.get("/v1/file/download/{file_id}")
@router.get("/api/v1/file/download/{file_id}")
@router.get("/d/{file_id}")
@router.get("/api/d/{file_id}")
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
@router.post("/api/v1/mc/auto-build")
@router.post("/mc/auto-build")
@router.post("/auto-build")
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

    meta_sem = asyncio.Semaphore(10)
    dl_sem = asyncio.Semaphore(8)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Step 1: Concurrently match metadata on Modrinth
        match_tasks = [
            _match_mod_version(client, meta_sem, mod_name, mod_id, version, loader)
            for mod_name, mod_id in mods.items()
        ]
        match_results = await asyncio.gather(*match_tasks)

        valid_files = [r[0] for r in match_results if r[0] is not None]
        missing_mods = [r[1] for r in match_results if r[1] is not None]

        if not valid_files:
            return JSONResponse(
                status_code=404,
                content={
                    "error": "No mod files compatible with the selected version and loader were found!",
                    "missingMods": missing_mods,
                },
            )

        # Step 2: Concurrently download all mod jars
        dl_tasks = [
            _download_mod_file(client, dl_sem, file_info)
            for file_info in valid_files
        ]
        downloaded = await asyncio.gather(*dl_tasks)

    # Step 3: Write downloaded jars directly to ZIP
    with zipfile.ZipFile(zip_file_path, "w", zipfile.ZIP_DEFLATED) as zip_f:
        packed_count = 0
        for item in downloaded:
            if item and item.get("content"):
                zip_f.writestr(item["filename"], item["content"])
                packed_count += 1

    file_id = generate_file_id(8)
    db = read_file_db()
    db[file_id] = {
        "originalName": zip_file_name,
        "filename": zip_file_name,
        "path": str(zip_file_path),
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
        "totalMods": packed_count,
    }
    write_file_db(db)

    download_link = f"{settings.BASE_URL}/d/{file_id}"
    direct_link = f"{settings.BASE_URL}/v1/file/download/{file_id}"

    return {
        "success": True,
        "message": f"Automatically build mod collection [{version}] successfully!",
        "fileId": file_id,
        "zipName": zip_file_name,
        "downloadUrl": download_link,
        "directUrl": direct_link,
        "totalModsPacked": packed_count,
        "totalModsRequested": len(mods),
        "packedMods": [
            {"name": f["name"], "filename": f["filename"], "version": f.get("version_number", "")}
            for f in valid_files
        ],
        "missingMods": missing_mods,
    }
