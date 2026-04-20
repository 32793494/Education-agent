"""
审查 recall_backlog — 让 DeepSeek 在每个头词组内找出漏掉的合并机会。
展示每对实体的完整释义，供人工复查。

运行方法：
    1. 安装依赖（只需一次）：
           pip install openai

    2. 直接运行：
           python test_prompt/review_recall_backlog.py

    3. 运行完成后用浏览器打开：
           test_prompt/results/entity_merge/round_07_recall_backlog_review.html

    4. 仅重新生成 HTML（不再花钱调 API）：
           python test_prompt/review_recall_backlog.py --skip-api
"""

import argparse
import asyncio
import html
import json
import os
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# ★ 填入你的 DeepSeek API Key
# --------------------------------------------------------------------------- #
DEEPSEEK_API_KEY = "sk-9362e9de868b466faaae0d1bf2a0a842"

# --------------------------------------------------------------------------- #
# 路径配置
# --------------------------------------------------------------------------- #
BASE          = Path(__file__).parent / "results/entity_merge"
BACKLOG_FILE  = BASE / "round_07_all15_merge_v7_recall_backlog.jsonl"
FORMS_FILE    = BASE / "round_07_all15_merge_v7_entity_forms.jsonl"
CACHE_FILE    = BASE / "round_07_recall_backlog_ai_cache.jsonl"
OUTPUT_HTML   = BASE / "round_07_recall_backlog_review.html"

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL    = "deepseek-chat"

# --------------------------------------------------------------------------- #
# 数据加载
# --------------------------------------------------------------------------- #

