"""图片下载缓存工具"""
import os
import hashlib
import requests
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import IMAGE_CACHE_DIR


def _url_to_filename(url):
    """将URL转换为缓存文件名"""
    ext = os.path.splitext(urlparse(url).path)[1] or ".jpg"
    return hashlib.md5(url.encode()).hexdigest() + ext


def download_image(url, timeout=15):
    """下载单张图片到缓存，返回本地路径，失败返回None"""
    os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
    fname = _url_to_filename(url)
    local_path = os.path.join(IMAGE_CACHE_DIR, fname)
    if os.path.exists(local_path) and os.path.getsize(local_path) > 1024:
        return local_path
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if resp.status_code == 200 and len(resp.content) > 1024:
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return local_path
    except Exception:
        pass
    return None


def download_images(urls, max_workers=3):
    """批量下载图片，返回 {url: local_path} 字典"""
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_map = {ex.submit(download_image, url): url for url in urls}
        for fut in as_completed(fut_map):
            url = fut_map[fut]
            try:
                path = fut.result()
                if path:
                    results[url] = path
            except Exception:
                pass
    return results


def parse_image_urls(cell_value):
    """解析产品图片列（分号分隔的URL列表）"""
    if not cell_value or not isinstance(cell_value, str):
        return []
    return [u.strip() for u in cell_value.split(";") if u.strip() and u.strip().startswith("http")]
