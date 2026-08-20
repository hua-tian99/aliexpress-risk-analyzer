"""
速卖通在线产品违规风险分析 — 配置文件
"""
import re

# ========== 阿里云API配置 ==========
ALIBABA_CLOUD_ACCESS_KEY_ID = "your_access_key_id"
ALIBABA_CLOUD_ACCESS_KEY_SECRET = "your_access_key_secret"
ALIBABA_CLOUD_REGION = "cn-shanghai"

# ========== 千问 AI 配置（Token Plan 团队版） ==========
QWEN_API_KEY = "sk-your-qwen-api-key"
QWEN_API_BASE_URL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
QWEN_MODEL = "qwen3.6-flash"       # 统一使用快速模型
AI_REQUEST_TIMEOUT = 30              # 单次请求超时（秒），flash 模型一般 <10s
AI_MAX_RETRIES = 1                   # 失败重试次数（只重试一次，避免堆积）

# ========== 路径配置（相对于项目根目录，兼容 PyInstaller 打包） ==========
import os as _os
import sys as _sys

# PyInstaller 打包后资源在 sys._MEIPASS，开发环境则用 __file__ 目录
if getattr(_sys, 'frozen', False):
    _BASE_DIR = _sys._MEIPASS
else:
    _BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))

# Clippings 规则文件夹路径
CLIPPINGS_DIR = _os.path.join(_BASE_DIR, "Clippings")
# 全类目树路径（4级层级，5813条路径）
CATEGORY_TREE_PATH = _os.path.join(_BASE_DIR, "data", "category_tree.xlsx")
# 图片下载缓存目录（运行时写入，不能用 _MEIPASS）
_APP_DIR = _os.path.dirname(_os.path.abspath(__file__)) if not getattr(_sys, 'frozen', False) else _os.path.dirname(_sys.executable)
IMAGE_CACHE_DIR = _os.path.join(_APP_DIR, "image_cache")
# 上传Excel临时存放目录
UPLOAD_DIR = _os.path.join(_APP_DIR, "uploads")
# 批量处理输入/输出目录
BATCH_INPUT_DIR = _os.path.join(_APP_DIR, "input")
BATCH_OUTPUT_DIR = _os.path.join(_APP_DIR, "output")

# ========== 阈值 ==========
TITLE_LENGTH_MAX = 128        # 字符，高风险
TITLE_KEYWORD_REPEAT_MAX = 3  # 同一词出现超过此次数标记为堆砌
MIN_IMAGE_COUNT = 3           # 最少主图数量
SKU_PRICE_RATIO_MAX = 10      # SKU价差比超过此值标记
SKU_PRICE_MAX = 10000         # 美元，单SKU价格异常上限
SKU_PRICE_MIN = 1             # 美元，单SKU价格异常下限

# ========== 速卖通官方域名白名单 ==========
AE_OFFICIAL_DOMAINS = (
    "aliexpress.com", "aliexpress.ru", "aliexpress-media.com",
    "alicdn.com", "ae-pic-a1.aliexpress-media.com",
    "ae01.alicdn.com", "ae02.alicdn.com", "ae03.alicdn.com",
    "ae04.alicdn.com", "ae05.alicdn.com",
)

# ========== 标题停用词（词频统计时过滤） ==========
TITLE_STOP_WORDS = {
    "the", "a", "an", "for", "with", "and", "in", "of", "to", "is",
    "on", "or", "at", "by", "from", "it", "as", "be", "are", "was",
    "were", "been", "not", "but", "if", "so", "no", "all", "can",
    "will", "this", "that", "has", "have", "had", "do", "does", "did",
    "1pcs", "lot", "new", "hot", "high", "quality", "free", "shipping",
    "wholesale", "retail", "cheap", "sale", "buy", "best", "top",
    "original", "brand", "product", "item", "goods", "1pc", "1", "2",
    "3", "4", "5", "6", "7", "8", "9", "10", "20", "30", "50", "100",
    "2023", "2024", "2025", "2026",
}

