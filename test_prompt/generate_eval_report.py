"""
生成任务11人工评估HTML报告
用法: python test_prompt/generate_eval_report.py
输出: test_prompt/results/entity_merge/eval_report.html
"""

import json
import os
from pathlib import Path

BASE = Path("test_prompt/results/entity_merge")
ROUND = "round_07_all15_merge_v7"

def load_jsonl(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]

def badge(text, color):
    colors = {
        "green": "#2da44e", "red": "#cf222e", "blue": "#0969da",
        "orange": "#bc4c00", "gray": "#6e7781", "purple": "#8250df"
    }
    bg = colors.get(color, "#6e7781")
    return f'<span style="background:{bg};color:#fff;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:600">{text}</span>'

def decision_badge(decision):
    if decision == "merge":
        return badge("合并", "green")
    elif decision == "keep_separate":
        return badge("保持分离", "red")
    else:
        return badge(decision, "gray")

def signal_tags(signals):
    colors = {
        "seed_alias_match": "blue", "surface_key_match": "green",
        "parenthetical_alias": "purple", "plural_variant": "orange",
        "head_word_match": "gray", "surface_containment": "gray",
        "definition_overlap": "orange", "merge_role_mismatch": "red",
    }
    tags = []
    for s in (signals or []):
        c = colors.get(s, "gray")
        tags.append(badge(s, c))
    return " ".join(tags)

def render_candidate_table(rows, title, description="", max_rows=None):
    if not rows:
        return f"<p style='color:#888'>（无数据）</p>"
    display = rows[:max_rows] if max_rows else rows
    html = f"""
    <p style="color:#57606a;margin:4px 0 12px">{description}，共 <strong>{len(rows)}</strong> 条
    {"（仅显示前 " + str(max_rows) + " 条）" if max_rows and len(rows) > max_rows else ""}
    </p>
    <table>
    <thead><tr>
      <th style="width:22%">左词</th><th style="width:22%">右词</th>
      <th style="width:10%">决策</th><th style="width:10%">得分</th>
      <th style="width:36%">触发信号</th>
    </tr></thead><tbody>
    """
    for i, r in enumerate(display):
        bg = "#fff" if i % 2 == 0 else "#f6f8fa"
        left_def = (r.get("left_top_definitions") or [""])[:1]
        right_def = (r.get("right_top_definitions") or [""])[:1]
        left_tip = left_def[0] if left_def else ""
        right_tip = right_def[0] if right_def else ""
        html += f"""
        <tr style="background:{bg}">
          <td><strong>{r['left_name']}</strong>
              {"<br><small style='color:#888'>" + left_tip[:60] + ("…" if len(left_tip)>60 else "") + "</small>" if left_tip else ""}
          </td>
          <td><strong>{r['right_name']}</strong>
              {"<br><small style='color:#888'>" + right_tip[:60] + ("…" if len(right_tip)>60 else "") + "</small>" if right_tip else ""}
          </td>
          <td>{decision_badge(r.get('decision',''))}</td>
          <td style="text-align:center">{r.get('score_raw', 0):.2f}</td>
          <td>{signal_tags(r.get('signals', []))}</td>
        </tr>"""
    html += "</tbody></table>"
    return html

def render_cluster_table(clusters, max_rows=None):
    if not clusters:
        return "<p style='color:#888'>（无数据）</p>"
    multi = [c for c in clusters if c.get("form_count", 1) >= 2]
    multi.sort(key=lambda x: (-x.get("form_count", 0), -x.get("book_count", 0)))
    display = multi[:max_rows] if max_rows else multi
    html = f"""
    <p style="color:#57606a;margin:4px 0 12px">
    共 <strong>{len(clusters)}</strong> 个 cluster，其中多词形合并 <strong>{len(multi)}</strong> 个
    {"（仅显示前 " + str(max_rows) + " 条，按词形数量排序）" if max_rows else ""}
    </p>
    <table><thead><tr>
      <th style="width:22%">规范名</th><th style="width:12%">类型</th>
      <th style="width:8%">词形数</th><th style="width:8%">出现次数</th>
      <th style="width:8%">书籍数</th><th style="width:42%">所有词形</th>
    </tr></thead><tbody>"""
    for i, c in enumerate(display):
        bg = "#fff" if i % 2 == 0 else "#f6f8fa"
        forms = [m["name"] for m in c.get("member_forms", [])]
        forms_html = " / ".join(f"<code style='background:#eee;padding:1px 4px;border-radius:3px'>{f}</code>" for f in forms)
        html += f"""
        <tr style="background:{bg}">
          <td><strong>{c['canonical_name']}</strong></td>
          <td>{badge(c.get('type','?'), 'blue')}</td>
          <td style="text-align:center">{c.get('form_count',0)}</td>
          <td style="text-align:center">{c.get('mention_count',0)}</td>
          <td style="text-align:center">{c.get('book_count',0)}</td>
          <td style="font-size:13px">{forms_html}</td>
        </tr>"""
    html += "</tbody></table>"
    return html

