# -*- coding: utf-8 -*-
import json, logging, re, requests, time
from config import (QWEN_API_KEY, QWEN_API_BASE_URL, QWEN_MODEL, AI_REQUEST_TIMEOUT, AI_MAX_RETRIES)
logger = logging.getLogger(__name__)

# Simple in-memory cache to avoid duplicate AI calls
_AI_CACHE = {}

# Reusable HTTP session with connection pooling
_SESSION = None

# Last AI error text — callers can inspect to adjust fallback behavior
_LAST_AI_ERROR = ""


def _get_session():
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({
            "Authorization": "Bearer " + QWEN_API_KEY,
            "Content-Type": "application/json",
        })
        # Force IPv4 to avoid IPv6 timeout (~30s) on networks without IPv6
        import urllib3
        # Monkey-patch the connection pool to resolve only IPv4
        _orig_new_conn = urllib3.util.connection.create_connection
        def _create_conn_ipv4(address, *args, **kwargs):
            import socket
            host, port = address
            # Resolve IPv4 only
            addrs = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
            for family, socktype, proto, canonname, sockaddr in addrs:
                try:
                    sock = socket.socket(family, socktype, proto)
                    sock.settimeout(kwargs.get('timeout', 10))
                    sock.connect(sockaddr)
                    return sock
                except Exception:
                    continue
            raise OSError("Could not connect to %s" % host)
        urllib3.util.connection.create_connection = _create_conn_ipv4
    return _SESSION

PROMPT_PROHIBITED = 'You are an Aliexpress compliance auditor. Determine if a detected keyword in product text indicates a real prohibited product being sold.\n\nRules:\n1. If the keyword appears in safety warnings / usage instructions / caution notes (e.g. \'do not use in explosive gas environments\'), it is NOT a violation.\n2. If the keyword appears in compatibility descriptions / accessory notes (e.g. \'phone case for Samsung Galaxy\'), it is NOT a violation.\n3. If the keyword describes the prohibited product itself that the seller is selling (e.g. \'pure heroin powder for sale\'), it IS a violation.\n4. If the keyword is part of a legitimate product name that is NOT prohibited (e.g. \'wine fridge\' is a refrigerator appliance, not alcohol), it is NOT a violation.\n\nReturn ONLY strict JSON: {"results": [{"index": 1, "is_violation": false, "reason": "short reason in English"}]}'
PROMPT_BRAND = 'You are an Aliexpress IP auditor. Determine if brand words found in a product listing constitute trademark infringement.\n\nRules:\n1. If the title/description uses \'for / compatible with / replacement for / fit for\' + brand name, it is a legitimate compatible accessory — NOT infringement.\n2. If the product itself appears to be genuine/counterfeit goods of that brand (e.g. \'Nike shoes original 2025\'), it IS infringement.\n3. If the brand word is a common/generic word used in a different sense (e.g. \'apple\' meaning the fruit, not the phone), it is NOT infringement.\n4. If the brand is used as a model/spec number reference (e.g. \'BMW F30 sensor\'), likely NOT infringement — compatible part.\n\nReturn ONLY strict JSON: {"results": [{"brand": "nike", "is_infringement": true, "reason": "short reason in English"}]}'


