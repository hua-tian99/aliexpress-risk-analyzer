"""
B. 联系方式泄露检测 — 标题+描述+属性中的联系方式
"""
import re
from config import CONTACT_PATTERNS
from detectors.base import BaseDetector
from utils.text_utils import normalize_text, find_contacts_in_text
from utils.html_parser import HtmlParsedResult
from rule_index import get_rule_index


class ContactLeakDetector(BaseDetector):
    """联系方式泄露检测（文本）"""

    def __init__(self):
        super().__init__()
        self.rule_index = get_rule_index()
        self.rule_ref = self.rule_index.get_clause_ref(
            "全球速卖通卖家基础规则（违规及处罚规则）",
            "第八十六条(五) 留有联系信息或广告商品",
        )

    def detect(self, row, context=None):
        results = []
        fields_to_check = {}

        # 标题
        title = str(row.get("产品名称", ""))
        if title:
            fields_to_check["标题"] = title

        # 产品简述
        brief = str(row.get("产品简述", ""))
        if brief:
            fields_to_check["产品简述"] = brief

        # 产品详细描述1 & 2 — 分别检测可见文本和隐藏文本
        desc1 = str(row.get("产品详细描述1", ""))
        desc2 = str(row.get("产品详细描述2", ""))
        desc_raw = desc1 + " " + desc2
        if desc_raw.strip():
            parsed = HtmlParsedResult(desc_raw)
            # 可见文本
            if parsed.visible_text.strip():
                fields_to_check["产品描述(可见文本)"] = parsed.visible_text
            # 隐藏文本 — 故意隐藏联系方式=加重违规
            if parsed.hidden_text.strip():
                hidden_matches = find_contacts_in_text(parsed.hidden_text)
                if hidden_matches:
                    results.extend(self._make_contact_results(
                        "产品描述(隐藏文本)", parsed.hidden_text, hidden_matches,
                        extra_note="（信息位于HTML隐藏元素中，属故意规避行为，情节更严重）"
                    ))

        # 系统属性
        sys_attrs = str(row.get("系统属性", ""))
        if sys_attrs:
            fields_to_check["系统属性"] = sys_attrs

        # 自定义属性
        cust_attrs = str(row.get("自定义属性", ""))
        if cust_attrs:
            fields_to_check["自定义属性"] = cust_attrs

        # 逐字段检测
        for field_name, text in fields_to_check.items():
            matches = find_contacts_in_text(text)
            if matches:
                results.extend(self._make_contact_results(field_name, text, matches))

        return results

    def _make_contact_results(self, field_name, text, matches, extra_note=""):
        """构造联系方式结果"""
        results = []
        for contact_type, matched_text in matches:
            reasons_detail = "、".join(set(c[0] for c in matches))
            reason = f"【{field_name}】检测到{reasons_detail}联系方式：'{matched_text}'{extra_note}。任何字段或图片中禁止出现联系方式，如邮箱、微信、手机号、QQ等"
            remedy_parts = []
            if "邮箱" in reasons_detail:
                remedy_parts.append(f"删除邮箱地址")
            if "微信" in reasons_detail:
                remedy_parts.append(f"删除微信信息")
            if "手机号" in reasons_detail or "电话" in reasons_detail:
                remedy_parts.append(f"删除手机号码")
            if "WhatsApp" in reasons_detail:
                remedy_parts.append(f"删除WhatsApp联系方式")
            remedy = f"请立即从【{field_name}】中删除所有联系方式信息。{'；'.join(remedy_parts)}。根据规则第八十六条(五)，任何字段或图片中禁止出现联系方式"

            results.append(self._make_result(
                risk_level="中",
                category="联系方式泄露",
                reason=reason,
                remedy=remedy,
                rule_ref=self.rule_ref,
                contact_type="、".join(set(c[0] for c in matches)),
                matched_text=matched_text,
                matched_field=field_name,
            ))
        return results
