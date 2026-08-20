"""
速卖通规则索引器 — 扫描 Clippings 目录并构建规则字典
每条规则包括: file, clauses, summary, penalty, wiki_link
"""
import os
import re
import glob

from config import CLIPPINGS_DIR


class RuleIndex:
    """规则索引，启动时从 Clippings 扫描构建"""

    def __init__(self, clippings_dir=None):
        self.clippings_dir = clippings_dir or CLIPPINGS_DIR
        self.rules = {}       # filename -> {file, clauses, summary, penalty, wiki_link}
        self.all_files = []   # 所有 .md 文件路径
        self._scan()

    def _scan(self):
        """扫描 Clippings 目录下所有 .md 文件"""
        pattern = os.path.join(self.clippings_dir, "*.md")
        files = glob.glob(pattern)
        self.all_files = sorted(f for f in files if not os.path.basename(f).startswith("__"))
        for fp in self.all_files:
            fname = os.path.splitext(os.path.basename(fp))[0]
            self.rules[fname] = self._parse_file(fp)

    def _parse_file(self, filepath):
        """解析一个规则 Markdown 文件，提取条款、处罚等信息"""
        fname = os.path.splitext(os.path.basename(filepath))[0]
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # 去掉 YAML frontmatter
        body = content
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                body = parts[2]

        clauses = {}       # clause_id -> summary_text
        penalties = {}     # clause_id -> penalty_text
        wiki_link = f"[[{fname}]]"

        # 提取"最新版本修订日期"
        summary = ""
        m1 = re.search(r"最新版本修订日期[：:]\s*(.+)", body)
        if m1:
            summary = f"最新修订: {m1.group(1).strip()}"

        # 提取标题行（第一个 ## 或 # 后的文本）
        title_m = re.search(r"^#+\s+(.+)", body, re.MULTILINE)
        if title_m and not summary:
            summary = title_m.group(1).strip()

        # 提取第X条 / 第X章 / 第X节
        clause_pattern = re.compile(
            r"(第[一二三四五六七八九十百零\d]+[条章节]|"
            r"\d+[\.\、][\.\d]*\s*(?:定义|处罚|情景|举例|概述|温馨提示|风险举例|常见问题))",
            re.MULTILINE
        )
        # 先找所有 '第X条' 或 '第X章' 位置
        clause_matches = list(clause_pattern.finditer(body))
        for i, m in enumerate(clause_matches):
            clause_id = m.group(1).strip()
            # 找到从这个 clause 到下一个 clause 之间的文本
            start = m.end()
            end = clause_matches[i + 1].start() if i + 1 < len(clause_matches) else len(body)
            section_text = body[start:end].strip()
            # 提取纯文本摘要（去掉HTML标签）
            clean = re.sub(r"<[^>]+>", "", section_text)
            clean = re.sub(r"\s+", " ", clean)[:400].strip()
            clauses[clause_id] = clean

            # 提取处罚相关的句子（含"处罚"/"扣分"/"关闭"等词）
            penalty_sentences = []
            for line in section_text.split("\n"):
                if any(kw in line for kw in ["处罚", "扣分", "关闭", "冻结", "删除", "警告", "屏蔽"]):
                    penalty_clean = re.sub(r"<[^>]+>", "", line).strip()
                    if penalty_clean and len(penalty_clean) < 250:
                        penalty_sentences.append(penalty_clean)
            if penalty_sentences:
                penalties[clause_id] = "; ".join(penalty_sentences[:3])

        # 如果没提取到结构化条款，尝试提取 ## 标题层级
        if not clauses:
            headings = re.findall(r"^##\s+(.+)", body, re.MULTILINE)
            for h in headings:
                h_clean = h.strip()
                if h_clean and len(h_clean) < 100:
                    clauses[h_clean] = ""

        return {
            "file": fname,
            "filepath": filepath,
            "clauses": clauses,
            "penalties": penalties,
            "summary": summary,
            "wiki_link": wiki_link,
        }

    def get_rule(self, filename):
        """按文件名获取规则"""
        return self.rules.get(filename)

    def search_clauses(self, keyword):
        """搜索包含关键词的条款"""
        results = []
        for fname, rule in self.rules.items():
            for cid, ctext in rule["clauses"].items():
                if keyword.lower() in cid.lower() or keyword.lower() in ctext.lower():
                    results.append({
                        "file": fname,
                        "clause": cid,
                        "summary": ctext[:200],
                        "wiki_link": rule["wiki_link"],
                    })
        return results

    def get_clause_ref(self, filename, clause_id=None):
        """获取规则引用对象"""
        rule = self.rules.get(filename)
        if not rule:
            return {
                "file": filename,
                "clause": clause_id or "",
                "summary": "",
                "penalty": "",
                "wiki_link": f"[[{filename}]]",
            }
        summary = ""
        penalty = ""
        if clause_id:
            summary = rule["clauses"].get(clause_id, "")
            penalty = rule["penalties"].get(clause_id, "")
        return {
            "file": filename,
            "clause": clause_id or "",
            "summary": summary[:300] if summary else rule.get("summary", ""),
            "penalty": penalty[:300] if penalty else "",
            "wiki_link": rule["wiki_link"],
        }

    def list_all(self):
        """列出所有规则文件"""
        return list(self.rules.keys())


# 模块级单例（在 app.py 启动时初始化）
_rule_index = None


def get_rule_index():
    global _rule_index
    if _rule_index is None:
        _rule_index = RuleIndex()
    return _rule_index


def rebuild_index():
    global _rule_index
    _rule_index = RuleIndex()
    return _rule_index