def _call_qwen(messages, model=None, max_tokens=500, temperature=0.1):
    if model is None:
        model = QWEN_MODEL

    # Check cache to avoid duplicate API calls
    try:
        cache_key = json.dumps({"msgs": messages, "mdl": model}, sort_keys=True, ensure_ascii=False)
    except Exception:
        cache_key = None
    if cache_key and cache_key in _AI_CACHE:
        return _AI_CACHE[cache_key]

    url = QWEN_API_BASE_URL + "/chat/completions"
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "enable_thinking": False}
    session = _get_session()
    last_error = None
    attempts_made = 0
    for attempt in range(AI_MAX_RETRIES + 1):
        attempts_made = attempt + 1
        try:
            resp = session.post(url, json=payload, timeout=AI_REQUEST_TIMEOUT)
            if resp.status_code == 200:
                result = resp.json()["choices"][0]["message"]["content"]
                if cache_key:
                    _AI_CACHE[cache_key] = result
                return result
            elif resp.status_code == 429:
                last_error = "Rate limited (429)"
                time.sleep(2 * (attempt + 1))
            else:
                last_error = "HTTP %d: %s" % (resp.status_code, resp.text[:200])
                # data_inspection_failed: retry once (could be transient), but
                # do NOT fall back to base64 — content is the issue, not delivery
                if "data_inspection_failed" in resp.text:
                    if attempt < AI_MAX_RETRIES:
                        time.sleep(1)
                        continue
                break
        except requests.exceptions.Timeout:
            last_error = "Timeout after %ds" % AI_REQUEST_TIMEOUT
        except requests.exceptions.ConnectionError as e:
            last_error = "Connection error: %s" % e
        except Exception as e:
            last_error = "Unexpected error: %s" % e
    global _LAST_AI_ERROR
    _LAST_AI_ERROR = last_error or ""
    logger.warning("Qwen API call failed after %d attempts: %s" % (attempts_made, last_error))
    print("[AI Error] %s" % last_error, flush=True)
    return None


def _extract_json_block(text):
    """Extract the first complete JSON object from text using bracket counting.
    Handles nested braces that a simple regex cannot."""
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None


def _parse_json_response(response_text):
    if not response_text:
        print("[AI] Empty response", flush=True)
        return None
    text = response_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # Qwen sometimes returns Python dicts with single quotes instead of JSON
        import ast
        try:
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            pass
        # Bracket-counting extraction: handles nested JSON (e.g. {"brands": [{...}, {...}]})
        block = _extract_json_block(text)
        if block:
            try:
                return json.loads(block)
            except (json.JSONDecodeError, ValueError):
                pass
        print("[AI] JSON parse failed, raw response (first 300 chars):", flush=True)
        print("  " + response_text[:300], flush=True)
        return None


def verify_prohibited_words(product_name, matches):
    if not matches:
        return {}
    parts = []
    for i, m in enumerate(matches):
        parts.append("#%d keyword: %s | category: %s | context: %s" % (
            i + 1, m["matched_word"], m["category"], m["field_text"][:300]))
    user_prompt = "Product: " + product_name + "\n\n" + "\n".join(parts)
    response = _call_qwen([
        {"role": "system", "content": PROMPT_PROHIBITED},
        {"role": "user", "content": user_prompt},
    ], max_tokens=800)
    parsed = _parse_json_response(response)
    if not parsed or "results" not in parsed:
        logger.warning("AI prohibited verification failed, falling back")
        return {m["matched_word"]: {"is_violation": True, "ai_reason": "AI unavailable"} for m in matches}
    results = {}
    for item in parsed.get("results", []):
        idx = item.get("index", 0) - 1
        if 0 <= idx < len(matches):
            results[matches[idx]["matched_word"]] = {
                "is_violation": item.get("is_violation", True),
                "ai_reason": item.get("reason", ""),
            }
    for m in matches:
        if m["matched_word"] not in results:
            results[m["matched_word"]] = {"is_violation": True, "ai_reason": "AI missed"}
    return results


def verify_brand_infringement(product_name, description, found_brands):
    if not found_brands:
        return {}
    brands_list = ", ".join(found_brands)
    desc_preview = description[:500] if description else "(no description)"
    user_prompt = "Product: " + product_name + "\nDescription: " + desc_preview
    user_prompt += "\n\nBrands found: " + brands_list
    response = _call_qwen([
        {"role": "system", "content": PROMPT_BRAND},
        {"role": "user", "content": user_prompt},
    ], max_tokens=600)
    parsed = _parse_json_response(response)
    if not parsed or "results" not in parsed:
        logger.warning("AI brand verification failed, falling back")
        return {b: {"is_infringement": True, "ai_reason": "AI unavailable"} for b in found_brands}
    results = {}
    for item in parsed.get("results", []):
        brand = item.get("brand", "").lower()
        key = brand if brand else (found_brands[0] if found_brands else "")
        results[key] = {
            "is_infringement": item.get("is_infringement", True),
            "ai_reason": item.get("reason", ""),
        }
    for b in found_brands:
        if b not in results:
            results[b] = {"is_infringement": True, "ai_reason": "AI missed"}
    return results


