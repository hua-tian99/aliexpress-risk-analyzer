"""
速卖通在线产品违规风险分析 — Flask Web 应用
"""
import os
import sys
import json
import traceback
import uuid
from datetime import datetime

from flask import Flask, request, jsonify, render_template, send_file, session

# 修正导入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import UPLOAD_DIR
from utils.excel_io import read_excel
from rule_index import get_rule_index, rebuild_index
from output_writer import OutputWriter

# 初始化Flask
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR

# 确保目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 全局状态
analysis_state = {
    "raw_df": None,
    "all_results": None,
    "output_path": None,
    "is_analyzing": False,
    "progress": 0,
    "total_products": 0,
}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {"xlsx", "xls"}


# ========== 路由 ==========

@app.route("/")
def index():
    """主页面"""
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload_file():
    """上传Excel文件"""
    if "file" not in request.files:
        return jsonify({"success": False, "error": "未选择文件"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "文件名为空"}), 400

    if not allowed_file(file.filename):
        return jsonify({"success": False, "error": "仅支持 .xlsx / .xls 格式"}), 400

    # 保存文件
    file_id = str(uuid.uuid4())[:8]
    safe_name = f"upload_{file_id}_{file.filename}"
    save_path = os.path.join(UPLOAD_DIR, safe_name)
    file.save(save_path)

    # 读取Excel
    try:
        df, columns = read_excel(save_path)
    except Exception as e:
        return jsonify({"success": False, "error": f"读取Excel失败: {str(e)}"}), 400

    # 保存到session
    analysis_state["raw_df"] = df
    analysis_state["all_results"] = None
    analysis_state["output_path"] = None
    session["uploaded_file"] = save_path

    # 返回预览数据
    preview = []
    for idx, row in df.head(20).iterrows():
        preview.append({
            "index": idx,
            "product_id": str(row.get("店小秘产品ID", row.get("product_id", ""))),
            "name": str(row.get("产品名称", ""))[:80],
            "image": str(row.get("产品图片", "")).split(";")[0] if str(row.get("产品图片", "")).strip() else "",
        })

    return jsonify({
        "success": True,
        "file_name": file.filename,
        "total_rows": len(df),
        "columns": columns,
        "preview": preview[:20],
    })