def render_backlog_table(rows, max_rows=50):
    if not rows:
        return "<p style='color:#888'>（无数据）</p>"
    rows = sorted(rows, key=lambda x: -x.get("form_count", 0))
    display = rows[:max_rows]
    html = f"""
    <p style="color:#57606a;margin:4px 0 12px">共 <strong>{len(rows)}</strong> 个未处理词群（显示前 {max_rows} 个，按词形数量排序）</p>
    <table><thead><tr>
      <th style="width:15%">头词</th><th style="width:10%">类型</th>
      <th style="width:8%">词形数</th><th style="width:8%">待审对数</th>
      <th style="width:59%">包含词形（前12个）</th>
    </tr></thead><tbody>"""
    for i, r in enumerate(display):
        bg = "#fff" if i % 2 == 0 else "#f6f8fa"
        names = r.get("member_names", [])[:12]
        names_html = " · ".join(f"<code style='font-size:12px'>{n}</code>" for n in names)
        if len(r.get("member_names", [])) > 12:
            names_html += f" <span style='color:#888'>…共{len(r['member_names'])}个</span>"
        html += f"""
        <tr style="background:{bg}">
          <td><strong>{r.get('head_word','')}</strong></td>
          <td>{badge(r.get('type','?'), 'orange')}</td>
          <td style="text-align:center">{r.get('form_count',0)}</td>
          <td style="text-align:center">{r.get('unresolved_pairs',0)}</td>
          <td style="font-size:12px">{names_html}</td>
        </tr>"""
    html += "</tbody></table>"
    return html