VISION_PROMPT = 'You are an Aliexpress compliance auditor analyzing product images. For each image, check the following violations based on Aliexpress rules:\n\n1. BRAND LOGO/TEXT: Any brand logos, brand names, or trademark symbols visible — this may indicate trademark infringement. Risk levels per Aliexpress IP rules: general infringement (unauthorized use of others\' trademark) = medium; serious infringement (using identical/similar trademark on same goods, or obvious counterfeit) = high.\n2. CONTACT INFO: Any phone numbers, email addresses, WeChat/WhatsApp/QQ IDs, website URLs — images must not contain contact information.\n3. WATERMARK: Any watermarks, store names, or seller logos that do not belong to the seller — this may indicate stolen images. Risk levels per Aliexpress rules: general (basic image theft, first offense) = medium; serious (deliberate evasion, bad consumer impact) = high.\n4. TEXT-ONLY IMAGE: If the image is mainly text/banners/promotions rather than showing the product — main images should show the product. However, do NOT flag images that simply show product specifications, size charts, dimension tables, parameter lists, or basic product info — these are normal and acceptable.\n5. PROHIBITED ITEMS: If the image shows prohibited items (weapons, drugs, tobacco, counterfeit goods, etc.).\n6. INAPPROPRIATE CONTENT: Nudity, gore, offensive content.\n7. MISMATCH: If the image content clearly does NOT match the product title (e.g. title says \'charger\' but image shows \'shoes\').\n8. DESIGN PATENT RISK: If the product design closely imitates a well-known patented design (e.g. Dyson bladeless fan shape, Apple AirPods/EarPods design, LEGO brick shape, Crocs shoe shape, etc.), flag as potential design patent risk (medium risk level — warning only, not definite infringement).\n\nIMPORTANT: Do NOT flag these authorized company brands as violations — they are our partner brands: A-ECHOES, Aiersi, Airow, AMT, ANDREW GOLD, ANIC, APO, Aquila, Audi, BarberPro, Beatbot, BLANTH, BOJLT, BSCI, Bullfighter, Cadillac, Carbon bos, Carplay, CE, connectivity, Coolfull, Der jung, DUOCAI, Freightliner, GARA EQUIPMENTS, GIANT, GRA, Guo Yulong, Hengsen, Hohenberg ESTATE, iBestGol, iHeart, INGAHOOKS, JIULING REFIT, JUMP4KIDS, KAIYUE, Koa Pili Koko, KOAPILIKOKO, KTI, Lin, LUMA, Maiker, MaXpeedingrods, NallonHU, NPR One, PAREZ, RHINO HI-FIVE, S925, SAVAREZ, Schellenberg ESTATE, SINGING DRAGON, SINGING DRAGON CLASSICAL GUITARS, Sino, Sinomusik, SiriusXM, Spotify, Sterling, Surdoca, TAISHANMADE, TAIZHOU ETERNAL HYDRAULIC, Tong, Tong Lin, UniQlyptic, UNITE, Waze, Weststar, XMSJ, Yulong Guo, YuMei, ZUOAN. Their logos/watermarks/names in images are legitimate.\n\nReturn ONLY strict JSON (no markdown, no extra text):\n{"results": [{"image_index": 0, "findings": [{"risk_level": "high", "category": "Brand Logo in Image", "reason": "brief description of what was found", "remedy": "suggested action to fix"}]}]}\n\nIf an image has NO violations, return empty findings array for that image.\nIf an image URL is broken/inaccessible, mark it with a single finding: {"risk_level": "low", "category": "Image Not Accessible", "reason": "Could not load image", "remedy": "Check image URL"}'

