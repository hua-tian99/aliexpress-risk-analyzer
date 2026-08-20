"""HTML 结构化解析器 — 不剥离HTML，深度分析结构"""
from bs4 import BeautifulSoup, Tag
import re
from config import HIDDEN_STYLE_PATTERNS


class HtmlParsedResult:
    """HTML解析结果"""
    def __init__(self, html_text):
        self.raw_html = html_text
        self.soup = None
        self.visible_text = ""         # 可见文本
        self.hidden_text = ""          # 隐藏元素的文本
        self.tables = []               # 表格数据 [{key: val, ...}]
        self.external_links = []       # 外部链接 [{url, text}]
        self.image_urls = []           # 图片URL列表
        self.hidden_elements = []      # 隐藏元素列表 [{tag, method, text}]
        self.meta_text = ""            # <meta>标签内容
        if html_text and html_text.strip():
            self._parse()

    def _parse(self):
        soup = BeautifulSoup(self.raw_html, "html.parser")
        self.soup = soup

        # 1. 提取图片链接
        for img in soup.find_all("img"):
            src = img.get("src", "") or img.get("data-src", "")
            if src:
                self.image_urls.append(src)

        # 2. 提取外部链接
        for a_tag in soup.find_all("a"):
            href = a_tag.get("href", "").strip()
            if href and href != "#" and not href.startswith("javascript:"):
                self.external_links.append({
                    "url": href,
                    "text": a_tag.get_text(strip=True),
                })

        # 3. 提取隐藏元素
        for el in soup.find_all(True):  # 所有标签
            style = el.get("style", "")
            if not style:
                continue
            for method_name, pattern in HIDDEN_STYLE_PATTERNS.items():
                if pattern.search(style):
                    hidden_text = el.get_text(strip=True)
                    if hidden_text:
                        self.hidden_elements.append({
                            "tag": el.name,
                            "method": method_name,
                            "text": hidden_text,
                        })

        # 4. 收集隐藏文本和可见文本
        # 可见文本：所有非隐藏元素的文本
        for el in soup.find_all(True):
            style = el.get("style", "")
            is_hidden = any(p.search(style) for p in HIDDEN_STYLE_PATTERNS.values())
            el_text = el.get_text(separator=" ", strip=True)
            if not el_text:
                continue
            if is_hidden:
                self.hidden_text += " " + el_text
            else:
                self.visible_text += " " + el_text

        # 如果没有分离出可见文本，取整个body文本
        if not self.visible_text.strip():
            body = soup.find("body")
            if body:
                self.visible_text = body.get_text(separator=" ", strip=True)
            else:
                self.visible_text = soup.get_text(separator=" ", strip=True)

        # 5. 提取表格数据
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            table_data = {}
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True)
                    val = cells[1].get_text(strip=True)
                    if key and val:
                        table_data[key] = val
            if table_data:
                self.tables.append(table_data)

        # 6. meta标签内容
        for meta in soup.find_all("meta"):
            content = meta.get("content", "").strip()
            if content:
                self.meta_text += " " + content


def parse_html(html_text):
    """解析HTML，返回HtmlParsedResult"""
    return HtmlParsedResult(html_text)


def extract_visible_text(html_text):
    """快速提取可见文本（不全面解析）"""
    return HtmlParsedResult(html_text).visible_text


def extract_all_text(html_text):
    """提取所有文本（包括隐藏）"""
    r = HtmlParsedResult(html_text)
    return r.visible_text + " " + r.hidden_text