def main():
    clusters = load_jsonl(BASE / f"{ROUND}_clusters.jsonl")
    decisions = load_jsonl(BASE / f"{ROUND}_merge_decisions.jsonl")
    backlog = load_jsonl(BASE / f"{ROUND}_recall_backlog.jsonl")
    surface = load_jsonl(BASE / f"{ROUND}_board_surface_variants.jsonl")
    inflection = load_jsonl(BASE / f"{ROUND}_board_inflection_variants.jsonl")
    aliases = load_jsonl(BASE / f"{ROUND}_board_explicit_aliases.jsonl")
    blocked = load_jsonl(BASE / f"{ROUND}_board_blocked_by_role.jsonl")

    merged_decisions = [d for d in decisions if d.get("decision") == "merge"]
    uncertain = [d for d in decisions if d.get("decision") not in ("merge", "keep_separate")]
    kept_sep = [d for d in decisions if d.get("decision") == "keep_separate"]

    total_forms = sum(c.get("form_count", 1) for c in clusters)
    merged_nodes = sum(c.get("form_count", 1) - 1 for c in clusters if c.get("form_count", 1) > 1)

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>任务11 实体去重评估报告 — {ROUND}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f6f8fa; color:#1f2328; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
h1 {{ font-size: 24px; margin-bottom: 4px; }}
.subtitle {{ color:#57606a; margin-bottom: 24px; font-size: 14px; }}
.stats {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:28px; }}
.stat-card {{ background:#fff; border:1px solid #d0d7de; border-radius:8px; padding:16px 20px; min-width:140px; }}
.stat-card .num {{ font-size:28px; font-weight:700; }}
.stat-card .label {{ font-size:13px; color:#57606a; margin-top:4px; }}
.stat-card.green .num {{ color:#2da44e; }}
.stat-card.red .num {{ color:#cf222e; }}
.stat-card.blue .num {{ color:#0969da; }}
.stat-card.orange .num {{ color:#bc4c00; }}
.section {{ background:#fff; border:1px solid #d0d7de; border-radius:8px; margin-bottom:20px; }}
.section-header {{ padding:16px 20px; border-bottom:1px solid #d0d7de; display:flex; align-items:center; gap:10px; cursor:pointer; }}
.section-header h2 {{ font-size:16px; }}
.section-body {{ padding:16px 20px; overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th {{ background:#f6f8fa; text-align:left; padding:8px 12px; border:1px solid #d0d7de; font-weight:600; position:sticky; top:0; }}
td {{ padding:8px 12px; border:1px solid #d0d7de; vertical-align:top; }}
.tip {{ background:#ddf4ff; border:1px solid #54aeff; border-radius:6px; padding:10px 14px; margin-bottom:14px; font-size:14px; }}
.warn {{ background:#fff8c5; border:1px solid #d4a72c; border-radius:6px; padding:10px 14px; margin-bottom:14px; font-size:14px; }}
</style>
</head>
<body>
<div class="container">
<h1>任务11 实体去重评估报告</h1>
<p class="subtitle">基线版本：{ROUND} &nbsp;·&nbsp; 生成时间自动填入</p>

<div class="stats">
  <div class="stat-card blue"><div class="num">{len(clusters)}</div><div class="label">合并后 cluster 数</div></div>
  <div class="stat-card green"><div class="num">{len(merged_decisions)}</div><div class="label">自动合并决策</div></div>
  <div class="stat-card red"><div class="num">{merged_nodes}</div><div class="label">节点净减少</div></div>
  <div class="stat-card orange"><div class="num">{len(backlog)}</div><div class="label">召回 backlog 词群</div></div>
  <div class="stat-card"><div class="num">{len(kept_sep)}</div><div class="label">被拦截（保持分离）</div></div>
</div>

<div class="section">
  <div class="section-header"><h2>📋 一、合并后的 Cluster 列表（精确率评估）</h2></div>
  <div class="section-body">
    <div class="tip">👀 <strong>你要看什么：</strong>每行是一个合并后的节点，检查"所有词形"列里的词是否确实是同一个概念。重点关注词形数≥3的行和跨语言合并（中英混合）。</div>
    {render_cluster_table(clusters, max_rows=200)}
  </div>
</div>

<div class="section">
  <div class="section-header"><h2>🔗 二、显式别名合并（中英对照、缩写展开）</h2></div>
  <div class="section-body">
    <div class="tip">👀 <strong>你要看什么：</strong>缩写展开和中英对照是否正确。例如 SVD ↔ 奇异值分解、PCA ↔ 主成分分析。</div>
    {render_candidate_table(aliases, "显式别名", "括号式缩写或seed别名触发的合并")}
  </div>
</div>

<div class="section">
  <div class="section-header"><h2>🔤 三、表面变体合并（大小写、连字符）</h2></div>
  <div class="section-body">
    <div class="tip">👀 <strong>你要看什么：</strong>大小写、连字符差异是否是真正的同义词，有没有把不同概念错误合并。</div>
    {render_candidate_table(surface, "表面变体", "surface_key相同或近似触发的合并")}
  </div>
</div>

<div class="section">
  <div class="section-header"><h2>📝 四、词形变体合并（单复数、时态）</h2></div>
  <div class="section-body">
    <div class="tip">👀 <strong>你要看什么：</strong>单复数/词形变化合并是否正确，有没有把"heatmap"和"heat maps"等不同词形错误处理。</div>
    {render_candidate_table(inflection, "词形变体", "单复数等词形变化触发的合并")}
  </div>
</div>

<div class="section">
  <div class="section-header"><h2>🚫 五、被拦截的候选（误并检查）</h2></div>
  <div class="section-body">
    <div class="warn">⚠️ <strong>你要看什么：</strong>这些是系统主动拦截、不合并的候选对。检查有没有"本该合并但被错误拦截"的情况。</div>
    {render_candidate_table(blocked, "角色拦截", "因merge_role不匹配被拦截", max_rows=100)}
  </div>
</div>

<div class="section">
  <div class="section-header"><h2>🔍 六、召回 Backlog（漏网之鱼检查）</h2></div>
  <div class="section-body">
    <div class="warn">⚠️ <strong>你要看什么：</strong>这些词群里有没有明显应该合并但没被合并的词？尤其关注 form_count 大的词群（如 network、model、data 下的子词）。</div>
    {render_backlog_table(backlog)}
  </div>
</div>

</div>
</body>
</html>"""

    out = BASE / "eval_report.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK] Report generated: {out.resolve()}")

if __name__ == "__main__":
    main()
