import ast
import asyncio
import io
import json
import os
import pty
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter()

# Thư mục lưu trữ dữ liệu các dự án được chia sẻ
SHARE_DIR = Path("data/shares")
SHARE_DIR.mkdir(parents=True, exist_ok=True)


# --- DATA MODELS ---

class FileItem(BaseModel):
    name: str = Field(..., description="Tên file hoặc đường dẫn tương đối (ví dụ: main.py, utils/helper.py)")
    content: str = Field(..., description="Nội dung file văn bản")


class CodeExecutionRequest(BaseModel):
    code: Optional[str] = Field(None, description="Code đơn file (tương thích cũ)")
    files: Optional[List[FileItem]] = Field(None, description="Danh sách các file trong dự án")
    entrypoint: str = Field(default="main.py", description="File chạy chính")
    stdin: Optional[str] = Field(default="", description="Dữ liệu đầu vào cho input()")


class CodeExecutionResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: float


class ShareCreateRequest(BaseModel):
    title: Optional[str] = Field(default="Untitled Project", description="Tiêu đề dự án")
    files: List[FileItem] = Field(..., description="Danh sách toàn bộ các file")
    entrypoint: str = Field(default="main.py", description="File chạy chính")
    ttl_days: int = Field(default=30, ge=1, le=365, description="Thời hạn tồn tại (1 - 365 ngày)")


class ShareResponse(BaseModel):
    share_id: str
    delete_token: str
    title: str
    expires_at: int
    share_url: str


class FormatCodeRequest(BaseModel):
    code: str = Field(..., description="Mã nguồn Python cần format")


class LintCodeRequest(BaseModel):
    code: str = Field(..., description="Mã nguồn Python")
    filename: Optional[str] = Field(default="main.py")


class LintIssue(BaseModel):
    line: int
    column: int
    message: str
    severity: str = "error"


class LintCodeResponse(BaseModel):
    is_valid: bool
    issues: List[LintIssue]


class SymbolItem(BaseModel):
    name: str
    kind: str
    line: int


class SymbolInspectRequest(BaseModel):
    code: str


# --- HELPER FUNCTIONS ---

def safe_join(base_dir: str, target_path: str) -> str:
    """Ghép đường dẫn an toàn, chặn tấn công Path Traversal"""
    clean_path = os.path.normpath(target_path).strip().lstrip("/\\")
    if not clean_path or clean_path.startswith(".."):
        clean_path = "script.py"
    full_path = os.path.abspath(os.path.join(base_dir, clean_path))
    base_abs = os.path.abspath(base_dir)
    if not full_path.startswith(base_abs):
        raise ValueError("Đường dẫn file nằm ngoài thư mục sandbox an toàn.")
    return full_path


def write_project_files(target_dir: str, payload: CodeExecutionRequest) -> str:
    """Ghi toàn bộ file của dự án vào thư mục tạm"""
    files_to_write: List[FileItem] = []

    if payload.files and len(payload.files) > 0:
        files_to_write = payload.files
    elif payload.code is not None:
        files_to_write = [FileItem(name=payload.entrypoint or "main.py", content=payload.code)]
    else:
        files_to_write = [FileItem(name="main.py", content="print('Hello World')")]

    entrypoint_name = os.path.basename(payload.entrypoint) if payload.entrypoint else "main.py"
    has_entrypoint = False

    for item in files_to_write:
        try:
            file_path = safe_join(target_dir, item.name)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(item.content)
            if item.name == payload.entrypoint or os.path.basename(file_path) == entrypoint_name:
                has_entrypoint = True
        except ValueError:
            continue

    if not has_entrypoint and files_to_write:
        entrypoint_name = files_to_write[0].name

    return entrypoint_name


# --- ENDPOINTS ---