@app.route("/api/analyze", methods=["POST"])
def start_analysis():
    """开始分析（同步处理）"""
    df = analysis_state.get("raw_df")
    if df is None:
        return jsonify({"success": False, "error": "请先上传Excel文件"}), 400

    data = request.get_json() or {}
    enabled_detectors = data.get("detectors", [
        "text_prohibited", "contact_leak", "html_structure",
        "brand_check", "search_cheating", "image_analysis",
        "category_mismatch", "fda_claims",
    ])

    # 初始化规则索引
    try:
        rule_index = rebuild_index()
    except Exception as e:
        rule_index = get_rule_index()

    # 初始化检测器
    from detectors.text_prohibited import TextProhibitedDetector
    from detectors.text_contact_leak import ContactLeakDetector
    from detectors.html_structure import HtmlStructureDetector
    from detectors.brand_check import BrandCheckDetector
    from detectors.search_cheating import SearchCheatingDetector
    from detectors.image_analysis import ImageAnalysisDetector
    from detectors.category_mismatch import CategoryMismatchDetector
    from detectors.fda_claims import FDAClaimsDetector

    detector_map = {
        "text_prohibited": ("违禁关键词", TextProhibitedDetector()),
        "contact_leak": ("联系方式泄露", ContactLeakDetector()),
        "html_structure": ("HTML结构分析", HtmlStructureDetector()),
        "brand_check": ("品牌侵权", BrandCheckDetector()),
        "search_cheating": ("搜索作弊", SearchCheatingDetector()),
        "image_analysis": ("图片内容分析", ImageAnalysisDetector()),
        "category_mismatch": ("类目错放", CategoryMismatchDetector()),
        "fda_claims": ("FDA非法宣称", FDAClaimsDetector()),
    }

    # 选择启用哪些检测器
    active_detectors = []
    for det_key in enabled_detectors:
        if det_key in detector_map:
            active_detectors.append(detector_map[det_key])

    if not active_detectors:
        return jsonify({"success": False, "error": "请至少选择一个检测维度"}), 400

    # 逐行检测
    total = len(df)
    all_results = {}
    ocr_cache = {}
    context = {"ocr_cache": ocr_cache}

    for idx, (_, row) in enumerate(df.iterrows()):
        row_results = []
        row_dict = row.to_dict()
        # 清除上下文中的图片分析结果，防止上一个产品的图片泄漏到当前产品
        context.pop("image_analysis", None)
        context.pop("ocr_texts", None)

        for det_name, detector in active_detectors:
            try:
                det_results = detector.detect(row_dict, context)
                if det_results:
                    row_results.extend(det_results)
            except Exception as e:
                # 单个检测器失败不影响其他
                pass

        all_results[idx] = row_results

    # 生成输出
    writer = OutputWriter(df, all_results)
    writer.add_columns()

    # 保存输出
    output_file = os.path.join(UPLOAD_DIR, f"risk_analysis_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    writer.save(output_file)
    analysis_state["all_results"] = all_results
    analysis_state["output_path"] = output_file

    # 统计
    stats = writer.get_stats()

    return jsonify({
        "success": True,
        "stats": stats,
        "output_file": os.path.basename(output_file),
    })


@app.route("/api/products")
def get_products():
    """获取产品列表（用于前端表格展示）"""
    df = analysis_state.get("raw_df")
    all_results = analysis_state.get("all_results")

    if df is None or all_results is None:
        return jsonify({"success": False, "error": "请先进行分析"}), 400

    # 筛选参数
    risk_filter = request.args.get("risk", "全部")
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 50))

    from risk_evaluator import RiskEvaluator

    products = []
    for idx, (_, row) in enumerate(df.iterrows()):
        results = all_results.get(idx, [])
        evaluator = RiskEvaluator(results)
        risk = evaluator.get_overall_risk()

        # 筛选
        if risk_filter != "全部":
            if risk_filter == "高" and "高" not in risk:
                continue
            if risk_filter == "中" and "中" not in risk:
                continue
            if risk_filter == "低" and "低" not in risk:
                continue

        # 获取违规维度
        categories = list(set(r.get("category", "") for r in results))
        reasons_preview = evaluator.format_reasons()[:200]

        # 获取主图
        img_cell = str(row.get("产品图片", ""))
        first_img = img_cell.split(";")[0] if img_cell else ""

        products.append({
            "index": idx,
            "product_id": str(row.get("店小秘产品ID", row.get("product_id", ""))),
            "name": str(row.get("产品名称", ""))[:100],
            "image": first_img,
            "risk": risk,
            "categories": categories,
            "reasons_preview": reasons_preview,
            "shop_name": str(row.get("所属店铺", "")),
        })

    # 分页
    total = len(products)
    start = (page - 1) * page_size
    end = start + page_size
    page_products = products[start:end] if start < total else []

    return jsonify({
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "products": page_products,
    })