def load_groups() -> list[dict]:
    groups = []
    with open(BACKLOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                groups.append(json.loads(line))
    print(f"加载 {len(groups)} 个头词组")
    return groups


def load_entity_forms() -> dict[str, list[str]]:
    """返回 name(小写) -> top_definitions 的查找表。"""
    lookup: dict[str, list[str]] = {}
    with open(FORMS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                key = obj["name"].lower()
                lookup[key] = obj.get("top_definitions", [])
    print(f"加载 {len(lookup)} 个实体形式（用于查定义）")
    return lookup


def get_defs(lookup: dict, name: str) -> list[str]:
    return lookup.get(name.lower(), [])


def group_key(g: dict) -> str:
    return f"{g['type']}::{g['head_word']}"


def load_cache() -> dict[str, dict]:
    cache: dict[str, dict] = {}
    if CACHE_FILE.exists():
        with open(CACHE_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    cache[obj["_key"]] = obj
    return cache


def save_to_cache(result: dict) -> None:
    with open(CACHE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# DeepSeek API
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """\
你是知识图谱实体消歧专家。
我会给你一组从技术书籍中提取的实体，它们共享同一个头词。每个实体附有其定义。
请找出其中语义完全等价、应该合并为同一实体的对。

注意：
- 只报告你有把握的同义对，宁可漏报，不要误报
- 单复数变体（如 heat map / heat maps）算同义
- 中英文对照（如 机器学习 / machine learning）算同义
- 仅修饰语不同表示不同概念的不算（如 objective data ≠ subjective data）

请以 JSON 数组回复，每个元素格式：
{"left": "实体A名称", "right": "实体B名称", "reason": "一句话说明为何等价"}

若没有发现任何应合并的对，返回空数组 []。
只输出 JSON，不要有其他文字。
"""


def build_prompt(group: dict, lookup: dict) -> str:
    names = group.get("member_names", [])
    lines = []
    for n in names:
        defs = get_defs(lookup, n)
        if defs:
            defs_str = " | ".join(defs[:2])  # 最多2条定义，避免 prompt 太长
            lines.append(f"  - 「{n}」: {defs_str}")
        else:
            lines.append(f"  - 「{n}」")
    names_str = "\n".join(lines)
    return f"""\
类型: {group['type']}
头词: {group['head_word']}
组内实体（共 {group['form_count']} 个）:
{names_str}
"""


async def call_deepseek(
    client, group: dict, lookup: dict, semaphore: asyncio.Semaphore
) -> dict:
    key = group_key(group)
    async with semaphore:
        try:
            response = await client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": build_prompt(group, lookup)},
                ],
                temperature=0.0,
                max_tokens=1024,
            )
            raw = response.choices[0].message.content.strip()
            try:
                pairs = json.loads(raw)
                if not isinstance(pairs, list):
                    pairs = []
            except json.JSONDecodeError:
                m = re.search(r"\[.*\]", raw, re.DOTALL)
                pairs = json.loads(m.group()) if m else []
        except Exception as exc:
            pairs = []
            raw   = str(exc)

        result = dict(group)
        result["_key"]     = key
        result["ai_pairs"] = pairs
        result["ai_raw"]   = raw
        return result


async def run_ai_review(
    groups: list[dict],
    lookup: dict,
    api_key: str,
    workers: int,
    cache: dict[str, dict],
) -> list[dict]:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        print("[error] 请先安装: pip install openai")
        sys.exit(1)

    client    = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
    semaphore = asyncio.Semaphore(workers)

    todo = [g for g in groups if group_key(g) not in cache]
    done = [cache[group_key(g)] for g in groups if group_key(g) in cache]
    print(f"缓存命中 {len(done)} 组，待请求 {len(todo)} 组（并发={workers}）\n")

    if not todo:
        return [cache[group_key(g)] for g in groups]

    tasks   = [call_deepseek(client, g, lookup, semaphore) for g in todo]
    new_res = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        result = await coro
        new_res.append(result)
        save_to_cache(result)
        n = len(result.get("ai_pairs", []))
        print(f"  [{i:3d}/{len(todo)}] {result['type']:10s} / {result['head_word']:20s}  → {n} 对")

    by_key = {r["_key"]: r for r in done + new_res}
    return [by_key[group_key(g)] for g in groups]


# --------------------------------------------------------------------------- #
# HTML 生成
# --------------------------------------------------------------------------- #

def e(s) -> str:
    return html.escape(str(s))


def defs_html(defs: list[str]) -> str:
    if not defs:
        return '<li class="no-def">（无定义）</li>'
    return "".join(f"<li>{e(d)}</li>" for d in defs)


def build_html(results: list[dict], lookup: dict) -> str:
    total_groups  = len(results)
    total_suggest = sum(len(r.get("ai_pairs", [])) for r in results)
    groups_with   = sum(1 for r in results if r.get("ai_pairs"))

    cards_html = []
    for idx, r in enumerate(results, 1):
        key       = e(group_key(r))
        head      = e(r["head_word"])
        gtype     = e(r["type"])
        fc        = r.get("form_count", 0)
        up        = r.get("unresolved_pairs", 0)
        pairs     = r.get("ai_pairs", [])
        n_pairs   = len(pairs)
        all_names = r.get("member_names", [])

        # 成员名列表（带 tooltip 定义）
        names_html = ""
        for n in all_names:
            defs = get_defs(lookup, n)
            tip  = " | ".join(defs[:2]) if defs else ""
            names_html += f'<span class="name-tag" title="{e(tip)}">{e(n)}</span>'

        # AI 建议合并对 — 包含双方释义
        pair_rows = ""
        for pi, p in enumerate(pairs):
            ln    = p.get("left",   "")
            rn    = p.get("right",  "")
            reason = p.get("reason", "")
            pid   = f"{key}__{pi}"

            ldefs = get_defs(lookup, ln)
            rdefs = get_defs(lookup, rn)

            # 序列化定义供导出用
            ldefs_json = e(json.dumps(ldefs, ensure_ascii=False)).replace('"', '&quot;')
            rdefs_json = e(json.dumps(rdefs, ensure_ascii=False)).replace('"', '&quot;')

            pair_rows += f"""
<div class="pair-row" id="pair-{pid}"
  data-left="{e(ln)}" data-right="{e(rn)}"
  data-group="{key}"
  data-left-defs="{ldefs_json}"
  data-right-defs="{rdefs_json}">
  <div class="pair-header">
    <span class="pair-names">「{e(ln)}」 <span class="vs">↔</span> 「{e(rn)}」</span>
    <span class="pair-reason-inline">{e(reason)}</span>
  </div>
  <div class="entity-grid">
    <div class="entity-col">
      <div class="entity-name">{e(ln)}</div>
      <ul class="def-list">{defs_html(ldefs)}</ul>
    </div>
    <div class="entity-col">
      <div class="entity-name">{e(rn)}</div>
      <ul class="def-list">{defs_html(rdefs)}</ul>
    </div>
  </div>
  <div class="pair-btns">
    <button class="dec-btn dec-merge"    onclick="markPair('{pid}','merge')">✅ 合并</button>
    <button class="dec-btn dec-separate" onclick="markPair('{pid}','separate')">❌ 分离</button>
    <button class="dec-btn dec-skip"     onclick="markPair('{pid}','skip')">⏭ 跳过</button>
    <span class="pair-dec-result" id="pres-{pid}"></span>
  </div>
</div>"""

        badge_cls = "has-pairs" if n_pairs > 0 else "no-pairs"
        badge_txt = f"建议合并 {n_pairs} 对" if n_pairs > 0 else "无建议"

        cards_html.append(f"""
<div class="card" id="{key}" data-key="{key}" data-has-pairs="{1 if n_pairs else 0}">
  <div class="card-header" onclick="toggleCard(this)">
    <span class="idx">#{idx}</span>
    <span class="head-word">{head}</span>
    <span class="type-badge">{gtype}</span>
    <span class="stat-small">成员 {fc} · 未解决对 {up}</span>
    <span class="pair-badge {badge_cls}">{badge_txt}</span>
    <span class="toggle-icon">▼</span>
  </div>
  <div class="card-body collapsed">
    <div class="section-label">组内全部实体 <span style="font-weight:400;color:#aaa">（悬停查看定义）</span></div>
    <div class="names-wrap">{names_html}</div>
    {'<div class="section-label suggest-label">AI 建议合并的对</div>' + pair_rows if n_pairs else '<div class="no-suggest">AI 未发现应合并的对</div>'}
  </div>
</div>""")

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Recall Backlog 审查 — round_07</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:13px;background:#f0f2f5;color:#222}}
h1{{padding:16px 20px 4px;font-size:17px;font-weight:600}}
.subtitle{{padding:0 20px 12px;color:#666;font-size:12px}}
.stats-bar{{display:flex;gap:20px;padding:8px 20px;background:#fff;border-bottom:1px solid #eee;font-size:12px;flex-wrap:wrap}}
.stat-item strong{{font-size:15px}}
.controls{{display:flex;gap:10px;padding:10px 20px;background:#fff;border-bottom:1px solid #ddd;flex-wrap:wrap;align-items:center}}
#search{{flex:1;min-width:180px;padding:5px 10px;border:1px solid #ccc;border-radius:4px;font-size:13px}}
.filter-btn{{padding:4px 12px;border:1px solid #ccc;border-radius:12px;background:#f5f5f5;cursor:pointer;font-size:12px}}
.filter-btn.active{{background:#1677ff;color:#fff;border-color:#1677ff}}
.export-btn{{margin-left:auto;padding:5px 14px;background:#52c41a;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px}}
.export-btn:hover{{background:#389e0d}}
.list{{padding:12px 20px;display:flex;flex-direction:column;gap:8px}}
.card{{background:#fff;border-radius:8px;border:1px solid #e8e8e8;overflow:hidden}}
.card:hover{{box-shadow:0 2px 10px rgba(0,0,0,.07)}}
.card-header{{display:flex;align-items:center;gap:8px;padding:10px 14px;cursor:pointer;flex-wrap:wrap;user-select:none}}
.card-header:hover{{background:#fafafa}}
.idx{{color:#bbb;font-size:11px;min-width:26px}}
.head-word{{font-weight:600;font-size:14px;min-width:80px}}
.type-badge{{padding:2px 8px;border-radius:10px;font-size:11px;background:#e6f4ff;color:#0958d9;border:1px solid #bae0ff}}
.stat-small{{font-size:11px;color:#aaa}}
.pair-badge{{padding:2px 9px;border-radius:10px;font-size:11px;font-weight:500;margin-left:4px}}
.has-pairs{{background:#f6ffed;color:#389e0d;border:1px solid #b7eb8f}}
.no-pairs{{background:#f5f5f5;color:#bbb;border:1px solid #eee}}
.toggle-icon{{margin-left:auto;color:#aaa;font-size:11px;transition:transform .2s}}
.card-body{{padding:0 14px 4px}}
.card-body.collapsed{{display:none}}
.section-label{{font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.5px;margin:10px 0 6px}}
.suggest-label{{color:#389e0d}}
.names-wrap{{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px}}
.name-tag{{display:inline-block;background:#f5f5f5;border:1px solid #e8e8e8;border-radius:4px;padding:2px 8px;font-size:12px;color:#444;cursor:default}}
.name-tag:hover{{background:#e6f4ff;border-color:#bae0ff}}
/* 合并对卡片 */
.pair-row{{background:#f6ffed;border:1px solid #d9f7be;border-radius:6px;padding:10px 12px;margin-bottom:10px}}
.pair-header{{margin-bottom:8px}}
.pair-names{{font-weight:600;font-size:13px}}
.vs{{color:#bbb;font-size:11px;margin:0 4px}}
.pair-reason-inline{{display:block;font-size:12px;color:#555;margin-top:3px;font-style:italic}}
/* 双列定义 */
.entity-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}}
@media(max-width:560px){{.entity-grid{{grid-template-columns:1fr}}}}
.entity-col{{background:#fff;border:1px solid #e8e8e8;border-radius:5px;padding:8px 10px}}
.entity-name{{font-weight:500;color:#222;margin-bottom:5px;font-size:12px}}
.def-list{{padding-left:14px;font-size:12px;color:#444;line-height:1.7}}
.def-list .no-def{{color:#bbb;list-style:none;padding-left:0}}
/* 按钮 */
.pair-btns{{display:flex;align-items:center;gap:6px;flex-wrap:wrap}}
.dec-btn{{padding:3px 10px;border-radius:4px;border:1px solid #ddd;cursor:pointer;font-size:12px}}
.dec-merge{{background:#f6ffed;color:#389e0d;border-color:#b7eb8f}}
.dec-merge:hover,.dec-merge.active{{background:#52c41a;color:#fff;border-color:#52c41a}}
.dec-separate{{background:#fff1f0;color:#cf1322;border-color:#ffa39e}}
.dec-separate:hover,.dec-separate.active{{background:#ff4d4f;color:#fff;border-color:#ff4d4f}}
.dec-skip{{background:#f5f5f5;color:#666;border-color:#ddd}}
.dec-skip:hover,.dec-skip.active{{background:#bbb;color:#fff}}
.pair-dec-result{{font-size:12px;font-weight:500;margin-left:4px}}
.no-suggest{{color:#bbb;font-size:12px;padding:8px 0 12px}}
.hidden{{display:none!important}}
#export-area{{display:none;width:calc(100% - 40px);height:160px;margin:0 20px 20px;font-size:11px;border:1px solid #ccc;border-radius:4px;padding:6px}}
</style>
</head>
<body>
<h1>Recall Backlog 审查 — AI 辅助合并机会发现</h1>
<p class="subtitle">基线 <code>round_07_all15_merge_v7</code> · 共 <strong>{total_groups}</strong> 个头词组 · AI 在 <strong>{groups_with}</strong> 个组中发现 <strong>{total_suggest}</strong> 对合并建议</p>

<div class="stats-bar">
  <div class="stat-item">头词组总数 <strong>{total_groups}</strong></div>
  <div class="stat-item">有建议的组 <strong>{groups_with}</strong></div>
  <div class="stat-item">AI 建议合并对 <strong>{total_suggest}</strong></div>
</div>

<div class="controls">
  <input id="search" type="text" placeholder="搜索头词或实体名称..." />
  <button class="filter-btn active" data-filter="all">全部 ({total_groups})</button>
  <button class="filter-btn" data-filter="has">有建议 ({groups_with})</button>
  <button class="filter-btn" data-filter="none">无建议 ({total_groups - groups_with})</button>
  <button class="export-btn" onclick="exportDecisions()">导出判断 JSON</button>
</div>

<div class="list" id="card-list">
{''.join(cards_html)}
</div>
<textarea id="export-area" placeholder="点击「导出判断 JSON」后结果显示在这里并自动复制到剪贴板"></textarea>

<script>
const pairDecisions = {{}};

function toggleCard(header) {{
  const body = header.nextElementSibling;
  const icon = header.querySelector('.toggle-icon');
  const collapsed = body.classList.toggle('collapsed');
  icon.style.transform = collapsed ? '' : 'rotate(180deg)';
}}

function markPair(pid, val) {{
  pairDecisions[pid] = val;
  const el = document.getElementById('pres-' + pid);
  const labels = {{merge:'✅ 合并', separate:'❌ 分离', skip:'⏭ 跳过'}};
  el.textContent = labels[val] || val;
  el.style.color = val==='merge' ? '#52c41a' : val==='separate' ? '#ff4d4f' : '#aaa';
  const row = document.getElementById('pair-' + pid);
  row.querySelectorAll('.dec-btn').forEach(b => b.classList.remove('active'));
  row.querySelector('.dec-' + val)?.classList.add('active');
}}

function exportDecisions() {{
  const out = [];
  document.querySelectorAll('.pair-row').forEach(row => {{
    const pid  = row.id.replace('pair-', '');
    const d    = row.dataset;
    let ldefs = [], rdefs = [];
    try {{ ldefs = JSON.parse(d.leftDefs  || '[]'); }} catch(e) {{}}
    try {{ rdefs = JSON.parse(d.rightDefs || '[]'); }} catch(e) {{}}
    const final = pairDecisions[pid] || 'merge';
    out.push({{
      group_key:         d.group,
      left_name:         d.left,
      right_name:        d.right,
      decision:          final,
      left_definitions:  ldefs,
      right_definitions: rdefs,
    }});
  }});
  const textarea = document.getElementById('export-area');
  textarea.style.display = 'block';
  textarea.value = JSON.stringify(out, null, 2);
  textarea.select();
  document.execCommand('copy');
  alert(`已复制！共 ${{out.length}} 对`);
}}

let activeFilter = 'all', searchTerm = '';
function applyFilter() {{
  document.querySelectorAll('.card').forEach(card => {{
    const hasPairs = card.dataset.hasPairs === '1';
    const text = card.textContent.toLowerCase();
    const fOk = activeFilter==='all' || (activeFilter==='has' && hasPairs) || (activeFilter==='none' && !hasPairs);
    const sOk = !searchTerm || text.includes(searchTerm);
    card.classList.toggle('hidden', !(fOk && sOk));
  }});
}}
document.querySelectorAll('.filter-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeFilter = btn.dataset.filter;
    applyFilter();
  }});
}});
document.getElementById('search').addEventListener('input', ev => {{
  searchTerm = ev.target.value.toLowerCase();
  applyFilter();
}});
</script>
</body>
</html>"""


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #

async def main_async(args):
    print("=== Recall Backlog AI 审查工具 ===\n")
    groups = load_groups()
    lookup = load_entity_forms()
    cache  = load_cache()
    print(f"缓存中已有 {len(cache)} 组结果\n")

    if args.skip_api:
        print("--skip-api：跳过 API 调用，仅用缓存")
        results = []
        for g in groups:
            k = group_key(g)
            if k in cache:
                results.append(cache[k])
            else:
                r = dict(g); r["_key"] = k; r["ai_pairs"] = []; r["ai_raw"] = ""
                results.append(r)
    else:
        api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "") or DEEPSEEK_API_KEY
        if not api_key or api_key.startswith("sk-在这里"):
            print("[error] 请在文件顶部填入 DEEPSEEK_API_KEY")
            sys.exit(1)
        results = await run_ai_review(groups, lookup, api_key, args.workers, cache)

    print("\n生成 HTML...")
    OUTPUT_HTML.write_text(build_html(results, lookup), encoding="utf-8")
    print(f"输出: {OUTPUT_HTML}")

    total_suggest = sum(len(r.get("ai_pairs", [])) for r in results)
    groups_with   = sum(1 for r in results if r.get("ai_pairs"))
    print(f"AI 汇总: {groups_with} 个组有建议，共 {total_suggest} 对")
    print("完成。")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api-key",  default="", help="DeepSeek API Key")
    p.add_argument("--skip-api", action="store_true")
    p.add_argument("--workers",  type=int, default=8, help="并发请求数（默认 8）")
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
