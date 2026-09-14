from typing import Any
from fastapi.responses import JSONResponse

def send_success(message: str, data: Any = None) -> dict:
    res = {
        "success": True,
        "message": message
    }
    if data is not None:
        res["data"] = data
    else:
        res["data"] = {}
    return res

def send_error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "message": message
        }
    )