@app.route("/api/product/<int:product_index>")
def get_product_detail(product_index):
    """获取单个产品的详细检测结果"""
    df = analysis_state.get("raw_df")
    all_results = analysis_state.get("all_results")

    if df is None or all_results is None:
        return jsonify({"success": False, "error": "请先进行分析"}), 400

    if product_index < 0 or product_index >= len(df):
        return jsonify({"success": False, "error": "产品索引超出范围"}), 404

    row = df.iloc[product_index]
    results = all_results.get(product_index, [])
    from risk_evaluator import RiskEvaluator
    evaluator = RiskEvaluator(results)

    # 图片URL列表
    img_cell = str(row.get("产品图片", ""))
    images = [u.strip() for u in img_cell.split(";") if u.strip() and u.strip().startswith("http")]

    # 详细结果
    detail_results = []
    for i, r in enumerate(results):
        rule_ref = r.get("rule_ref", {})
        detail_results.append({
            "index": i,
            "risk_level": r.get("risk_level", ""),
            "category": r.get("category", ""),
            "reason": r.get("reason", ""),
            "remedy": r.get("remedy", ""),
            "rule_file": rule_ref.get("file", ""),
            "rule_clause": rule_ref.get("clause", ""),
            "rule_summary": rule_ref.get("summary", "")[:300],
            "rule_wiki_link": rule_ref.get("wiki_link", ""),
            "image_index": r.get("image_index"),
            "image_url": r.get("image_url"),
            "ocr_text": r.get("ocr_text", ""),
            "html_fragment": r.get("html_fragment", ""),
            "hidden_element_count": r.get("hidden_element_count"),
        })

    # 产品基本信息
    product_info = {
        "index": product_index,
        "product_id": str(row.get("店小秘产品ID", row.get("product_id", ""))),
        "name": str(row.get("产品名称", "")),
        "images": images,
        "shop": str(row.get("所属店铺", "")),
        "category": str(row.get("产品分组", "")),
        "price_info": str(row.get("价格信息", ""))[:500],
        "weight": str(row.get("产品包装后的重量", "")),
    }

    return jsonify({
        "success": True,
        "product": product_info,
        "risk_level": evaluator.get_overall_risk(),
        "reasons_html": evaluator.format_reasons_html(),
        "reasons_text": evaluator.format_reasons(),
        "remedies_text": evaluator.format_remedies(),
        "high_risk_reasons": evaluator.format_high_risk_reasons(),
        "high_risk_remedies": evaluator.format_high_risk_remedies(),
        "medium_risk_reasons": evaluator.format_medium_risk_reasons(),
        "medium_risk_remedies": evaluator.format_medium_risk_remedies(),
        "details": detail_results,
        "total_findings": len(results),
    })


@app.route("/api/export")
def export_result():
    """下载分析结果Excel"""
    output_path = analysis_state.get("output_path")
    if not output_path or not os.path.exists(output_path):
        return jsonify({"success": False, "error": "没有可导出的文件"}), 400

    return send_file(
        output_path,
        as_attachment=True,
        download_name=f"aliexpress_risk_result_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/api/rules")