VISION_PROMPT_FURNITURE = 'You are an Aliexpress compliance auditor analyzing product images for FURNITURE/HOME products. For each image, check the following violations based on Aliexpress rules:\n\n1. BRAND LOGO/TEXT — FURNITURE RULE: ONLY flag a brand if it is PRINTED, ENGRAVED, or EMBOSSED directly ON the furniture product being sold (e.g. a Nike logo molded into a toilet seat). Do NOT flag: certification marks (CE, ISO, WRAS, KTW, DVGW, UL, etc.), company names/logos on factory walls or documents, brand logos on background objects or distant buildings (e.g. a Starbucks sign on a building), factory photos, production line images, business licenses, insurance certificates, promotional banners, Chinese/English signage, the seller\'s own branding. These are NORMAL for furniture products and NEVER violations.\n2. CONTACT INFO: Any phone numbers, email addresses, WeChat/WhatsApp/QQ IDs, website URLs — images must not contain contact information.\n3. WATERMARK: Any watermarks, store names, or seller logos that do not belong to the seller — this may indicate stolen images. Risk levels per Aliexpress rules: general (basic image theft, first offense) = medium; serious (deliberate evasion, bad consumer impact) = high.\n4. TEXT-ONLY IMAGE: If the image is mainly text/banners/promotions rather than showing the product — main images should show the product. However, do NOT flag images that simply show product specifications, size charts, dimension tables, parameter lists, or basic product info — these are normal and acceptable.\n5. PROHIBITED ITEMS: If the image shows prohibited items (weapons, drugs, tobacco, counterfeit goods, etc.).\n6. INAPPROPRIATE CONTENT: Nudity, gore, offensive content.\n7. MISMATCH: If the image content clearly does NOT match the product title (e.g. title says \'charger\' but image shows \'shoes\').\n8. DESIGN PATENT RISK: If the product design closely imitates a well-known patented design (e.g. Dyson bladeless fan shape, Apple AirPods/EarPods design, LEGO brick shape, Crocs shoe shape, etc.), flag as potential design patent risk (medium risk level — warning only, not definite infringement).\n\nIMPORTANT: Do NOT flag these authorized company brands as violations — they are our partner brands: A-ECHOES, Aiersi, Airow, AMT, ANDREW GOLD, ANIC, APO, Aquila, Audi, BarberPro, Beatbot, BLANTH, BOJLT, BSCI, Bullfighter, Cadillac, Carbon bos, Carplay, CE, connectivity, Coolfull, Der jung, DUOCAI, Freightliner, GARA EQUIPMENTS, GIANT, GRA, Guo Yulong, Hengsen, Hohenberg ESTATE, iBestGol, iHeart, INGAHOOKS, JIULING REFIT, JUMP4KIDS, KAIYUE, Koa Pili Koko, KOAPILIKOKO, KTI, Lin, LUMA, Maiker, MaXpeedingrods, NallonHU, NPR One, PAREZ, RHINO HI-FIVE, S925, SAVAREZ, Schellenberg ESTATE, SINGING DRAGON, SINGING DRAGON CLASSICAL GUITARS, Sino, Sinomusik, SiriusXM, Spotify, Sterling, Surdoca, TAISHANMADE, TAIZHOU ETERNAL HYDRAULIC, Tong, Tong Lin, UniQlyptic, UNITE, Waze, Weststar, XMSJ, Yulong Guo, YuMei, ZUOAN. Their logos/watermarks/names in images are legitimate.\n\nReturn ONLY strict JSON (no markdown, no extra text):\n{"results": [{"image_index": 0, "findings": [{"risk_level": "high", "category": "Brand Logo in Image", "reason": "brief description of what was found", "remedy": "suggested action to fix"}]}]}\n\nIf an image has NO violations, return empty findings array for that image.\nIf an image URL is broken/inaccessible, mark it with a single finding: {"risk_level": "low", "category": "Image Not Accessible", "reason": "Could not load image", "remedy": "Check image URL"}'


