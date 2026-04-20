"""
抽样审查已合并的实体对 — 让 DeepSeek 验证合并是否正确，供人工复核。

运行方法：
    1. 安装依赖（只需一次）：
           pip install openai

    2. 直接运行（随机抽取 50 对已合并决策）：
           python test_prompt/review_merged_sample.py

    3. 运行完成后用浏览器打开：
           test_prompt/results/entity_merge/round_07_merged_sample_review.html

    4. 仅重新生成 HTML（不再调 API）：
           python test_prompt/review_merged_sample.py --skip-api

    5. 指定随机种子（复现同一批样本）：
           python test_prompt/review_merged_sample.py --seed 42
"""

import argparse
import asyncio
import html
import json
import os
import random
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
BASE           = Path(__file__).parent / "results/entity_merge"
DECISIONS_FILE = BASE / "round_07_all15_merge_v7_merge_decisions.jsonl"
CACHE_FILE     = BASE / "round_07_merged_sample_ai_cache.jsonl"

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL    = "deepseek-chat"
SAMPLE_SIZE       = 50

# --------------------------------------------------------------------------- #
# 数据加载
# --------------------------------------------------------------------------- #

def load_merged(seed: int) -> list[dict]:
    all_merged = []
    with open(DECISIONS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if obj.get("decision") == "merge":
                    all_merged.append(obj)
    print(f"全部已合并决策: {len(all_merged)} 条")
    rng = random.Random(seed)
    sample = rng.sample(all_merged, min(SAMPLE_SIZE, len(all_merged)))
    print(f"随机抽取: {len(sample)} 条（seed={seed}）")
    return sample


def load_cache() -> dict[str, dict]:
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
    with open(CACHE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# DeepSeek API
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """\
你是知识图谱实体消歧专家。
系统已将下面两个实体合并为同一个实体，请判断这个合并是否正确。

判断标准：
1. 两个实体是否真正表示同一个概念/算法/工具/过程？
2. 合并是否会造成语义损失或混淆？

请以 JSON 格式回复：
{
  "verdict": "correct" | "wrong" | "uncertain",
  "confidence": 0.0~1.0,
  "reason": "一句话说明"
}
只输出 JSON，不要有其他文字。
"""


def build_prompt(cand: dict) -> str:
    left_defs  = "\n".join(f"  - {d}" for d in cand.get("left_top_definitions",  []))
    right_defs = "\n".join(f"  - {d}" for d in cand.get("right_top_definitions", []))
    signals    = ", ".join(cand.get("signals", []))
    return f"""\
实体 A：「{cand['left_name']}」
  类型: {cand.get('left_type','?')}  |  角色: {cand.get('left_merge_role','?')}
  定义:
{left_defs or '  （无）'}

实体 B：「{cand['right_name']}」
  类型: {cand.get('right_type','?')}  |  角色: {cand.get('right_merge_role','?')}
  定义:
{right_defs or '  （无）'}

合并依据信号: {signals or '（无）'}
合并得分: {cand.get('score_raw','?')}
"""


async def call_deepseek(client, cand: dict, semaphore: asyncio.Semaphore) -> dict:
    async with semaphore:
        try:
            response = await client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": build_prompt(cand)},
                ],
                temperature=0.0,
                max_tokens=256,
            )
            raw = response.choices[0].message.content.strip()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                parsed = json.loads(m.group()) if m else {}
            result = dict(cand)
            result["ai_verdict"]     = parsed.get("verdict",    "error")
            result["ai_confidence"]  = parsed.get("confidence", 0.0)
            result["ai_reason"]      = parsed.get("reason",     raw)
        except Exception as exc:
            result = dict(cand)
            result["ai_verdict"]    = "error"
            result["ai_confidence"] = 0.0
            result["ai_reason"]     = f"API 调用失败: {exc}"
        return result


