"""
审查未合并实体对 — 调用 DeepSeek API 给出合并建议，输出 HTML 供人工最终判定。

运行方法：
    1. 安装依赖（只需一次）：
           pip install openai

    2. 直接运行（API Key 已填在下方 DEEPSEEK_API_KEY 变量中）：
           python test_prompt/review_unmerged_with_ai.py

    3. 运行完成后，用浏览器打开生成的 HTML：
           test_prompt/results/entity_merge/round_07_unmerged_review.html

    4. 如果已经调用过 API、只想重新生成 HTML 不再花钱请求：
           python test_prompt/review_unmerged_with_ai.py --skip-api
"""

import argparse
import asyncio
import html
import json
import os
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# ★ 在这里填入你的 DeepSeek API Key
# --------------------------------------------------------------------------- #
DEEPSEEK_API_KEY = "sk-9362e9de868b466faaae0d1bf2a0a842"

# --------------------------------------------------------------------------- #
# 路径配置
# --------------------------------------------------------------------------- #
BASE = Path(__file__).parent / "results/entity_merge"
CACHE_FILE = BASE / "round_07_ai_review_cache.jsonl"
OUTPUT_HTML = BASE / "round_07_unmerged_review.html"

# 要审查的文件 -> (来源标签, 说明)
REVIEW_SOURCES = {
    "round_07_all15_merge_v7_review_samples.jsonl": (
        "uncertain",
        "得分处于边界、系统无法确定的候选对",
    ),
    "round_07_all15_merge_v7_board_recall_review.jsonl": (
        "recall_review",
        "召回扩展发现的弱信号候选对",
    ),
    "round_07_all15_merge_v7_board_blocked_by_role.jsonl": (
        "blocked_by_role",
        "因 merge_role 不一致被强制拒绝，但名称几乎相同",
    ),
}

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# --------------------------------------------------------------------------- #
# 数据加载
# --------------------------------------------------------------------------- #

def load_candidates() -> list[dict]:
    """加载所有待审查候选对，附加来源标签。"""
    candidates = []
    for filename, (source_tag, source_desc) in REVIEW_SOURCES.items():
        path = BASE / filename
        if not path.exists():
            print(f"[warn] 文件不存在，跳过: {path.name}")
            continue
        count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    obj["_source"] = source_tag
                    obj["_source_desc"] = source_desc
                    candidates.append(obj)
                    count += 1
        print(f"  加载 {count:3d} 对  ← {filename}")
    return candidates


def load_cache() -> dict[str, dict]:
    """从缓存文件加载已有 AI 结果，key = candidate_id。"""
    cache: dict[str, dict] = {}
    if CACHE_FILE.exists():
        with open(CACHE_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    cache[obj["candidate_id"]] = obj
    return cache


def save_to_cache(result: dict) -> None:
    """追加写入缓存。"""
    with open(CACHE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# DeepSeek API 调用
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """\
你是一个专业的知识图谱实体消歧专家。
我会给你两个从技术书籍中提取的实体，请判断它们是否应该合并为同一个实体。

判断标准：
1. 它们是否表示同一个概念/算法/工具/过程？
2. 语义上是否完全等价，而不仅仅是相关？
3. 若合并，会不会丢失重要的语义区分？

请以 JSON 格式回复，结构如下：
{
  "recommendation": "merge" | "keep_separate" | "uncertain",
  "confidence": 0.0~1.0,
  "reason": "一句话解释你的判断"
}
只输出 JSON，不要有其他文字。
"""

def build_user_prompt(cand: dict) -> str:
    left_defs = "\n".join(f"  - {d}" for d in cand.get("left_top_definitions", []))
    right_defs = "\n".join(f"  - {d}" for d in cand.get("right_top_definitions", []))
    signals = ", ".join(cand.get("signals", []))
    return f"""\
实体 A：「{cand['left_name']}」
  类型: {cand.get('left_type', '?')}  |  角色: {cand.get('left_merge_role', '?')}
  定义:
{left_defs or '  （无）'}

实体 B：「{cand['right_name']}」
  类型: {cand.get('right_type', '?')}  |  角色: {cand.get('right_merge_role', '?')}
  定义:
{right_defs or '  （无）'}

系统检测到的相似信号: {signals or '（无）'}
系统原始得分: {cand.get('score_raw', '?')}
系统原始判断: {cand.get('decision', '?')}（原因: {cand.get('reason', '?')}）
"""


async def call_deepseek(client, cand: dict, semaphore: asyncio.Semaphore) -> dict:
    """调用 DeepSeek API，返回附有 ai_* 字段的候选对字典。"""
    async with semaphore:
        try:
            response = await client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(cand)},
                ],
                temperature=0.0,
                max_tokens=256,
            )
            raw = response.choices[0].message.content.strip()
            # 尝试解析 JSON
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                # 提取第一个 {...}
                import re
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                parsed = json.loads(m.group()) if m else {}
            result = dict(cand)
            result["ai_recommendation"] = parsed.get("recommendation", "error")
            result["ai_confidence"] = parsed.get("confidence", 0.0)
            result["ai_reason"] = parsed.get("reason", raw)
            result["ai_raw"] = raw
        except Exception as e:
            result = dict(cand)
            result["ai_recommendation"] = "error"
            result["ai_confidence"] = 0.0
            result["ai_reason"] = f"API 调用失败: {e}"
            result["ai_raw"] = str(e)
        return result


