import re
from typing import Any, Dict, List
from bs4 import BeautifulSoup
import httpx

CODES_API_URL = "https://genshin-impact.fandom.com/api.php?action=parse&page=Promotional_Code&prop=text&format=json"

async def get_raw_wiki_html() -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(CODES_API_URL, headers=headers)
        data = res.json()
        return data.get("parse", {}).get("text", {}).get("*", "")

async def get_all_codes() -> List[Dict[str, Any]]:
    html = await get_raw_wiki_html()
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    cards = []

    for row in soup.select("table.wikitable tbody tr"):
        tds = row.find_all("td")
        if len(tds) < 3:
            continue

        codes = []
        for c in tds[0].find_all("code"):
            code_text = c.get_text().strip()
            if code_text:
                codes.append(code_text)

        if not codes:
            continue

        server = re.sub(r"\s+", " ", tds[1].get_text()).strip()
        rewards = []
        for el in tds[2].find_all(class_="item-text"):
            text = re.sub(r"\s+", " ", el.get_text()).strip()
            if text:
                rewards.append(text)

        validity = re.sub(r"\s+", " ", tds[3].get_text()).strip() if len(tds) >= 4 else None
        cards.append({"codes": codes, "server": server, "rewards": rewards, "validity": validity})

    return cards

async def get_code_info(target_code: str) -> Dict[str, Any]:
    try:
        html = await get_raw_wiki_html()
        if not html:
            return {}

        soup = BeautifulSoup(html, "html.parser")
        for row in soup.select("table.wikitable tbody tr"):
            tds = row.find_all("td")
            if len(tds) < 3:
                continue

            codes = [c.get_text().strip() for c in tds[0].find_all("code") if c.get_text().strip()]
            if target_code in codes:
                rewards = [
                    re.sub(r"\s+", " ", el.get_text()).replace("Ã—", "×").strip()
                    for el in tds[2].find_all(class_="item-text")
                    if el.get_text().strip()
                ]
                validity = (
                    re.sub(r"\s+", " ", tds[3].get_text()).replace("Ã—", "×").strip()
                    if len(tds) >= 4
                    else None
                )
                return {"rewards": rewards, "validity": validity}
        return {}
    except Exception:
        return {}
