"""Generate an HTML review page from round_07 clusters for manual duplicate inspection."""
import json
import html
from pathlib import Path
from collections import defaultdict

CLUSTERS_FILE = Path(__file__).parent / "results/entity_merge/round_07_all15_merge_v7_clusters.jsonl"
OUTPUT_FILE = Path(__file__).parent / "results/entity_merge/round_07_cluster_review.html"

def short_book(name):
    # Extract short book label from filename like "01_Data-Driven Science..."
    parts = name.split("_", 1)
    if len(parts) > 1:
        label = parts[1]
        # Cut at first "(" or 40 chars
        paren = label.find(" (")
        if paren > 0:
            label = label[:paren]
        return label[:60]
    return name[:60]

def main():
    clusters = []
    with open(CLUSTERS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                clusters.append(json.loads(line))

    # Group by type
    by_type = defaultdict(list)
    for c in clusters:
        by_type[c.get("type", "unknown")].append(c)

    # Sort each group alphabetically by canonical_name
    for t in by_type:
        by_type[t].sort(key=lambda x: x["canonical_name"].lower())

    types_sorted = sorted(by_type.keys())
    type_counts = {t: len(by_type[t]) for t in types_sorted}
    total = len(clusters)

    rows_html = []
    row_id = 0
    for t in types_sorted:
        for c in by_type[t]:
            canon = html.escape(c["canonical_name"])
            ctype = html.escape(c.get("type", ""))
            forms = c.get("member_forms", [])
            form_names = [html.escape(f["name"]) for f in forms]
            form_tags = "".join(
                f'<span class="form-tag">{n}</span>' for n in form_names
            )
            books = c.get("books", [])
            book_tags = "".join(
                f'<span class="book-tag" title="{html.escape(b)}">{html.escape(short_book(b))}</span>'
                for b in books
            )
            mention = c.get("mention_count", 0)
            fc = c.get("form_count", 1)
            bc = c.get("book_count", 0)
            # data-search stores lowercase text for filtering
            search_data = (c["canonical_name"] + " " + " ".join(f["name"] for f in forms)).lower()
            rows_html.append(
                f'<tr class="row" data-type="{ctype}" data-search="{html.escape(search_data)}">'
                f'<td class="col-canon">{canon}</td>'
                f'<td><span class="badge badge-{ctype}">{ctype}</span></td>'
                f'<td class="col-forms">{form_tags}</td>'
                f'<td class="col-books">{book_tags}</td>'
                f'<td class="col-num">{fc}</td>'
                f'<td class="col-num">{bc}</td>'
                f'<td class="col-num">{mention}</td>'
                f'</tr>'
            )
            row_id += 1

    tabs_html = '<button class="tab-btn active" data-type="__all__">All <span class="cnt">(' + str(total) + ')</span></button>'
    for t in types_sorted:
        tabs_html += f'<button class="tab-btn" data-type="{html.escape(t)}">{html.escape(t)} <span class="cnt">({type_counts[t]})</span></button>'

    html_content = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Round 07 Cluster Review — {total} clusters</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 13px; background: #f5f5f5; color: #222; }}
  h1 {{ padding: 14px 20px 4px; font-size: 17px; font-weight: 600; }}
  .subtitle {{ padding: 0 20px 10px; color: #666; font-size: 12px; }}
  .controls {{ display: flex; gap: 10px; padding: 8px 20px; background: #fff; border-bottom: 1px solid #ddd; align-items: center; flex-wrap: wrap; }}
  #search {{ flex: 1; min-width: 220px; padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }}
  .tab-strip {{ display: flex; gap: 4px; flex-wrap: wrap; padding: 8px 20px 0; background: #fff; border-bottom: 1px solid #ddd; }}
  .tab-btn {{ padding: 5px 10px; border: 1px solid #ccc; border-bottom: none; border-radius: 4px 4px 0 0; background: #f0f0f0; cursor: pointer; font-size: 12px; }}
  .tab-btn.active {{ background: #fff; border-color: #999; font-weight: 600; }}
  .tab-btn:hover {{ background: #e8e8e8; }}
  .stats-bar {{ padding: 6px 20px; background: #fffbe6; border-bottom: 1px solid #ffe58f; font-size: 12px; color: #7d6608; }}
  #visible-count {{ font-weight: 600; }}
  .table-wrap {{ overflow: auto; padding: 0 20px 20px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; background: #fff; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  thead tr {{ background: #f0f2f5; }}
  th {{ padding: 8px 10px; text-align: left; font-size: 12px; color: #555; border-bottom: 2px solid #ddd; white-space: nowrap; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #f0f0f0; vertical-align: top; }}
  tr:hover td {{ background: #fafafa; }}
  .col-canon {{ font-weight: 500; min-width: 160px; max-width: 260px; word-break: break-word; }}
  .col-forms {{ max-width: 380px; }}
  .col-books {{ max-width: 360px; }}
  .col-num {{ text-align: right; white-space: nowrap; color: #888; width: 40px; }}
  .form-tag {{ display: inline-block; background: #e6f4ff; color: #0958d9; border: 1px solid #bae0ff; border-radius: 3px; padding: 1px 5px; margin: 2px 2px 0 0; font-size: 11px; white-space: nowrap; }}
  .book-tag {{ display: inline-block; background: #f6ffed; color: #389e0d; border: 1px solid #b7eb8f; border-radius: 3px; padding: 1px 5px; margin: 2px 2px 0 0; font-size: 11px; cursor: default; }}
  .badge {{ display: inline-block; padding: 2px 7px; border-radius: 10px; font-size: 11px; font-weight: 500; }}
  .badge-algorithm {{ background: #fff0f6; color: #c41d7f; }}
  .badge-concept {{ background: #e6f4ff; color: #0958d9; }}
  .badge-process {{ background: #fff7e6; color: #d46b08; }}
  .badge-tool {{ background: #f9f0ff; color: #531dab; }}
  .badge-method {{ background: #f0fff0; color: #237804; }}
  .badge-task {{ background: #fafafa; color: #444; }}
  .badge-unknown {{ background: #eee; color: #666; }}
  .hidden {{ display: none !important; }}
  th.sortable {{ cursor: pointer; user-select: none; }}
  th.sortable:hover {{ color: #222; }}
  th.sortable::after {{ content: " ↕"; font-size: 10px; color: #aaa; }}
  th.asc::after {{ content: " ↑"; color: #555; }}
  th.desc::after {{ content: " ↓"; color: #555; }}
</style>
</head>
<body>
<h1>Task 11 — Round 07 Cluster Review</h1>
<p class="subtitle">基线 <code>round_07_all15_merge_v7</code> · 合并后共 <strong>{total}</strong> 个实体簇 · 请人工排查是否仍有重复</p>

<div class="tab-strip">{tabs_html}</div>

<div class="controls">
  <input id="search" type="text" placeholder="搜索实体名称 / 成员形式 (支持多词空格分隔)..." autocomplete="off" />
  <label style="font-size:12px;color:#666;">
    <input type="checkbox" id="multi-form-only"> 仅显示多形式簇 (form≥2)
  </label>
  <label style="font-size:12px;color:#666;">
    <input type="checkbox" id="multi-book-only"> 仅显示跨书簇 (book≥2)
  </label>
</div>

<div class="stats-bar">显示 <span id="visible-count">{total}</span> / {total} 个簇</div>

<div class="table-wrap">
<table id="main-table">
  <thead>
    <tr>
      <th class="sortable" data-col="0">标准名</th>
      <th class="sortable" data-col="1">类型</th>
      <th>成员形式</th>
      <th>来源书籍</th>
      <th class="sortable col-num" data-col="4" title="成员形式数">形式</th>
      <th class="sortable col-num" data-col="5" title="出现书籍数">书</th>
      <th class="sortable col-num" data-col="6" title="提及次数">提及</th>
    </tr>
  </thead>
  <tbody id="tbody">
    {''.join(rows_html)}
  </tbody>
</table>
</div>

<script>
const tbody = document.getElementById('tbody');
const searchInput = document.getElementById('search');
const multiFormCb = document.getElementById('multi-form-only');
const multiBookCb = document.getElementById('multi-book-only');
const visibleCount = document.getElementById('visible-count');
const tabBtns = document.querySelectorAll('.tab-btn');
let activeType = '__all__';

function applyFilters() {{
  const terms = searchInput.value.toLowerCase().split(/\\s+/).filter(Boolean);
  const onlyMultiForm = multiFormCb.checked;
  const onlyMultiBook = multiBookCb.checked;
  let count = 0;
  const rows = tbody.querySelectorAll('tr.row');
  rows.forEach(row => {{
    const t = row.dataset.type;
    const s = row.dataset.search;
    const formCount = parseInt(row.cells[4].textContent) || 0;
    const bookCount = parseInt(row.cells[5].textContent) || 0;
    const typeMatch = activeType === '__all__' || t === activeType;
    const termMatch = terms.every(term => s.includes(term));
    const formMatch = !onlyMultiForm || formCount >= 2;
    const bookMatch = !onlyMultiBook || bookCount >= 2;
    if (typeMatch && termMatch && formMatch && bookMatch) {{
      row.classList.remove('hidden');
      count++;
    }} else {{
      row.classList.add('hidden');
    }}
  }});
  visibleCount.textContent = count;
}}

searchInput.addEventListener('input', applyFilters);
multiFormCb.addEventListener('change', applyFilters);
multiBookCb.addEventListener('change', applyFilters);

tabBtns.forEach(btn => {{
  btn.addEventListener('click', () => {{
    tabBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeType = btn.dataset.type;
    applyFilters();
  }});
}});

// Simple column sort
let sortState = {{col: -1, dir: 1}};
document.querySelectorAll('th.sortable').forEach(th => {{
  th.addEventListener('click', () => {{
    const col = parseInt(th.dataset.col);
    if (sortState.col === col) sortState.dir *= -1;
    else {{ sortState.col = col; sortState.dir = 1; }}
    document.querySelectorAll('th.sortable').forEach(h => h.classList.remove('asc','desc'));
    th.classList.add(sortState.dir === 1 ? 'asc' : 'desc');
    const rows = Array.from(tbody.querySelectorAll('tr.row'));
    rows.sort((a, b) => {{
      let av = a.cells[col]?.textContent.trim() || '';
      let bv = b.cells[col]?.textContent.trim() || '';
      const an = parseFloat(av), bn = parseFloat(bv);
      if (!isNaN(an) && !isNaN(bn)) return (an - bn) * sortState.dir;
      return av.localeCompare(bv, 'zh') * sortState.dir;
    }});
    rows.forEach(r => tbody.appendChild(r));
  }});
}});
</script>
</body>
</html>"""

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(html_content, encoding="utf-8")
    print(f"Generated: {OUTPUT_FILE}")
    print(f"Total clusters: {total}")
    for t in types_sorted:
        print(f"  {t}: {type_counts[t]}")

if __name__ == "__main__":
    main()