async def run_ai_review(
    candidates: list[dict],
    api_key: str,
    workers: int,
    cache: dict[str, dict],
) -> list[dict]:
    """并发调用 DeepSeek，跳过已缓存的结果。"""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        print("[error] 请先安装 openai 库: pip install openai")
        sys.exit(1)

    client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
    semaphore = asyncio.Semaphore(workers)

    todo = [c for c in candidates if c["candidate_id"] not in cache]
    done = [cache[c["candidate_id"]] for c in candidates if c["candidate_id"] in cache]

    print(f"\n缓存命中 {len(done)} 对，待请求 {len(todo)} 对（并发={workers}）")

    if not todo:
        return [cache[c["candidate_id"]] for c in candidates]

    tasks = [call_deepseek(client, cand, semaphore) for cand in todo]
    results_new = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        result = await coro
        results_new.append(result)
        save_to_cache(result)
        rec = result.get("ai_recommendation", "?")
        conf = result.get("ai_confidence", 0)
        print(f"  [{i:3d}/{len(todo)}] {result['left_name']!r} ↔ {result['right_name']!r}  →  {rec} ({conf:.2f})")

    # 按原始顺序返回
    all_by_id = {r["candidate_id"]: r for r in done + results_new}
    return [all_by_id[c["candidate_id"]] for c in candidates]


# --------------------------------------------------------------------------- #
# HTML 生成
# --------------------------------------------------------------------------- #

REC_STYLE = {
    "merge":         ("✅ 建议合并",     "badge-merge"),
    "keep_separate": ("❌ 建议保留分离", "badge-separate"),
    "uncertain":     ("❓ 不确定",       "badge-uncertain"),
    "error":         ("⚠️ API 错误",     "badge-error"),
}

SOURCE_LABEL = {
    "uncertain":     ("灰", "边界uncertain"),
    "recall_review": ("蓝", "召回扩展"),
    "blocked_by_role": ("橙", "角色拒绝"),
}


def e(s) -> str:
    return html.escape(str(s))


