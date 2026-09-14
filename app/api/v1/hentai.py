import time
import re
import json
import base64
import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
import httpx
from bs4 import BeautifulSoup

router = APIRouter()
logger = logging.getLogger(__name__)

# --- Caching ---
ht_home_cache: Dict[str, Any] = {"data": None, "expire": 0}
HT_HOME_CACHE_TTL = 5 * 60  # 5 minutes

watch_cache: Dict[str, Any] = {}
WATCH_CACHE_TTL = 10 * 60  # 10 minutes

STORAGE_BASE = "https://storage.haiten.org"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
    "Referer": "https://hentaiz1.com/",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}

def normalize_ihentai_slug(slug: str) -> str:
    """Normalize slug to kebab-case for ihentai.red."""
    slug = slug.strip().lower()
    slug = re.sub(r'[_\.\s]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug

def generate_hentaiz_candidates(raw_slug: str) -> List[str]:
    candidates = []
    for c in [raw_slug, normalize_ihentai_slug(raw_slug), raw_slug.replace('-', '_'), raw_slug.replace('_', '-')]:
        if c not in candidates:
            candidates.append(c)
    return candidates

def resolve_ref(pool: Any, ref: Any, visited: Optional[set] = None) -> Any:
    if visited is None:
        visited = set()
    if ref is None:
        return None

    if isinstance(ref, int) and 0 <= ref < len(pool):
        if ref in visited:
            return None
        visited.add(ref)
        val = pool[ref]
        if isinstance(val, int):
            return val
        return resolve_ref(pool, val, visited)

    if isinstance(ref, list):
        return [resolve_ref(pool, item, set(visited)) for item in ref]

    if isinstance(ref, dict):
        res = {}
        for k, v in ref.items():
            res[k] = resolve_ref(pool, v, set(visited))
        return res

    return ref

def parse_ep_number(val: Any, fallback: int = 1) -> int:
    if isinstance(val, int):
        return val
    if isinstance(val, str) and val.isdigit():
        return int(val)
    return fallback

def make_skrao_payload(meta: dict, target_value: str) -> str:
    raw = [["__skrao", 1], meta, target_value]
    raw_bytes = json.dumps(raw, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw_bytes).decode('utf-8').rstrip('=')

async def fetch_episodes_from_hentaiz(slug: str) -> List[dict]:
    candidates = generate_hentaiz_candidates(slug)

    async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
        for cand_slug in candidates:
            try:
                series_payload = make_skrao_payload({"currentSlug": 2}, cand_slug)
                url = f"https://hentaiz1.com/_app/remote/1edhnia/getSeriesEpisodes?payload={series_payload}"
                series_res = await client.get(url, headers=HEADERS)

                if series_res.status_code == 200:
                    try:
                        res_json = series_res.json()
                    except Exception:
                        res_json = series_res.text

                    ep_result_data = res_json.get("value", {}).get("data") if isinstance(res_json, dict) and "value" in res_json else res_json
                    pool_str = ep_result_data.get("data") if isinstance(ep_result_data, dict) and "data" in ep_result_data else ep_result_data
                    pool = json.loads(pool_str) if isinstance(pool_str, str) else pool_str

                    if isinstance(pool, list) and len(pool) > 1 and isinstance(pool[1], dict) and "episodes" in pool[1]:
                        resolved_episodes = resolve_ref(pool, pool[1]["episodes"])
                        if isinstance(resolved_episodes, list) and len(resolved_episodes) > 0:
                            episodes = []
                            for ep in resolved_episodes:
                                if not isinstance(ep, dict):
                                    continue
                                poster_image = ""
                                if ep.get("posterImage") and isinstance(ep["posterImage"], dict) and ep["posterImage"].get("filePath"):
                                    fp = ep["posterImage"]["filePath"]
                                    poster_image = fp if fp.startswith("http") else f"{STORAGE_BASE}{fp}"

                                backdrop_image = ""
                                if ep.get("backdropImage") and isinstance(ep["backdropImage"], dict) and ep["backdropImage"].get("filePath"):
                                    fp = ep["backdropImage"]["filePath"]
                                    backdrop_image = fp if fp.startswith("http") else f"{STORAGE_BASE}{fp}"

                                episodes.append({
                                    "id": ep.get("id", ""),
                                    "title": ep.get("title", ""),
                                    "slug": ep.get("slug", ""),
                                    "episodeNumber": parse_ep_number(ep.get("episodeNumber"), 1),
                                    "posterImage": poster_image,
                                    "backdropImage": backdrop_image,
                                })
                            return episodes
            except Exception:
                continue
    return []

async def crawl_ihentai_detail(slug: str) -> dict:
    ihentai_slug = normalize_ihentai_slug(slug)
    target_url = f"https://ihentai.red/{ihentai_slug}"

    scrape_headers = {
        **HEADERS,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": "https://ihentai.red/",
    }

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        resp = await client.get(target_url, headers=scrape_headers)
        if resp.status_code != 200:
            raise Exception(f"ihentai returned status {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")

    title_el = soup.select_one(".pf-detail-title")
    title = title_el.get_text(strip=True) if title_el else ""

    synopsis_el = soup.select_one(".pf-synopsis p")
    synopsis = synopsis_el.get_text(strip=True) if synopsis_el else ""

    servers = []
    for el in soup.select(".pf-server-btn"):
        name = el.get_text(strip=True)
        src = el.get("data-src")
        if src:
            servers.append({"name": name, "src": src})

    if not servers:
        player_frame = soup.select_one("#player-frame")
        if player_frame and player_frame.get("src"):
            servers.append({"name": "#1", "src": player_frame.get("src")})

    categories = []
    for block in soup.select(".pf-meta-block"):
        h2 = block.select_one("h2")
        label = h2.get_text(strip=True) if h2 else ""
        tags = []
        for tag in block.select(".pf-tag-chip"):
            tags.append({
                "name": tag.get_text(strip=True),
                "url": tag.get("href") or ""
            })
        if label:
            categories.append({"label": label, "tags": tags})

    return {
        "title": title,
        "synopsis": synopsis,
        "embedServers": servers,
        "categories": categories,
        "url": target_url
    }

# -------------------------------------------------------------
# 1. GET /v1/crawl/hentai/watch?slug=...
# -------------------------------------------------------------
@router.get("/crawl/hentai/watch")
async def crawl_hentai_watch(slug: Optional[str] = Query(None)):
    if not slug:
        return JSONResponse(status_code=400, content={"success": False, "message": "Thiếu query parameter: slug"})

    target_url = f"https://ihentai.red/{slug}"
    scrape_headers = {
        **HEADERS,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": "https://ihentai.red/",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(target_url, headers=scrape_headers)

        soup = BeautifulSoup(response.text, "html.parser")

        title_el = soup.select_one('.pf-detail-title')
        title = title_el.get_text(strip=True) if title_el else ""

        player_frame = soup.select_one('#player-frame')
        default_embed = player_frame.get('src') if player_frame else None

        synopsis_el = soup.select_one('.pf-synopsis p')
        synopsis = synopsis_el.get_text(strip=True) if synopsis_el else ""

        servers = []
        for el in soup.select('.pf-server-btn'):
            name = el.get_text(strip=True)
            src = el.get('data-src')
            if src:
                servers.append({"name": name, "src": src})

        categories = []
        for block in soup.select('.pf-meta-block'):
            h2 = block.select_one('h2')
            label = h2.get_text(strip=True) if h2 else ""
            tags = []
            for tag in block.select('.pf-tag-chip'):
                tags.append({
                    "name": tag.get_text(strip=True),
                    "url": tag.get('href') or ""
                })
            if label:
                categories.append({"label": label, "tags": tags})

        return {
            "success": True,
            "data": {
                "title": title,
                "synopsis": synopsis,
                "defaultEmbed": default_embed,
                "servers": servers,
                "categories": categories,
                "url": target_url
            }
        }
    except Exception as error:
        logger.error(f"[Crawl Error]: {error}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Lỗi cào dữ liệu",
                "error": str(error)
            }
        )

# -------------------------------------------------------------
# 2. GET /v1/hentai/home
# -------------------------------------------------------------
@router.get("/hentai/home")
async def hentai_home():
    global ht_home_cache
    now = time.time()

    if ht_home_cache["data"] and now < ht_home_cache["expire"]:
        return PlainTextResponse(content=ht_home_cache["data"], media_type="text/plain; charset=utf-8")

    target_api = "https://hentaivs.cc/__data.json?x-sveltekit-trailing-slash=1&x-sveltekit-invalidated=011"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://hentaiz1.com/",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1"
    }

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(target_api, headers=headers)

        if response.status_code == 200 and response.text:
            ht_home_cache["data"] = response.text
            ht_home_cache["expire"] = now + HT_HOME_CACHE_TTL
            return PlainTextResponse(content=ht_home_cache["data"], media_type="text/plain; charset=utf-8")
        else:
            raise Exception(f"Target responded with status: {response.status_code}")
    except Exception as error:
        logger.error(f"[HentaiHome Error]: {error}")
        if ht_home_cache["data"]:
            return PlainTextResponse(content=ht_home_cache["data"], media_type="text/plain; charset=utf-8")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"Proxy fetch failed: {error}"})