def get_rules():
    """获取规则索引信息"""
    try:
        rule_index = get_rule_index()
        rules_info = []
        for fname, rule in rule_index.rules.items():
            rules_info.append({
                "name": fname,
                "summary": rule["summary"],
                "wiki_link": rule["wiki_link"],
                "clause_count": len(rule["clauses"]),
            })
        return jsonify({
            "success": True,
            "count": len(rules_info),
            "rules": rules_info,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def run_batch():
    """批量处理 input 文件夹下的所有 Excel，逐个分析后输出到 output 文件夹"""
    import glob
    import time as time_module
    from config import BATCH_INPUT_DIR, BATCH_OUTPUT_DIR

    # 初始化规则索引
    print("正在初始化规则索引...")
    try:
        rebuild_index()
        print(f"  规则索引已加载 ({len(get_rule_index().rules)} 个规则文件)")
    except Exception as e:
        print(f"  规则索引加载失败: {e}")

    # 初始化检测器
    from detectors.text_prohibited import TextProhibitedDetector
    from detectors.text_contact_leak import ContactLeakDetector
    from detectors.html_structure import HtmlStructureDetector
    from detectors.brand_check import BrandCheckDetector
    from detectors.search_cheating import SearchCheatingDetector
    from detectors.image_analysis import ImageAnalysisDetector
    from detectors.category_mismatch import CategoryMismatchDetector
    from detectors.fda_claims import FDAClaimsDetector
    from utils.excel_io import read_excel

    detectors = [
        ("违禁关键词", TextProhibitedDetector()),
        ("联系方式泄露", ContactLeakDetector()),
        ("HTML结构分析", HtmlStructureDetector()),
        ("品牌侵权", BrandCheckDetector()),
        ("搜索作弊", SearchCheatingDetector()),
        ("图片内容分析", ImageAnalysisDetector()),
        ("类目错放", CategoryMismatchDetector()),
        ("FDA非法宣称", FDAClaimsDetector()),
    ]

    # 确保输出目录存在
    os.makedirs(BATCH_OUTPUT_DIR, exist_ok=True)

    # 扫描输入目录
    files = sorted(glob.glob(os.path.join(BATCH_INPUT_DIR, "*.xlsx"))) + \
            sorted(glob.glob(os.path.join(BATCH_INPUT_DIR, "*.xls")))
    if not files:
        print(f"\n[!] input 文件夹为空，请放入待分析的 Excel 文件")
        print(f"    路径: {BATCH_INPUT_DIR}")
        return

    print(f"\n找到 {len(files)} 个文件待处理\n")

    for file_idx, filepath in enumerate(files, 1):
        filename = os.path.basename(filepath)
        print(f"[{file_idx}/{len(files)}] {filename}")
        t_start = time_module.time()

        try:
            # 读取 Excel
            df, columns = read_excel(filepath)
            print(f"  读取: {len(df)} 行, {len(columns)} 列")
        except Exception as e:
            print(f"  [FAIL] 读取失败: {e}")
            continue

        # 逐行检测
        all_results = {}
        context = {}

        for idx, (_, row) in enumerate(df.iterrows()):
            row_results = []
            row_dict = row.to_dict()
            # 清除上下文中的图片分析结果，防止泄漏
            context.pop("image_analysis", None)
            context.pop("ocr_texts", None)

            for det_name, detector in detectors:
                try:
                    det_results = detector.detect(row_dict, context)
                    if det_results:
                        row_results.extend(det_results)
                except Exception:
                    pass

            all_results[idx] = row_results

            # 进度条（每10条或最后一条打印）
            if (idx + 1) % 10 == 0 or idx == len(df) - 1:
                pct = (idx + 1) / len(df) * 100
                done = int(pct / 5)
                bar = "#" * done + "-" * (20 - done)
                print(f"\r  [{bar}] {pct:.0f}% ({idx + 1}/{len(df)})", end="", flush=True)

        print()  # 换行

        # 生成输出
        from output_writer import OutputWriter
        writer = OutputWriter(df, all_results)
        stats = writer.get_stats()

        out_name = filename.rsplit(".", 1)[0] + "_风险分析.xlsx"
        out_path = os.path.join(BATCH_OUTPUT_DIR, out_name)
        writer.save(out_path)

        elapsed = time_module.time() - t_start
        print(f"  输出: {out_name}")
        print(f"  结果: 高 {stats['high']} | 中 {stats['medium']} | 低 {stats['low']} | 耗时 {elapsed:.1f}s")
        print()

    print(f"全部完成！输出目录: {BATCH_OUTPUT_DIR}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--batch":
        # 批量模式：扫描 input 文件夹，逐个分析导出到 output 文件夹
        run_batch()
    else:
        # Web 模式
        print("正在初始化规则索引...")
        try:
            rebuild_index()
            print(f"规则索引已加载 ({len(get_rule_index().rules)} 个规则文件)")
        except Exception as e:
            print(f"规则索引加载失败（不影响启动）：{e}")

        print("*" * 60)
        print("  速卖通在线产品违规风险分析系统")
        print(f"  访问地址: http://localhost:5000")
        print(f"  批量模式: python app.py --batch")
        print("  Ctrl+C 停止服务")
        print("*" * 60)

        app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
