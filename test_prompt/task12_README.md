# 任务 12：实体合并质量评测（AI + 人工审查）

## 任务背景

基于任务 11 产出的基线 `round_07_all15_merge_v7`（合并后 9354 个实体簇，节点压缩 407），本任务对合并结果进行系统性质量评测。评测分三个维度：

1. **未合并候选对审查** — 检查算法保守拒绝或不确定的对，是否存在应该合并但漏掉的
2. **Recall Backlog 审查** — 检查 300 个头词组，发掘算法完全未触及的跨形式合并机会
3. **已合并样本抽查** — 随机抽取已合并决策，核验是否存在误并（合并了不该合并的）

所有评测均通过 DeepSeek API 辅助初判，再由人工最终复核。

---

## 评测结果汇总

### 1. 未合并候选对审查

- **输入**：65 对（60 个 `uncertain` 边界对 + 3 个召回扩展对 + 2 个角色拒绝对）
- **AI + 人工最终判断**：
  - 建议合并：**55 对**
  - 保留分离：**10 对**
- **结论**：算法在边界候选中漏掉了约 55 对可合并的情况，主要集中在单复数变体和中英对照场景

### 2. Recall Backlog 审查（头词组内部）

- **输入**：300 个头词组，每组包含同类型、同头词的实体列表
- **AI 扫描发现**：**329 对**潜在合并机会（分布在 137 个头词组中）
- **结论**：大量跨书同义表达仍处于未合并状态，算法召回约为潜力的一半

### 3. 已合并样本抽查

- **输入**：从 453 条合并决策中随机多次抽取，每次 50 条
- **结论**：已合并的内容经多轮抽样检查，**几乎未发现错误合并**，精确率接近 100%

### 综合结论

| 指标 | 情况 |
|------|------|
| 精确率（已合并） | ✅ 极高，抽样无明显误并 |
| 召回率（潜力） | ⚠️ 偏低，估计只合并了潜在机会的约一半 |
| 算法整体倾向 | 保守优先，宁可漏并，不误并 |
| 改进空间 | 单复数变体、中英对照、跨书弱信号场景仍有大量扩召回空间 |

---

## 生成的脚本文件

### `test_prompt/generate_cluster_review.py`

将 `round_07_all15_merge_v7_clusters.jsonl` 中的 9354 个合并后实体簇导出为可交互 HTML，供人工浏览查找残余重复。

**功能**：按类型分标签页、全文搜索、按形式数/书籍数过滤、列排序。

**输出**：`results/entity_merge/round_07_cluster_review.html`

---

### `test_prompt/review_unmerged_with_ai.py`

审查算法未合并的 65 个候选对，调用 DeepSeek API 对每对给出合并建议，生成带人工判断按钮的 HTML。

**输入来源**：
- `round_07_all15_merge_v7_review_samples.jsonl`（60 对，边界 uncertain）
- `round_07_all15_merge_v7_board_recall_review.jsonl`（3 对，召回扩展）
- `round_07_all15_merge_v7_board_blocked_by_role.jsonl`（2 对，角色拒绝）

**运行方式**：
```bash
python test_prompt/review_unmerged_with_ai.py          # 调用 API
python test_prompt/review_unmerged_with_ai.py --skip-api  # 仅用缓存重生成 HTML
```

**缓存**：`results/entity_merge/round_07_ai_review_cache.jsonl`

**输出 HTML**：`results/entity_merge/round_07_unmerged_review.html`

**导出结果**：`results/entity_merge/round_07_unmerged_review_result.json`
- 每条含 `candidate_id`、`decision`、双方名称、定义、信号、得分

---

### `test_prompt/review_recall_backlog.py`

针对 `recall_backlog` 中的 300 个头词组，让 DeepSeek 在每个组内识别应合并但未合并的实体对，生成带释义展示和人工判断按钮的 HTML。

**输入**：`round_07_all15_merge_v7_recall_backlog.jsonl`（300 个头词组）

**特点**：
- AI prompt 附带每个实体的前 2 条定义，提升判断质量
- HTML 展开后每对均显示双侧完整释义，供人工复核
- 成员名悬停可预览定义

**运行方式**：
```bash
python test_prompt/review_recall_backlog.py
python test_prompt/review_recall_backlog.py --skip-api
```

**缓存**：`results/entity_merge/round_07_recall_backlog_ai_cache.jsonl`

**输出 HTML**：`results/entity_merge/round_07_recall_backlog_review.html`

---

### `test_prompt/review_merged_sample.py`

从 453 条已合并决策中随机抽取 50 条，调用 DeepSeek 验证合并是否正确（`correct` / `wrong` / `uncertain`），生成审查 HTML。

**特点**：
- 每次运行默认使用随机 seed，不同批次独立存档，不互相覆盖
- 输出 HTML 文件名带 seed，便于复现（如 `..._seed8231_review.html`）
- 导出时弹窗直接显示错误合并数量

**运行方式**：
```bash
python test_prompt/review_merged_sample.py              # 随机 seed
python test_prompt/review_merged_sample.py --seed 8231  # 复现指定批次
python test_prompt/review_merged_sample.py --skip-api   # 仅重生成 HTML
```

**缓存**：`results/entity_merge/round_07_merged_sample_ai_cache.jsonl`

**输出 HTML**（每次不同）：
- `results/entity_merge/round_07_merged_sample_seed8231_review.html`
- `results/entity_merge/round_07_merged_sample_seed29764_review.html`
- `results/entity_merge/round_07_merged_sample_seed52658_review.html`
- `results/entity_merge/round_07_merged_sample_seed87670_review.html`

---

## 生成的 HTML 文件一览

| 文件 | 用途 |
|------|------|
| `round_07_cluster_review.html` | 浏览合并后全量 9354 个实体簇，排查残余重复 |
| `round_07_unmerged_review.html` | 审查 65 对未合并候选，AI 建议 + 人工判断 |
| `round_07_recall_backlog_review.html` | 审查 300 头词组的漏合并机会，带双侧释义 |
| `round_07_merged_sample_seed*.html` | 已合并决策多轮随机抽查，验证精确率 |

---

## 后续建议

1. **扩召回**：将本次审查出的 55 + 329 对合并建议写入种子别名表或规则，作为 round_08 的输入
2. **针对性扩信号**：单复数变体、中英对照的漏报较集中，可强化对应信号权重
3. **召回 Backlog 优先级**：头词组按 `unresolved_pairs` 数量排序，优先处理 `data`、`model`、`algorithm` 等大组
