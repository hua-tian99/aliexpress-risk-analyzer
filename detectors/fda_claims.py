# -*- coding: utf-8 -*-
"""
H. FDA 非法宣称检测 — 标题+描述中的虚假 FDA 认证/医疗功效/保健品宣称

基于《不当发布行为规则》第三条：《全球速卖通产品发布政策》第七条。
"""
import re
from config import FDA_COMPILED
from detectors.base import BaseDetector
from utils.text_utils import normalize_text
from utils.ai_client import verify_prohibited_words
from rule_index import get_rule_index


class FDAClaimsDetector(BaseDetector):
    """FDA 非法宣称检测 — 正则 + AI 验证"""

    def __init__(self):
        super().__init__()
        self.rule_index = get_rule_index()
        self.rule_ref = self.rule_index.get_clause_ref(
            "全球速卖通其他不当发布行为规则",
            "3. 虚假描述",
        )

    def detect(self, row, context=None):
        results = []
        fields_to_check = []

        title = str(row.get("产品名称", ""))
        if title:
            fields_to_check.append(("标题", title))

        brief = str(row.get("产品简述", ""))
        if brief:
            fields_to_check.append(("产品简述", brief))

        desc1 = str(row.get("产品详细描述1", ""))
        desc2 = str(row.get("产品详细描述2", ""))
        desc_combined = desc1 + " " + desc2
        desc_text = re.sub(r"<[^>]+>", " ", desc_combined)
        desc_text = re.sub(r"\s+", " ", desc_text).strip()
        if desc_text:
            fields_to_check.append(("产品描述", desc_text))

        # 阶段1：正则扫描
        candidate_matches = []

        for field_name, text in fields_to_check:
            text_lower = normalize_text(text).lower()
            for cat, patterns in FDA_COMPILED.items():
                for pat in patterns:
                    m = pat.search(text_lower)
                    if m:
                        candidate_matches.append({
                            "category": cat,
                            "matched_word": m.group(),
                            "field_name": field_name,
                            "field_text": text,
                        })
                        break  # 每类每字段只报一次

        if not candidate_matches:
            return results

        # 阶段2：AI 二次验证
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
            is_violation = verdict.get("is_violation", True) if verdict else True
            ai_reason = verdict.get("ai_reason", "") if verdict else ""

            if not is_violation:
                continue

            cat = m["category"]
            keyword = m["matched_word"]
            field_name = m["field_name"]

            reason = f"【{field_name}】检测到{cat}关键词'{keyword}'。虚假FDA认证或非法医疗宣称违反平台规则"
            if ai_reason:
                reason += f" [AI判定: {ai_reason}]"

            results.append(self._make_result(
                risk_level="高",
                category=f"FDA-{cat}",
                reason=reason,
                remedy=f"请删除【{field_name}】中的虚假宣称内容'{keyword}'。只有经FDA正式批准的产品才可使用FDA认证标识，非医疗器械不得声称医疗功效",
                rule_ref=self.rule_ref,
                matched_keyword=keyword,
                matched_field=field_name,
                claim_category=cat,
                ai_verified=True,
                ai_reason=ai_reason,
            ))

        return results