def _download_image_as_base64(url, timeout=20):
    """Download an image and return as base64 data URI string, or None on failure."""
    import base64
    session = _get_session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.aliexpress.com/",
    }
    for attempt in range(2):  # 1 retry
        try:
            resp = session.get(url, timeout=timeout, headers=headers)
            if resp.status_code == 200 and len(resp.content) > 1024:
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                b64 = base64.b64encode(resp.content).decode("ascii")
                return f"data:{content_type};base64,{b64}"
        except Exception:
            if attempt == 0:
                time.sleep(1)
    return None


def _check_urls_reachable(image_urls, timeout=5):
    """Quick HEAD check — returns True if at least one image URL is reachable.
    Avoids wasting AI vision calls on products whose CDN image links have all expired."""
    for url in image_urls[:3]:  # check first 3 images only
        try:
            resp = requests.head(url, timeout=timeout, allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            if resp.status_code < 400:
                return True
        except Exception:
            continue
    return False


# Keywords for identifying furniture/home categories where vision brand
# detection should be relaxed (background logos, factory certs are normal)
_FURNITURE_CATEGORY_KW = [
    # English
    "furniture", "home & garden", "home improvement", "home decor",
    "bathroom", "kitchen", "lighting", "garden", "bedroom",
    "living room", "dining room", "office furniture",
    # Chinese
    "家居", "家具", "家装", "卫浴", "厨", "灯", "花园", "家纺",
    # Specific product types
    "书柜", "会议桌", "儿童家具", "茶几", "沙发", "椅", "桌", "柜",
    "床", "垫", "浴", "马桶", "洗手盆", "水龙头", "淋浴",
    "花洒", "毛巾架", "镜", "帘", "地毯", "墙纸", "地板",
    "晾衣架", "置物架", "收纳", "衣柜", "鞋柜", "梳妆",
    "水槽", "浴缸", "便器", "蹲便", "小便",
]


def _is_furniture_category(category_path):
    """Check if a product category belongs to furniture/home/garden."""
    if not category_path:
        return False
    path_lower = category_path.lower()
    return any(kw in path_lower for kw in _FURNITURE_CATEGORY_KW)


def analyze_product_images(image_urls, product_name, description="", product_category=""):
    """Analyze product images using Qwen vision AI for compliance violations.

    First tries passing image URLs directly (faster, no local bandwidth).
    If Qwen server fails to download images (HTTP 400), falls back to
    downloading images locally and passing as base64 data URIs.

    Args:
        image_urls: list of image URL strings (max ~10 per call)
        product_name: product title for mismatch detection
        description: optional product description for context
        product_category: optional product category path, used to apply
            relaxed brand detection for furniture/home products

    Returns:
        list[dict]: per-image findings, or empty list on failure
    """
    if not image_urls:
        return []

    # Quick pre-check: if all image URLs are unreachable, skip AI call entirely
    reachable = _check_urls_reachable(image_urls)
    if not reachable:
        print("  [Vision] All image URLs unreachable (expired), skipping vision analysis", flush=True)
        return []

    # Determine if we should use the furniture-specific system prompt
    is_furniture = _is_furniture_category(product_category)
    system_prompt = VISION_PROMPT_FURNITURE if is_furniture else VISION_PROMPT

    # Helper to build multimodal content
    def _build_content(urls, use_base64=False):
        content = [
            {"type": "text", "text": (
                "Product: " + product_name + "\n"
                "Description: " + (description[:300] if description else "N/A") + "\n\n"
                "Analyze these product images for compliance violations."
            )},
        ]
        for url in urls:
            url = url.strip()
            if not url.startswith("http"):
                continue
            if use_base64:
                print("  [Vision] Downloading image for base64: %s..." % url[:60], flush=True)
                data_uri = _download_image_as_base64(url)
                if data_uri:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": data_uri},
                    })
                else:
                    print("  [Vision] Failed to download image, will skip", flush=True)
            else:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": url},
                })
        return content

    # Attempt 1: pass URLs directly (preferred — no local bandwidth)
    content = _build_content(image_urls, use_base64=False)
    response = _call_qwen([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ], max_tokens=1500, temperature=0.1)

    # If Qwen server couldn't download images, retry with base64 — unless the
    # failure was content moderation (data_inspection_failed), where base64 won't help
    if response is None and len(image_urls) > 0:
        if "data_inspection_failed" in _LAST_AI_ERROR:
            print("  [Vision] Image content flagged by safety system, skipping base64 fallback", flush=True)
        else:
            print("  [Vision] URL mode failed, retrying with base64...", flush=True)
            content = _build_content(image_urls, use_base64=True)
            # Skip if all base64 downloads failed (wasted API call)
            image_parts = [p for p in content if p.get("type") == "image_url"]
            if not image_parts:
                print("  [Vision] All base64 downloads failed, skipping vision AI call", flush=True)
                return []
            response = _call_qwen([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ], max_tokens=1500, temperature=0.1)

    parsed = _parse_json_response(response)
    if not parsed or "results" not in parsed:
        logger.warning("Vision AI analysis failed, returning empty")
        print("[Vision] Analysis failed, returning empty", flush=True)
        return []

    return parsed.get("results", [])


