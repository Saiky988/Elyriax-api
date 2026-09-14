import os
import platform
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
import psutil
from fastapi import APIRouter, Request

router = APIRouter()

HISTORY_LIMIT = 30
system_history = deque(maxlen=HISTORY_LIMIT)
start_time = time.time()

def format_bytes(bytes_val: int) -> str:
    if bytes_val == 0:
        return "0 B"
    k = 1024
    sizes = ["B", "KiB", "MiB", "GiB", "TiB"]
    import math
    i = int(math.floor(math.log(bytes_val) / math.log(k)))
    i = min(i, len(sizes) - 1)
    val = round(bytes_val / (k ** i), 2)
    return f"{val} {sizes[i]}"

def format_uptime(seconds: float) -> str:
    sec = int(seconds)
    d = sec // (3600 * 24)
    h = (sec % (3600 * 24)) // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    parts = []
    if d > 0:
        parts.append(f"{d}d")
    if h > 0:
        parts.append(f"{h}h")
    if m > 0:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)

def get_disk_usage() -> int:
    try:
        # Check current working directory size or disk usage
        du = psutil.disk_usage(".")
        return du.used
    except Exception:
        return 486 * 1024 * 1024

def get_network_traffic() -> Dict[str, int]:
    try:
        net = psutil.net_io_counters()
        return {"inbound": net.bytes_recv, "outbound": net.bytes_sent}
    except Exception:
        return {"inbound": 0, "outbound": 0}

def generate_system_snapshot(latency: int = 0) -> Dict[str, Any]:
    RAM_LIMIT_BYTES = 1 * 1024 * 1024 * 1024
    CPU_LIMIT_PERCENT = 100
    DISK_LIMIT_BYTES = 20 * 1024 * 1024 * 1024

    process = psutil.Process()
    mem_info = process.memory_info()
    cpu_percent = round(process.cpu_percent(interval=None), 2)

    vm = psutil.virtual_memory()
    total_os_mem_mb = round(vm.total / 1024 / 1024, 2)
    free_os_mem_mb = round(vm.available / 1024 / 1024, 2)
    used_os_mem_mb = round(total_os_mem_mb - free_os_mem_mb, 2)

    disk_used_bytes = get_disk_usage()
    network = get_network_traffic()

    try:
        load_avg = [f"{x:.2f}" for x in psutil.getloadavg()]
    except Exception:
        load_avg = ["0.00", "0.00", "0.00"]

    return {
        "success": True,
        "status": "online",
        "latency": f"{latency}ms",
        "api_info": {
            "version": "1.0.0",
            "environment": os.getenv("ENVIRONMENT", "development"),
            "app_uptime": format_uptime(time.time() - start_time),
            "node_version": f"Python {platform.python_version()}",
        },
        "panel_stats": {
            "cpu": {
                "used_percent": cpu_percent,
                "limit_percent": CPU_LIMIT_PERCENT,
                "formatted": f"{cpu_percent}% / {CPU_LIMIT_PERCENT}%",
            },
            "ram": {
                "used_bytes": mem_info.rss,
                "limit_bytes": RAM_LIMIT_BYTES,
                "usage_percent": round((mem_info.rss / RAM_LIMIT_BYTES) * 100, 2),
                "formatted": f"{format_bytes(mem_info.rss)} / {format_bytes(RAM_LIMIT_BYTES)}",
            },
            "disk": {
                "used_bytes": disk_used_bytes,
                "limit_bytes": DISK_LIMIT_BYTES,
                "usage_percent": round((disk_used_bytes / DISK_LIMIT_BYTES) * 100, 2),
                "formatted": f"{format_bytes(disk_used_bytes)} / {format_bytes(DISK_LIMIT_BYTES)}",
            },
            "network": {
                "inbound": format_bytes(network["inbound"]),
                "outbound": format_bytes(network["outbound"]),
            },
        },
        "system_info": {
            "platform": platform.system().lower(),
            "architecture": platform.machine(),
            "os_uptime": format_uptime(time.time() - psutil.boot_time()),
            "cpu": {
                "model": platform.processor() or "CPU",
                "cores": psutil.cpu_count(logical=True) or 1,
                "load_average_1m_5m_15m": load_avg,
            },
            "memory": {
                "total": f"{total_os_mem_mb} MB",
                "used": f"{used_os_mem_mb} MB",
                "free": f"{free_os_mem_mb} MB",
            },
        },
        "history_chart_data": list(system_history),
    }

def record_system_history(sio_server=None):
    process = psutil.Process()
    mem_info = process.memory_info()
    app_cpu = round(process.cpu_percent(interval=None), 2)
    app_ram_mb = round(mem_info.rss / 1024 / 1024, 2)

    vm = psutil.virtual_memory()
    sys_ram_percent = round(vm.percent, 2)
    now_str = datetime.now().strftime("%H:%M:%S")

    system_history.append({
        "time": now_str,
        "app_cpu_percent": app_cpu,
        "app_ram_mb": app_ram_mb,
        "sys_ram_percent": sys_ram_percent,
    })

    if sio_server is not None:
        return generate_system_snapshot(0)
    return None

@router.get("/system")
async def get_system_stats(request: Request):
    req_start = getattr(request.state, "start_time", time.time())
    latency = int((time.time() - req_start) * 1000)
    return generate_system_snapshot(latency)
