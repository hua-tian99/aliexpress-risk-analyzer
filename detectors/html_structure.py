"""
C. HTML结构分析 — 隐藏信息 / CSS作弊 / 外部链接 / 表格比对
不剥离HTML，深度解析结构
"""
import re
from bs4 import BeautifulSoup
from config import AE_OFFICIAL_DOMAINS, HIDDEN_STYLE_PATTERNS, CONTACT_PATTERNS, COMPILED_PROHIBITED
from detectors.base import BaseDetector
from utils.html_parser import HtmlParsedResult
from utils.text_utils import normalize_text, count_keyword_frequency, find_contacts_in_text, is_structured_data
from rule_index import get_rule_index


class HtmlStructureDetector(BaseDetector):
    """HTML结构违规检测"""

    def __init__(self):
        super().__init__()
        self.rule_index = get_rule_index()

    def detect(self, row, context=None):
        results = []

        desc1 = str(row.get("产品详细描述1", ""))
        desc2 = str(row.get("产品详细描述2", ""))
        desc_raw = (desc1 + " " + desc2).strip()

        if not desc_raw:
            return results

        parsed = HtmlParsedResult(desc_raw)

        # C1: 隐藏信息检测
        hidden_results = self._check_hidden_elements(parsed)
        results.extend(hidden_results)

        # C2: 外部链接检测
        link_results = self._check_external_links(parsed)
        results.extend(link_results)

        # C3: 描述与系统属性不一致
        if parsed.tables:
            table_results = self._check_table_vs_attrs(parsed, row)
            results.extend(table_results)

        # C4: CSS中隐藏的关键词堆砌
        if parsed.hidden_text.strip():
            kw_results = self._check_hidden_keyword_stuffing(parsed)
            results.extend(kw_results)

        return results

    def _check_hidden_elements(self, parsed):
        """C1: 检测隐藏元素中的违规内容

        跳过平台注入的结构化数据（JSON/配置），只检查人工编写内容。
        """
        results = []
        rule_ref = self.rule_index.get_clause_ref(
            "全球速卖通其他不当发布行为规则",
            "二、2、躲避平台规则的",
        )

        if not parsed.hidden_elements:
            return results

        # 过滤掉平台注入的结构化数据，只保留人工编写的内容
        meaningful_elements = [
            e for e in parsed.hidden_elements
            if not is_structured_data(e["text"])
        ]

        # 如果过滤后没有有意义的隐藏元素，不报告
        if not meaningful_elements:
            return results

        hidden_text = " ".join(e["text"] for e in meaningful_elements)
        methods_used = list(set(e["method"] for e in meaningful_elements))
        methods_str = "、".join(methods_used)

        # 检查隐藏文本中是否含联系方式（使用统一的手机号上下文验证）
        contact_found = [c[0] for c in find_contacts_in_text(hidden_text)]

        # 检查隐藏文本中是否含违禁词
        prohibited_found = []
        for cat, patterns in COMPILED_PROHIBITED.items():
            for pat in patterns:
                if pat.search(hidden_text):
                    prohibited_found.append(cat)
                    break

        # 报告隐藏元素数量
        n_hidden = len(meaningful_elements)
        reasons_parts = []

        if contact_found:
            reasons_parts.append(f"使用{methods_str}技术隐藏了联系方式({','.join(contact_found)})")
        if prohibited_found:
            reasons_parts.append(f"隐藏文本含违禁关键词({','.join(prohibited_found)})")

        details = f"发现{n_hidden}个隐藏元素(方法:{methods_str})"
        if contact_found or prohibited_found:
            details += "，" + "，".join(reasons_parts)

        if contact_found or prohibited_found or n_hidden > 0:
            results.append(self._make_result(
                risk_level="高" if prohibited_found else "中",
                category="HTML隐藏信息",
                reason=details + "。使用CSS隐藏技术放置信息属于故意规避平台规则的行为",
                remedy="请移除所有使用CSS隐藏技术(display:none/visibility:hidden/opacity:0等)的元素，将需要展示的信息正常显示在页面中",
                rule_ref=rule_ref,
                hidden_element_count=n_hidden,
                hidden_methods=methods_used,
                html_fragment=self._get_sample_html(parsed),
            ))

        return results

    def _check_external_links(self, parsed):
        """C2: 检测外部链接"""
        results = []
        rule_ref = self.rule_index.get_clause_ref(
            "全球速卖通卖家基础规则（违规及处罚规则）",
            "第八十六条(五) 留有联系信息或广告商品",
        )

        external_links = []
        for link in parsed.external_links:
            url = link["url"].lower()
            domain = re.search(r"https?://([^/]+)", url)
            if domain:
                domain_name = domain.group(1)
                # 排除速卖通官方域名
                is_official = any(
                    official in domain_name or domain_name.endswith("." + official)
                    for official in AE_OFFICIAL_DOMAINS
                )
                if not is_official:
                    external_links.append(link)

        if external_links:
            urls_str = "; ".join(l["url"] for l in external_links[:5])
            results.append(self._make_result(
                risk_level="高",
                category="外部链接引流",
                reason=f"产品描述中发现{len(external_links)}个非速卖通外部链接：{urls_str}。产品描述禁止放置非速卖通平台的网站链接",
                remedy="请删除所有非速卖通官方域名的外部链接。如需引用参考内容，请直接在描述中说明",
                rule_ref=rule_ref,
                external_links=external_links,
            ))

        return results

    def _check_table_vs_attrs(self, parsed, row):
        """C3: 描述表格 vs 系统属性不一致"""
        results = []
        rule_ref = self.rule_index.get_clause_ref(
            "全球速卖通搜索作弊通用规则",
            "3. 属性错选",
        )

        # 提取系统属性
        sys_attrs_text = str(row.get("系统属性", ""))
        # 系统属性通常是 JSON 或 key:value 格式
        sys_attrs = {}
        if sys_attrs_text:
            # 尝试解析 key:value 对
            for pair in sys_attrs_text.split(";"):
                if ":" in pair:
                    k, v = pair.split(":", 1)
                    sys_attrs[k.strip().lower()] = v.strip().lower()
                elif "：" in pair:
                    k, v = pair.split("：", 1)
                    sys_attrs[k.strip().lower()] = v.strip().lower()

        for table_dict in parsed.tables:
            for key, val in table_dict.items():
                key_lower = key.strip().lower()
                val_lower = val.strip().lower()
                # 检查关键属性（材质、品牌等）
                for attr_key, attr_val in sys_attrs.items():
                    # 如果表格的key包含系统属性的key
                    if any(kw in key_lower for kw in ["material", "材质", "面料",
                                                       "cotton", "棉", "polyester",
                                                       "涤纶", "leather", "皮"]):
                        # 比对值
                        if attr_key in ("material", "材质", "面料"):
                            kw_val = attr_val.strip().lower()
                            if kw_val and val_lower and kw_val != val_lower:
                                if kw_val not in val_lower and val_lower not in kw_val:
                                    results.append(self._make_result(
                                        risk_level="中",
                                        category="描述与属性不一致",
                                        reason=f"产品描述表格说'{key}: {val}'但系统属性选择'{attr_key}: {attr_val}'，两者不一致",
                                        remedy="请确保产品描述表格中的参数与系统属性选择的参数一致，修改其中一方使匹配",
                                        rule_ref=rule_ref,
                                        table_key=key,
                                        table_val=val,
                                        attr_key=attr_key,
                                        attr_val=attr_val,
                                    ))
        return results

    def _check_hidden_keyword_stuffing(self, parsed):
        """C4: 隐藏文本中的关键词堆砌

        跳过平台注入的结构化数据，只检查人工编写内容。
        """
        results = []
        rule_ref = self.rule_index.get_clause_ref(
            "全球速卖通搜索作弊通用规则",
            "2.1 标题描述违规",
        )

        # 过滤掉平台注入的结构化数据
        meaningful_elements = [
            e for e in parsed.hidden_elements
            if not is_structured_data(e["text"])
        ]
        hidden_text = " ".join(e["text"] for e in meaningful_elements)
        if not hidden_text.strip():
            return results
        freq = count_keyword_frequency(hidden_text)
        stuffed_words = {k: v for k, v in freq.items() if v >= 3}

        if stuffed_words:
            kw_detail = "、".join(f"'{k}'({v}次)" for k, v in
                                  sorted(stuffed_words.items(), key=lambda x: -x[1])[:10])
            results.append(self._make_result(
                risk_level="中",
                category="HTML隐藏关键词堆砌",
                reason=f"产品描述隐藏文本中检测到关键词堆砌：{kw_detail}。隐藏堆砌关键词是严重搜索作弊行为",
                remedy="删除隐藏元素中的所有堆砌关键词，确保所有展示内容对消费者正常可见",
                rule_ref=rule_ref,
                stuffed_words=stuffed_words,
            ))

        return results

    def _get_sample_html(self, parsed):
        """获取隐藏元素的HTML片段（用于展示）"""
        if parsed.hidden_elements:
            fragments = []
            for el in parsed.hidden_elements[:3]:
                tag = el["tag"]
                method = el["method"]
                text = el["text"][:100]
                fragments.append(f"<{tag} style='...{method}...'>{text}</{tag}>")
            return "\n".join(fragments)
        return ""
