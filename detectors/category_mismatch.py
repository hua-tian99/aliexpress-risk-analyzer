# -*- coding: utf-8 -*-
"""
G. 类目错放检测 — 层级关键词匹配 + AI 兜底

L1 约束模式（有"一级类目"列）：
  确定性层级匹配：先匹配 L4 → 再匹配 L3 → 都不匹配则提示人工核实。
  不依赖 AI，避免 LLM 幻觉导致的跨 L1 误判。

全树模式（无"一级类目"列）：
  AI 判断 + 关键词兜底（兼容旧版行为）。
"""
import re
from detectors.base import BaseDetector
from utils.category_loader import (
    get_category_name,
    format_tree_for_prompt,
    search_categories,
    find_closest_path,
    is_valid_path,
)
from utils.ai_client import _call_qwen, _parse_json_response
from rule_index import get_rule_index

# AI prompt — used when NO L1 hint is available (full tree)
CATEGORY_MISMATCH_SYSTEM_FULL = """You are an AliExpress category auditor. Below is the COMPLETE AliExpress category tree. Your job: determine if the product's chosen category is clearly wrong.

{category_tree}

--- RULES ---
Be VERY conservative — only flag the most obvious, indefensible category mistakes.

ONLY flag these TWO cases:
1. PHYSICAL PRODUCT in SPECIAL CATEGORY: The product is a tangible item but the category is for shipping fees, price differences, VIP links, gifts, coupons, deposits, prepayments, dropshipping, or customization services.
2. ABSURD DEPARTMENT MISMATCH: The product belongs to a completely unrelated department — different Level-1 category AND different product type.

Do NOT flag:
- Any product in Tools/Electronics/Home/Garden/Sports/Toys that is even remotely related.
- Sub-category precision issues within the SAME Level-1 or Level-2 branch.
- Products where the chosen sub-category is close enough to the correct one.

--- OUTPUT ---
Return ONLY strict JSON:
{{"is_mismatch": true/false, "correct_path": "L1 > L2 > L3 > L4", "reasoning": "why (15 words max)"}}

If is_mismatch is false, set correct_path to empty string "".
If is_mismatch is true, correct_path MUST be an EXACT path copied from the category tree above."""


CATEGORY_MISMATCH_USER = """Product: {product_title}
Description: {description}
Seller chose category: {chosen_category}

{task_instruction}"""