# ========== 违禁品类关键词（10大类） ==========
PROHIBITED_PATTERNS = {
    "毒品类": [
        r"cocaine", r"heroin", r"marijuana", r"cannabis", r"opium",
        r"methamphetamine", r"lsd", r"ecstasy", r"fentanyl", r"mdma",
        r"amphetamine", r"morphine", r"ketamine", r"methadone",
    ],
    "武器弹药类": [
        r"weapon", r"firearm", r"gun\b", r"pistol", r"rifle", r"shotgun",
        r"ammunition", r"bullet", r"bomb\b", r"explosive", r"grenade",
        r"missile", r"rocket", r"military\s?grade",
    ],
    "管制刀具": [
        r"switchblade", r"butterfly\s?knife", r"balisong", r"dagger",
        r"throwing\s?star", r"shuriken", r"brass\s?knuckle",
    ],
    "烟草类": [
        r"tobacco", r"cigarette", r"cigar", r"nicotine", r"e-cig",
        r"vape\s?juice", r"e[\-\s]?liquid", r"hookah", r"shisha",
    ],
    "酒精饮料": [
        r"alcohol", r"liquor", r"whisky", r"whiskey", r"vodka", r"beer",
        r"\bwine\b", r"champagne", r"spirit", r"brandy", r"\bgin\b", r"\brum\b",
    ],
    "赌博类": [
        r"lottery", r"gambling", r"casino", r"poker\s?chip", r"slot\s?machine",
        r"roulette", r"betting",
    ],
    "色情低俗": [
        r"\bsex\b(?!\s+(?:and|&|education|toy|ual|y\b))",
        r"porn", r"pornographic", r"naked", r"nude", r"nudity",
        r"xxx\b", r"adult\s?video", r"escort", r"sexual\s?service",
    ],
    "虚拟货币": [
        r"bitcoin", r"cryptocurrency", r"ethereum", r"usdt", r"tether",
        r"dogecoin", r"litecoin", r"ripple", r"xrp",
    ],
    "假币/伪造": [
        r"fake\s?money", r"counterfeit\s?(money|currency|bill|note)",
        r"prop\s?money", r"forgery",
    ],
    "暴力歧视": [
        r"nazi", r"kkk", r"terrorist", r"racial\s?slur", r"hate\s?speech",
    ],
}

# 编译好的正则（启动时初始化）
COMPILED_PROHIBITED = {}
for cat, patterns in PROHIBITED_PATTERNS.items():
    COMPILED_PROHIBITED[cat] = [re.compile(p, re.IGNORECASE) for p in patterns]


# ========== 联系方式检测正则 ==========
CONTACT_PATTERNS = {
    "微信": re.compile(r"\bwechat\b|微信|we\s?chat", re.IGNORECASE),
    "WhatsApp": re.compile(r"\bwhatsapp\b", re.IGNORECASE),
    "QQ号": re.compile(r"\bqq\s?\d|\bqicq\b", re.IGNORECASE),
    "邮箱": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "Skype": re.compile(r"\bskype\b", re.IGNORECASE),
    "Facebook": re.compile(r"\bfacebook\b", re.IGNORECASE),
    "Instagram": re.compile(r"\binstagram\b", re.IGNORECASE),
    "Telegram": re.compile(r"\btelegram\b", re.IGNORECASE),
    "VKontakte": re.compile(r"\bvk(ontakte|\.com)\b", re.IGNORECASE),
    "Line": re.compile(r"(line\s?(id|app|chat|me)|line\.me)", re.IGNORECASE),
    "手机号(中国)": re.compile(r"(?<!\d)(\+86[\s\-]?)?1[3-9]\d{9}(?!\d)"),
    "WhatsApp短链": re.compile(r"wa\.me/", re.IGNORECASE),
}

