"""
Markdown 组装回填脚本 (doc_to_md_assembler.py) v2.0
将视觉描述回填至 Markdown 骨架，生成 front-matter / 摘要 / TOC，输出最终 Agent 友好的 .md 文件。

v2.0 变化：
- 缓存契约：首选 JSONL（每行 {"file": "image_001.png", "text": "描述"}），兼容旧版扁平 dict JSON
- 修复：未描述占位符超过 10 个时只有前 10 个被标记的泄漏问题（现在全部处理）
- 新增：--summary-file（避免命令行引号转义）、--clean-decisions（声明式清洗）、--force
- 新增：YAML front-matter 溯源块（写入源文件、转换时间、各类对象计数）
- 新增：覆盖保护——目标文件已存在且不是本工具生成物时拒绝覆盖
- 新增：TOC 重复标题锚点自动加 -1/-2 后缀

用法: python doc_to_md_assembler.py "<骨架文件>" "<缓存JSON/JSONL>" "<输出文件>" [--summary-file <摘要文件>]
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime

__version__ = "2.0.0"

GENERATOR_MARK = "doc-to-agent-markdown"


# =============================================================================
# 缓存加载（JSONL 优先，兼容多种历史格式）
# =============================================================================

def _normalize_cache_entry(obj):
    """从一条记录对象中提取 (文件名, 描述文本)，识别多种字段命名"""
    if not isinstance(obj, dict):
        return None, None
    name = obj.get('file') or obj.get('name') or obj.get('image') or obj.get('filename')
    text = obj.get('text') or obj.get('description') or obj.get('desc')
    return name, text


def load_cache(cache_path):
    """加载视觉描述缓存 -> {图片文件名: 描述文本}

    支持格式：
    1. JSONL（推荐）：每行 {"file": "image_001.png", "text": "描述"}；后写覆盖先写
    2. JSON 扁平字典：{"image_001.png": "描述", ...}
    3. JSON 列表：[{"file": ..., "text": ...}, ...]
    """
    if not os.path.exists(cache_path):
        print(f"[!] 缓存文件不存在: {cache_path}（将按无描述处理）")
        return {}
    with open(cache_path, 'r', encoding='utf-8') as f:
        raw = f.read().strip()
    if not raw:
        return {}

    result = {}
    # 先尝试整体 JSON
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str):
                    result[k] = v
                else:
                    name, text = _normalize_cache_entry(v if isinstance(v, dict) else {})
                    if text:
                        result[name or k] = text
            return result
        if isinstance(data, list):
            for item in data:
                name, text = _normalize_cache_entry(item)
                if name and text:
                    result[name] = text
            return result
    except json.JSONDecodeError:
        pass

    # 按 JSONL 逐行解析
    bad_lines = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            bad_lines += 1
            continue
        name, text = _normalize_cache_entry(obj)
        if name and text:
            result[name] = text
    if bad_lines:
        print(f"[!] 缓存中有 {bad_lines} 行无法解析为 JSON，已跳过")
    return result


# =============================================================================
# 声明式清洗（阶段 1.5 的 LLM 决策由脚本执行，避免手工编辑大文件）
# =============================================================================

def load_clean_decisions(path):
    """读取清洗决策 JSON：{"drop_zones": ["header","footer"], "drop_images": ["image_003.png"]}"""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("清洗决策文件必须是 JSON 对象")
    return data


def remove_image_block(content, name):
    """移除某图片的 IMAGE 注释行 + 占位符（含格式变体兜底）"""
    content = re.sub(
        r'\n?\s*<!-- IMAGE: ' + re.escape(name) + r'[^>]*-->\s*\n?\s*\[VISION_PLACEHOLDER_'
        + re.escape(name) + r'\]\s*\n?',
        '\n', content)
    content = re.sub(
        r'\s*\[VISION_PLACEHOLDER_' + re.escape(name) + r'\]\s*\n?',
        '\n', content)
    return content


def apply_clean_decisions(content, decisions):
    """执行清洗决策，返回 (清洗后内容, 报告字符串列表)"""
    report = []
    zones = decisions.get('drop_zones') or []
    for zone in zones:
        if zone not in ('header', 'footer'):
            report.append(f"[!] 忽略未知 zone: {zone}（仅支持 header/footer）")
            continue
        pattern = re.compile(
            r'<!-- meta:zone ' + re.escape(zone) + r' -->.*?<!-- meta:zone_end -->\n?',
            re.DOTALL)
        content, n = pattern.subn('', content)
        report.append(f"已删除 {n} 个 {zone} 区块")
    images = decisions.get('drop_images') or []
    for name in images:
        before = content
        content = remove_image_block(content, name)
        report.append(f"已移除图片 {name}" if content != before else f"[!] 未找到图片 {name} 的占位符")
    return content, report


# =============================================================================
# TOC 生成（重复标题锚点加后缀）
# =============================================================================

def generate_toc(content):
    """根据 Markdown 标题层级生成目录（排除 meta 注释；重复锚点自动加 -N 后缀）"""
    toc_lines = ["# 目录\n"]
    anchor_seen = Counter()
    for line in content.split('\n'):
        if line.strip().startswith('<!-- meta:'):
            continue
        match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if not match:
            continue
        level = len(match.group(1))
        title = match.group(2).strip()
        if title == "目录":
            continue
        anchor = re.sub(r'[^\w一-鿿\s-]', '', title).strip().replace(' ', '-').lower()
        n = anchor_seen[anchor]
        anchor_seen[anchor] += 1
        if n:
            anchor = f"{anchor}-{n}"
        toc_lines.append(f"{'  ' * (level - 1)}- [{title}](#{anchor})")

    if len(toc_lines) <= 1:
        return ""
    return "\n".join(toc_lines) + "\n\n---\n\n"


# =============================================================================
# 元信息与 front-matter
# =============================================================================

def find_extract_meta(skeleton_path):
    """根据骨架文件名定位同目录的 {base}_extract_meta.json"""
    directory = os.path.dirname(os.path.abspath(skeleton_path))
    base = os.path.basename(skeleton_path)
    if base.endswith('_skeleton.md'):
        meta_path = os.path.join(directory, base[:-len('_skeleton.md')] + '_extract_meta.json')
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return None
    return None


def build_front_matter(meta, total_images, replaced, skipped, failed, has_summary):
    """YAML front-matter：让下游 Agent 知道这份知识资产是什么、哪来的、缺什么"""
    stats = (meta or {}).get('structured_stats', {})
    lines = [
        "---",
        f"generated_by: {GENERATOR_MARK} v{__version__}",
        f"source_file: {os.path.basename((meta or {}).get('source_file', '') or '未知')}",
        f"source_format: {(meta or {}).get('source_format', '未知')}",
        f"converted_at: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"images_total: {total_images}",
        f"images_described: {replaced}",
        f"images_skipped: {skipped}",
        f"images_failed: {failed}",
    ]
    for key, label in (("formula", "formulas"), ("chart", "charts"), ("smartart", "smartart"),
                       ("link", "links"), ("textbox", "textboxes"), ("notes", "speaker_notes"),
                       ("unparsed", "unparsed_objects")):
        if stats.get(key):
            lines.append(f"{label}: {stats[key]}")
    lines.append(f"summary_included: {'true' if has_summary else 'false'}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def check_overwrite_safety(output_path, meta, force):
    """覆盖保护：目标已存在且非本工具产物 / 源文件不同 -> 拒绝（--force 跳过）"""
    if force or not os.path.exists(output_path):
        return
    try:
        with open(output_path, 'r', encoding='utf-8', errors='replace') as f:
            head = f.read(600)
    except Exception:
        head = ""
    if f"generated_by: {GENERATOR_MARK}" not in head:
        raise RuntimeError(
            f"输出文件已存在且不是本工具生成的: {output_path}\n"
            f"为防止覆盖原始数据已中止。请换一个输出文件名（推荐 <原文件名>_agent.md），"
            f"或确认无误后加 --force 强制覆盖。")
    src = os.path.basename((meta or {}).get('source_file', '') or '')
    m = re.search(r'^source_file:\s*(.+)$', head, re.MULTILINE)
    if src and m and m.group(1).strip() != src:
        raise RuntimeError(
            f"输出文件已存在，但来自另一个源文件（{m.group(1).strip()}），与当前源（{src}）不同。\n"
            f"请使用不同的输出名（如 <原文件名>_{(meta or {}).get('source_format', '').lstrip('.')}_agent.md），"
            f"或加 --force 强制覆盖。")


# =============================================================================
# 主组装流程
# =============================================================================

def assemble_final_md(skeleton_path, cache_path, output_path, summary_text=None,
                      skip_undescribed=False, clean_decisions_path=None, force=False):
    meta = find_extract_meta(skeleton_path)
    check_overwrite_safety(output_path, meta, force)

    with open(skeleton_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 声明式清洗（阶段 1.5 决策）
    if clean_decisions_path:
        decisions = load_clean_decisions(clean_decisions_path)
        content, clean_report = apply_clean_decisions(content, decisions)
        for line in clean_report:
            print(f"   [清洗] {line}")

    descriptions = load_cache(cache_path)

    total_placeholders = len(re.findall(r'\[VISION_PLACEHOLDER_[^\]]+\]', content))
    replaced_count = 0

    # 回填视觉描述（带图片文件名，保留向 workdir 原图溯源的能力）
    for img_name, desc in descriptions.items():
        placeholder = f"[VISION_PLACEHOLDER_{img_name}]"
        if placeholder in content:
            desc_lines = (desc or "").strip().split('\n')
            formatted = f"> **[图片 {img_name}]** {desc_lines[0]}"
            for line in desc_lines[1:]:
                formatted += f"\n> {line}"
            content = content.replace(placeholder, formatted)
            replaced_count += 1

    # 处理未被替换的占位符（v1 的 [:10] 截断 bug 已修复：先全部处理，再限量打印）
    remaining = re.findall(r'\[VISION_PLACEHOLDER_([^\]]+)\]', content)
    skipped_count = 0
    failed_count = 0
    if remaining:
        if skip_undescribed:
            print(f"[INFO] 静默跳过 {len(remaining)} 个未描述的图片占位符")
            for name in remaining:
                content = remove_image_block(content, name)
            skipped_count = len(remaining)
        else:
            failed_count = len(remaining)
            print(f"[!] 仍有 {failed_count} 个占位符未获得描述（已替换为 L3 占位标记）:")
            for name in remaining:
                content = content.replace(
                    f"[VISION_PLACEHOLDER_{name}]",
                    f"> [未解析: 图片 {name}] 视觉描述缺失，原图见 workdir/extracted_images/")
            for name in remaining[:10]:
                print(f"   - {name}")
            if failed_count > 10:
                print(f"   ...（其余 {failed_count - 10} 个略，均已标记）")

    # 清洗
    content = re.sub(r'[ \t]+$', '', content, flags=re.MULTILINE)
    content = re.sub(r'^<!-- meta:page_start page=(\d+) -->', r'> **[第 \1 页]**', content, flags=re.MULTILINE)
    content = re.sub(r'^<!-- meta:[^>]* -->\n?', '', content, flags=re.MULTILINE)
    content = re.sub(r'\n{3,}', '\n\n', content)

    # 文档标题
    title_match = re.search(r'^# (.+)$', content, re.MULTILINE)

    summary_block = f"\n> **文档摘要**：{summary_text.strip()}\n\n" if summary_text else ""
    toc = generate_toc(content)

    if title_match:
        title_end = title_match.end()
        body = content[:title_end] + "\n" + summary_block + toc + content[title_end:].lstrip('\n')
    else:
        body = summary_block + toc + content

    front_matter = build_front_matter(
        meta, total_placeholders, replaced_count, skipped_count, failed_count, bool(summary_text))
    final_content = front_matter + body.lstrip('\n')
    if not final_content.endswith('\n'):
        final_content += '\n'

    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(final_content)

    # 质量报告
    file_size_kb = os.path.getsize(output_path) / 1024
    estimated_tokens = len(final_content) // 2
    heading_count = len(re.findall(r'^#{1,6}\s+', final_content, re.MULTILINE))
    table_count = len(re.findall(r'^\|[\s:-]*-{3}', final_content, re.MULTILINE))
    unparsed_count = len(re.findall(r'\[未解析:', final_content))
    stats = (meta or {}).get('structured_stats', {})

    report = f"""
