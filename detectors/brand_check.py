"""
D. 品牌侵权检测 — 标题+属性中的品牌词匹配

正则匹配品牌 → AI 二次验证（判定是侵权还是兼容配件/合法描述）
"""
import re
from config import SAFE_BRANDS
from detectors.base import BaseDetector
from utils.ai_client import discover_brands_in_title
from rule_index import get_rule_index

# Keywords that indicate measurement/specification context (not brand usage)
_MEASUREMENT_CONTEXT_KW = [
    # English — physical products measured by length
    "cable", "wire", "strip", "rope", "cord", "tube", "pipe", "hose",
    "long", "length", "meter", "metre", "foot", "feet", "inch",
    "led strip", "led", "light", "chain", "line",
    "extension", "charging", "charger", "adapter", "usb", "hdmi",
    # Chinese
    "米", "线", "绳", "带", "管", "灯", "缆", "链", "尺",
]


def _is_measurement_context(title, brand_name):
    """Check if a detected 'brand' is actually a measurement unit in context.

    Handles cases like '3M' meaning 3 meters (not the 3M brand).
    The AI prompt also covers this, but this code-level filter provides
    a safety net for when the AI misses the measurement context.
    """
    brand_lower = brand_name.lower().strip()
    title_lower = title.lower()

    # Pattern: brand is a number followed by a unit (e.g. "3m", "5 m", "10m")
    if re.match(r'^\d+\s*m$', brand_lower):
        if any(kw in title_lower for kw in _MEASUREMENT_CONTEXT_KW):
            return True

    return False


class BrandCheckDetector(BaseDetector):
    """品牌侵权检测（标题+属性+图片OCR文字）"""

    def __init__(self):
        super().__init__()
        self.rule_index = get_rule_index()
        self.rule_ref = self.rule_index.get_clause_ref(
            "全球速卖通知识产权规则",
            "商标侵权",
        )

    def detect(self, row, context=None):
        results = []

        title = str(row.get("产品名称", "")).strip()
        if not title:
            return results

        # 构建产品描述（标题+简述+描述，用于AI判断上下文）
        description = title
        brief = str(row.get("产品简述", "")).strip()
        desc1 = str(row.get("产品详细描述1", "")).strip()
        desc2 = str(row.get("产品详细描述2", "")).strip()
        if brief:
            description += " " + brief
        if desc1 or desc2:
            desc_text = re.sub(r"<[^>]+>", " ", desc1 + " " + desc2)
            desc_text = re.sub(r"\s+", " ", desc_text).strip()
            if desc_text:
                description += " " + desc_text

        # D1: 标题中检测知名品牌（含AI二次验证）
        brand_results = self._check_title_brands(title, description, row)
        results.extend(brand_results)

        # D2: 图片视觉分析中的品牌发现（通过 context 传递）
        if context and "image_analysis" in context:
            img_brand_results = self._check_image_brands(context["image_analysis"])
            results.extend(img_brand_results)

        return results

    def _check_title_brands(self, title, description, row):
        results = []

        # AI 全量扫描：从标题中发现品牌名并判断侵权
        discovered = discover_brands_in_title(title, description)

        if not discovered:
            return results

        # 过滤公司合作品牌白名单
        infringing = []
        for b in discovered:
            brand_name = b.get("brand_name", "").lower()
            # 白名单过滤
            if brand_name in SAFE_BRANDS:
                continue
            # 测量单位误判过滤（如 "3M" = 3米，非3M品牌）
            if _is_measurement_context(title, b.get("brand_name", "")):
                continue
            if b.get("is_infringement", False):
                infringing.append(b)

        if not infringing:
            return results

        brands_detail = "、".join(f"'{b['brand_name']}'" for b in infringing[:5])
        ai_reasons = "; ".join(
            f"'{b['brand_name']}': {b.get('reason', '')}" for b in infringing if b.get('reason')
        )

        reason = (
            f"标题中检测到品牌词：{brands_detail}。"
            "如未获得品牌方授权，使用品牌词构成商标侵权风险"
        )
        if ai_reasons:
            reason += f" [AI判定: {ai_reasons}]"

        title_lower = title.lower()
        compatible_keywords = ["for ", "compatible", "replacement", "fit for",
                              "适用于", "兼容", "替代"]
        is_compatible = any(kw in title_lower for kw in compatible_keywords)

        if is_compatible:
            remedy = (
                "如产品为兼容配件，请在标题中使用'for/适用于'等介词明确表示兼容关系，"
                "并确保不暗示该产品为原厂正品。建议格式：'[产品名] for [品牌名] [设备型号]'"
            )
        else:
            remedy = (
                "请确认是否持有相关品牌的商标授权。如已获得授权，请完成品牌准入流程；"
                "如未获得授权，请立即删除标题中的品牌词，修改为不含品牌描述的通用标题"
            )

        results.append(self._make_result(
            risk_level="高",
            category="品牌侵权",
            reason=reason,
            remedy=remedy,
            rule_ref=self.rule_ref,
            found_brands=[b["brand_name"] for b in infringing],
            is_compatible=is_compatible,
            ai_verified=True,
            ai_reasons=ai_reasons,
        ))

        return results

    def _check_image_brands(self, image_analysis):
        """从视觉 AI 图片分析结果中提取品牌相关发现"""
        results = []
        for img_data in image_analysis:
            img_idx = img_data.get("image_index", 0)
            img_url = img_data.get("image_url", "")
            findings = img_data.get("findings", [])

            for f in findings:
                category = f.get("category", "").lower()
                if "brand" in category or "logo" in category or "trademark" in category:
                    # 白名单品牌过滤：跳过合作品牌的图片发现
                    reason_lower = f.get("reason", "").lower()
                    if any(safe_brand in reason_lower for safe_brand in SAFE_BRANDS):
                        continue
                    results.append(self._make_result(
                        risk_level="高",
                        category="图片含品牌标识",
                        reason=f"第{img_idx + 1}张产品图片AI检测到品牌问题: {f.get('reason', '')}",
                        remedy=f.get("remedy", "请确认品牌授权或替换图片"),
                        rule_ref=self.rule_ref,
                        image_index=img_idx,
                        image_url=img_url,
                    ))
        return results
