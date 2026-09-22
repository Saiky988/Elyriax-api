import asyncio
import os
import shutil
import tempfile
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

router = APIRouter()

# --- HTTP ENDPOINT (GIỮ LẠI ĐỂ DÙNG KHI CẦN) ---
class CodeExecutionRequest(BaseModel):
    code: str = Field(..., description="Mã nguồn Python")
    stdin: Optional[str] = Field(default="", description="Dữ liệu đầu vào")

class CodeExecutionResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: float

@router.post("/execute", response_model=CodeExecutionResponse)
async def execute_python_code(payload: CodeExecutionRequest):
    loop = asyncio.get_running_loop()
    start_time = loop.time()
    temp_dir = tempfile.mkdtemp(prefix="py_sandbox_")
    script_path = os.path.join(temp_dir, "main.py")

    with open(script_path, "w", encoding="utf-8") as f:
        f.write(payload.code)

    docker_cmd = [
        "docker", "run", "--rm", "-i",
        "--security-opt", "apparmor=unconfined",
        "--network", "host",
        "--memory", "128m",
        "--cpus", "0.5",
        "-v", f"{script_path}:/app/main.py:ro",
        "-w", "/app",
        "python:3.11-alpine",
        "python", "-u", "main.py"
    ]

    try:
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
            stdout_bytes, stderr_bytes = b"", b"Timeout 10s."
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


# --- WEBSOCKET LIVE STREAMING TERMINAL ---
@router.websocket("/ws/execute")
async def websocket_execute_python(websocket: WebSocket):
    await websocket.accept()
    temp_dir = tempfile.mkdtemp(prefix="py_ws_")
    script_path = os.path.join(temp_dir, "main.py")
    process = None

    try:
        # Bước 1: Nhận payload chứa code lúc vừa bấm Run
        init_data = await websocket.receive_json()
        code = init_data.get("code", "")

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        docker_cmd = [
            "docker", "run", "--rm", "-i",
            "--security-opt", "apparmor=unconfined",
            "--network", "host",
            "--memory", "128m",
            "--cpus", "0.5",
            "-v", f"{script_path}:/app/main.py:ro",
            "-w", "/app",
            "python:3.11-alpine",
            "python", "-u", "main.py"
        ]

        # Gộp stderr vào stdout để luồng hiển thị đúng thứ tự xuất hiện
        process = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        # Task 1: Đọc stdout liên tục từ docker container gửi về client
        async def stream_output():
            try:
                while True:
                    chunk = await process.stdout.read(1024)
                    if not chunk:
                        break
                    await websocket.send_text(chunk.decode("utf-8", errors="replace"))
            except Exception:
                pass

        # Task 2: Đọc dữ liệu user gõ phím từ client đẩy vào stdin của docker
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

        # Giới hạn tối đa 60s cho mỗi session tương tác
        try:
            await asyncio.wait(
                [task_out, asyncio.create_task(process.wait())],
                return_when=asyncio.FIRST_COMPLETED,
                timeout=60.0
            )
        except asyncio.TimeoutError:
            await websocket.send_text("\r\n[Quá thời gian thực thi tối đa 60s]\r\n")

        task_out.cancel()
        task_in.cancel()
        await websocket.send_text(f"\r\n[Tiến trình hoàn tất - Mã thoát: {process.returncode}]\r\n")

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