def build_html(results: list[dict]) -> str:
    rows = []
    for idx, r in enumerate(results, 1):
        rec = r.get("ai_recommendation", "error")
        conf = r.get("ai_confidence", 0.0)
        reason = r.get("ai_reason", "")
        badge_text, badge_cls = REC_STYLE.get(rec, ("?", "badge-error"))
        source = r.get("_source", "?")
        source_desc = r.get("_source_desc", "")

        left_defs = "".join(
            f"<li>{e(d)}</li>" for d in r.get("left_top_definitions", [])
        ) or "<li>（无）</li>"
        right_defs = "".join(
            f"<li>{e(d)}</li>" for d in r.get("right_top_definitions", [])
        ) or "<li>（无）</li>"
        signals = ", ".join(r.get("signals", [])) or "—"
        sys_score = r.get("score_raw", "?")
        sys_decision = r.get("decision", "?")
        sys_reason = r.get("reason", "?")
        cid = e(r.get("candidate_id", ""))

        conf_bar = int(conf * 100)
        conf_color = "#52c41a" if rec == "merge" else ("#ff4d4f" if rec == "keep_separate" else "#faad14")

        import json as _json
        left_defs_json = e(_json.dumps(r.get("left_top_definitions", []), ensure_ascii=False)).replace('"', '&quot;')
        right_defs_json = e(_json.dumps(r.get("right_top_definitions", []), ensure_ascii=False)).replace('"', '&quot;')
        rows.append(f"""
<div class="card" data-rec="{e(rec)}" data-source="{e(source)}" id="{cid}"
  data-left="{e(r['left_name'])}" data-right="{e(r['right_name'])}"
  data-type="{e(r.get('left_type',''))}" data-signals="{e(signals)}"
  data-score="{e(sys_score)}"
  data-left-defs="{left_defs_json}"
  data-right-defs="{right_defs_json}">
  <div class="card-header">
    <span class="idx">#{idx}</span>
    <span class="pair-title">{e(r['left_name'])} <span class="vs">↔</span> {e(r['right_name'])}</span>
    <span class="badge {badge_cls}">{badge_text}</span>
    <span class="conf-wrap" title="AI置信度 {conf:.0%}">
      <span class="conf-bar" style="width:{conf_bar}px;background:{conf_color}"></span>
      <span class="conf-num">{conf:.0%}</span>
    </span>
    <span class="src-badge src-{e(source)}" title="{e(source_desc)}">{e(source)}</span>
    <button class="toggle-btn" onclick="toggleCard(this)">展开 ▼</button>
  </div>

  <div class="card-body collapsed">
    <div class="ai-reason">
      <strong>AI 判断理由：</strong>{e(reason)}
    </div>

    <div class="entity-grid">
      <div class="entity-col">
        <div class="entity-name">A: {e(r['left_name'])}</div>
        <div class="entity-meta">类型: {e(r.get('left_type','?'))} · 角色: {e(r.get('left_merge_role','?'))} · 书: {r.get('left_book_count',0)} · 提及: {r.get('left_mention_count',0)}</div>
        <ul class="def-list">{left_defs}</ul>
      </div>
      <div class="entity-col">
        <div class="entity-name">B: {e(r['right_name'])}</div>
        <div class="entity-meta">类型: {e(r.get('right_type','?'))} · 角色: {e(r.get('right_merge_role','?'))} · 书: {r.get('right_book_count',0)} · 提及: {r.get('right_mention_count',0)}</div>
        <ul class="def-list">{right_defs}</ul>
      </div>
    </div>

    <div class="sys-row">
      <span class="sys-label">系统信号：</span>{e(signals)}
      <span class="sys-label" style="margin-left:16px">原始得分：</span>{e(sys_score)}
      <span class="sys-label" style="margin-left:16px">系统判断：</span>{e(sys_decision)}（{e(sys_reason)}）
    </div>

    <div class="decision-row">
      <span class="decision-label">你的判断：</span>
      <button class="dec-btn dec-merge"   onclick="markDecision('{cid}','merge')">✅ 合并</button>
      <button class="dec-btn dec-separate" onclick="markDecision('{cid}','separate')">❌ 保留分离</button>
      <button class="dec-btn dec-skip"    onclick="markDecision('{cid}','skip')">⏭ 跳过</button>
      <span class="decision-result" id="dec-{cid}"></span>
    </div>
  </div>
</div>""")

    total = len(results)
    merge_count = sum(1 for r in results if r.get("ai_recommendation") == "merge")
    sep_count = sum(1 for r in results if r.get("ai_recommendation") == "keep_separate")
    unc_count = sum(1 for r in results if r.get("ai_recommendation") == "uncertain")
    err_count = sum(1 for r in results if r.get("ai_recommendation") == "error")

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>未合并实体对 AI 审查 — round_07</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:13px;background:#f0f2f5;color:#222}}
h1{{padding:16px 20px 4px;font-size:17px;font-weight:600}}
.subtitle{{padding:0 20px 12px;color:#666;font-size:12px}}
.stats-bar{{display:flex;gap:16px;padding:8px 20px;background:#fff;border-bottom:1px solid #eee;font-size:12px;flex-wrap:wrap;align-items:center}}
.stat-item{{display:flex;align-items:center;gap:4px}}
.stat-dot{{width:10px;height:10px;border-radius:50%;display:inline-block}}
.controls{{display:flex;gap:10px;padding:10px 20px;background:#fff;border-bottom:1px solid #ddd;flex-wrap:wrap;align-items:center}}
#search{{flex:1;min-width:180px;padding:5px 10px;border:1px solid #ccc;border-radius:4px;font-size:13px}}
.filter-group{{display:flex;gap:6px;flex-wrap:wrap}}
.filter-btn{{padding:4px 10px;border:1px solid #ccc;border-radius:12px;background:#f5f5f5;cursor:pointer;font-size:12px}}
.filter-btn.active{{background:#1677ff;color:#fff;border-color:#1677ff}}
.export-btn{{margin-left:auto;padding:5px 14px;background:#52c41a;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px}}
.export-btn:hover{{background:#389e0d}}
.list{{padding:12px 20px;display:flex;flex-direction:column;gap:10px}}
.card{{background:#fff;border-radius:8px;border:1px solid #e8e8e8;overflow:hidden;transition:box-shadow .15s}}
.card:hover{{box-shadow:0 2px 12px rgba(0,0,0,.08)}}
.card-header{{display:flex;align-items:center;gap:8px;padding:10px 14px;cursor:pointer;flex-wrap:wrap}}
.idx{{color:#aaa;font-size:11px;min-width:28px}}
.pair-title{{font-weight:500;flex:1;min-width:200px}}
.vs{{color:#bbb;font-size:11px}}
.badge{{padding:3px 9px;border-radius:10px;font-size:11px;font-weight:500;white-space:nowrap}}
.badge-merge{{background:#f6ffed;color:#389e0d;border:1px solid #b7eb8f}}
.badge-separate{{background:#fff1f0;color:#cf1322;border:1px solid #ffa39e}}
.badge-uncertain{{background:#fffbe6;color:#d46b08;border:1px solid #ffe58f}}
.badge-error{{background:#f5f5f5;color:#999;border:1px solid #ddd}}
.conf-wrap{{display:flex;align-items:center;gap:4px}}
.conf-bar{{display:inline-block;height:6px;border-radius:3px;min-width:2px;max-width:100px}}
.conf-num{{font-size:11px;color:#888;min-width:28px}}
.src-badge{{font-size:10px;padding:2px 7px;border-radius:8px;white-space:nowrap}}
.src-uncertain{{background:#f5f5f5;color:#666;border:1px solid #ddd}}
.src-recall_review{{background:#e6f4ff;color:#0958d9;border:1px solid #bae0ff}}
.src-blocked_by_role{{background:#fff7e6;color:#d46b08;border:1px solid #ffe58f}}
.toggle-btn{{margin-left:auto;padding:3px 8px;font-size:11px;border:1px solid #ddd;border-radius:4px;background:#fafafa;cursor:pointer;white-space:nowrap}}
.card-body{{padding:0 14px;overflow:hidden}}
.card-body.collapsed{{display:none}}
.ai-reason{{background:#f6f8ff;border-left:3px solid #1677ff;padding:8px 12px;margin:10px 0;border-radius:0 4px 4px 0;font-size:12px;line-height:1.6}}
.entity-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:10px 0}}
@media(max-width:600px){{.entity-grid{{grid-template-columns:1fr}}}}
.entity-col{{background:#fafafa;border:1px solid #f0f0f0;border-radius:6px;padding:10px}}
.entity-name{{font-weight:600;margin-bottom:4px;color:#222}}
.entity-meta{{font-size:11px;color:#888;margin-bottom:6px}}
.def-list{{padding-left:16px;font-size:12px;color:#444;line-height:1.7}}
.sys-row{{font-size:11px;color:#888;padding:6px 0;border-top:1px solid #f0f0f0;margin-top:4px}}
.sys-label{{font-weight:500;color:#666}}
.decision-row{{display:flex;align-items:center;gap:8px;padding:10px 0;border-top:1px solid #f0f0f0;margin-top:4px;flex-wrap:wrap}}
.decision-label{{font-size:12px;color:#666;font-weight:500}}
.dec-btn{{padding:4px 12px;border-radius:4px;border:1px solid #ddd;cursor:pointer;font-size:12px}}
.dec-merge{{background:#f6ffed;color:#389e0d;border-color:#b7eb8f}}
.dec-merge:hover,.dec-merge.active{{background:#52c41a;color:#fff}}
.dec-separate{{background:#fff1f0;color:#cf1322;border-color:#ffa39e}}
.dec-separate:hover,.dec-separate.active{{background:#ff4d4f;color:#fff}}
.dec-skip{{background:#f5f5f5;color:#666}}
.dec-skip:hover,.dec-skip.active{{background:#bbb;color:#fff}}
.decision-result{{font-size:12px;font-weight:500;margin-left:4px}}
.hidden{{display:none!important}}
#export-area{{display:none}}
</style>
</head>
<body>
<h1>未合并实体对 — AI 辅助审查</h1>
<p class="subtitle">基线 <code>round_07_all15_merge_v7</code> · 共 <strong>{total}</strong> 对 · AI 模型: {DEEPSEEK_MODEL}</p>

<div class="stats-bar">
  <div class="stat-item"><span class="stat-dot" style="background:#52c41a"></span> AI 建议合并: <strong>{merge_count}</strong></div>
  <div class="stat-item"><span class="stat-dot" style="background:#ff4d4f"></span> 建议保留分离: <strong>{sep_count}</strong></div>
  <div class="stat-item"><span class="stat-dot" style="background:#faad14"></span> 不确定: <strong>{unc_count}</strong></div>
  <div class="stat-item"><span class="stat-dot" style="background:#ccc"></span> 错误: <strong>{err_count}</strong></div>
  <div style="margin-left:auto;font-size:12px;color:#aaa">人工已判断: <span id="judged-count">0</span> / {total}</div>
</div>

<div class="controls">
  <input id="search" type="text" placeholder="搜索实体名称..." />
  <div class="filter-group">
    <button class="filter-btn active" data-filter="all">全部 ({total})</button>
    <button class="filter-btn" data-filter="merge">AI建议合并 ({merge_count})</button>
    <button class="filter-btn" data-filter="keep_separate">建议分离 ({sep_count})</button>
    <button class="filter-btn" data-filter="uncertain">不确定 ({unc_count})</button>
    <button class="filter-btn" data-filter="uncertain_src" data-src="uncertain">来源:边界</button>
    <button class="filter-btn" data-filter="recall_review" data-src="recall_review">来源:召回</button>
    <button class="filter-btn" data-filter="blocked_by_role" data-src="blocked_by_role">来源:角色拒绝</button>
  </div>
  <button class="export-btn" onclick="exportDecisions()">导出最终判断 JSON（未改动默认用AI答案）</button>
</div>

<div class="list" id="card-list">
{''.join(rows)}
</div>

<textarea id="export-area"></textarea>

<script>
const decisions = {{}};
let judgedCount = 0;

function toggleCard(btn) {{
  const body = btn.closest('.card').querySelector('.card-body');
  const collapsed = body.classList.toggle('collapsed');
  btn.textContent = collapsed ? '展开 ▼' : '收起 ▲';
}}

function markDecision(cid, val) {{
  const prev = decisions[cid];
  decisions[cid] = val;
  if (!prev) judgedCount++;
  document.getElementById('judged-count').textContent = judgedCount;
  const result = document.getElementById('dec-' + cid);
  const labels = {{merge:'✅ 标记为合并', separate:'❌ 标记为分离', skip:'⏭ 已跳过'}};
  result.textContent = labels[val] || val;
  result.style.color = val === 'merge' ? '#52c41a' : val === 'separate' ? '#ff4d4f' : '#aaa';
  // 更新按钮激活状态
  const card = document.getElementById(cid);
  card.querySelectorAll('.dec-btn').forEach(b => b.classList.remove('active'));
  card.querySelector('.dec-' + val)?.classList.add('active');
}}

function exportDecisions() {{
  const out = [];
  document.querySelectorAll('.card').forEach(card => {{
    const d = card.dataset;
    const cid = card.id;
    const final = decisions[cid] || d.rec || 'uncertain';
    let leftDefs = [], rightDefs = [];
    try {{ leftDefs  = JSON.parse(d.leftDefs  || '[]'); }} catch(e) {{}}
    try {{ rightDefs = JSON.parse(d.rightDefs || '[]'); }} catch(e) {{}}
    out.push({{
      candidate_id: cid,
      decision: final,
      left_name: d.left,
      right_name: d.right,
      entity_type: d.type,
      signals: d.signals,
      system_score: parseFloat(d.score) || null,
      left_definitions: leftDefs,
      right_definitions: rightDefs,
    }});
  }});
  const textarea = document.getElementById('export-area');
  textarea.style.display = 'block';
  textarea.value = JSON.stringify(out, null, 2);
  textarea.select();
  document.execCommand('copy');
  alert(`已复制到剪贴板！共 ${{out.length}} 条`);
}}

// 过滤逻辑
let activeRec = 'all';
let activeSrc = null;
let searchTerm = '';

function applyFilter() {{
  const cards = document.querySelectorAll('.card');
  cards.forEach(card => {{
    const rec = card.dataset.rec;
    const src = card.dataset.source;
    const text = card.querySelector('.pair-title').textContent.toLowerCase();
    const recMatch = activeRec === 'all' || rec === activeRec;
    const srcMatch = !activeSrc || src === activeSrc;
    const searchMatch = !searchTerm || text.includes(searchTerm);
    card.classList.toggle('hidden', !(recMatch && srcMatch && searchMatch));
  }});
}}

document.querySelectorAll('.filter-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const f = btn.dataset.filter;
    if (btn.dataset.src) {{
      activeSrc = btn.dataset.src;
      activeRec = 'all';
    }} else {{
      activeSrc = null;
      activeRec = f === 'all' ? 'all' : f;
    }}
    applyFilter();
  }});
}});

document.getElementById('search').addEventListener('input', e => {{
  searchTerm = e.target.value.toLowerCase();
  applyFilter();
}});
</script>
</body>
</html>"""


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #

async def main_async(args):
    print("=== 未合并实体对 AI 审查工具 ===\n")
    print("加载候选对...")
    candidates = load_candidates()
    print(f"共 {len(candidates)} 对待审查\n")

    cache = load_cache()
    print(f"缓存中已有 {len(cache)} 条 AI 结果")

    if args.skip_api:
        print("--skip-api：跳过 API 调用，仅使用缓存")
        # 对没有缓存的条目填充占位
        results = []
        for c in candidates:
            if c["candidate_id"] in cache:
                results.append(cache[c["candidate_id"]])
            else:
                r = dict(c)
                r["ai_recommendation"] = "error"
                r["ai_confidence"] = 0.0
                r["ai_reason"] = "（未调用 API）"
                results.append(r)
    else:
        api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "") or DEEPSEEK_API_KEY
        if not api_key or api_key.startswith("sk-在这里"):
            print("[error] 请先在文件顶部 DEEPSEEK_API_KEY 变量中填入你的 DeepSeek API Key")
            sys.exit(1)
        results = await run_ai_review(candidates, api_key, args.workers, cache)

    print(f"\n生成 HTML...")
    html_content = build_html(results)
    OUTPUT_HTML.write_text(html_content, encoding="utf-8")
    print(f"输出: {OUTPUT_HTML}")

    merge = sum(1 for r in results if r.get("ai_recommendation") == "merge")
    sep   = sum(1 for r in results if r.get("ai_recommendation") == "keep_separate")
    unc   = sum(1 for r in results if r.get("ai_recommendation") == "uncertain")
    print(f"\nAI 汇总: 建议合并 {merge} · 保留分离 {sep} · 不确定 {unc}")
    print("完成。")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-key", default="", help="DeepSeek API Key")
    parser.add_argument("--skip-api", action="store_true", help="跳过 API 调用，仅生成 HTML")
    parser.add_argument("--workers", type=int, default=5, help="并发请求数（默认 5）")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
