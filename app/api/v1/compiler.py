import asyncio
import os
import shutil
import tempfile
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()

class CodeExecutionRequest(BaseModel):
    code: str = Field(..., description="Mã nguồn Python cần thực thi")
    stdin: Optional[str] = Field(default="", description="Dữ liệu đầu vào cho các hàm input()")

class CodeExecutionResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: float

@router.post("/execute", response_model=CodeExecutionResponse, summary="Chạy mã nguồn Python cách ly trong Docker sandbox")
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
        "--network", "none",
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
            stdout_bytes = b""
            stderr_bytes = b"Loi: Thoi gian thuc thi vuot qua gioi han cho phep."
            exit_code = 124

        end_time = loop.time()

        return CodeExecutionResponse(
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            exit_code=exit_code if exit_code is not None else 1,
            execution_time_ms=round((end_time - start_time) * 1000, 2)
        )

    finally:
        # Xóa sạch thư mục tạm sau khi kết thúc tác vụ
        shutil.rmtree(temp_dir, ignore_errors=True)
