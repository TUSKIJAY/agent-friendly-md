"""
多格式文档结构提取器 (doc_to_md_extractor.py) v2.0
将 .docx / .pdf / .xlsx / .pptx / .md / .txt 文档解析为 Markdown 骨架 + 提取图片。

v2.0 核心原则：降维分级（L0 无损结构化 > L1 估读结构化 > L2 散文描述 > L3 诚实占位），
任何对象最低落到 L3 占位标记，绝不静默丢失。

v2.0 新增的 L0 结构化能力：
- Word 原生公式 (OMML) -> LaTeX
- Word/PPT 原生图表 -> 精确数据表（解析 chart XML 的 numCache）
- Excel 原生图表 -> 数据表（解析 series 引用）
- SmartArt 图示 -> 节点文本列表
- 文本框、演讲者备注、超链接 URL、组合形状递归
v2.0 修复：图片顺序确定性、.xls 误支持、Excel 空首行表格分隔行、
同名不同格式工作目录冲突、PDF 中文断行空格污染、WPS「标题 N」样式识别等。

用法: python doc_to_md_extractor.py "<输入文件路径>" [--output-dir <输出目录>]
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

__version__ = "2.0.0"

# =============================================================================
# XML 命名空间
# =============================================================================

NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
NS_DGM = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def q(ns, tag):
    return f"{{{ns}}}{tag}"


def wq(tag):
    return q(NS_W, tag)


CHART_TYPE_NAMES = {
    "barChart": "柱状图", "bar3DChart": "三维柱状图",
    "lineChart": "折线图", "line3DChart": "三维折线图",
    "pieChart": "饼图", "pie3DChart": "三维饼图",
    "doughnutChart": "环形图", "areaChart": "面积图", "area3DChart": "三维面积图",
    "scatterChart": "散点图", "radarChart": "雷达图",
    "bubbleChart": "气泡图", "stockChart": "K线图", "surfaceChart": "曲面图",
    "ofPieChart": "复合饼图",
}


# =============================================================================
# 通用工具
# =============================================================================

def ensure_dir(path):
    """确保目录存在"""
    os.makedirs(path, exist_ok=True)
    return path


def clean_text(text):
    """清洗文本：去除不可见字符、多余空白"""
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u2028-\u202f\ufeff]', '', text)
    return text.strip()


def escape_md_cell(text):
    """转义 Markdown 表格单元格中的管道符与换行"""
    if not text:
        return ""
    return text.replace("|", "\\|").replace("\n", "<br>")


def save_image(blob, img_dir, img_counter, ext="png"):
    """保存图片二进制数据到文件，返回 (文件路径, 文件名, 新计数器)"""
    ext = (ext or "png").lower()
    if ext == 'jpeg':
        ext = 'jpg'
    if not re.fullmatch(r'[a-z0-9]{1,5}', ext):
        ext = 'png'
    img_filename = f"image_{img_counter:03d}.{ext}"
    img_path = os.path.join(img_dir, img_filename)
    with open(img_path, 'wb') as f:
        f.write(blob)
    return img_path, img_filename, img_counter + 1


_CJK_RE = re.compile(r'[⺀-鿿　-〿＀-￯]')


def _is_cjk(ch):
    return bool(ch) and bool(_CJK_RE.match(ch))


def smart_join(parts):
    """拼接断行文本：CJK 字符之间不加空格，西文之间加空格"""
    out = ""
    for p in parts:
        if not p:
            continue
        if not out:
            out = p
            continue
        if _is_cjk(out[-1]) or _is_cjk(p[0]):
            out += p
        else:
            out += " " + p
    return out


def unparsed_marker(kind, note=""):
    """L3 诚实占位：对象无法结构化时的最低保真标记"""
    suffix = f"（{note}）" if note else ""
    return f"> [未解析: {kind}]{suffix}"


# =============================================================================
# OMML（Word 原生公式）-> LaTeX 转换器
# =============================================================================

_NARY_DEFAULT = "∫"
_ACC_MAP = {"̂": "hat", "̄": "bar", "⃗": "vec", "̃": "tilde", "̇": "dot", "̈": "ddot"}


def _omml_first(node, tag):
    child = node.find(q(NS_M, tag))
    return _omml_node(child) if child is not None else ""


def _omml_children(node):
    return "".join(_omml_node(c) for c in node)


def _omml_node(node):
    if node is None:
        return ""
    tag = node.tag.split('}')[-1]
    if tag.endswith('Pr') or tag == 'ctrlPr':
        return ""
    if tag == 't':
        return node.text or ""
    if tag == 'f':
        return "\\frac{%s}{%s}" % (_omml_first(node, 'num'), _omml_first(node, 'den'))
    if tag == 'sSup':
        return "{%s}^{%s}" % (_omml_first(node, 'e'), _omml_first(node, 'sup'))
    if tag == 'sSub':
        return "{%s}_{%s}" % (_omml_first(node, 'e'), _omml_first(node, 'sub'))
    if tag == 'sSubSup':
        return "{%s}_{%s}^{%s}" % (
            _omml_first(node, 'e'), _omml_first(node, 'sub'), _omml_first(node, 'sup'))
    if tag == 'sPre':
        return "{}_{%s}^{%s}{%s}" % (
            _omml_first(node, 'sub'), _omml_first(node, 'sup'), _omml_first(node, 'e'))
    if tag == 'rad':
        deg = _omml_first(node, 'deg').strip()
        e = _omml_first(node, 'e')
        return ("\\sqrt[%s]{%s}" % (deg, e)) if deg else ("\\sqrt{%s}" % e)
    if tag == 'nary':
        chr_el = node.find(f"{q(NS_M, 'naryPr')}/{q(NS_M, 'chr')}")
        op = chr_el.get(q(NS_M, 'val'), _NARY_DEFAULT) if chr_el is not None else _NARY_DEFAULT
        sub = _omml_first(node, 'sub').strip()
        sup = _omml_first(node, 'sup').strip()
        e = _omml_first(node, 'e')
        out = op
        if sub:
            out += "_{%s}" % sub
        if sup:
            out += "^{%s}" % sup
        return out + " " + e
    if tag == 'd':
        dpr = node.find(q(NS_M, 'dPr'))
        beg, end = "(", ")"
        if dpr is not None:
            b = dpr.find(q(NS_M, 'begChr'))
            e2 = dpr.find(q(NS_M, 'endChr'))
            if b is not None:
                beg = b.get(q(NS_M, 'val'), "(")
            if e2 is not None:
                end = e2.get(q(NS_M, 'val'), ")")
        inner = ", ".join(_omml_node(e) for e in node.findall(q(NS_M, 'e')))
        return f"{beg}{inner}{end}"
    if tag == 'func':
        fname = _omml_first(node, 'fName')
        e = _omml_first(node, 'e')
        return f"{fname}{e}" if e.startswith("(") else f"{fname}({e})"
    if tag == 'limLow':
        return "%s_{%s}" % (_omml_first(node, 'e'), _omml_first(node, 'lim'))
    if tag == 'limUpp':
        return "%s^{%s}" % (_omml_first(node, 'e'), _omml_first(node, 'lim'))
    if tag == 'bar':
        pos_el = node.find(f"{q(NS_M, 'barPr')}/{q(NS_M, 'pos')}")
        pos = pos_el.get(q(NS_M, 'val'), 'bot') if pos_el is not None else 'bot'
        cmd = "\\overline" if pos == 'top' else "\\underline"
        return "%s{%s}" % (cmd, _omml_first(node, 'e'))
    if tag == 'acc':
        chr_el = node.find(f"{q(NS_M, 'accPr')}/{q(NS_M, 'chr')}")
        ch = chr_el.get(q(NS_M, 'val'), "̂") if chr_el is not None else "̂"
        return "\\%s{%s}" % (_ACC_MAP.get(ch, "hat"), _omml_first(node, 'e'))
    if tag == 'groupChr':
        return "\\underbrace{%s}" % _omml_first(node, 'e')
    if tag == 'm':
        rows = []
        for mr in node.findall(q(NS_M, 'mr')):
            rows.append(" & ".join(_omml_node(e) for e in mr.findall(q(NS_M, 'e'))))
        return "\\begin{matrix}%s\\end{matrix}" % " \\\\ ".join(rows)
    if tag == 'eqArr':
        rows = [_omml_node(e) for e in node.findall(q(NS_M, 'e'))]
        return " \\\\ ".join(rows)
    # r/e/num/den/sub/sup/deg/fName/lim/box/borderBox/phant/oMath/oMathPara 及未知节点：透传子节点
    return _omml_children(node)


def omml_to_latex(omath_el):
    """OMML 元素 -> LaTeX 字符串；覆盖常见结构，失败返回 None（调用方落 L3）"""
    try:
        latex = _omml_node(omath_el)
        latex = re.sub(r'\s+', ' ', latex).strip()
        return latex or None
    except Exception:
        return None


# =============================================================================
# DrawingML 图表 XML -> Markdown 数据表（docx 与 pptx 共用）
# =============================================================================

def _chart_pts(el):
    """提取 c:pt 列表为 {idx: 文本值}"""
    d = {}
    if el is None:
        return d
    for pt in el.iter(q(NS_C, 'pt')):
        try:
            idx = int(pt.get('idx', '0'))
        except ValueError:
            continue
        v = pt.find(q(NS_C, 'v'))
        d[idx] = clean_text(v.text or "") if v is not None else ""
    return d


def chart_xml_to_md(blob, max_rows=60):
    """解析 chartSpace XML（含缓存数据），返回 Markdown 行列表；失败返回 None"""
    try:
        root = ET.fromstring(blob)
    except Exception:
        return None
    chart = root.find(q(NS_C, 'chart'))
    if chart is None:
        return None
    title = ""
    t_el = chart.find(q(NS_C, 'title'))
    if t_el is not None:
        title = clean_text("".join(t.text or "" for t in t_el.iter(q(NS_A, 't'))))
    plot = chart.find(q(NS_C, 'plotArea'))
    if plot is None:
        return None

    type_names, series = [], []
    for child in plot:
        local = child.tag.split('}')[-1]
        if not local.endswith('Chart'):
            continue
        type_names.append(CHART_TYPE_NAMES.get(local, local))
        for ser in child.findall(q(NS_C, 'ser')):
            name = ""
            tx = ser.find(q(NS_C, 'tx'))
            if tx is not None:
                vs = [v.text for v in tx.iter(q(NS_C, 'v')) if v.text]
                name = clean_text(vs[0]) if vs else ""
            cat_el = ser.find(q(NS_C, 'cat'))
            if cat_el is None:
                cat_el = ser.find(q(NS_C, 'xVal'))
            val_el = ser.find(q(NS_C, 'val'))
            if val_el is None:
                val_el = ser.find(q(NS_C, 'yVal'))
            series.append({"name": name, "cats": _chart_pts(cat_el), "vals": _chart_pts(val_el)})

    if not type_names:
        return None
    head = f"> [图表: {'+'.join(type_names)}]"
    if title:
        head += f" {title}"
    head += "（数据为文档内嵌原生值）"
    lines = [head, ""]

    has_data = any(s["vals"] for s in series)
    if not has_data:
        lines.append("> （图表中未读取到缓存数据系列）")
        return lines

    all_idx = sorted(set().union(*[set(s["vals"].keys()) for s in series]))
    cats = next((s["cats"] for s in series if s["cats"]), {})
    header = ["类目"] + [(s["name"] or f"系列{i + 1}") for i, s in enumerate(series)]
    lines.append("| " + " | ".join(escape_md_cell(h) for h in header) + " |")
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")
    for n, idx in enumerate(all_idx):
        if n >= max_rows:
            lines.append(f"\n*（图表数据共 {len(all_idx)} 行，已截取前 {max_rows} 行）*")
            break
        row = [cats.get(idx, str(idx + 1))] + [s["vals"].get(idx, "") for s in series]
        lines.append("| " + " | ".join(escape_md_cell(c) for c in row) + " |")
    lines.append("")
    return lines


def smartart_node_texts(graphic_data_el, related_parts):
    """提取 SmartArt 数据模型中的节点文本；失败返回 None"""
    rel = graphic_data_el.find(q(NS_DGM, 'relIds'))
    if rel is None:
        return None
    rid = rel.get(q(NS_R, 'dm'))
    part = related_parts.get(rid) if rid else None
    if part is None:
        return None
    try:
        root = ET.fromstring(part.blob)
    except Exception:
        return None
    texts = []
    for pt in root.iter(q(NS_DGM, 'pt')):
        t = clean_text("".join(x.text or "" for x in pt.iter(q(NS_A, 't'))))
        if t and t not in texts:
            texts.append(t)
    return texts or None


def smartart_md(graphic_data_el, related_parts, stats):
    texts = smartart_node_texts(graphic_data_el, related_parts)
    if texts:
        stats['smartart'] += 1
        shown = "、".join(texts[:40])
        if len(texts) > 40:
            shown += f"…（共 {len(texts)} 个节点）"
        return f"> [SmartArt 图示] 节点文本: {shown}"
    stats['unparsed'] += 1
    return unparsed_marker("SmartArt 图示", "未能读取节点文本，请查看原文档")


def extract_images_from_xml(xml_str, parent_part, img_dir, img_counter):
    """按出现顺序提取 XML 片段中引用的图片关系（确定性顺序，修复 set 乱序问题）"""
    names = []
    for rId in dict.fromkeys(re.findall(r'rId\d+', xml_str)):
        try:
            part = parent_part.related_parts.get(rId)
            if part is not None and 'image' in getattr(part, 'content_type', ''):
                ext = part.content_type.split('/')[-1]
                _, img_filename, img_counter = save_image(part.blob, img_dir, img_counter, ext)
                names.append(img_filename)
        except Exception:
            pass
    return names, img_counter


# =============================================================================
# Word (.docx) 解析器
# =============================================================================

def parse_docx(file_path, img_dir):
    """解析 .docx 文件，返回 (Markdown 行列表, 图片计数, 统计)"""
    from docx import Document
    from docx.document import Document as _Document
    from docx.oxml.text.paragraph import CT_P
    from docx.oxml.table import CT_Tbl
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    try:
        from docx.text.hyperlink import Hyperlink as _Hyperlink
    except Exception:
        _Hyperlink = None

    stats = Counter()

    def iter_block_items(parent):
        parent_elm = parent.element.body if isinstance(parent, _Document) else parent
        for child in parent_elm.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)

    def paragraph_text_with_links(block):
        """构建段落文本，外部超链接渲染为 [文字](URL)"""
        if _Hyperlink is not None:
            try:
                parts = []
                for item in block.iter_inner_content():
                    if isinstance(item, _Hyperlink):
                        addr = item.address or ""
                        t = item.text or ""
                        if addr and t:
                            parts.append(f"[{t}]({addr})")
                            stats['link'] += 1
                        else:
                            parts.append(t)
                    else:
                        parts.append(item.text or "")
                return "".join(parts)
            except Exception:
                pass
        return block.text or ""

    def heading_level(block):
        """标题层级：兼容英文 Heading N、WPS/中文 标题 N、Title，以及 outlineLvl 回退"""
        name = (block.style.name or "") if block.style else ""
        m = re.match(r'(?:heading|标题)\s*(\d+)$', name.strip(), re.I)
        if m:
            return max(1, min(6, int(m.group(1))))
        if name.strip() in ('Title', '标题'):
            return 1
        try:
            pPr = block._p.pPr
            if pPr is not None:
                lvl = pPr.find(wq('outlineLvl'))
                if lvl is not None:
                    return max(1, min(6, int(lvl.get(wq('val'), '0')) + 1))
        except Exception:
            pass
        return 0

    def list_prefix(block):
        """检测编号/项目符号列表（w:numPr），返回 Markdown 列表前缀"""
        try:
            pPr = block._p.pPr
            if pPr is None:
                return ""
            numPr = pPr.find(wq('numPr'))
            if numPr is None:
                return ""
            ilvl_el = numPr.find(wq('ilvl'))
            ilvl = int(ilvl_el.get(wq('val'), '0')) if ilvl_el is not None else 0
            return "  " * max(0, ilvl) + "- "
        except Exception:
            return ""

    def cell_text(tc):
        """单元格文本：扁平化所有段落（含嵌套表格内容），按 <br> 连接"""
        parts = []
        for p_el in tc.iter(wq('p')):
            t = clean_text("".join(n.text or "" for n in p_el.iter(wq('t'))))
            if t:
                parts.append(t)
        return "<br>".join(parts)

    def parse_table_with_merge(table, img_counter):
        """
        解析 Word 表格，通过底层 XML 的 gridSpan/vMerge 构建真实网格，
        合并区域只在左上角保留内容（python-docx 的 row.cells 会重复合并单元格）。
        """
        tbl = table._tbl
        rows_xml = tbl.findall(wq('tr'))
        if not rows_xml:
            return [], img_counter

        tbl_grid = tbl.find(wq('tblGrid'))
        if tbl_grid is not None:
            num_cols = len(tbl_grid.findall(wq('gridCol')))
        else:
            num_cols = 0
            for tr in rows_xml:
                col_count = 0
                for tc in tr.findall(wq('tc')):
                    tc_pr = tc.find(wq('tcPr'))
                    span = 1
                    if tc_pr is not None:
                        gs = tc_pr.find(wq('gridSpan'))
                        if gs is not None:
                            span = int(gs.get(wq('val'), '1'))
                    col_count += span
                num_cols = max(num_cols, col_count)
        if num_cols == 0:
            return [], img_counter

        num_rows = len(rows_xml)
        grid = [["" for _ in range(num_cols)] for _ in range(num_rows)]
        occupied = [[False for _ in range(num_cols)] for _ in range(num_rows)]
        cell_images = []

        for row_idx, tr in enumerate(rows_xml):
            col_idx = 0
            for tc in tr.findall(wq('tc')):
                while col_idx < num_cols and occupied[row_idx][col_idx]:
                    col_idx += 1
                if col_idx >= num_cols:
                    break

                tc_pr = tc.find(wq('tcPr'))
                h_span = 1
                is_v_merge_continue = False
                if tc_pr is not None:
                    gs = tc_pr.find(wq('gridSpan'))
                    if gs is not None:
                        h_span = int(gs.get(wq('val'), '1'))
                    vm = tc_pr.find(wq('vMerge'))
                    if vm is not None and vm.get(wq('val'), '') != 'restart':
                        is_v_merge_continue = True

                text = cell_text(tc)
                imgs, img_counter = extract_images_from_xml(tc.xml, doc.part, img_dir, img_counter)
                for img_name in imgs:
                    cell_images.append(img_name)
                    text = f"{text} [图:{img_name}]" if text else f"[图:{img_name}]"

                if not is_v_merge_continue:
                    grid[row_idx][col_idx] = text
                for c in range(col_idx, min(col_idx + h_span, num_cols)):
                    occupied[row_idx][c] = True
                    if is_v_merge_continue:
                        grid[row_idx][c] = ""
                col_idx += h_span

        # 剔除全空列（表头与所有数据行都为空的列，多为合并产生的占位列）。
        # 注意：v1 曾按「整列值与前列相等」推断重复列，会误删合法的相同值数据列，已移除。
        cols_to_keep = list(range(num_cols))
        if num_cols > 1 and num_rows > 0:
            kept = []
            for c in range(num_cols):
                if any(grid[r][c].strip() for r in range(num_rows)):
                    kept.append(c)
            if kept:
                cols_to_keep = kept

        final_num_cols = len(cols_to_keep)
        md_table = []
        header_written = False
        for row_idx in range(num_rows):
            row_data = [grid[row_idx][c] for c in cols_to_keep]
            non_empty = [(i, v) for i, v in enumerate(row_data) if v.strip()]
            if len(non_empty) == 1 and final_num_cols > 2:
                # 横跨全行的合并标题行，转为独立加粗文本
                if md_table and md_table[-1].startswith("|"):
                    md_table.append("")
                md_table.append(f"**{non_empty[0][1].strip()}**")
                md_table.append("")
                header_written = False
            else:
                md_table.append("| " + " | ".join(escape_md_cell(v) for v in row_data) + " |")
                if not header_written:
                    md_table.append("| " + " | ".join(["---"] * final_num_cols) + " |")
                    header_written = True
        md_table.append("")
        return md_table, img_counter, cell_images

    doc = Document(file_path)
    md_lines = []
    img_counter = 1

    # 节 (Section) 页眉/页脚文本（供阶段 1.5 审阅）
    for sec_idx, section in enumerate(doc.sections):
        sec_header_texts, sec_footer_texts = [], []
        try:
            if section.header and not section.header.is_linked_to_previous:
                sec_header_texts = [clean_text(p.text) for p in section.header.paragraphs if clean_text(p.text)]
        except Exception:
            pass
        try:
            if section.footer and not section.footer.is_linked_to_previous:
                sec_footer_texts = [clean_text(p.text) for p in section.footer.paragraphs if clean_text(p.text)]
        except Exception:
            pass
        if sec_header_texts or sec_footer_texts:
            md_lines.append(f"<!-- meta:section_start section={sec_idx + 1} -->")
            if sec_header_texts:
                md_lines.append("<!-- meta:zone header -->")
                md_lines.extend(sec_header_texts)
                md_lines.append("<!-- meta:zone_end -->")
            if sec_footer_texts:
                md_lines.append("<!-- meta:zone footer -->")
                md_lines.extend(sec_footer_texts)
                md_lines.append("<!-- meta:zone_end -->")
            md_lines.append("<!-- meta:section_end -->\n")

    # 正文
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = clean_text(paragraph_text_with_links(block))

            # L0: 原生公式 OMML -> LaTeX
            formula_md = []
            for om in block._p.findall('.//' + q(NS_M, 'oMath')):
                latex = omml_to_latex(om)
                if latex:
                    formula_md.append(f"${latex}$")
                    stats['formula'] += 1
                else:
                    formula_md.append(unparsed_marker("公式", "OMML 转换失败，请查看原文档"))
                    stats['unparsed'] += 1

            if text:
                if formula_md:
                    inline = " ".join(f for f in formula_md if f.startswith("$"))
                    if inline:
                        text = f"{text} {inline}"
                level = heading_level(block)
                if level:
                    md_lines.append(f"{'#' * level} {text}")
                else:
                    md_lines.append(f"{list_prefix(block)}{text}")
                for f in formula_md:
                    if not f.startswith("$"):
                        md_lines.append(f)
            elif formula_md:
                for f in formula_md:
                    md_lines.append(f"$${f[1:-1]}$$" if f.startswith("$") else f)

            # 嵌入图片（顺序确定）
            imgs, img_counter = extract_images_from_xml(block._p.xml, doc.part, img_dir, img_counter)
            for img_name in imgs:
                md_lines.append(f"\n<!-- IMAGE: {img_name} -->\n[VISION_PLACEHOLDER_{img_name}]\n")

            # L0: 原生图表 / SmartArt
            for gd in block._p.findall('.//' + q(NS_A, 'graphicData')):
                uri = gd.get('uri') or ""
                if 'chart' in uri:
                    chart_lines = None
                    try:
                        ch_ref = gd.find(q(NS_C, 'chart'))
                        rid = ch_ref.get(q(NS_R, 'id')) if ch_ref is not None else None
                        part = doc.part.related_parts.get(rid) if rid else None
                        if part is not None:
                            chart_lines = chart_xml_to_md(part.blob)
                    except Exception:
                        chart_lines = None
                    if chart_lines:
                        md_lines.append("\n".join(chart_lines))
                        stats['chart'] += 1
                    else:
                        md_lines.append(unparsed_marker("图表", "检测到内嵌图表但无法读取数据"))
                        stats['unparsed'] += 1
                elif 'diagram' in uri:
                    md_lines.append(smartart_md(gd, doc.part.related_parts, stats))

            # 文本框（封面、红头、流程标注常见载体）
            for txbx in block._p.findall('.//' + wq('txbxContent')):
                for tp in txbx.findall('.//' + wq('p')):
                    t = clean_text("".join(n.text or "" for n in tp.iter(wq('t'))))
                    if t:
                        md_lines.append(f"> [文本框] {t}")
                        stats['textbox'] += 1

        elif isinstance(block, Table):
            table_lines, img_counter, cell_imgs = parse_table_with_merge(block, img_counter)
            md_lines.extend(table_lines)
            for img_name in cell_imgs:
                md_lines.append(f"\n<!-- IMAGE: {img_name} (表格内嵌图片) -->\n[VISION_PLACEHOLDER_{img_name}]\n")

    return md_lines, img_counter - 1, stats


# =============================================================================
# PDF (.pdf) 解析器
# =============================================================================

def _render_full_page(page, img_dir, page_num, render_counter, dpi=200):
    """整页渲染为高分辨率 PNG，命名 page_NNN.png（区别于碎片图 image_NNN）"""
    pix = page.get_pixmap(dpi=dpi)
    img_filename = f"page_{page_num + 1:03d}.png"
    pix.save(os.path.join(img_dir, img_filename))
    return img_filename, render_counter + 1


def _should_force_page_render(header_texts, body_texts, footer_texts, image_list):
    """判断是否放弃碎片提取、改用整页渲染（设计型 PDF：画册/宣传册等）"""
    all_texts = header_texts + body_texts + footer_texts
    total_text_len = sum(len(t) for t in all_texts)
    num_text_blocks = len(all_texts)
    num_images = len(image_list)

    if num_images >= 5 and total_text_len < 100:
        return True
    if num_text_blocks > 0 and num_images >= 3:
        if num_images / num_text_blocks >= 3 and total_text_len < 300:
            return True
    if num_images > 0 and total_text_len == 0:
        return True
    return False


def is_inside_tables(bbox, tables):
    bx0, by0, bx1, by1 = bbox
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    for tab in tables:
        tx0, ty0, tx1, ty1 = tab.bbox
        if tx0 <= cx <= tx1 and ty0 <= cy <= ty1:
            return True
    return False


def format_pdf_table(table):
    data = table.extract()
    if not data:
        return ""
    md_lines = []
    num_cols = max(len(row) for row in data)
    if num_cols == 0:
        return ""
    for i, row in enumerate(data):
        cells = [escape_md_cell(clean_text(str(c))) if c is not None else "" for c in row]
        cells.extend([""] * (num_cols - len(cells)))
        md_lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            md_lines.append("| " + " | ".join(["---"] * num_cols) + " |")
    return "\n".join(md_lines) + "\n"


def parse_pdf(file_path, img_dir, force_page_render=False, detect_headings=True):
    """解析 PDF：文本块按 zone 分区输出，表格/图片按 Y 坐标流式插入，
    中文断行无空格拼接；可选基于字号推断标题层级；提取页面超链接。"""
    import fitz  # PyMuPDF

    stats = Counter()
    doc = fitz.open(file_path)
    md_lines = []
    img_counter = 1
    render_counter = 0
    page_render_count = 0
    size_weight = Counter()       # round(字号) -> 加权字符数（用于推断正文字号）
    heading_candidates = []       # (md_lines 索引, 字号, 文本)

    def page_links(page):
        uris = []
        try:
            for l in page.get_links():
                u = l.get('uri')
                if u and u not in uris:
                    uris.append(u)
        except Exception:
            pass
        return uris

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_height = page.rect.height
        links = page_links(page)

        def emit_links():
            for u in links:
                md_lines.append(f"> [页面链接] {u}")
                stats['link'] += 1

        # ====== 强制整页渲染 ======
        if force_page_render:
            img_filename, render_counter = _render_full_page(page, img_dir, page_num, render_counter)
            page_render_count += 1
            md_lines.append(f"\n<!-- meta:page_start page={page_num + 1} -->")
            md_lines.append(f"\n<!-- IMAGE: {img_filename} zone=body page_render=true -->\n[VISION_PLACEHOLDER_{img_filename}]\n")
            emit_links()
            md_lines.append("<!-- meta:page_end -->\n")
            continue

        try:
            tables = page.find_tables()
        except AttributeError:
            tables = []
            if page_num == 0:
                print("   [WARN] 当前 PyMuPDF 版本不支持 find_tables（需 >=1.23），表格按普通文本处理")

        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        blocks = text_dict.get("blocks", [])

        layout_items = []
        for block in blocks:
            if block["type"] != 0:
                continue
            bbox = block["bbox"]
            if is_inside_tables(bbox, tables):
                continue
            y_top_ratio = bbox[1] / page_height if page_height > 0 else 0
            y_bottom_ratio = bbox[3] / page_height if page_height > 0 else 1
            zone = "header" if y_top_ratio < 0.1 else ("footer" if y_bottom_ratio > 0.9 else "body")

            line_texts, span_sizes = [], []
            for line in block.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                line_text = clean_text(line_text)
                if line_text:
                    line_texts.append(line_text)
                span_sizes.extend(s.get("size", 0) for s in line.get("spans", []))

            block_text = smart_join(line_texts)
            if block_text:
                layout_items.append({
                    "type": "text", "bbox": bbox, "text": block_text, "zone": zone,
                    "font_size": max(span_sizes) if span_sizes else 0,
                })
                if zone == "body":
                    size_weight[round(max(span_sizes))] += len(block_text) if span_sizes else 0

        # 表格按 Y 轴流式插入
        for tab in sorted(tables, key=lambda t: t.bbox[1]):
            tb_y = (tab.bbox[1] + tab.bbox[3]) / 2
            y_top_ratio = tab.bbox[1] / page_height if page_height > 0 else 0
            y_bottom_ratio = tab.bbox[3] / page_height if page_height > 0 else 1
            zone = "header" if y_top_ratio < 0.1 else ("footer" if y_bottom_ratio > 0.9 else "body")
            insert_idx = 0
            for idx, item in enumerate(layout_items):
                if (item["bbox"][1] + item["bbox"][3]) / 2 < tb_y:
                    insert_idx = idx + 1
            layout_items.insert(insert_idx, {"type": "table", "bbox": tab.bbox, "table": tab, "zone": zone})

        # 收集图片块
        image_list = page.get_images(full=True)
        images_to_insert = []
        for img_info in image_list:
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                if not base_image:
                    continue
                img_blob = base_image["image"]
                if len(img_blob) < 2048:
                    continue
                if base_image.get("width", 999) < 50 or base_image.get("height", 999) < 50:
                    continue
                img_zone, img_bbox = "body", (0, 0, 0, 0)
                try:
                    img_rects = page.get_image_rects(xref)
                    if img_rects:
                        rect = img_rects[0]
                        img_bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
                        y0r = rect.y0 / page_height if page_height > 0 else 0
                        y1r = rect.y1 / page_height if page_height > 0 else 1
                        if y0r < 0.1:
                            img_zone = "header"
                        elif y1r > 0.9:
                            img_zone = "footer"
                except Exception:
                    pass
                images_to_insert.append({
                    "ext": base_image.get("ext", "png"), "img_blob": img_blob,
                    "bbox": img_bbox, "zone": img_zone,
                })
            except Exception:
                pass

        header_texts = [i["text"] for i in layout_items if i["type"] == "text" and i["zone"] == "header"]
        body_texts = [i["text"] for i in layout_items if i["type"] == "text" and i["zone"] == "body"]
        footer_texts = [i["text"] for i in layout_items if i["type"] == "text" and i["zone"] == "footer"]

        use_page_render = False
        if not any([header_texts, body_texts, footer_texts]) and not image_list and not len(tables):
            use_page_render = True  # 扫描型：无文本、无图片、无表格
        if not use_page_render and _should_force_page_render(header_texts, body_texts, footer_texts, image_list):
            use_page_render = True
            print(f"   [INFO] 第 {page_num + 1} 页检测为设计型排版，改用整页渲染")

        if use_page_render:
            img_filename, render_counter = _render_full_page(page, img_dir, page_num, render_counter)
            page_render_count += 1
            md_lines.append(f"\n<!-- meta:page_start page={page_num + 1} -->")
            md_lines.append(f"\n<!-- IMAGE: {img_filename} zone=body page_render=true -->\n[VISION_PLACEHOLDER_{img_filename}]\n")
            emit_links()
            md_lines.append("<!-- meta:page_end -->\n")
            continue

        # 碎片图片落盘并按 Y 轴插入
        for img in sorted(images_to_insert, key=lambda im: im["bbox"][1]):
            img_y = (img["bbox"][1] + img["bbox"][3]) / 2
            _, img_filename, img_counter = save_image(img["img_blob"], img_dir, img_counter, img["ext"])
            insert_idx = 0
            for idx, item in enumerate(layout_items):
                if (item["bbox"][1] + item["bbox"][3]) / 2 < img_y:
                    insert_idx = idx + 1
            layout_items.insert(insert_idx, {
                "type": "image", "bbox": img["bbox"], "filename": img_filename, "zone": img["zone"],
            })

        if not layout_items and not links:
            continue  # 完全空页

        md_lines.append(f"\n<!-- meta:page_start page={page_num + 1} -->")
        for zone in ("header", "body", "footer"):
            zone_items = [i for i in layout_items if i["zone"] == zone]
            if not zone_items:
                continue
            md_lines.append(f"<!-- meta:zone {zone} -->")
            for item in zone_items:
                if item["type"] == "text":
                    if zone == "body" and detect_headings and item.get("font_size"):
                        heading_candidates.append((len(md_lines), item["font_size"], item["text"]))
                    md_lines.append(item["text"])
                    if zone == "body":
                        md_lines.append("")
                elif item["type"] == "table":
                    md_lines.append(format_pdf_table(item["table"]))
                    if zone == "body":
                        md_lines.append("")
                elif item["type"] == "image":
                    md_lines.append(f"\n<!-- IMAGE: {item['filename']} zone={item['zone']} -->\n[VISION_PLACEHOLDER_{item['filename']}]\n")
            md_lines.append("<!-- meta:zone_end -->")
        emit_links()
        md_lines.append("<!-- meta:page_end -->\n")

    total_pages = len(doc)
    doc.close()

    # 基于字号的标题推断（保守阈值：明显大于正文字号、短、非完整句）
    if detect_headings and size_weight and heading_candidates:
        body_size = max(size_weight.items(), key=lambda kv: kv[1])[0]
        eligible = {}
        for idx, fsize, text in heading_candidates:
            rs = round(fsize)
            if rs < body_size * 1.22 or rs - body_size < 1.5:
                continue
            if len(text) > 40 or text.startswith("|"):
                continue
            if re.search(r'[。．.,，;；:：、]$', text):
                continue
            eligible.setdefault(rs, []).append((idx, text))
        tier_sizes = sorted(eligible.keys(), reverse=True)[:3]
        for tier, rs in enumerate(tier_sizes):
            for idx, text in eligible[rs]:
                if 0 <= idx < len(md_lines) and md_lines[idx] == text:
                    md_lines[idx] = f"{'#' * (tier + 2)} {text}"
                    stats['pdf_heading'] += 1

    if page_render_count > 0:
        print(f"   [INFO] 共 {page_render_count}/{total_pages} 页使用了整页渲染模式")

    return md_lines, img_counter - 1 + render_counter, stats


# =============================================================================
# Excel (.xlsx) 解析器
# =============================================================================

def _resolve_xlsx_ref(wb, formula):
    """解析 'Sheet'!$B$1:$B$3 形式的引用为值列表；失败返回 None"""
    try:
        from openpyxl.utils import column_index_from_string
        m = re.match(r"^'?([^'!]+)'?!\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?$", formula or "")
        if not m:
            return None
        ws = wb[m.group(1)]
        c1 = column_index_from_string(m.group(2))
        r1 = int(m.group(3))
        c2 = column_index_from_string(m.group(4)) if m.group(4) else c1
        r2 = int(m.group(5)) if m.group(5) else r1
        values = []
        for row in ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2, values_only=True):
            values.extend(row)
        return values
    except Exception:
        return None


def _xlsx_chart_md(wb, ch, stats):
    """openpyxl 图表对象 -> Markdown；解析失败时降级为类型+标题说明（数据通常已在工作表中）"""
    ctype = CHART_TYPE_NAMES.get(getattr(ch, 'tagname', ''), getattr(ch, 'tagname', '图表'))
    title = ""
    try:
        rich = ch.title.tx.rich
        title = clean_text("".join((r.t or "") for p in rich.p for r in (p.r or [])))
    except Exception:
        try:
            if isinstance(ch.title, str):
                title = clean_text(ch.title)
        except Exception:
            pass

    head = f"> [图表: {ctype}]" + (f" {title}" if title else "")
    cats, cols = None, []
    try:
        for ser in ch.series:
            name = None
            try:
                nv = _resolve_xlsx_ref(wb, ser.tx.strRef.f)
                name = clean_text(str(nv[0])) if nv else None
            except Exception:
                pass
            vals = None
            try:
                vals = _resolve_xlsx_ref(wb, ser.val.numRef.f)
            except Exception:
                pass
            if cats is None:
                try:
                    cref = getattr(ser.cat, 'strRef', None) or getattr(ser.cat, 'numRef', None)
                    if cref is not None:
                        cats = _resolve_xlsx_ref(wb, cref.f)
                except Exception:
                    pass
            cols.append((name, vals))
    except Exception:
        cols = []

    lines = [head]
    valid_cols = [(n, v) for n, v in cols if v]
    if valid_cols:
        n_rows = max(len(v) for _, v in valid_cols)
        header = ["类目"] + [(n or f"系列{i + 1}") for i, (n, _) in enumerate(valid_cols)]
        lines.append("")
        lines.append("| " + " | ".join(escape_md_cell(h) for h in header) + " |")
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        for i in range(min(n_rows, 30)):
            cat = clean_text(str(cats[i])) if cats and i < len(cats) and cats[i] is not None else str(i + 1)
            row = [cat] + [clean_text(str(v[i])) if i < len(v) and v[i] is not None else "" for _, v in valid_cols]
            lines.append("| " + " | ".join(escape_md_cell(c) for c in row) + " |")
        if n_rows > 30:
            lines.append(f"\n*（图表数据共 {n_rows} 行，已截取前 30 行）*")
        stats['chart'] += 1
    else:
        lines.append("> （未能解析图表数据引用，源数据通常已包含在上方工作表表格中）")
        stats['chart'] += 1
    lines.append("")
    return lines


def parse_xlsx(file_path, img_dir, max_rows=500, keep_formulas=False):
    """解析 Excel：逐 Sheet 转 Markdown 表格（大表自动切 CSV 代码块），提取图表与图片"""
    from openpyxl import load_workbook

    stats = Counter()
    wb = load_workbook(file_path, data_only=True)
    fwb = None
    if keep_formulas:
        try:
            fwb = load_workbook(file_path, data_only=False)
        except Exception:
            fwb = None

    md_lines = []
    img_counter = 1
    CSV_SWITCH_ROWS = 50  # 超过此行数的表改用 CSV 代码块（更省 token、解析更稳）

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        fws = fwb[sheet_name] if fwb is not None and sheet_name in fwb.sheetnames else None
        md_lines.append(f"\n## Sheet: {sheet_name}\n")

        total_rows = ws.max_row or 0
        data_rows = []
        truncated = False
        for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if all(c is None or str(c).strip() == '' for c in row):
                continue
            if len(data_rows) >= max_rows:
                truncated = True
                break
            cells = []
            for j, val in enumerate(row):
                s = clean_text(str(val)) if val is not None else ""
                if fws is not None:
                    try:
                        fv = fws.cell(row=r_idx, column=j + 1).value
                        if isinstance(fv, str) and fv.startswith('='):
                            s = f"{s} (= {fv[1:][:60]})" if s else f"(= {fv[1:][:60]})"
                    except Exception:
                        pass
                cells.append(s)
            data_rows.append(cells)

        if not data_rows:
            md_lines.append("*(空工作表)*\n")
        else:
            width = max(len(r) for r in data_rows)
            data_rows = [r + [""] * (width - len(r)) for r in data_rows]
            # 剔除整列为空的列
            keep_cols = [c for c in range(width) if any(r[c].strip() for r in data_rows)]
            if keep_cols:
                data_rows = [[r[c] for c in keep_cols] for r in data_rows]

            if len(data_rows) > CSV_SWITCH_ROWS:
                note = f"*(共约 {total_rows} 行，以 CSV 代码块呈现"
                note += f"，已截取前 {max_rows} 行)*" if truncated else ")*"
                md_lines.append(note + "\n")
                buf = io.StringIO()
                csv.writer(buf, lineterminator="\n").writerows(data_rows)
                md_lines.append("```csv")
                md_lines.append(buf.getvalue().rstrip("\n"))
                md_lines.append("```")
                stats['csv_tables'] += 1
            else:
                header_written = False
                for r in data_rows:
                    md_lines.append("| " + " | ".join(escape_md_cell(c) for c in r) + " |")
                    if not header_written:
                        md_lines.append("| " + " | ".join(["---"] * len(r)) + " |")
                        header_written = True
                if truncated:
                    md_lines.append(f"\n*(工作表共约 {total_rows} 行，已截取前 {max_rows} 行，需要完整数据请调大 --max-rows)*")
            if truncated:
                stats['truncated_sheets'] += 1
            md_lines.append("")

        # L0: 原生图表
        for ch in list(getattr(ws, '_charts', [])):
            try:
                md_lines.extend(_xlsx_chart_md(wb, ch, stats))
            except Exception:
                md_lines.append(unparsed_marker("图表", "Excel 图表解析失败"))
                stats['unparsed'] += 1

        # 嵌入图片
        for img in list(getattr(ws, '_images', [])):
            try:
                img_blob = img._data()
                _, img_filename, img_counter = save_image(img_blob, img_dir, img_counter, "png")
                md_lines.append(f"\n<!-- IMAGE: {img_filename} -->\n[VISION_PLACEHOLDER_{img_filename}]\n")
            except Exception:
                md_lines.append(unparsed_marker("图片", "Excel 嵌入图片提取失败"))
                stats['unparsed'] += 1

    wb.close()
    if fwb is not None:
        fwb.close()
    return md_lines, img_counter - 1, stats


# =============================================================================
# PowerPoint (.pptx) 解析器
# =============================================================================

def parse_pptx(file_path, img_dir):
    """解析 PPT：递归遍历形状（含组合形状），提取文本/图片/表格/原生图表/SmartArt/备注"""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    stats = Counter()
    prs = Presentation(file_path)
    md_lines = []
    img_counter = 1

    def shape_sort_key(s):
        try:
            return (s.top if s.top is not None else 0, s.left if s.left is not None else 0)
        except Exception:
            return (0, 0)

    def process_shapes(shapes, slide_part, out, title):
        nonlocal img_counter
        for shape in sorted(list(shapes), key=shape_sort_key):
            try:
                stype = shape.shape_type
            except Exception:
                stype = None

            # 组合形状：递归展开
            if stype == MSO_SHAPE_TYPE.GROUP:
                stats['groups'] += 1
                try:
                    process_shapes(shape.shapes, slide_part, out, title)
                except Exception:
                    out.append(unparsed_marker("组合形状", "递归展开失败"))
                    stats['unparsed'] += 1
                continue

            # 图片（覆盖普通图片与占位符内图片）
            img_blob, ext = None, "png"
            try:
                img_blob = shape.image.blob
                ext = shape.image.content_type.split('/')[-1]
            except Exception:
                pass
            if img_blob:
                _, img_filename, img_counter = save_image(img_blob, img_dir, img_counter, ext)
                out.append(f"\n<!-- IMAGE: {img_filename} -->\n[VISION_PLACEHOLDER_{img_filename}]\n")
                continue

            # L0: 原生图表
            if getattr(shape, 'has_chart', False):
                chart_lines = None
                try:
                    chart_lines = chart_xml_to_md(shape.chart.part.blob)
                except Exception:
                    chart_lines = None
                if chart_lines:
                    out.append("\n".join(chart_lines))
                    stats['chart'] += 1
                else:
                    out.append(unparsed_marker("图表", "检测到图表但无法读取数据"))
                    stats['unparsed'] += 1
                continue

            # SmartArt
            try:
                gd = shape._element.find('.//' + q(NS_A, 'graphicData'))
            except Exception:
                gd = None
            if gd is not None and 'diagram' in (gd.get('uri') or ""):
                out.append(smartart_md(gd, slide_part.related_parts, stats))
                continue

            # 表格
            if getattr(shape, 'has_table', False):
                table = shape.table
                for i, row in enumerate(table.rows):
                    cells = [escape_md_cell(clean_text(cell.text)) for cell in row.cells]
                    out.append("| " + " | ".join(cells) + " |")
                    if i == 0:
                        out.append("| " + " | ".join(["---"] * len(cells)) + " |")
                out.append("")
                continue

            # 文本框（含超链接保留）
            if getattr(shape, 'has_text_frame', False):
                for para in shape.text_frame.paragraphs:
                    parts = []
                    for run in para.runs:
                        t = run.text or ""
                        addr = None
                        try:
                            addr = run.hyperlink.address
                        except Exception:
                            pass
                        if addr and t:
                            parts.append(f"[{t}]({addr})")
                            stats['link'] += 1
                        else:
                            parts.append(t)
                    text = clean_text("".join(parts)) or clean_text(para.text)
                    if text and text != title:
                        if para.level > 0:
                            out.append("  " * para.level + f"- {text}")
                        else:
                            out.append(text)

    for slide_num, slide in enumerate(prs.slides, 1):
        title = ""
        try:
            if slide.shapes.title:
                title = clean_text(slide.shapes.title.text)
        except Exception:
            pass

        slide_lines = []
        process_shapes(slide.shapes, slide.part, slide_lines, title)

        # 演讲者备注（知识密度通常很高）
        try:
            if slide.has_notes_slide:
                note_text = clean_text(slide.notes_slide.notes_text_frame.text)
                if note_text:
                    slide_lines.append(f"> [演讲者备注] {note_text}")
                    stats['notes'] += 1
        except Exception:
            pass

        has_content = any(l.strip() for l in slide_lines)
        if not has_content and not title:
            md_lines.append(f"\n<!-- meta:slide slide={slide_num} empty=true -->\n")
            continue

        md_lines.append(f"\n## Slide {slide_num}: {title if title else '(无标题)'}\n")
        if has_content:
            md_lines.extend(slide_lines)
        else:
            md_lines.append("*(分节页，无正文内容)*")
        md_lines.append("")

    return md_lines, img_counter - 1, stats


# =============================================================================
# Markdown / 纯文本 解析器
# =============================================================================

def parse_text(file_path, img_dir):
    """读取 .md / .txt 文件，处理本地图片引用"""
    stats = Counter()
    encodings = ['utf-8-sig', 'utf-8', 'gbk', 'big5', 'utf-16', 'latin-1']
    content = None
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                content = f.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if content is None:
        raise ValueError(f"无法以任何已知编码读取文件: {file_path}")

    img_counter = 1
    processed_lines = []
    img_pattern = re.compile(r'!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+"[^"]*")?\s*\)')
    for line in content.split('\n'):
        for alt, img_path in img_pattern.findall(line):
            if img_path.startswith(('http://', 'https://', 'data:')):
                continue  # 远程/内联图片保持原样
            abs_path = os.path.join(os.path.dirname(file_path), img_path)
            if os.path.exists(abs_path):
                ext = os.path.splitext(img_path)[1].lstrip('.')
                with open(abs_path, 'rb') as f:
                    blob = f.read()
                _, img_filename, img_counter = save_image(blob, img_dir, img_counter, ext or 'png')
                line = line.replace(
                    f"![{alt}]({img_path})",
                    f"\n<!-- IMAGE: {img_filename} -->\n[VISION_PLACEHOLDER_{img_filename}]\n")
        processed_lines.append(line)

    return processed_lines, img_counter - 1, stats


# =============================================================================
# 主函数：格式路由
# =============================================================================

FORMAT_PARSERS = {
    '.docx': parse_docx,
    '.pdf': parse_pdf,
    '.xlsx': parse_xlsx,
    '.pptx': parse_pptx,
    '.md': parse_text,
    '.txt': parse_text,
}

UNSUPPORTED_FORMATS = {
    '.doc': '不支持旧版 .doc 格式，请先用 Word/WPS/LibreOffice 转换为 .docx',
    '.xls': '不支持旧版 .xls 格式（openpyxl 无法读取），请先用 Excel/WPS 另存为 .xlsx',
    '.ppt': '不支持旧版 .ppt 格式，请先用 PowerPoint/WPS 另存为 .pptx',
}


def _resolve_work_dir(source_dir, base_name, ext, file_path, output_dir):
    """确定工作目录；同名不同格式的源文件会冲突，依据 meta 自动加后缀隔离"""
    if output_dir is not None:
        return ensure_dir(output_dir)
    candidate = os.path.join(source_dir, f"{base_name}_workdir")
    meta_path = os.path.join(candidate, f"{base_name}_extract_meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                old_source = json.load(f).get('source_file', '')
            if old_source and os.path.abspath(old_source) != os.path.abspath(file_path):
                suffixed = os.path.join(source_dir, f"{base_name}_{ext.lstrip('.')}_workdir")
                print(f"   [INFO] {os.path.basename(candidate)} 已被其他源文件占用，改用 {os.path.basename(suffixed)}")
                return ensure_dir(suffixed)
        except Exception:
            pass
    return ensure_dir(candidate)


def extract_document(file_path, output_dir=None, force_page_render=False,
                     max_rows=500, keep_formulas=False, detect_pdf_headings=True):
    """
    主入口：根据文件格式路由到对应解析器。
    过程文件输出至 `{原文件名}_workdir/`；返回 (骨架路径, 图片目录, 图片数, 格式, 工作目录)
    """
    file_path = os.path.abspath(file_path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    base_name = os.path.splitext(os.path.basename(file_path))[0]

    if ext in UNSUPPORTED_FORMATS:
        raise ValueError(UNSUPPORTED_FORMATS[ext])
    if ext not in FORMAT_PARSERS:
        raise ValueError(f"不支持的文件格式: {ext}\n支持的格式: {', '.join(FORMAT_PARSERS.keys())}")

    source_dir = os.path.dirname(file_path)
    work_dir = _resolve_work_dir(source_dir, base_name, ext, file_path, output_dir)
    img_dir = ensure_dir(os.path.join(work_dir, "extracted_images"))
    skeleton_path = os.path.join(work_dir, f"{base_name}_skeleton.md")

    print(f"  正在解析 {ext} 文件: {os.path.basename(file_path)}")
    if force_page_render and ext == '.pdf':
        print("  [INFO] 强制整页渲染模式已启用")
    print(f"  过程文件将输出至: {work_dir}")

    parser = FORMAT_PARSERS[ext]
    if ext == '.pdf':
        md_lines, img_count, stats = parser(
            file_path, img_dir, force_page_render=force_page_render,
            detect_headings=detect_pdf_headings)
    elif ext == '.xlsx':
        md_lines, img_count, stats = parser(
            file_path, img_dir, max_rows=max_rows, keep_formulas=keep_formulas)
    else:
        md_lines, img_count, stats = parser(file_path, img_dir)

    content = "\n".join(md_lines)
    content = re.sub(r'\n{3,}', '\n\n', content)

    with open(skeleton_path, 'w', encoding='utf-8') as f:
        f.write(content)

    # 图片去重检测（整页渲染模式跳过：每页天然不同）
    image_hash_map, duplicate_map = {}, {}
    if not force_page_render and os.path.isdir(img_dir):
        for img_file in sorted(os.listdir(img_dir)):
            full = os.path.join(img_dir, img_file)
            if not os.path.isfile(full):
                continue
            with open(full, 'rb') as f:
                h = hashlib.md5(f.read()).hexdigest()
            if h in image_hash_map:
                duplicate_map[img_file] = image_hash_map[h]
            else:
                image_hash_map[h] = img_file

    if duplicate_map:
        with open(skeleton_path, 'r', encoding='utf-8') as f:
            content = f.read()
        for dup_file, orig_file in duplicate_map.items():
            content = content.replace(f"<!-- IMAGE: {dup_file}", f"<!-- IMAGE: {dup_file} duplicate_of={orig_file}")
        with open(skeleton_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"   [INFO] 检测到 {len(duplicate_map)} 张重复图片（可能是 logo/水印）")

    placeholder_count = content.count("[VISION_PLACEHOLDER_")

    print("[OK] 阶段1完成！")
    print(f"   - 文件格式: {ext}")
    print(f"   - 提取图片: {img_count} 张")
    s = stats or Counter()
    print(f"   - 结构化对象: 公式 {s.get('formula', 0)} | 原生图表 {s.get('chart', 0)} | SmartArt {s.get('smartart', 0)}"
          f" | 文本框 {s.get('textbox', 0)} | 链接 {s.get('link', 0)} | 备注 {s.get('notes', 0)} | 未解析 {s.get('unparsed', 0)}")
    print(f"   - 工作目录: {work_dir}")
    print(f"   - 骨架文件: {skeleton_path}")
    print(f"   - 图片目录: {img_dir}")
    if placeholder_count != img_count:
        print(f"   [!] 注意：占位符数量 ({placeholder_count}) 与图片数量 ({img_count}) 不一致")

    meta = {
        "extractor_version": __version__,
        "source_file": file_path,
        "source_format": ext,
        "work_dir": work_dir,
        "skeleton_file": skeleton_path,
        "image_dir": img_dir,
        "image_count": img_count,
        "placeholder_count": placeholder_count,
        "duplicate_images": duplicate_map,
        "force_page_render": force_page_render,
        "structured_stats": dict(s),
    }
    meta_path = os.path.join(work_dir, f"{base_name}_extract_meta.json")
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return skeleton_path, img_dir, img_count, ext, work_dir


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="多格式文档结构提取器 v2：文档 -> Markdown 骨架 + 图片 + 结构化对象（公式/图表/SmartArt）"
    )
    parser.add_argument("input_file", help="输入文件路径")
    parser.add_argument("--output-dir", "-o", default=None,
                        help="工作目录（默认在源文件同级创建 {文件名}_workdir/）")
    parser.add_argument("--force-page-render", action="store_true",
                        help="强制 PDF 所有页面整页渲染为图片（适合画册/宣传册/设计型文档）")
    parser.add_argument("--max-rows", type=int, default=500,
                        help="Excel 单 Sheet 最大提取行数（默认 500，超出截断并标注）")
    parser.add_argument("--keep-formulas", action="store_true",
                        help="Excel 单元格保留计算公式（在值后追加 (= 公式)）")
    parser.add_argument("--no-pdf-headings", action="store_true",
                        help="关闭 PDF 基于字号的标题层级推断")

    args = parser.parse_args()

    try:
        skeleton_path, img_dir, img_count, fmt, work_dir = extract_document(
            args.input_file, args.output_dir,
            force_page_render=args.force_page_render,
            max_rows=args.max_rows,
            keep_formulas=args.keep_formulas,
            detect_pdf_headings=not args.no_pdf_headings,
        )
        print(f"\n[OK] 提取完成！过程文件在 {work_dir}，可以开始阶段1.5（清洗）与阶段2（图片视觉降维）。")
    except Exception as e:
        print(f"[FAIL] 提取失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
