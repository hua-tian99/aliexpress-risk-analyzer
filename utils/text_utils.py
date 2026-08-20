"""文本处理工具"""
import re
from config import TITLE_STOP_WORDS, CONTACT_PATTERNS


def normalize_text(text):
    """标准化文本：转小写、合并空白"""
    if not text:
        return ""
    text = str(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_words(text):
    """分词（英文），返回单词列表"""
    text = normalize_text(text).lower()
    words = re.findall(r"[a-z]+(?:[-'][a-z]+)?", text)
    return words


def count_keyword_frequency(text):
    """统计关键词频率（过滤停用词）"""
    words = split_words(text)
    freq = {}
    for w in words:
        if w in TITLE_STOP_WORDS:
            continue
        freq[w] = freq.get(w, 0) + 1
    return freq


def is_brand_word(word, known_brands):
    """判断一个词是否出现在已知品牌库中"""
    w = word.lower().strip()
    for brand in known_brands:
        if w == brand or w in brand.split() or brand == w:
            return True
    return False


def extract_brand_candidates(title, known_brands):
    """从标题中提取品牌候选词（使用单词边界匹配，避免子串误报）
    例如 '1hp' 不会匹配 'hp', 'original' 不会匹配 'gin'
    """
    title_lower = title.lower()
    found = []
    # 先匹配完整品牌名（可能含空格）
    for brand in sorted(known_brands, key=len, reverse=True):
        # 使用字母数字边界确保只匹配完整单词
        # (?<![a-zA-Z0-9]) 防止 '1hp' 匹配 'hp'
        # (?![a-zA-Z0-9])  防止 'hps' 匹配 'hp'
        pattern = re.compile(
            r'(?<![a-zA-Z0-9])' + re.escape(brand) + r'(?![a-zA-Z0-9])',
            re.IGNORECASE,
        )
        if pattern.search(title_lower):
            found.append(brand)
    return found


def find_contacts_in_text(text):
    """在文本中检测联系方式，返回 [(contact_type, matched_text), ...]

    手机号需要上下文验证：附近必须出现 phone/tel/mobile/微信/contact 等词才判定为真实手机号。
    这是所有检测器（text_contact_leak、html_structure、image_analysis）共享的统一实现。
    """
    text_lower = text.lower()
    found = []
    for name, pattern in CONTACT_PATTERNS.items():
        # 手机号正则容易误报，只检测前后有上下文关键词的
        if name == "手机号(中国)":
            m = pattern.search(text)
            if m:
                # 检查上下文是否真是手机号（附近有 tel/phone/contact/微信等词）
                ctx = text[max(0, m.start() - 20):m.end() + 20].lower()
                if any(kw in ctx for kw in ["phone", "tel", "mobile", "whatsapp",
                                             "微信", "contact", "call", "sms",
                                             "chat", "line"]):
                    found.append((name, m.group()))
        else:
            m = pattern.search(text_lower)
            if m:
                # 邮箱正则取原文
                if name == "邮箱":
                    email_m = re.search(
                        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                        text
                    )
                    if email_m:
                        found.append((name, email_m.group()))
                else:
                    found.append((name, m.group()))
    return found


def is_structured_data(text):
    """判断文本是否像结构化数据（JSON/配置），而非人工编写的内容。

    速卖通平台会在产品描述中注入 display:none 的 div，内容为 JSON 配置数据。
    这类平台注入数据不应被判定为卖家故意隐藏信息。
    """
    text = text.strip()
    if not text:
        return False
    # JSON object: {"key": "value", ...}
    # 宽松匹配：以 { 或 [ 开头，且包含双引号和冒号（JSON 的典型特征）
    if (text.startswith("{") or text.startswith("[")):
        if '"' in text and ":" in text:
            return True
    return False
