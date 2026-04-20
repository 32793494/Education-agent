"""
生成中文书籍实体去重评估报告
用法: python test_prompt/generate_zh_eval_report.py
输出: test_prompt/results/entity_merge/zh_eval_report.html
"""

import json
from pathlib import Path
from collections import defaultdict

BASE = Path("test_prompt/results/entity_merge")
ROUND = "round_07_all15_merge_v7"

ZH_BOOK_LABELS = {
    "09": "09_可解释AI导论",
    "10": "10_大数据与AI导论",
    "11": "11_数据科学概率",
    "12": "12_游戏设计师25年",
    "13": "13_游戏设计师修炼",
    "14": "14_知识图谱",
    "15": "15_AB测试设计",
}

def book_label(book_path):
    for k, v in ZH_BOOK_LABELS.items():
        if f"_{k}_" in book_path or book_path.startswith(k + "_"):
            return v
    return book_path[:30]

def is_zh_book(book_path):
    return any(ord(ch) > 127 for ch in book_path)

def load_jsonl(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]

def badge(text, color):
    colors = {
        "green": "#2da44e", "red": "#cf222e", "blue": "#0969da",
        "orange": "#bc4c00", "gray": "#6e7781", "purple": "#8250df",
        "teal": "#1b7c83",
    }
    bg = colors.get(color, "#6e7781")
    return f'<span style="background:{bg};color:#fff;padding:2px 7px;border-radius:10px;font-size:12px;font-weight:600">{text}</span>'

def book_badges(books):
    tags = []
    for b in books:
        label = book_label(b)
        color = "blue" if is_zh_book(b) else "gray"
        tags.append(badge(label, color))
    return " ".join(tags)