@router.post("/execute", response_model=CodeExecutionResponse, summary="Thực thi Python Sandbox (HTTP)")
async def execute_python_code(payload: CodeExecutionRequest):
    loop = asyncio.get_running_loop()
    start_time = loop.time()
    temp_dir = tempfile.mkdtemp(prefix="py_sandbox_")

    try:
        entrypoint_file = write_project_files(temp_dir, payload)

        docker_cmd = [
            "docker", "run", "--rm", "-i",
            "--security-opt", "apparmor=unconfined",
            "--network", "host",
            "--memory", "256m",
            "--cpus", "0.5",
            "-v", f"{temp_dir}:/app:ro",
            "-w", "/app",
            "python:3.11-alpine",
            "python", "-u", entrypoint_file
        ]

        process = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdin_data = payload.stdin.encode("utf-8") if payload.stdin else b""

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input=stdin_data),
                timeout=10.0
            )
            exit_code = process.returncode
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            stdout_bytes = b""
            stderr_bytes = b"Loi: Thoi gian thuc thi vuot qua gioi han cho phep (Timeout 10s)."
            exit_code = 124

        end_time = loop.time()

        return CodeExecutionResponse(
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            exit_code=exit_code if exit_code is not None else 1,
            execution_time_ms=round((end_time - start_time) * 1000, 2)
        )

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.websocket("/ws/execute")
async def websocket_execute_python(websocket: WebSocket):
    """Thực thi nhanh file chính (Entrypoint) qua WebSocket"""
    await websocket.accept()
    temp_dir = tempfile.mkdtemp(prefix="py_ws_")
    process = None

    try:
        init_data = await websocket.receive_json()
        payload = CodeExecutionRequest(**init_data)
        entrypoint_file = write_project_files(temp_dir, payload)

        docker_cmd = [
            "docker", "run", "--rm", "-i",
            "--security-opt", "apparmor=unconfined",
            "--network", "host",
            "--memory", "256m",
            "--cpus", "0.5",
            "-v", f"{temp_dir}:/app:ro",
            "-w", "/app",
            "python:3.11-alpine",
            "python", "-u", entrypoint_file
        ]

        process = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        async def stream_output():
            try:
                while True:
                    chunk = await process.stdout.read(1024)
                    if not chunk:
                        break
                    await websocket.send_text(chunk.decode("utf-8", errors="replace"))
            except Exception:
                pass

        async def handle_input():
            try:
                while True:
                    user_input = await websocket.receive_text()
                    if process.stdin and not process.stdin.is_closing():
                        process.stdin.write(user_input.encode("utf-8"))
                        await process.stdin.drain()
            except (WebSocketDisconnect, Exception):
                pass

        task_out = asyncio.create_task(stream_output())
        task_in = asyncio.create_task(handle_input())

        try:
            await asyncio.wait(
                [task_out, asyncio.create_task(process.wait())],
                return_when=asyncio.FIRST_COMPLETED,
                timeout=60.0
            )
        except asyncio.TimeoutError:
            await websocket.send_text("\r\n[Error: Quá thời gian thực thi tối đa 60s]\r\n")

        task_out.cancel()
        task_in.cancel()
        await websocket.send_text(f"\r\n[Tiến trình hoàn tất - Exit code: {process.returncode}]\r\n")

    except WebSocketDisconnect:
        pass
    finally:
        if process and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        shutil.rmtree(temp_dir, ignore_errors=True)
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/terminal")
async def websocket_interactive_terminal(websocket: WebSocket):
    """Mở Full Interactive Linux Shell Terminal (chạy python3 main.py, pip install, ls, v.v...)"""
    await websocket.accept()
    temp_dir = tempfile.mkdtemp(prefix="py_term_")
    master_fd = None
    slave_fd = None
    process = None

    try:
        init_data = await websocket.receive_json()
        payload = CodeExecutionRequest(**init_data) if init_data else CodeExecutionRequest()
        write_project_files(temp_dir, payload)

        # Mở master/slave pseudo-terminal (PTY)
        master_fd, slave_fd = pty.openpty()

        docker_cmd = [
            "docker", "run", "--rm", "-it",
            "--security-opt", "apparmor=unconfined",
            "--network", "host",
            "--memory", "256m",
            "--cpus", "0.5",
            "-v", f"{temp_dir}:/app",
            "-w", "/app",
            "python:3.11-alpine",
            "/bin/sh"
        ]

        process = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True
        )

        os.close(slave_fd)
        slave_fd = None

        loop = asyncio.get_running_loop()

        async def pty_to_ws():
            try:
                while True:
                    data = await loop.run_in_executor(None, os.read, master_fd, 1024)
                    if not data:
                        break
                    await websocket.send_text(data.decode("utf-8", errors="replace"))
            except Exception:
                pass

        async def ws_to_pty():
            try:
                while True:
                    msg = await websocket.receive_text()
                    os.write(master_fd, msg.encode("utf-8"))
            except Exception:
                pass

        task_read = asyncio.create_task(pty_to_ws())
        task_write = asyncio.create_task(ws_to_pty())

        await asyncio.wait(
            [task_read, asyncio.create_task(process.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )

        task_read.cancel()
        task_write.cancel()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_text(f"\r\n[Terminal Shell Error: {str(e)}]\r\n")
        except Exception:
            pass
    finally:
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass
        if slave_fd is not None:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        if process and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        shutil.rmtree(temp_dir, ignore_errors=True)
        try:
            await websocket.close()
        except Exception:
            pass


# --- CODE SHARE SYSTEM ---

@router.post("/share", response_model=ShareResponse, summary="Tạo link chia sẻ dự án")
async def create_share_link(payload: ShareCreateRequest):
    share_id = uuid.uuid4().hex[:8]
    delete_token = uuid.uuid4().hex
    created_at = int(time.time())
    expires_at = created_at + (payload.ttl_days * 86400)

    share_data = {
        "id": share_id,
        "delete_token": delete_token,
        "title": payload.title,
        "files": [f.model_dump() for f in payload.files],
        "entrypoint": payload.entrypoint,
        "created_at": created_at,
        "expires_at": expires_at
    }

    file_path = SHARE_DIR / f"{share_id}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(share_data, f, ensure_ascii=False, indent=2)

    return ShareResponse(
        share_id=share_id,
        delete_token=delete_token,
        title=payload.title,
        expires_at=expires_at,
        share_url=f"https://py.nvirya.com?share={share_id}"
    )


@router.get("/share/{share_id}", summary="Tải dữ liệu dự án từ ID chia sẻ")
async def get_share_link(share_id: str):
    file_path = SHARE_DIR / f"{share_id}.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Mã chia sẻ không tồn tại hoặc đã bị xóa.")

    with open(file_path, "r", encoding="utf-8") as f:
        share_data = json.load(f)

    if int(time.time()) > share_data.get("expires_at", 0):
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=410, detail="Link chia sẻ này đã hết hạn sử dụng.")

    # Loại bỏ delete_token trước khi trả về public client
    share_data.pop("delete_token", None)
    return share_data