# ========== HTML隐藏样式检测 ==========
HIDDEN_STYLE_PATTERNS = {
    "display_none": re.compile(r"display\s*:\s*none"),
    "visibility_hidden": re.compile(r"visibility\s*:\s*hidden"),
    "opacity_zero": re.compile(r"opacity\s*:\s*0(\.0+)?(\s|;|$|!)"),
    "zero_font": re.compile(r"font[\-\s]?size\s*:\s*0\s*(px|pt)?(\s|;|$|!)"),
    "negative_indent": re.compile(r"text[\-\s]?indent\s*:\s*-\d+"),
    "zero_dimensions": re.compile(r"(width|height)\s*:\s*0\s*(px)?(\s|;|$|!)"),
    "offscreen_position": re.compile(
        r"position\s*:\s*absolute.*?(left\s*:\s*-\d+|top\s*:\s*-\d+)",
        re.DOTALL,
    ),
}


# ========== 品牌库 ==========
# 知名品牌（约150个）
KNOWN_MAJOR_BRANDS = [
    # 运动时尚
    "nike", "adidas", "puma", "reebok", "under armour", "the north face",
    "columbia", "new balance", "converse", "vans", "timberland",
    "louis vuitton", "gucci", "chanel", "hermes", "prada", "dior",
    "burberry", "versace", "balenciaga", "fendi", "givenchy", "ysl",
    "supreme", "off-white", "yeezy", "air jordan", "valentino",
    "armani", "boss", "ralph lauren", "tommy hilfiger", "calvin klein",
    "coach", "mk", "michael kors", "tory burch", "kate spade",
    "ray-ban", "oakley", "carrera",
    # 电子产品
    "apple", "samsung", "sony", "lg", "panasonic", "philips", "sharp",
    "bose", "jbl", "beats", "sennheiser", "b&o", "bang & olufsen",
    "microsoft", "google", "intel", "amd", "nvidia", "dell", "hp",
    "lenovo", "asus", "acer", "huawei", "xiaomi", "oppo", "vivo",
    "oneplus", "canon", "nikon", "fujifilm", "sony", "gopro",
    "dyson", "playstation", "xbox", "nintendo", "sega",
    "dji", "roku", "amazon", "echo", "kindle", "fitbit", "garmin",
    # 汽车
    "bmw", "mercedes", "audi", "toyota", "honda", "ford", "chevrolet",
    "porsche", "ferrari", "lamborghini", "rolls-royce", "bentley",
    "jaguar", "land rover", "volkswagen", "nissan", "mazda", "subaru",
    "volvo", "hyundai", "kia", "lexus", "acura", "infiniti", "tesla",
    # 手表珠宝
    "rolex", "omega", "cartier", "tiffany", "swarovski", "casio",
    "seiko", "tag heuer", "breitling", "patek philippe", "audemars piguet",
    "hublot", "rado", "longines", "tissot", "citizen",
    # 玩具
    "lego", "barbie", "hasbro", "mattel", "bandai", "hot wheels",
    "transformers", "nerf", "playmobil", "mga entertainment",
    # 娱乐IP
    "disney", "marvel", "star wars", "harry potter", "pokemon",
    "hello kitty", "minions", "spider-man", "batman", "superman",
    "peppa pig", "paw patrol", "frozen", "mickey mouse",
    # 美妆护肤
    "l'oreal", "estee lauder", "dove", "nivea", "gillette", "olay",
    "clinique", "shiseido", "lancome", "mac", "maybelline", "neutrogena",
    # 奢侈品
    "gucci", "prada", "fendi", "givenchy", "balenciaga", "dolce & gabbana",
    "moncler", "canada goose",
]
KNOWN_MAJOR_BRANDS = sorted(set(b.lower() for b in KNOWN_MAJOR_BRANDS))

