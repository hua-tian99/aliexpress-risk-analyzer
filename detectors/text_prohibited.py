"""
A. 违禁关键词检测 — 标题+描述+属性中的违禁品类关键词

上下文消歧规则（避免误报）：
- 正则上下文消歧作为第一道防线
- 千问 AI 作为第二道防线，对通过正则消歧的匹配做智能二次验证
"""
import re
from config import COMPILED_PROHIBITED
from detectors.base import BaseDetector
from utils.text_utils import normalize_text
from utils.ai_client import verify_prohibited_words
from rule_index import get_rule_index

# 上下文消歧规则：key=违禁词类别 -> list of (违禁词, safe_context_pattern)
# 当违禁词匹配的文本同时匹配 safe_context_pattern 时，跳过此结果
CONTEXT_EXCLUSIONS = [
    # "wine"在家电/家具语境中是合法商品（酒柜/酒架/酒具）
    ("酒精饮料", r"\bwine\b", r"\b(?:refrigerator|cooler|cabinet|fridge|rack|chiller|storage|cellar|holder|bar|set|gift|bottle|tasting|aerator|stopper|preserver|vacuum|pump|opener|pourer|glass|carafe|decanter|cooler bag|chiller sleeve|thermoelectric|compressor|dual[-\s]zone|wine\s?cooler|wine\s?fridge|wine\s?cabinet|wine\s?rack|wine\s?cellar)\b"),
    # "rum"在正常商品描述中
    ("酒精饮料", r"\brum\b", r"\b(?:cocktail|syrup|rum\s?cake|extract|flavou?r|essence|bakery|dessert|recipe|food)\b"),
    # "sex"在合成词中（Unisex/bisexual等）
    ("色情低俗", r"\bsex\b", r"\b(?:unisex|bisexual|intersex|transsexual)\b"),
    # "explosive"在安全警告语境中（"flammable and explosive gas"等），是安全说明而非卖爆炸物
    ("武器弹药类", r"\bexplosive\b", r"\b(?:flammable\s?(?:and|&|/)\s?explosive|explosive\s?gas|explosive\s?atmosphere|explosive\s?environment|keep\s?away\s?from|do\s?not\s?(?:use|put|place|store|expose|operate)|safety\s?instruction|warning|caution|danger|hazard)\b"),
]


class TextProhibitedDetector(BaseDetector):
    """禁限售违禁关键词检测"""

    def __init__(self):
        super().__init__()
        self.rule_index = get_rule_index()
        self.rule_ref_ban = self.rule_index.get_clause_ref(
            "全球速卖通禁限售规则(含违禁信息列表)"
        )
        self.rule_ref_interpret = self.rule_index.get_clause_ref(
            "全球速卖通禁限售违禁信息解读"
        )
        # 编译上下文消歧规则
        self._context_exclusions = []
        for cat, keyword_pat, context_pat in CONTEXT_EXCLUSIONS:
            self._context_exclusions.append((
                cat,
                re.compile(keyword_pat, re.IGNORECASE),
                re.compile(context_pat, re.IGNORECASE),
            ))

    def _is_safe_context(self, cat, matched_keyword, text):
        """检查是否在安全上下文中，避免误报"""
        text_lower = text.lower()
        for exc_cat, kw_pat, ctx_pat in self._context_exclusions:
            if exc_cat == cat and kw_pat.search(matched_keyword):
                if ctx_pat.search(text_lower):
                    return True
        return False

    def detect(self, row, context=None):
        results = []
        fields_to_check = []

        # 标题
        title = str(row.get("产品名称", ""))
        if title:
            fields_to_check.append(("标题", title))

        # 产品简述
        brief = str(row.get("产品简述", ""))
        if brief:
            fields_to_check.append(("产品简述", brief))

        # 产品详细描述1 & 2 (HTML文本)
        desc1 = str(row.get("产品详细描述1", ""))
        desc2 = str(row.get("产品详细描述2", ""))
        desc_combined = desc1 + " " + desc2
        desc_text = re.sub(r"<[^>]+>", " ", desc_combined)
        desc_text = re.sub(r"\s+", " ", desc_text).strip()
        if desc_text:
            fields_to_check.append(("产品描述", desc_text))

        # 系统属性
        sys_attrs = str(row.get("系统属性", ""))
        if sys_attrs:
            fields_to_check.append(("系统属性", sys_attrs))

        # 自定义属性
        cust_attrs = str(row.get("自定义属性", ""))
        if cust_attrs:
            fields_to_check.append(("自定义属性", cust_attrs))

        # 阶段1：正则扫描 + 上下文消歧 → 收集候选匹配
        candidate_matches = []  # [{category, matched_word, field_name, field_text}, ...]

        for field_name, text in fields_to_check:
            text_lower = normalize_text(text).lower()
            for cat, patterns in COMPILED_PROHIBITED.items():
                for pat in patterns:
                    m = pat.search(text_lower)
                    if m:
                        # 上下文消歧：检查是否在安全语境中
                        if self._is_safe_context(cat, m.group(), text):
                            continue
                        candidate_matches.append({
                            "category": cat,
                            "matched_word": m.group(),
                            "field_name": field_name,
                            "field_text": text,
                        })
                        break  # 每类只报告一次

        if not candidate_matches:
            return results

        # 阶段2：AI 二次验证 — 批量判定所有候选匹配是否真的构成违规
        product_name = title if title else ""
        ai_matches = [
            {"category": m["category"], "matched_word": m["matched_word"],
             "field_text": f"[{m['field_name']}] {m['field_text'][:300]}"}
            for m in candidate_matches
        ]
        ai_results = verify_prohibited_words(product_name, ai_matches)

        # 阶段3：只保留 AI 确认的违规
        for m in candidate_matches:
            verdict = ai_results.get(m["matched_word"])
            if verdict is None:
                # AI 未覆盖，保守处理：视为违规
                is_violation = True
                ai_reason = ""
            else:
                is_violation = verdict.get("is_violation", True)
                ai_reason = verdict.get("ai_reason", "")

            if not is_violation:
                continue  # AI 判定为非违规，跳过

            cat = m["category"]
            keyword = m["matched_word"]
            field_name = m["field_name"]

            # 规则引用
            if cat in ("毒品类", "武器弹药类", "管制刀具", "烟草类", "色情低俗",
                       "虚拟货币", "假币/伪造", "暴力歧视"):
                rule_ref = self.rule_index.get_clause_ref(
                    "全球速卖通禁限售规则(含违禁信息列表)",
                    f"第{['毒品','武器','管制器具','烟草','色情','非法用途','非法服务','收藏'].index(cat[:-1]) if cat[:-1] in ['毒品','武器','管制器具','烟草','色情'] else ''}类"
                )
            else:
                rule_ref = self.rule_ref_ban

            reason = f"【{field_name}】检测到违禁品类关键词'{keyword}'（类别：{cat}），违反平台禁限售规则"
            if ai_reason:
                reason += f" [AI判定: {ai_reason}]"

            results.append(self._make_result(
                risk_level="高",
                category="禁限售违禁关键词",
                reason=reason,
                remedy=f"请立即删除【{field_name}】中的违禁关键词'{keyword}'，如商品本身属于该品类请确认是否有平台授权。建议修改为合规描述",
                rule_ref=rule_ref,
                matched_keyword=keyword,
                matched_field=field_name,
                prohibited_category=cat,
                ai_verified=True,
                ai_reason=ai_reason,
            ))

        return results