async def run_ai_review(
    sample: list[dict],
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

    todo = [c for c in sample if c["candidate_id"] not in cache]
    done = [cache[c["candidate_id"]] for c in sample if c["candidate_id"] in cache]
    print(f"缓存命中 {len(done)} 条，待请求 {len(todo)} 条（并发={workers}）\n")

    if not todo:
        by_id = {r["candidate_id"]: r for r in done}
        return [by_id[c["candidate_id"]] for c in sample]

    tasks   = [call_deepseek(client, c, semaphore) for c in todo]
    new_res = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        result = await coro
        new_res.append(result)
        save_to_cache(result)
        v    = result.get("ai_verdict", "?")
        conf = result.get("ai_confidence", 0)
        print(f"  [{i:2d}/{len(todo)}] {result['left_name']!r} ↔ {result['right_name']!r}  →  {v} ({conf:.2f})")

    by_id = {r["candidate_id"]: r for r in done + new_res}
    return [by_id[c["candidate_id"]] for c in sample]


# --------------------------------------------------------------------------- #
# HTML 生成
# --------------------------------------------------------------------------- #

VERDICT_STYLE = {
    "correct":   ("✅ 合并正确",  "v-correct"),
    "wrong":     ("❌ 合并错误",  "v-wrong"),
    "uncertain": ("❓ 不确定",    "v-uncertain"),
    "error":     ("⚠️ API 错误", "v-error"),
}


def e(s) -> str:
    return html.escape(str(s))


def defs_html(defs: list[str]) -> str:
    if not defs:
        return '<li class="no-def">（无定义）</li>'
    return "".join(f"<li>{e(d)}</li>" for d in defs)


def build_html(results: list[dict]) -> str:
    total    = len(results)
    n_correct   = sum(1 for r in results if r.get("ai_verdict") == "correct")
    n_wrong     = sum(1 for r in results if r.get("ai_verdict") == "wrong")
    n_uncertain = sum(1 for r in results if r.get("ai_verdict") == "uncertain")
    n_error     = sum(1 for r in results if r.get("ai_verdict") == "error")

    cards = []
    for idx, r in enumerate(results, 1):
        cid     = e(r.get("candidate_id", ""))
        verdict = r.get("ai_verdict", "error")
        conf    = r.get("ai_confidence", 0.0)
        reason  = r.get("ai_reason", "")
        badge_text, badge_cls = VERDICT_STYLE.get(verdict, ("?", "v-error"))

        ldefs = r.get("left_top_definitions",  [])
        rdefs = r.get("right_top_definitions", [])
        ldefs_json = e(json.dumps(ldefs, ensure_ascii=False)).replace('"', '&quot;')
        rdefs_json = e(json.dumps(rdefs, ensure_ascii=False)).replace('"', '&quot;')

        signals   = ", ".join(r.get("signals", [])) or "—"
        score     = r.get("score_raw", "?")
        sys_reason = r.get("reason", "?")

        conf_bar   = int(conf * 100)
        conf_color = "#52c41a" if verdict == "correct" else ("#ff4d4f" if verdict == "wrong" else "#faad14")

        cards.append(f"""
<div class="card" id="{cid}" data-verdict="{e(verdict)}"
  data-left="{e(r['left_name'])}" data-right="{e(r['right_name'])}"
  data-type="{e(r.get('left_type',''))}" data-signals="{e(signals)}"
  data-score="{e(score)}"
  data-left-defs="{ldefs_json}" data-right-defs="{rdefs_json}">
  <div class="card-header">
    <span class="idx">#{idx}</span>
    <span class="pair-title">{e(r['left_name'])} <span class="vs">↔</span> {e(r['right_name'])}</span>
    <span class="badge {badge_cls}">{badge_text}</span>
    <span class="conf-wrap" title="AI置信度 {conf:.0%}">
      <span class="conf-bar" style="width:{conf_bar}px;background:{conf_color}"></span>
      <span class="conf-num">{conf:.0%}</span>
    </span>
    <button class="toggle-btn" onclick="toggleCard(this)">展开 ▼</button>
  </div>
  <div class="card-body collapsed">
    <div class="ai-reason">
      <strong>AI 判断：</strong>{e(reason)}
    </div>
    <div class="entity-grid">
      <div class="entity-col">
        <div class="entity-name">A: {e(r['left_name'])}</div>
        <div class="entity-meta">类型: {e(r.get('left_type','?'))} · 角色: {e(r.get('left_merge_role','?'))}</div>
        <ul class="def-list">{defs_html(ldefs)}</ul>
      </div>
      <div class="entity-col">
        <div class="entity-name">B: {e(r['right_name'])}</div>
        <div class="entity-meta">类型: {e(r.get('right_type','?'))} · 角色: {e(r.get('right_merge_role','?'))}</div>
        <ul class="def-list">{defs_html(rdefs)}</ul>
      </div>
    </div>
    <div class="sys-row">
      <span class="sys-label">合并信号：</span>{e(signals)}
      <span class="sys-label" style="margin-left:16px">得分：</span>{e(score)}
      <span class="sys-label" style="margin-left:16px">系统理由：</span>{e(sys_reason)}
    </div>
    <div class="decision-row">
      <span class="decision-label">你的判断：</span>
      <button class="dec-btn dec-correct"   onclick="markDecision('{cid}','correct')">✅ 合并正确</button>
      <button class="dec-btn dec-wrong"     onclick="markDecision('{cid}','wrong')">❌ 合并错误</button>
      <button class="dec-btn dec-skip"      onclick="markDecision('{cid}','skip')">⏭ 跳过</button>
      <span class="decision-result" id="dec-{cid}"></span>
    </div>
  </div>
</div>""")

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>已合并实体对抽样审查 — round_07</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:13px;background:#f0f2f5;color:#222}}
h1{{padding:16px 20px 4px;font-size:17px;font-weight:600}}
.subtitle{{padding:0 20px 12px;color:#666;font-size:12px}}
.stats-bar{{display:flex;gap:16px;padding:8px 20px;background:#fff;border-bottom:1px solid #eee;font-size:12px;flex-wrap:wrap;align-items:center}}
.stat-dot{{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:3px}}
.controls{{display:flex;gap:10px;padding:10px 20px;background:#fff;border-bottom:1px solid #ddd;flex-wrap:wrap;align-items:center}}
#search{{flex:1;min-width:180px;padding:5px 10px;border:1px solid #ccc;border-radius:4px;font-size:13px}}
.filter-btn{{padding:4px 10px;border:1px solid #ccc;border-radius:12px;background:#f5f5f5;cursor:pointer;font-size:12px}}
.filter-btn.active{{background:#1677ff;color:#fff;border-color:#1677ff}}
.export-btn{{margin-left:auto;padding:5px 14px;background:#52c41a;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px}}
.export-btn:hover{{background:#389e0d}}
.list{{padding:12px 20px;display:flex;flex-direction:column;gap:10px}}
.card{{background:#fff;border-radius:8px;border:1px solid #e8e8e8;overflow:hidden}}
.card:hover{{box-shadow:0 2px 12px rgba(0,0,0,.08)}}
.card-header{{display:flex;align-items:center;gap:8px;padding:10px 14px;flex-wrap:wrap}}
.idx{{color:#aaa;font-size:11px;min-width:28px}}
.pair-title{{font-weight:500;flex:1;min-width:180px}}
.vs{{color:#bbb;font-size:11px;margin:0 3px}}
.badge{{padding:3px 9px;border-radius:10px;font-size:11px;font-weight:500;white-space:nowrap}}
.v-correct{{background:#f6ffed;color:#389e0d;border:1px solid #b7eb8f}}
.v-wrong{{background:#fff1f0;color:#cf1322;border:1px solid #ffa39e}}
.v-uncertain{{background:#fffbe6;color:#d46b08;border:1px solid #ffe58f}}
.v-error{{background:#f5f5f5;color:#999;border:1px solid #ddd}}
.conf-wrap{{display:flex;align-items:center;gap:4px}}
.conf-bar{{display:inline-block;height:6px;border-radius:3px;min-width:2px;max-width:100px}}
.conf-num{{font-size:11px;color:#888;min-width:28px}}
.toggle-btn{{margin-left:auto;padding:3px 8px;font-size:11px;border:1px solid #ddd;border-radius:4px;background:#fafafa;cursor:pointer}}
.card-body{{padding:0 14px;overflow:hidden}}
.card-body.collapsed{{display:none}}
.ai-reason{{background:#f6f8ff;border-left:3px solid #1677ff;padding:8px 12px;margin:10px 0;border-radius:0 4px 4px 0;font-size:12px;line-height:1.6}}
.entity-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:10px 0}}
@media(max-width:600px){{.entity-grid{{grid-template-columns:1fr}}}}
.entity-col{{background:#fafafa;border:1px solid #f0f0f0;border-radius:6px;padding:10px}}
.entity-name{{font-weight:600;margin-bottom:3px}}
.entity-meta{{font-size:11px;color:#888;margin-bottom:6px}}
.def-list{{padding-left:16px;font-size:12px;color:#444;line-height:1.7}}
.def-list .no-def{{color:#bbb;list-style:none;padding-left:0}}
.sys-row{{font-size:11px;color:#888;padding:6px 0;border-top:1px solid #f0f0f0}}
.sys-label{{font-weight:500;color:#666}}
.decision-row{{display:flex;align-items:center;gap:8px;padding:10px 0;border-top:1px solid #f0f0f0;flex-wrap:wrap}}
.decision-label{{font-size:12px;color:#666;font-weight:500}}
.dec-btn{{padding:4px 12px;border-radius:4px;border:1px solid #ddd;cursor:pointer;font-size:12px}}
.dec-correct{{background:#f6ffed;color:#389e0d;border-color:#b7eb8f}}
.dec-correct:hover,.dec-correct.active{{background:#52c41a;color:#fff}}
.dec-wrong{{background:#fff1f0;color:#cf1322;border-color:#ffa39e}}
.dec-wrong:hover,.dec-wrong.active{{background:#ff4d4f;color:#fff}}
.dec-skip{{background:#f5f5f5;color:#666}}
.dec-skip:hover,.dec-skip.active{{background:#bbb;color:#fff}}
.decision-result{{font-size:12px;font-weight:500}}
.hidden{{display:none!important}}
#export-area{{display:none;width:calc(100% - 40px);height:160px;margin:0 20px 20px;font-size:11px;border:1px solid #ccc;border-radius:4px;padding:6px}}
</style>
</head>
<body>
<h1>已合并实体对 — 抽样审查（{total} 条）</h1>
<p class="subtitle">基线 <code>round_07_all15_merge_v7</code> · 从 453 条合并决策中随机抽取 {total} 条 · AI 模型: {DEEPSEEK_MODEL}</p>

<div class="stats-bar">
  <span><span class="stat-dot" style="background:#52c41a"></span>AI 认为正确: <strong>{n_correct}</strong></span>
  <span><span class="stat-dot" style="background:#ff4d4f"></span>AI 认为错误: <strong>{n_wrong}</strong></span>
  <span><span class="stat-dot" style="background:#faad14"></span>不确定: <strong>{n_uncertain}</strong></span>
  <span><span class="stat-dot" style="background:#ccc"></span>错误: <strong>{n_error}</strong></span>
  <span style="margin-left:auto;color:#aaa">人工已判断: <span id="judged-count">0</span> / {total}</span>
</div>

<div class="controls">
  <input id="search" type="text" placeholder="搜索实体名称..." />
  <button class="filter-btn active" data-filter="all">全部 ({total})</button>
  <button class="filter-btn" data-filter="correct">AI 正确 ({n_correct})</button>
  <button class="filter-btn" data-filter="wrong">AI 错误 ({n_wrong})</button>
  <button class="filter-btn" data-filter="uncertain">不确定 ({n_uncertain})</button>
  <button class="export-btn" onclick="exportDecisions()">导出判断 JSON</button>
</div>

<div class="list">
{''.join(cards)}
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
  if (!prev) {{ judgedCount++; document.getElementById('judged-count').textContent = judgedCount; }}
  const el = document.getElementById('dec-' + cid);
  const labels = {{correct:'✅ 标记正确', wrong:'❌ 标记错误', skip:'⏭ 跳过'}};
  el.textContent = labels[val] || val;
  el.style.color = val==='correct' ? '#52c41a' : val==='wrong' ? '#ff4d4f' : '#aaa';
  const card = document.getElementById(cid);
  card.querySelectorAll('.dec-btn').forEach(b => b.classList.remove('active'));
  card.querySelector('.dec-' + val)?.classList.add('active');
}}

function exportDecisions() {{
  const out = [];
  document.querySelectorAll('.card').forEach(card => {{
    const d = card.dataset;
    const cid = card.id;
    const aiVerdict = d.verdict;
    const final = decisions[cid] || aiVerdict;
    let ldefs = [], rdefs = [];
    try {{ ldefs = JSON.parse(d.leftDefs  || '[]'); }} catch(e) {{}}
    try {{ rdefs = JSON.parse(d.rightDefs || '[]'); }} catch(e) {{}}
    out.push({{
      candidate_id:      cid,
      verdict:           final,
      left_name:         d.left,
      right_name:        d.right,
      entity_type:       d.type,
      signals:           d.signals,
      system_score:      parseFloat(d.score) || null,
      left_definitions:  ldefs,
      right_definitions: rdefs,
    }});
  }});
  const wrong = out.filter(o => o.verdict === 'wrong').length;
  const textarea = document.getElementById('export-area');
  textarea.style.display = 'block';
  textarea.value = JSON.stringify(out, null, 2);
  textarea.select();
  document.execCommand('copy');
  alert(`已复制！共 ${{out.length}} 条，其中判断为错误合并: ${{wrong}} 条`);
}}

let activeFilter = 'all', searchTerm = '';
function applyFilter() {{
  document.querySelectorAll('.card').forEach(card => {{
    const v = card.dataset.verdict;
    const t = card.querySelector('.pair-title').textContent.toLowerCase();
    const fOk = activeFilter === 'all' || v === activeFilter;
    const sOk = !searchTerm || t.includes(searchTerm);
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
    print("=== 已合并实体对抽样审查工具 ===\n")
    seed = args.seed if args.seed is not None else random.randint(0, 99999)
    args.seed = seed
    sample = load_merged(seed)
    output_html = BASE / f"round_07_merged_sample_seed{seed}_review.html"
    cache  = load_cache()
    print(f"缓存中已有 {len(cache)} 条 AI 结果\n")

    if args.skip_api:
        print("--skip-api：跳过 API，仅用缓存")
        results = []
        for c in sample:
            if c["candidate_id"] in cache:
                results.append(cache[c["candidate_id"]])
            else:
                r = dict(c); r["ai_verdict"] = "error"; r["ai_confidence"] = 0.0
                r["ai_reason"] = "（未调用 API）"; results.append(r)
    else:
        api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "") or DEEPSEEK_API_KEY
        if not api_key or api_key.startswith("sk-在这里"):
            print("[error] 请在文件顶部填入 DEEPSEEK_API_KEY")
            sys.exit(1)
        results = await run_ai_review(sample, api_key, args.workers, cache)

    print("\n生成 HTML...")
    output_html.write_text(build_html(results), encoding="utf-8")
    print(f"输出: {output_html}")

    n_wrong = sum(1 for r in results if r.get("ai_verdict") == "wrong")
    print(f"AI 认为错误的合并: {n_wrong} / {len(results)}")
    print("完成。")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api-key",  default="")
    p.add_argument("--skip-api", action="store_true")
    p.add_argument("--workers",  type=int, default=5)
    p.add_argument("--seed",     type=int, default=None, help="随机种子（默认每次随机）")
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