DISCOVER_BRAND_PROMPT = 'You are an Aliexpress brand auditor. Given a product title and description, identify ANY brand names mentioned and determine if each constitutes trademark infringement.\n\nWhat counts as a brand:\n- Any recognizable brand name (global or regional): Nike, Apple, Kemei, Mijia, Baseus, Ugreen, Anker, Xiaomi, etc.\n- Brand-like words: proper nouns that appear to be company/brand identifiers in the product context.\n- NOT model numbers (e.g. KM-1596, X200, D5200).\n- NOT measurement/unit abbreviations in product dimensions. If a short code (like "M", "CM", "MM") appears right after a number and describes product size/length/specification (e.g. "3M cable" means 3-meter cable, "5M LED strip" means 5-meter strip, "30CM ruler"), it is a product spec — NOT a brand name.\n\nInfringement rules:\n1. ANY brand name found in the product title -> infringement. The seller must have authorization to sell branded products. Even if the brand appears to be the manufacturer (e.g. Kemei hair clipper), flag it as infringement — only authorized sellers can use brand names.\n2. EXCEPTION: Compatible accessories that use \'for / compatible with / replacement for / fit for\' + brand name -> NOT infringement. This applies to items like \'brake pads for BMW\', \'charger for iPhone\', \'case for Samsung\'.\n\nReturn ONLY strict JSON (reason must be 15 words max, no nested quotes, no markdown):\n{"brands": [{"brand_name": "kemei", "is_infringement": true, "reason": "short reason"}]}\nIf no brands found, return: {"brands": []}'


def discover_brands_in_title(title, description=""):
    """Use AI to discover brand names in product title/description and judge infringement.

    Unlike the old approach (regex match known brands -> AI verify), this lets AI
    identify ANY brand, including brands not in our list.

    Args:
        title: product title
        description: optional product description for context

    Returns:
        list[dict]: [{"brand_name": str, "is_infringement": bool, "reason": str}, ...]
    """
    if not title:
        return []

    desc_preview = description[:500] if description else "(no description)"
    user_prompt = (
        "Product: " + title + "\n"
        "Description: " + desc_preview + "\n\n"
        "Identify any brands in this product and judge infringement."
    )

    response = _call_qwen([
        {"role": "system", "content": DISCOVER_BRAND_PROMPT},
        {"role": "user", "content": user_prompt},
    ], max_tokens=1000)

    parsed = _parse_json_response(response)
    if not parsed or "brands" not in parsed:
        logger.warning("AI brand discovery failed")
        return []

    return parsed.get("brands", [])