# -------------------------------------------------------------
# 3. GET /v1/hentai/watch?data=... or ?slug=...
# -------------------------------------------------------------
@router.get("/hentai/watch")
async def hentai_watch(data: Optional[str] = Query(None), slug: Optional[str] = Query(None)):
    raw_slug = data or slug
    if not raw_slug:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Missing slug/data parameter"})

    normalized_slug = normalize_ihentai_slug(raw_slug)
    cache_key = f"clean_watch_{normalized_slug}"
    now = time.time()

    if cache_key in watch_cache:
        cached = watch_cache[cache_key]
        if now < cached["expire"]:
            return cached["data"]

    try:
        crawl_data = await crawl_ihentai_detail(raw_slug)
        episodes = await fetch_episodes_from_hentaiz(raw_slug)

        default_embed = crawl_data["embedServers"][0]["src"] if crawl_data["embedServers"] else ""

        result = {
            "ok": True,
            "anime": {
                "title": crawl_data["title"],
                "slug": raw_slug,
                "description": crawl_data["synopsis"],
                "categories": crawl_data["categories"]
            },
            "embedUrls": crawl_data["embedServers"],
            "defaultEmbedUrl": default_embed,
            "episodes": episodes
        }

        watch_cache[cache_key] = {"data": result, "expire": now + WATCH_CACHE_TTL}
        return result
    except Exception as err:
        logger.error(f"[htWatch Error] {raw_slug}: {err}")
        return JSONResponse(status_code=500, content={"ok": False, "error": str(err)})

