# 缓存与待恢复任务交互边界

## Context

分析缓存（`AnalysisCache`，`.cache/analysis/`）和待恢复任务存储（`PendingClarificationStore`，`.cache/batch_pending/`）是两套独立的持久化系统，服务于不同阶段。但它们的交互存在三个冲突：

1. **恢复后旧缓存未失效**：用户通过 `continue_with_clarification` 恢复图纸后，旧分析缓存条目仍留在磁盘上。下次首次处理同一文件时，可能命中不含用户澄清信息的过时缓存。
2. **含澄清问题的结果被缓存**：首次处理进入 `needs_clarification` 的分析结果（包含未决 `clarification_questions`）仍被写入分析缓存。这类半成品命中缓存后仍需走澄清流程，没有实际收益，反而可能造成状态不一致。
3. **resolved/deleted 条目不删除磁盘文件**：`mark_resolved()` 和 `mark_deleted()` 只改写 JSON 中的 `status` 字段，不删除磁盘文件，长期运行积累废弃文件。

## Decision

1. 恢复成功后，主动调用 `AnalysisCache.invalidate(file_path)` 删除该文件的分析缓存条目，防止后续首次处理命中过时结果。
2. `_is_cacheable_analysis_result()` 增加排除条件：当分析结果包含未决 `clarification_questions` 时，不写入缓存。只有完整的、可直接继续执行的分析结果才进入缓存。
3. `mark_resolved()` 和 `mark_deleted()` 直接删除磁盘文件，而非改写 `status` 字段保留废弃 JSON。

## Consequences

- 分析缓存只包含完整结果，不含半成品；缓存命中意味着分析可直接进入建模执行，无需再走澄清流程。
- 恢复路径与缓存路径互不干扰：恢复后旧缓存被清除，首次处理不会命中过时数据。
- `.cache/batch_pending/` 不再积累 resolved/deleted 废弃文件。
- 含澄清问题的首次分析结果不缓存，意味着对同一文件再次首次处理时会重新调用 LLM；这是可接受的代价，因为这类结果缓存后也没有实际收益。