转换质量报告
━━━━━━━━━━━━━━━━━━━━
- 标题层级数：{heading_count} 个
- 表格数量：约 {table_count} 个
- 结构化对象：公式 {stats.get('formula', 0)} | 原生图表 {stats.get('chart', 0)} | SmartArt {stats.get('smartart', 0)} | 链接 {stats.get('link', 0)}
- 图片总数：{total_placeholders} 张
  - 成功描述：{replaced_count} 张
  - 静默跳过：{skipped_count} 张
  - 未能描述：{failed_count} 张（已标记 [未解析: 图片]）
- 最终文件中 [未解析] 标记：{unparsed_count} 处
- 全文摘要：{'已生成' if summary_text else '未生成'}
- 输出文件大小：{file_size_kb:.1f} KB
- 估算 Token 数：约 {estimated_tokens} tokens
━━━━━━━━━━━━━━━━━━━━
[OK] 最终文件已生成：{output_path}
"""
    print(report)

    return {
        "output_path": output_path,
        "heading_count": heading_count,
        "table_count": table_count,
        "total_images": total_placeholders,
        "described_images": replaced_count,
        "skipped_images": skipped_count,
        "failed_images": failed_count,
        "unparsed_markers": unparsed_count,
        "has_summary": bool(summary_text),
        "file_size_kb": round(file_size_kb, 1),
        "estimated_tokens": estimated_tokens,
    }


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Markdown 组装回填脚本 v2：回填视觉描述 + front-matter/摘要/TOC，输出 Agent 友好文件"
    )
    parser.add_argument("skeleton_file", help="骨架 Markdown 文件路径")
    parser.add_argument("cache_file", help="视觉描述缓存路径（.jsonl 推荐，兼容 .json）")
    parser.add_argument("output_file", help="最终输出的 .md 文件路径（推荐 <原文件名>_agent.md）")
    parser.add_argument("--summary", "-s", default=None, help="全文摘要文本（短摘要可直接传参）")
    parser.add_argument("--summary-file", default=None,
                        help="从文件读取全文摘要（推荐，避免命令行引号转义问题）")
    parser.add_argument("--clean-decisions", default=None,
                        help='阶段1.5清洗决策 JSON 路径，如 {"drop_zones":["header"],"drop_images":["image_003.png"]}')
    parser.add_argument("--skip-undescribed", action="store_true",
                        help="静默移除未描述的图片占位符（纯文本合同/批量场景）")
    parser.add_argument("--force", action="store_true",
                        help="跳过输出文件覆盖保护检查")

    args = parser.parse_args()

    summary_text = args.summary
    if args.summary_file:
        try:
            with open(args.summary_file, 'r', encoding='utf-8') as f:
                summary_text = f.read().strip()
        except Exception as e:
            print(f"[!] 摘要文件读取失败: {e}", file=sys.stderr)

    try:
        assemble_final_md(
            args.skeleton_file,
            args.cache_file,
            args.output_file,
            summary_text=summary_text,
            skip_undescribed=args.skip_undescribed,
            clean_decisions_path=args.clean_decisions,
            force=args.force,
        )
    except Exception as e:
        print(f"[FAIL] 组装失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