# -------------------------------------------------------------
# 4. GET /v1/hentai/player & /v1/hentai/_app/{path:path}
# -------------------------------------------------------------
PLAYER_ORIGIN = "https://x.haiten.org"

@router.get("/hentai/_app/{path:path}")
async def proxy_app(path: str):
    try:
        target_url = f"{PLAYER_ORIGIN}/_app/{path}"
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(
                target_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": f"{PLAYER_ORIGIN}/"
                }
            )
        content_type = response.headers.get("content-type", "application/javascript")
        return Response(content=response.content, media_type=content_type, headers={"Access-Control-Allow-Origin": "*"})
    except Exception:
        return PlainTextResponse("Asset not found", status_code=404)

@router.get("/hentai/player")
async def proxy_player(url: Optional[str] = Query(None)):
    if not url:
        return PlainTextResponse("Missing video URL", status_code=400)

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://hentaiz1.com/"
                }
            )

        html = response.text
        html = re.sub(r'(src|href)=["\']/_app/', r'\1="/api/v1/hentai/_app/', html)
        html = re.sub(r'import\(["\']/_app/', r'import("/api/v1/hentai/_app/', html)

        headers = {
            "Access-Control-Allow-Origin": "*",
            "Content-Type": "text/html; charset=utf-8"
        }
        return HTMLResponse(content=html, headers=headers)
    except Exception:
        return PlainTextResponse("Không thể tải Player", status_code=500)
