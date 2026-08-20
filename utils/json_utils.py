"""安全JSON解析工具"""
import json
import traceback


def safe_parse_json(text, default=None):
    """安全解析JSON，失败返回default"""
    if not text or not isinstance(text, str) or not text.strip():
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def parse_price_info(text):
    """解析价格信息列（JSON格式），提取skuArray"""
    data = safe_parse_json(text, {})
    if not data:
        return None
    return data.get("skuArray") or data.get("sku", [])
