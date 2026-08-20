"""
检测器基类 — 所有检测器的统一接口
每个检测器返回: {risk_level, category, reason, remedy, rule_ref, ...}
"""


class BaseDetector:
    """检测器基类"""

    def __init__(self):
        self.name = self.__class__.__name__

    def detect(self, row, context=None):
        """
        对一行数据进行检测
        Args:
            row: dict, 一行Excel数据
            context: dict, 可选上下文（规则索引、其他行等）
        Returns:
            list[dict]: 检测结果列表（可能多个）
                每个结果包含:
                - risk_level: "高" | "中" | "低"
                - category: 违规分类
                - reason: 违规原因描述
                - remedy: 补救措施
                - rule_ref: 规则引用 dict {file, clause, summary, penalty, wiki_link}
                - 可选扩展字段 (image_index, ocr_text, html_fragment 等)
        """
        raise NotImplementedError

    def _make_result(self, risk_level, category, reason, remedy, rule_ref, **extra):
        """构造标准结果"""
        return {
            "risk_level": risk_level,
            "category": category,
            "reason": reason,
            "remedy": remedy,
            "rule_ref": rule_ref,
            **extra,
        }