FURNITURE_BRAND_VERIFY_PROMPT = (
    'You are an Aliexpress compliance auditor. A vision AI flagged a potential '
    'brand infringement in a FURNITURE/HOME product image. Your job is to '
    'determine if this is a REAL infringement or a FALSE alarm.\n\n'
    'REAL infringement (return true):\n'
    '- The brand logo/name is printed, engraved, embossed, or molded directly '
    'ON the furniture product being sold (e.g. a Nike swoosh on a toilet seat, '
    'an Adidas logo stitched into a chair).\n'
    '- A luxury brand item is deliberately placed as a lifestyle prop WITH the '
    'product to imply brand association (e.g. LV perfume next to a showerhead).\n\n'
    'FALSE alarm (return false):\n'
    '- Brand logos on background objects, distant buildings, or unrelated items '
    'in the scene (e.g. Starbucks sign on a building, car logo in parking lot).\n'
    '- Certification marks (CE, ISO, WRAS, KTW, DVGW, UL, etc.).\n'
    '- Company names/logos on factory walls, documents, certificates, or signage.\n'
    '- Factory photos, production line images, business licenses, insurance certs.\n'
    '- Seller\'s own company name, logo, or promotional text.\n'
    '- Chinese/English text or signage on buildings.\n\n'
    'Return ONLY: {"is_real_risk": true/false, "reason": "one short sentence"}'
)


def verify_furniture_brand_risk(product_name, finding):
    """Verify whether a brand-related finding in a furniture product image
    is a real infringement risk or a false alarm (background, certification, etc.)

    Args:
        product_name: product title
        finding: dict with {category, reason} from vision AI

    Returns:
        bool: True = real risk, keep it; False = false alarm, discard it
    """
    user_prompt = (
        "Product: " + product_name + "\n"
        "AI finding: [" + finding.get("category", "") + "] "
        + finding.get("reason", "") + "\n\n"
        "Is this a REAL brand infringement on a furniture product, "
        "or a FALSE alarm (background/certification/signage/etc)?"
    )
    response = _call_qwen([
        {"role": "system", "content": FURNITURE_BRAND_VERIFY_PROMPT},
        {"role": "user", "content": user_prompt},
    ], max_tokens=100, temperature=0.1)
    parsed = _parse_json_response(response)
    if parsed and "is_real_risk" in parsed:
        is_real = parsed.get("is_real_risk", True)
        reason = parsed.get("reason", "")
        if not is_real:
            print("  [Furniture Verify] False alarm filtered: " + reason, flush=True)
        return is_real
    # If verification fails, keep the finding (conservative: don't drop real issues)
    return True


SCORE_CATEGORY_PROMPT = """You are a product category auditor. Score how well this product fits the given AliExpress category path.

Consider:
- Product type: is this item what the category describes?
- Function / use case: does the product serve the purpose of this category?
- If the product clearly belongs in this category → high score (70-100)
- If the product is somewhat related but not a perfect fit → medium score (40-69)
- If the product is clearly unrelated → low score (0-39)

Return ONLY strict JSON: {"score": 85, "reason": "brief reason in 15 words or less"}"""


def score_category_match(product_title, product_desc, category_path):
    """Use AI to score how well a product matches a category path (0-100).

    Args:
        product_title: product name
        product_desc: brief description (optional)
        category_path: full category path like "L1 > L2 > L3 > L4"

    Returns:
        dict {"score": int, "reason": str} or None on failure.
    """
    user_text = f"Product: {product_title}"
    if product_desc:
        user_text += f"\nDescription: {product_desc[:300]}"
    user_text += f"\nCategory: {category_path}"

    try:
        response = _call_qwen([
            {"role": "system", "content": SCORE_CATEGORY_PROMPT},
            {"role": "user", "content": user_text},
        ], max_tokens=100)
        parsed = _parse_json_response(response)
        if parsed and "score" in parsed:
            score = int(parsed.get("score", 0))
            reason = str(parsed.get("reason", ""))
            return {"score": max(0, min(100, score)), "reason": reason}
    except Exception:
        pass
    return None