class CategoryMismatchDetector(BaseDetector):
    """类目错放检测 — AI 判断明显错放（AI 优先，关键词兜底）"""

    def __init__(self):
        super().__init__()
        self.rule_index = get_rule_index()
        self.rule_ref = self.rule_index.get_clause_ref(
            "全球速卖通搜索作弊通用规则",
            "1. 类目错放",
        )

    def detect(self, row, context=None):
        results = []

        category_id = str(row.get("产品类型", "")).strip()
        if not category_id:
            return results

        chosen_category = get_category_name(category_id)
        # Normalize inconsistent separators in category path
        norm_path = chosen_category.replace(" -> ", ">").replace("->", ">")
        parts = [p.strip() for p in norm_path.split(">")]
        chosen_name = parts[-1] if len(parts) > 1 else chosen_category
        chosen_l1 = parts[0] if parts else ""

        title = str(row.get("产品名称", "")).strip()
        if not title:
            return results

        # Read the L1 hint column — tells us which L1 the product belongs to.
        # Supports both common column names: "一级类目" and "一级目录"
        l1_hint = str(row.get("一级类目", "") or row.get("一级目录", "")).strip()

        # Currently only 美容健康 is supported for category mismatch detection
        if l1_hint != "美容健康":
            return results

        # Build description for context
        brief = str(row.get("产品简述", "")).strip()
        desc1 = str(row.get("产品详细描述1", "")).strip()
        desc2 = str(row.get("产品详细描述2", "")).strip()
        desc_combined = brief
        if desc1 or desc2:
            desc_text = re.sub(r"<[^>]+>", " ", desc1 + " " + desc2)
            desc_text = re.sub(r"\s+", " ", desc_text).strip()
            if desc_combined:
                desc_combined += " " + desc_text
            else:
                desc_combined = desc_text

        if l1_hint:
            # ── L1约束模式：树查找 + AI相关度打分 ──
            from utils.category_loader import match_category_tiered
            from utils.ai_client import score_category_match

            # Extract seller's chosen L4 and L3 from the category path
            # Normalize separators: handle both "->" and " -> " (category mapping
            # uses inconsistent separators — "->" between L1-L3, " -> " before L4)
            norm_path = chosen_category.replace(" -> ", ">").replace("->", ">")
            chosen_parts = [p.strip() for p in norm_path.split(">")]
            chosen_l4 = chosen_parts[3] if len(chosen_parts) > 3 else ""
            chosen_l3 = chosen_parts[2] if len(chosen_parts) > 2 else ""

            # Step 1: Tree lookup — does seller's L4/L3 exist in the L1 subtree?
            matched = match_category_tiered(chosen_l4, chosen_l3, l1_hint)

            if not matched:
                # Seller's L4/L3 not in this L1 tree → wrong L1
                results.append(self._make_result(
                    risk_level="中",
                    category="类目错放",
                    reason=(
                        f"产品所选类目'{chosen_name}'（类目ID: {category_id}）"
                        f"不在'{l1_hint}'一级类目下。"
                        f"请核实该产品类目存放，有类目错放风险"
                    ),
                    remedy="请人工核实产品是否放置在正确的类目下",
                    rule_ref=self.rule_ref,
                    chosen_category=chosen_name,
                    chosen_category_id=category_id,
                    chosen_category_path=chosen_category,
                    correct_category_path="",
                    ai_verified=False,
                    ai_reason="类目树查找无匹配",
                ))
                return results

            matched_path, matched_level = matched

            # Step 2: AI score — how well does the product match this path?
            score_result = score_category_match(
                title, desc_combined[:200] if desc_combined else "", matched_path
            )

            if score_result and score_result["score"] >= 50:
                # High confidence match — product is correctly categorized
                return results

            # Step 3: Low AI score → search for better alternative within same L1
            ai_reason = score_result["reason"] if score_result else "AI打分失败"
            ai_score = score_result["score"] if score_result else 0

            alternative = search_categories(title, top_n=1, l1_filter=l1_hint)
            if alternative:
                alt_path, alt_score = alternative[0]
                if alt_path != matched_path and alt_score >= 0.3:
                    # Found a better category within the same L1
                    is_mismatch = True
                    correct_path = alt_path
                    reasoning = (
                        f"AI评分: {ai_score}/100（{ai_reason}），"
                        f"关键词匹配推荐: {alt_path}"
                    )
                    ai_used = False
                    # Fall through to common output below
                else:
                    # Alternative not meaningfully different → uncertain
                    results.append(self._make_result(
                        risk_level="中",
                        category="类目错放",
                        reason=(
                            f"AI对'{chosen_name}'与'{matched_path}'的匹配度评分仅{ai_score}分"
                            f"（{ai_reason}）。请核实该产品类目存放，有类目错放风险"
                        ),
                        remedy="请人工核实产品是否放置在正确的类目下",
                        rule_ref=self.rule_ref,
                        chosen_category=chosen_name,
                        chosen_category_id=category_id,
                        chosen_category_path=chosen_category,
                        correct_category_path="",
                        ai_verified=True,
                        ai_reason=f"AI评分{ai_score}: {ai_reason}",
                    ))
                    return results
            else:
                # No alternative found → uncertain
                results.append(self._make_result(
                    risk_level="中",
                    category="类目错放",
                    reason=(
                        f"AI对'{chosen_name}'与'{matched_path}'的匹配度评分仅{ai_score}分"
                        f"（{ai_reason}），且未找到更合适的替代类目。"
                        f"请核实该产品类目存放，有类目错放风险"
                    ),
                    remedy="请人工核实产品是否放置在正确的类目下",
                    rule_ref=self.rule_ref,
                    chosen_category=chosen_name,
                    chosen_category_id=category_id,
                    chosen_category_path=chosen_category,
                    correct_category_path="",
                    ai_verified=True,
                    ai_reason=f"AI评分{ai_score}: {ai_reason}",
                ))
                return results
        else:
            # ── 全树模式（无L1 hint）：保留AI + 关键词兜底 ──
            tree_prompt = format_tree_for_prompt()
            system_prompt = CATEGORY_MISMATCH_SYSTEM_FULL.format(category_tree=tree_prompt)
            task_instruction = (
                "Is this a clearly wrong category? Only flag if it is OBVIOUSLY "
                "incorrect at the Level-1/Level-2 level."
            )

            user_prompt = CATEGORY_MISMATCH_USER.format(
                product_title=title,
                description=desc_combined[:400] if desc_combined else "(no description)",
                chosen_category=chosen_category,
                task_instruction=task_instruction,
            )

            response = _call_qwen([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ], max_tokens=300)

            parsed = _parse_json_response(response)

            is_mismatch = False
            correct_path = ""
            reasoning = ""
            ai_used = True

            if parsed and "is_mismatch" in parsed:
                is_mismatch = parsed.get("is_mismatch", False)
                correct_path = parsed.get("correct_path", "")
                reasoning = parsed.get("reasoning", "")
            else:
                # AI 失败 → 关键词兜底
                ai_used = False
                fallback = find_closest_path(title, top_n=1, l1_filter=None)
                if fallback:
                    best_path, score = fallback[0]
                    if score >= 0.3:
                        fallback_l1 = best_path.split(" > ")[0] if " > " in best_path else ""
                        if chosen_l1 and fallback_l1 and chosen_l1 != fallback_l1:
                            is_mismatch = True
                            correct_path = best_path
                            reasoning = f"关键词匹配(L1不同): {chosen_l1} → {fallback_l1}"

            if not is_mismatch:
                return results

            # Validate correct_path against the tree
            if correct_path and not is_valid_path(correct_path):
                matched = find_closest_path(correct_path, top_n=1, l1_filter=None)
                if matched:
                    correct_path = matched[0][0]

            # If still no valid path, fallback search (full tree)
            if not correct_path or not is_valid_path(correct_path):
                fallback = search_categories(title, top_n=1)
                if fallback:
                    correct_path = fallback[0][0]

            if not correct_path:
                return results

        # ── 公共输出：构建结果 ──
        # Determine risk level: beauty/health/medical → high, others → medium
        health_kw = ["beauty", "health", "medical", "medicine", "美容", "健康", "医疗", "医药",
                     "美妆", "护肤", "保健", "hair", "skin", "makeup", "cosmetic", "fitness"]
        combined = (chosen_category + " " + correct_path).lower()
        is_health = any(kw.lower() in combined for kw in health_kw)
        risk_level = "高" if is_health else "中"

        # Build reason
        reason = f"产品实际类型应为'{correct_path}'，但选择了'{chosen_name}'（类目ID: {category_id}）"
        if l1_hint:
            reason += f"（一级类目: {l1_hint}）"
        if reasoning:
            reason += f"。{reasoning}"
        if not ai_used:
            reason += "（注意：基于关键词匹配，非AI判断，仅供参考）"

        remedy = f"请将产品从'{chosen_name}'类目移至正确类目。推荐路径: {correct_path}"

        results.append(self._make_result(
            risk_level=risk_level,
            category="类目错放",
            reason=reason,
            remedy=remedy,
            rule_ref=self.rule_ref,
            chosen_category=chosen_name,
            chosen_category_id=category_id,
            chosen_category_path=chosen_category,
            correct_category_path=correct_path,
            ai_verified=ai_used,
            ai_reason=reasoning,
        ))

        return results
