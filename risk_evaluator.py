"""
风险聚合器 — 聚合所有检测结果，确定最终风险等级
拼接"原因"和"补救措施"字段
"""
from rule_index import get_rule_index


class RiskEvaluator:
    """聚合所有检测结果"""

    RISK_ORDER = {"高": 3, "中": 2, "低": 1, "": 0}

    def __init__(self, detector_results):
        """
        Args:
            detector_results: list[dict], 所有检测器返回的结果列表
        """
        self.results = detector_results if detector_results else []

    @property
    def has_high_risk(self):
        return any(r.get("risk_level") == "高" for r in self.results)

    @property
    def has_medium_risk(self):
        return any(r.get("risk_level") == "中" for r in self.results)

    @property
    def has_low_risk(self):
        return any(r.get("risk_level") == "低" for r in self.results)

    def get_overall_risk(self):
        """获取聚合风险等级"""
        if self.has_high_risk:
            return "高风险有其他违规风险"
        if self.has_medium_risk:
            return "中风险只警告不扣分"
        if self.has_low_risk:
            return "低风险无违规风险"
        return "低风险无违规风险"

    def _format_reasons_by_level(self, risk_level):
        """Format reasons for a specific risk level"""
        filtered = [r for r in self.results if r.get("risk_level") == risk_level]
        if not filtered:
            return ""

        lines = []
        for idx, r in enumerate(filtered, 1):
            rule_ref = r.get("rule_ref", {})
            file_name = rule_ref.get("file", "")
            clause = rule_ref.get("clause", "")
            rule_summary = rule_ref.get("summary", "")

            rule_info = f"[{file_name}]"
            if clause:
                rule_info += f" {clause}"

            line = f"{idx}. {rule_info} {r.get('reason', '')}"
            if rule_summary:
                line += f"\n   ↳ 规则: {rule_summary[:200]}"

            lines.append(line)

        return "\n\n".join(lines)

    def _format_remedies_by_level(self, risk_level):
        """Format remedies for a specific risk level"""
        filtered = [r for r in self.results if r.get("risk_level") == risk_level]
        if not filtered:
            return ""

        lines = []
        for idx, r in enumerate(filtered, 1):
            line = f"{idx}. {r.get('remedy', '')}"
            lines.append(line)

        return "\n\n".join(lines)

    def format_high_risk_reasons(self):
        return self._format_reasons_by_level("高")

    def format_high_risk_remedies(self):
        return self._format_remedies_by_level("高")

    def format_medium_risk_reasons(self):
        return self._format_reasons_by_level("中")

    def format_medium_risk_remedies(self):
        return self._format_remedies_by_level("中")

    def format_reasons(self):
        """格式化为多行原因文本（带规则引用），兼容旧API"""
        if not self.results:
            return ""

        sorted_results = sorted(
            self.results,
            key=lambda r: -self.RISK_ORDER.get(r.get("risk_level", ""), 0),
        )

        lines = []
        for idx, r in enumerate(sorted_results, 1):
            rule_ref = r.get("rule_ref", {})
            file_name = rule_ref.get("file", "")
            clause = rule_ref.get("clause", "")
            rule_summary = rule_ref.get("summary", "")

            rule_info = f"[{file_name}]"
            if clause:
                rule_info += f" {clause}"

            line = f"{idx}. {rule_info} {r.get('reason', '')}"
            if rule_summary:
                line += f"\n   ↳ 规则: {rule_summary[:200]}"

            lines.append(line)

        return "\n\n".join(lines)

    def format_remedies(self):
        """格式化为多行补救措施，兼容旧API"""
        if not self.results:
            return ""

        sorted_results = sorted(
            self.results,
            key=lambda r: -self.RISK_ORDER.get(r.get("risk_level", ""), 0),
        )

        lines = []
        for idx, r in enumerate(sorted_results, 1):
            line = f"{idx}. {r.get('remedy', '')}"
            lines.append(line)

        return "\n\n".join(lines)

    def format_reasons_html(self):
        """HTML格式的原因（含规则Wiki链接），供前端展示"""
        if not self.results:
            return "<p>未检测到违规</p>"

        sorted_results = sorted(
            self.results,
            key=lambda r: -self.RISK_ORDER.get(r.get("risk_level", ""), 0),
        )

        parts = []
        for idx, r in enumerate(sorted_results, 1):
            rule_ref = r.get("rule_ref", {})
            file_name = rule_ref.get("file", "")
            clause = rule_ref.get("clause", "")
            rule_summary = rule_ref.get("summary", "")
            wiki_link = rule_ref.get("wiki_link", "")

            risk_symbol = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(r.get("risk_level", ""), "")

            html = f'<div class="risk-item risk-{r.get("risk_level", "low")}">'
            html += f'<div class="risk-header">{risk_symbol} <strong>[{r.get("category", "")}]</strong> {r.get("reason", "")}</div>'
            html += f'<div class="risk-meta">规则文件: <code>{wiki_link}</code>'
            if clause:
                html += f' — {clause}'
            html += '</div>'
            if rule_summary:
                html += f'<div class="risk-rule-summary">{rule_summary[:300]}</div>'
            html += '</div>'
            parts.append(html)

        return "\n".join(parts)

    def get_rule_refs(self):
        """获取所有规则引用（去重）"""
        seen = set()
        refs = []
        for r in self.results:
            ref = r.get("rule_ref", {})
            key = (ref.get("file", ""), ref.get("clause", ""))
            if key not in seen:
                seen.add(key)
                refs.append(ref)
        return refs
