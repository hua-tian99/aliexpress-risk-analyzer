# -*- coding: utf-8 -*-
"""
F. 图片内容分析 — 千问视觉 AI 直接分析产品图片

替代旧版阿里云 OCR 方案。直接传图片 URL 给千问多模态模型，
检测品牌logo、联系方式、水印、违禁品、不雅内容等违规。
"""
import re
from config import SAFE_BRANDS
from detectors.base import BaseDetector
from utils.image_fetch import parse_image_urls
from utils.ai_client import analyze_product_images
from utils.category_loader import get_category_name
from rule_index import get_rule_index


class ImageAnalysisDetector(BaseDetector):
    """图片内容分析 — 千问视觉 AI"""

    def __init__(self):
        super().__init__()
        self.rule_index = get_rule_index()

    def detect(self, row, context=None):
        results = []

        # 只读取「产品图片」列（跳过白底图、场景图）
        img_cell = str(row.get("产品图片", ""))
        image_urls = parse_image_urls(img_cell)

        if not image_urls:
            return results

        # 产品名称用于匹配检测
        product_name = str(row.get("产品名称", ""))
        # 产品描述用于提供上下文
        desc1 = str(row.get("产品详细描述1", ""))
        desc2 = str(row.get("产品详细描述2", ""))
        description = product_name
        if desc1 or desc2:
            desc_text = re.sub(r"<[^>]+>", " ", desc1 + " " + desc2)
            desc_text = re.sub(r"\s+", " ", desc_text).strip()
            if desc_text:
                description += " " + desc_text

        # 千问视觉 AI 分析产品图片（解析类目ID→路径，家居类会放宽品牌检测）
        category_id = str(row.get("产品类型", ""))
        product_category = get_category_name(category_id) if category_id else ""
        from utils.ai_client import _is_furniture_category
        is_furniture = _is_furniture_category(product_category)
        image_results = analyze_product_images(
            image_urls, product_name, description, product_category
        )

        # 存储到 context 供 brand_check 使用
        image_analysis_data = []

        for img_result in image_results:
            img_idx = img_result.get("image_index", 0)
            img_url = image_urls[img_idx] if img_idx < len(image_urls) else ""
            findings = img_result.get("findings", [])

            image_analysis_data.append({
                "image_index": img_idx,
                "image_url": img_url,
                "findings": findings,
            })

            for finding in findings:
                risk_level = finding.get("risk_level", "中")
                category = finding.get("category", "图片违规")

                # 品牌/logo/商标 → 高风险；水印 → 中风险
                cat_lower = category.lower()
                is_brand_finding = "brand" in cat_lower or "logo" in cat_lower or "trademark" in cat_lower

                # 白名单品牌过滤：合作品牌不应被图片分析标记
                if is_brand_finding:
                    reason_lower = finding.get("reason", "").lower()
                    if any(safe_brand in reason_lower for safe_brand in SAFE_BRANDS):
                        continue

                # 家居类：品牌/logo finding 走二次 AI 确认，排除背景/认证/标识误报
                if is_furniture and is_brand_finding:
                    from utils.ai_client import verify_furniture_brand_risk
                    if not verify_furniture_brand_risk(product_name, finding):
                        continue  # false alarm, skip this finding

                if is_brand_finding:
                    risk_level = "高"
                elif "watermark" in cat_lower:
                    risk_level = "中"
                reason = finding.get("reason", "")
                remedy = finding.get("remedy", "")

                # 映射到现有规则
                rule_ref = self._get_rule_ref(category)

                results.append(self._make_result(
                    risk_level=risk_level,
                    category=f"图片-{category}",
                    reason=f"第{img_idx + 1}张产品图片: {reason}",
                    remedy=remedy,
                    rule_ref=rule_ref,
                    image_index=img_idx,
                    image_url=img_url,
                ))

        # 主图数量检查
        if len(image_urls) < 3:
            rule_ref = self.rule_index.get_clause_ref(
                "全球速卖通店铺信息质量不合格管理规则"
            )
            results.append(self._make_result(
                risk_level="中",
                category="主图不足",
                reason=f"产品图片仅{len(image_urls)}张，建议至少上传3张",
                remedy="请补充产品图片至至少3张，从多角度展示商品细节",
                rule_ref=rule_ref,
                image_count=len(image_urls),
            ))

        # 把图片分析结果存入 context 供品牌检测器使用
        if context is not None:
            context["image_analysis"] = image_analysis_data

        return results

    def _get_rule_ref(self, category):
        """根据违规类别获取对应的规则引用"""
        if "brand" in category.lower() or "logo" in category.lower():
            return self.rule_index.get_clause_ref(
                "全球速卖通知识产权规则", "商标侵权"
            )
        elif "contact" in category.lower() or "phone" in category.lower():
            return self.rule_index.get_clause_ref(
                "全球速卖通卖家基础规则（违规及处罚规则）",
                "第八十六条(五) 留有联系信息或广告商品",
            )
        elif "watermark" in category.lower() or "stolen" in category.lower():
            return self.rule_index.get_clause_ref(
                "全球速卖通盗用图片及盗用水印图规则"
            )
        elif "text" in category.lower() and "only" in category.lower():
            return self.rule_index.get_clause_ref(
                "全球速卖通搜索作弊通用规则", "5.1 其他信息描述不合规"
            )
        elif "prohibit" in category.lower():
            return self.rule_index.get_clause_ref(
                "全球速卖通禁限售规则(含违禁信息列表)"
            )
        else:
            return self.rule_index.get_clause_ref(
                "全球速卖通其他不当发布行为规则"
            )