def escape(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def main():
    clusters = load_jsonl(BASE / f"{ROUND}_clusters.jsonl")

    # 分类
    zh_only_clusters = []    # 只出现在中文书
    zh_mixed_clusters = []   # 中英混合
    cross_zh_clusters = []   # 跨多本中文书

    for c in clusters:
        books = c.get("books", [])
        zh = [b for b in books if is_zh_book(b)]
        en = [b for b in books if not is_zh_book(b)]
        if zh and not en:
            zh_only_clusters.append(c)
        if zh and en:
            zh_mixed_clusters.append(c)
        if len(zh) >= 2:
            cross_zh_clusters.append(c)

    # 中文书各自实体数
    book_stat = defaultdict(int)
    for c in clusters:
        for b in c.get("books", []):
            if is_zh_book(b):
                book_stat[book_label(b)] += 1

    # 潜在重复：中文 canonical_name，前4字相同
    zh_clusters = [c for c in clusters if any(ord(ch) > 127 for ch in c.get("canonical_name", ""))]
    prefix_groups = defaultdict(list)
    for c in zh_clusters:
        name = c["canonical_name"]
        if len(name) >= 4:
            prefix_groups[name[:4]].append(c)
    potential_dups = sorted(
        [(k, v) for k, v in prefix_groups.items() if len(v) >= 2],
        key=lambda x: -len(x[1])
    )

    # 重复 canonical_name（完全相同的名字出现多次）
    name_count = defaultdict(list)
    for c in clusters:
        name_count[c["canonical_name"]].append(c)
    exact_dups = [(name, cs) for name, cs in name_count.items() if len(cs) >= 2]
    exact_dups.sort(key=lambda x: -len(x[1]))

    # ---- HTML ----
    css = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
       background: #f6f8fa; color: #1f2328; font-size: 14px; }
.container { max-width: 1280px; margin: 0 auto; padding: 24px; }
h1 { font-size: 22px; margin-bottom: 4px; }
.sub { color: #57606a; margin-bottom: 24px; font-size: 13px; }
.stats { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 24px; }
.stat { background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 14px 18px; min-width: 130px; }
.stat .num { font-size: 26px; font-weight: 700; }
.stat .label { font-size: 12px; color: #57606a; margin-top: 2px; }
.stat.blue .num { color: #0969da; }
.stat.green .num { color: #2da44e; }
.stat.orange .num { color: #bc4c00; }
.stat.red .num { color: #cf222e; }
.section { background: #fff; border: 1px solid #d0d7de; border-radius: 8px; margin-bottom: 18px; }
.sec-head { padding: 14px 18px; border-bottom: 1px solid #d0d7de; }
.sec-head h2 { font-size: 15px; }
.sec-body { padding: 16px 18px; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { background: #f6f8fa; text-align: left; padding: 7px 10px; border: 1px solid #d0d7de;
     font-weight: 600; position: sticky; top: 0; z-index: 1; }
td { padding: 7px 10px; border: 1px solid #d0d7de; vertical-align: top; }
tr:nth-child(even) td { background: #f6f8fa; }
.tip { background: #ddf4ff; border: 1px solid #54aeff; border-radius: 6px;
       padding: 9px 13px; margin-bottom: 12px; font-size: 13px; }
.warn { background: #fff8c5; border: 1px solid #d4a72c; border-radius: 6px;
        padding: 9px 13px; margin-bottom: 12px; font-size: 13px; }
.danger { background: #ffebe9; border: 1px solid #ff8182; border-radius: 6px;
          padding: 9px 13px; margin-bottom: 12px; font-size: 13px; }
code { background: #eaeef2; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
"""

    def render_cluster_rows(cs, max_rows=None):
        display = cs[:max_rows] if max_rows else cs
        rows = ""
        for c in display:
            forms = [m["name"] for m in c.get("member_forms", [])]
            forms_html = " / ".join(f"<code>{escape(f)}</code>" for f in forms)
            zh_books = [b for b in c.get("books", []) if is_zh_book(b)]
            en_books = [b for b in c.get("books", []) if not is_zh_book(b)]
            book_html = " ".join(badge(book_label(b), "blue") for b in zh_books)
            if en_books:
                book_html += " " + " ".join(badge("英文书", "gray") for _ in en_books)
            rows += f"""<tr>
              <td><strong>{escape(c['canonical_name'])}</strong></td>
              <td>{badge(c.get('type','?'), 'teal')}</td>
              <td style="text-align:center">{c.get('form_count',1)}</td>
              <td style="text-align:center">{c.get('mention_count',0)}</td>
              <td>{forms_html}</td>
              <td>{book_html}</td>
            </tr>"""
        return rows

    # 1. 中英混合合并（含多词形）
    zh_mixed_multi = sorted([c for c in zh_mixed_clusters if c.get("form_count", 1) >= 2],
                             key=lambda x: -x.get("form_count", 0))

    # 2. 纯中文书多词形合并
    zh_only_multi = sorted([c for c in zh_only_clusters if c.get("form_count", 1) >= 2],
                           key=lambda x: -x.get("form_count", 0))

    # 3. 跨中文书单词形（同一个词在多本书出现，form_count=1）
    cross_zh_single = sorted([c for c in cross_zh_clusters if c.get("form_count", 1) == 1],
                              key=lambda x: -x.get("book_count", 0))

    # Table header
    th = """<table><thead><tr>
      <th style="width:20%">规范名</th><th style="width:9%">类型</th>
      <th style="width:7%">词形数</th><th style="width:7%">出现次数</th>
      <th style="width:35%">所有词形</th><th style="width:22%">来源书籍</th>
    </tr></thead><tbody>"""

    def section(title, tip_type, tip_text, rows_html, total, shown):
        extra = f"（显示前 {shown} 条，共 {total} 条）" if shown < total else f"共 {total} 条"
        tip_cls = {"tip": "tip", "warn": "warn", "danger": "danger"}[tip_type]
        return f"""
<div class="section">
  <div class="sec-head"><h2>{title}</h2></div>
  <div class="sec-body">
    <div class="{tip_cls}">{tip_text}</div>
    <p style="color:#57606a;margin-bottom:10px">{extra}</p>
    {th}{rows_html}</tbody></table>
  </div>
</div>"""

    # 完全重复 canonical_name 表
    dup_rows = ""
    for name, cs in exact_dups[:100]:
        books_all = []
        for c in cs:
            books_all += [book_label(b) for b in c.get("books", []) if is_zh_book(b)]
        books_html = " ".join(badge(b, "blue") for b in books_all[:6])
        types = list({c.get("type","?") for c in cs})
        dup_rows += f"""<tr>
          <td><strong>{escape(name)}</strong></td>
          <td>{" ".join(badge(t,'teal') for t in types)}</td>
          <td style="text-align:center;color:#cf222e;font-weight:700">{len(cs)}</td>
          <td>{books_html}</td>
        </tr>"""

    dup_table = f"""<table><thead><tr>
      <th style="width:30%">实体名</th><th style="width:15%">类型</th>
      <th style="width:10%">重复次数</th><th style="width:45%">出现书籍</th>
    </tr></thead><tbody>{dup_rows}</tbody></table>"""

    # 前缀相似组（潜在漏合并）
    sim_rows = ""
    for prefix, group in potential_dups[:80]:
        names = [c["canonical_name"] for c in group]
        names_html = " / ".join(f"<code>{escape(n)}</code>" for n in names)
        zh_b = []
        for c in group:
            zh_b += [book_label(b) for b in c.get("books",[]) if is_zh_book(b)]
        books_html = " ".join(badge(b, "blue") for b in sorted(set(zh_b))[:5])
        sim_rows += f"""<tr>
          <td style="font-weight:600">{escape(prefix)}…</td>
          <td style="text-align:center">{len(group)}</td>
          <td>{names_html}</td>
          <td>{books_html}</td>
        </tr>"""

    sim_table = f"""<table><thead><tr>
      <th style="width:12%">共同前缀</th><th style="width:8%">词数</th>
      <th style="width:50%">所有相似词</th><th style="width:30%">出现书籍</th>
    </tr></thead><tbody>{sim_rows}</tbody></table>"""

    # 统计卡片
    stats_html = "".join(
        f'<div class="stat blue"><div class="num">{cnt}</div><div class="label">{label}</div></div>'
        for label, cnt in [
            ("7本中文书实体总量", sum(book_stat.values())),
            ("跨中文书 cluster", len(cross_zh_clusters)),
            ("中英混合合并", len(zh_mixed_multi)),
            ("纯中文书合并", len(zh_only_multi)),
            ("完全重复名称", len(exact_dups)),
            ("潜在前缀相似组", len(potential_dups)),
        ]
    )

    book_stat_rows = "".join(
        f'<tr><td>{badge(label,"blue")}</td><td style="text-align:right">{cnt}</td></tr>'
        for label, cnt in sorted(book_stat.items())
    )

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>任务11 中文书籍实体评估报告</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>任务11 — 中文书籍实体去重评估报告</h1>
<p class="sub">基线：{ROUND} &nbsp;·&nbsp; 专注中文书籍（09–15）的合并效果与潜在漏合并</p>

<div class="stats">{stats_html}</div>

<div class="section">
  <div class="sec-head"><h2>各中文书实体数量</h2></div>
  <div class="sec-body">
    <table style="width:300px"><thead><tr><th>书籍</th><th>实体数</th></tr></thead>
    <tbody>{book_stat_rows}</tbody></table>
  </div>
</div>

{section(
    "一、中英混合合并（中文概念名 ↔ 英文名）",
    "tip",
    "✅ <strong>已成功合并：</strong>这些是跨语言被合并的实体，如「机器学习 ↔ machine learning」。检查合并是否正确，有没有将不同概念错误合并。",
    render_cluster_rows(zh_mixed_multi),
    len(zh_mixed_multi), len(zh_mixed_multi)
)}

{section(
    "二、纯中文书内部合并（中文词形变体）",
    "tip",
    "✅ <strong>已成功合并：</strong>中文书籍内部的词形变体合并，如大小写、括号缩写等。",
    render_cluster_rows(zh_only_multi),
    len(zh_only_multi), len(zh_only_multi)
)}

{section(
    "三、跨中文书出现、未做词形合并的 cluster（同词跨书）",
    "warn",
    "⚠️ <strong>注意：</strong>这些概念在多本中文书里都出现，但只有一个词形（form_count=1）。说明同一个词在不同书里写法完全相同，已经被合到一个节点了 —— 这是正确的。但你需要检查：有没有语义一样但写法略有不同、却没被合并的？",
    render_cluster_rows(cross_zh_single, max_rows=100),
    len(cross_zh_single), min(100, len(cross_zh_single))
)}

<div class="section">
  <div class="sec-head"><h2>四、完全相同名称出现多次（可能是误未合并）</h2></div>
  <div class="sec-body">
    <div class="danger">🚨 <strong>需要重点检查：</strong>同一个 canonical_name 在 cluster 列表里出现了多次（理论上应该只有一个节点）。这说明合并可能有遗漏。共 <strong>{len(exact_dups)}</strong> 个。</div>
    <p style="color:#57606a;margin-bottom:10px">显示前 100 条，按重复次数排序</p>
    {dup_table}
  </div>
</div>

<div class="section">
  <div class="sec-head"><h2>五、前缀相似、可能未合并的词群（潜在漏合并）</h2></div>
  <div class="sec-body">
    <div class="warn">⚠️ <strong>需要人工判断：</strong>这些词前4个字相同，可能是同一概念的不同表述（如「知识图谱推理」和「知识图谱推理新进展」），也可能是合理的不同概念。逐组判断，标记哪些该合并。</div>
    <p style="color:#57606a;margin-bottom:10px">显示前 80 组，按组内词数排序</p>
    {sim_table}
  </div>
</div>

</div>
</body>
</html>"""

    out = BASE / "zh_eval_report.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK] Report: {out.resolve()}")

if __name__ == "__main__":
    main()