@router.delete("/share/{share_id}", summary="Xóa link chia sẻ bằng delete_token")
async def delete_share_link(share_id: str, token: str = Query(..., description="Mã delete_token")):
    file_path = SHARE_DIR / f"{share_id}.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Mã chia sẻ không tồn tại.")

    with open(file_path, "r", encoding="utf-8") as f:
        share_data = json.load(f)

    if share_data.get("delete_token") != token:
        raise HTTPException(status_code=403, detail="Mã delete_token không chính xác.")

    file_path.unlink(missing_ok=True)
    return {"message": "Đã xóa link chia sẻ thành công."}


# --- UTILITIES: LINT, FORMAT, SYMBOLS ---

@router.post("/lint", response_model=LintCodeResponse, summary="Kiểm tra lỗi cú pháp (Syntax Debugger)")
async def lint_python_code(payload: LintCodeRequest):
    issues = []
    try:
        ast.parse(payload.code, filename=payload.filename or "main.py")
        return LintCodeResponse(is_valid=True, issues=[])
    except SyntaxError as e:
        issues.append(LintIssue(
            line=e.lineno or 1,
            column=e.offset or 1,
            message=e.msg,
            severity="error"
        ))
        return LintCodeResponse(is_valid=False, issues=issues)


@router.post("/symbols", summary="Phân tích cấu trúc mã nguồn (Code Outline)")
async def inspect_code_symbols(payload: SymbolInspectRequest):
    symbols = []
    try:
        tree = ast.parse(payload.code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                symbols.append(SymbolItem(name=node.name, kind="function", line=node.lineno))
            elif isinstance(node, ast.AsyncFunctionDef):
                symbols.append(SymbolItem(name=node.name, kind="async_function", line=node.lineno))
            elif isinstance(node, ast.ClassDef):
                symbols.append(SymbolItem(name=node.name, kind="class", line=node.lineno))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    symbols.append(SymbolItem(name=alias.name, kind="import", line=node.lineno))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    symbols.append(SymbolItem(name=f"{module}.{alias.name}", kind="import", line=node.lineno))

        symbols.sort(key=lambda x: x.line)
        return {"symbols": [s.model_dump() for s in symbols]}
    except SyntaxError:
        return {"symbols": []}


@router.post("/format", summary="Format mã nguồn theo chuẩn PEP 8")
async def format_python_code(payload: FormatCodeRequest):
    code = payload.code
    try:
        import autopep8
        return {"formatted_code": autopep8.fix_code(code)}
    except ImportError:
        pass

    try:
        proc = await asyncio.create_subprocess_exec(
            "autopep8", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate(input=code.encode("utf-8"))
        if proc.returncode == 0 and stdout:
            return {"formatted_code": stdout.decode("utf-8")}
    except Exception:
        pass

    lines = code.splitlines()
    cleaned = [line.rstrip() for line in lines]
    return {"formatted_code": "\n".join(cleaned) + "\n"}


# --- EXPORT / IMPORT ZIP ---

@router.post("/export/zip", summary="Xuất dự án thành file .ZIP")
async def export_project_zip(payload: CodeExecutionRequest):
    zip_buffer = io.BytesIO()

    files_to_zip = payload.files if payload.files else [
        FileItem(name=payload.entrypoint or "main.py", content=payload.code or "")
    ]

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for item in files_to_zip:
            clean_name = os.path.normpath(item.name).strip().lstrip("/\\")
            zip_file.writestr(clean_name, item.content)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=nvirya_python_project.zip"}
    )


@router.post("/import/zip", summary="Tải file .ZIP lên để nhập dự án")
async def import_project_zip(file: UploadFile = File(...)):
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Chỉ chấp nhận file định dạng .zip")

    content = await file.read()
    extracted_files = []

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
            for zip_info in zip_file.infolist():
                if zip_info.is_dir() or zip_info.filename.startswith("__MACOSX"):
                    continue

                clean_name = os.path.normpath(zip_info.filename).strip().lstrip("/\\")
                if clean_name.endswith((".py", ".txt", ".json", ".csv", ".md", ".yaml", ".yml")):
                    file_bytes = zip_file.read(zip_info.filename)
                    extracted_files.append({
                        "name": clean_name,
                        "content": file_bytes.decode("utf-8", errors="replace")
                    })

        if not extracted_files:
            raise HTTPException(status_code=400, detail="Không tìm thấy file mã nguồn/văn bản hợp lệ trong file ZIP.")

        return {"files": extracted_files, "entrypoint": extracted_files[0]["name"]}

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="File ZIP bị lỗi hoặc không đúng cấu trúc.")