"""
E. 搜索作弊检测 — 标题堆砌/标题超长/SKU作弊
（运费倒挂、来源URL、标题偏长、描述质量差 已移除）
"""
import re
from detectors.base import BaseDetector
from utils.text_utils import count_keyword_frequency
from utils.json_utils import safe_parse_json
from config import (
    TITLE_LENGTH_MAX, TITLE_KEYWORD_REPEAT_MAX,
    SKU_PRICE_RATIO_MAX, SKU_PRICE_MIN, SKU_PRICE_MAX,
)
from rule_index import get_rule_index


class SearchCheatingDetector(BaseDetector):
    """搜索作弊检测（标题堆砌/标题超长/SKU作弊）"""

    def __init__(self):
        super().__init__()
        self.rule_index = get_rule_index()

    def detect(self, row, context=None):
        results = []
        title = str(row.get("产品名称", "")).strip()

        # E1: 标题关键词堆砌
        if title:
            stack_results = self._check_title_keyword_stuffing(title)
            results.extend(stack_results)

        # E2: 标题超长（仅>128字符的高风险）
        if title:
            len_results = self._check_title_length(title)
            results.extend(len_results)

        # E3: SKU作弊
        sku_results = self._check_sku_cheating(row)
        results.extend(sku_results)

        return results

    def _check_title_keyword_stuffing(self, title):
        """E1: 标题关键词堆砌"""
        results = []
        rule_ref = self.rule_index.get_clause_ref(
            "全球速卖通搜索作弊通用规则",
            "2.1 标题描述违规",
        )

        freq = count_keyword_frequency(title)
        stuffed = {k: v for k, v in freq.items() if v >= TITLE_KEYWORD_REPEAT_MAX}

        if stuffed:
            kw_detail = "、".join(f"'{k}'({v}次)" for k, v in
                                  sorted(stuffed.items(), key=lambda x: -x[1])[:10])
            first_kw = list(stuffed.keys())[0]
            remedy_title = title.replace(first_kw, "").strip()
            # 简单去重建议
            words = re.findall(r"\S+", title)
            deduped = []
            seen = set()
            for w in words:
                w_clean = re.sub(r"[^a-zA-Z0-9]", "", w).lower()
                if w_clean in stuffed and w_clean in seen:
                    continue
                seen.add(w_clean)
                deduped.append(w)
            remedy_suggest = " ".join(deduped)

            results.append(self._make_result(
                risk_level="中",
                category="标题关键词堆砌",
                reason=f"标题中检测到关键词堆砌：{kw_detail}。标题描述中出现关键词重复使用多次构成标题关键词滥用",
                remedy=f"请精简标题，删除重复的关键词。建议改为：'{remedy_suggest[:200]}'",
                rule_ref=rule_ref,
                stuffed_keywords=stuffed,
            ))

        return results

    def _check_title_length(self, title):
        """E2: 标题超长（仅>128字符的高风险）"""
        results = []
        rule_ref = self.rule_index.get_clause_ref(
            "全球速卖通搜索作弊通用规则",
            "2.1 标题描述违规",
        )

        length = len(title)
        if length > TITLE_LENGTH_MAX:
            results.append(self._make_result(
                risk_level="高",
                category="标题超长",
                reason=f"标题长度{length}字符，超过{TITLE_LENGTH_MAX}字符上限，过长标题影响搜索排序",
                remedy=f"请将标题精简至{TITLE_LENGTH_MAX}字符以内，删除冗余关键词和修饰词",
                rule_ref=rule_ref,
                title_length=length,
            ))

        return results

    def _get_sku_field(sku, *keys):
        """从sku字典中安全取值，依次尝试多个key名"""
        for k in keys:
            v = sku.get(k)
            if v is not None:
                return v
        return None

    def _get_sku_price(sku):
        return SearchCheatingDetector._get_sku_field(sku, "价格", "price", "skuPrice", "Price")

    def _get_sku_qty(sku):
        return SearchCheatingDetector._get_sku_field(sku, "库存", "qty", "skuQty", "stock", "quantity")

    def _check_sku_cheating(self, row):
        """E3: SKU作弊检测"""
        results = []
        rule_ref = self.rule_index.get_clause_ref(
            "全球速卖通搜索作弊通用规则",
            "4. SKU作弊",
        )

        price_info_str = str(row.get("价格信息", ""))
        if not price_info_str:
            return results

        # 价格信息列通常是JSON
        price_data = safe_parse_json(price_info_str)
        if not price_data:
            return results

        # 获取sku列表
        sku_list = []
        if "skuArray" in price_data:
            sku_list = price_data["skuArray"]
        elif "sku" in price_data:
            sku_list = price_data["sku"]

        if not sku_list or not isinstance(sku_list, list):
            return results

        # 收集所有活跃SKU（有库存、有价格的），废弃不用的零售价不参与评估
        all_prices = []
        active_prices = []
        zero_stock_count = 0
        zero_price_count = 0
        total_stock = 0
        for sku in sku_list:
            try:
                price_str = self._get_sku_price(sku)
                qty_str = self._get_sku_qty(sku)
                if price_str is None or qty_str is None:
                    continue
                price = float(price_str)
                qty = int(qty_str)
                all_prices.append(price)
                if price > 0 and qty > 0:
                    active_prices.append(price)
                if qty == 0:
                    zero_stock_count += 1
                if price == 0:
                    zero_price_count += 1
                total_stock += qty
            except (ValueError, TypeError):
                continue

        # 只用活跃SKU做价格评估
        prices = active_prices if active_prices else all_prices
        if not prices:
            return results

        max_price = max(prices)
        min_price = min(prices)

        # 价差超过10倍
        if min_price > 0 and max_price / min_price > SKU_PRICE_RATIO_MAX:
            results.append(self._make_result(
                risk_level="高",
                category="SKU价差异常",
                reason=f"SKU价格从${min_price:.2f}到${max_price:.2f}（价差{max_price / min_price:.1f}倍），超过{SKU_PRICE_RATIO_MAX}倍阈值，疑似SKU作弊（低价引流）",
                remedy="请确保SKU间价差合理，不要通过设置极低价SKU引流。如有不同规格应合理定价",
                rule_ref=rule_ref,
                min_price=min_price,
                max_price=max_price,
                price_ratio=max_price / min_price,
            ))

        # 价格异常（过高或过低）
        if max_price > SKU_PRICE_MAX:
            results.append(self._make_result(
                risk_level="高",
                category="SKU价格异常",
                reason=f"SKU最高价${max_price:.2f}，超过${SKU_PRICE_MAX}异常阈值，疑似价格异常SKU",
                remedy="请检查高价SKU是否设置错误，确保所有SKU价格合理",
                rule_ref=rule_ref,
                max_price=max_price,
            ))

        # SKU超低价检测：只用活跃SKU，排除零库存/零价格的废弃SKU
        if min_price < SKU_PRICE_MIN and min_price > 0 and active_prices:
            results.append(self._make_result(
                risk_level="高",
                category="SKU超低价",
                reason=f"SKU最低价${min_price:.2f}，低于${SKU_PRICE_MIN}阈值，疑似产品超低价违规",
                remedy="请检查低价SKU是否设置错误，避免以较大偏离正常销售价格的低价发布",
                rule_ref=rule_ref,
                min_price=min_price,
            ))

        # 零库存SKU
        if zero_stock_count > 0 and len(sku_list) > 1:
            results.append(self._make_result(
                risk_level="高",
                category="SKU零库存",
                reason=f"发现{zero_stock_count}个SKU库存为零，用户无法购买，属零库存SKU作弊",
                remedy="请为所有SKU设置合理库存，或删除不需要的SKU。零库存SKU可能被认定为SKU作弊",
                rule_ref=rule_ref,
                zero_stock_count=zero_stock_count,
            ))

        return results
