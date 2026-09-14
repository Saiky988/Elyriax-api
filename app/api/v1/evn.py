import re
import datetime
import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
import httpx
from bs4 import BeautifulSoup

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_URL = "https://www.cskh.evnspc.vn/TraCuu"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "text/html, */*; q=0.01"
}

# -------------------------------------------------------------
# 1. GET /v1/evn/provinces
# -------------------------------------------------------------
@router.get("/provinces")
async def get_evn_provinces():
    provinces = [
        {"code": "PB01", "name": "Đồng Nai"},
        {"code": "PB03", "name": "Lâm Đồng"},
        {"code": "PB05", "name": "Tây Ninh"},
        {"code": "PB07", "name": "Đồng Tháp"},
        {"code": "PB10", "name": "Vĩnh Long"},
        {"code": "PB11", "name": "TP Cần Thơ"},
        {"code": "PB12", "name": "An Giang"},
        {"code": "PB14", "name": "Cà Mau"}
    ]
    return {"success": True, "data": provinces}

# -------------------------------------------------------------
# 2. GET /v1/evn/units?provinceCode=PB01
# -------------------------------------------------------------
@router.get("/units")
async def get_evn_units(provinceCode: Optional[str] = Query(None)):
    if not provinceCode:
        return JSONResponse(status_code=400, content={"success": False, "message": "Thiếu tham số provinceCode"})

    url = f"{BASE_URL}/GetDanhMucDienLuc?pMA_DVICTREN={provinceCode}"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url, headers=DEFAULT_HEADERS)

        soup = BeautifulSoup(response.text, "html.parser")
        units = []
        for el in soup.select("option"):
            value = el.get("value")
            name = el.get_text(strip=True)
            if value:
                units.append({"code": value, "name": name})

        return {"success": True, "data": units}
    except Exception as error:
        logger.error(f"[EVN Units Error]: {error}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(error)})

# -------------------------------------------------------------
# 3. GET /v1/evn/outage
# -------------------------------------------------------------
def parse_outage_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    result: Dict[str, Any] = {
        "title": "",
        "unitName": "",
        "hasOutage": True,
        "schedules": []
    }

    no_schedule_msg = ""
    no_el = soup.select_one(".notification .ttl .red")
    if no_el:
        no_schedule_msg = no_el.get_text(strip=True)

    if "không có lịch" in no_schedule_msg.lower():
        result["hasOutage"] = False
        result["message"] = "Hiện tại khách hàng/đơn vị không có lịch ngừng giảm cung cấp điện"
        return result

    if no_el:
        result["title"] = no_el.get_text(strip=True)

    span_el = soup.select_one(".notification .ttl span")
    if span_el:
        result["unitName"] = span_el.get_text(strip=True).replace("Đơn vị:", "").strip()

    for el in soup.select(".entry"):
        where_el = el.select_one(".where")
        location = where_el.get_text(strip=True).replace("KHU VỰC:", "").strip() if where_el else ""

        time_el = el.select_one(".time span")
        time_text = re.sub(r'\s+', ' ', time_el.get_text(strip=True)).strip() if time_el else ""

        cause_el = el.select_one(".cause span")
        cause = cause_el.get_text(strip=True) if cause_el else ""

        if location or time_text:
            result["schedules"].append({
                "location": location,
                "time": time_text,
                "cause": cause
            })

    return result

@router.get("/outage")
async def get_evn_outage(
    type: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    tuNgay: Optional[str] = Query(None),
    denNgay: Optional[str] = Query(None)
):
    if not type or not code:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": 'Vui lòng cung cấp tham số type ("customer" hoặc "unit") và code'
            }
        )

    now = datetime.date.today()
    start_date = tuNgay or now.strftime("%d-%m-%Y")
    end_date = denNgay or (now + datetime.timedelta(days=4)).strftime("%d-%m-%Y")

    if type == "customer":
        url = f"{BASE_URL}/GetThongTinLichNgungGiamCungCapDien?tuNgay={start_date}&denNgay={end_date}&maKH={code}&ChucNang=MaKhachHang"
    elif type == "unit":
        url = f"{BASE_URL}/GetThongTinLichNgungGiamCungCapDien?madvi={code}&tuNgay={start_date}&denNgay={end_date}&ChucNang=MaDonVi"
    else:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": 'Type không hợp lệ. Chỉ chấp nhận "customer" hoặc "unit"'}
        )

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url, headers=DEFAULT_HEADERS)

        parsed_data = parse_outage_html(response.text)

        return {
            "success": True,
            "query": {"type": type, "code": code, "tuNgay": start_date, "denNgay": end_date},
            "data": parsed_data
        }
    except Exception as error:
        logger.error(f"[EVN Outage Error]: {error}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(error)})