# ========== 公司合作品牌白名单（标题/图片中出现不标记风险） ==========
SAFE_BRANDS = [
    "a-echoes", "aiersi", "airow", "amt",
    "andrew gold", "anic", "apo", "aquila",
    "audi", "barberpro", "beatbot", "blanth",
    "bojlt", "bsci", "bullfighter", "cadillac",
    "carbon bos", "carplay", "ce", "connectivity",
    "coolfull", "der jung",
    "duocai", "freightliner", "gara equipments", "giant",
    "gra", "guo yulong", "hengsen", "hohenberg estate",
    "ibestgol", "iheart", "ingahooks", "jiuling refit",
    "jump4kids", "kaiyue", "koa pili koko", "koapilikoko",
    "kti", "lin", "luma", "maiker",
    "maxpeedingrods", "nallonhu", "npr one", "parez",
    "rhino hi-five", "s925", "savarez", "schellenberg estate",
    "singing dragon", "singing dragon classical guitars", "sino", "sinomusik",
    "siriusxm",
    "spotify", "sterling", "surdoca", "taishanmade",
    "taizhou eternal hydraulic", "tong", "tong lin", "uniqlyptic",
    "unite", "waze", "weststar", "xmsj",
    "yulong guo", "yumei", "zuoan",
]

# ========== 敏感属性ID（系统属性列） ==========
# 速卖通常用属性ID前缀，用于检测属性异常
ATTR_ID_MATERIAL = "200000"  # 材质类属性ID前缀
ATTR_ID_BRAND = "200001"    # 品牌类属性ID前缀

# ========== 列名映射 ==========
COL_PRODUCT_ID = "店小秘产品ID"
COL_PRODUCT_NAME = "产品名称"
COL_PRODUCT_IMAGES = "产品图片"
COL_PRODUCT_TYPE = "产品类型"
COL_PRODUCT_GROUP = "产品分组"
COL_DESC_BRIEF = "产品简述"
COL_DESC1 = "产品详细描述1"
COL_DESC2 = "产品详细描述2"
COL_SYS_ATTRS = "系统属性"
COL_CUSTOM_ATTRS = "自定义属性"
COL_PRICE_INFO = "价格信息"
COL_WEIGHT = "产品包装后的重量"
COL_SHIPPING_TEMPLATE = "运费模板"
COL_SOURCE_URL = "来源url"
COL_SHOP_NAME = "所属店铺"

# ========== FDA 非法宣称检测 ==========
FDA_ILLEGAL_PATTERNS = {
    "FDA虚假认证": [
        r"\bFDA\s?(approved|certified|registered|cleared|listed|compliant|approved|certificat(?:e|ion)|approval|register(?:ed|ation)?)\b",
        r"\bFDA\s?(grade|standard|level)\b",
    ],
    "虚假医疗功效": [
        r"\b(cure|treats?|heals?|removes?|eliminates?)\s+(cancer|tumor|diabet|HIV|AIDS|herpes|psoriasis|eczema|arthritis|asthma|alopecia)\b",
        r"\b(medical|clinical)\s?grade\b",
        r"\b(therapeutic|therapy)\s?device\b",
        r"\b(anti[\-\s]?aging|anti[\-\s]?wrinkle)\s?(treatment|cream|solution|device|machine)\b",
    ],
    "非法医疗器械宣称": [
        r"\b(laser\s?(hair\s?)?removal|lipo\s?(laser|suction|cavitation)|ultrasound\s?(cavitation|fat)|RF\s?(radio\s?frequency)\s?(skin\s?tightening))\b",
        r"\b(dermal\s?filler|botox|hyaluronic\s?acid\s?injection)\b",
        r"\b(medical\s?(device|equipment|instrument))\b",
    ],
    "虚假保健品宣称": [
        r"\b((?:lose|loss)\s?(?:weight|fat|\d+\s?kg)\s?(?:in|within)\s?\d+\s?(?:days?|weeks?))\b",
        r"\b(weight\s?loss\s?(?:in|within)\s?\d+\s?(?:days?|weeks?))\b",
        r"\b(grow\s?(?:taller|hair|muscle)\s?(?:in|within))\b",
        r"\b(detox\s?(?:body|colon|liver|kidney))\b",
        r"\b(fat\s?(?:burn|loss|melting)\s?(?:in|within))\b",
    ],
}

# 编译好的正则
FDA_COMPILED = {}
for _cat, _patterns in FDA_ILLEGAL_PATTERNS.items():
    FDA_COMPILED[_cat] = [re.compile(p, re.IGNORECASE) for p in _patterns]
