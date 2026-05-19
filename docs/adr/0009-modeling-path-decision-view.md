# 建模路径裁决视图

建模路径裁决结果仍需要兼容既有 dict 调用方，但路径契约、路径优选、追问阻塞和降级语义不能继续依赖各调用点手写字段判断。否则每新增一条专用建模路径，调用方都需要理解 `candidate_paths`、`blocked_by_path_contract`、`requires_path_preference`、`clarification_questions` 等内部字段组合。

## Decision

1. `modeling_path_decision` 的外部数据形态暂时保持 dict，避免一次性改动 GUI、批处理、测试和执行器调用。
2. 新增 `ModelingPathDecision` 作为只读裁决视图，集中提供 `modeling_path`、`candidate_paths`、`clarification_questions`、`requires_clarification`、`path_requiring_clarification` 和 `missing_contract_fields`。
3. 路径层追问判断、路径路由执行和追问降级上下文应优先通过 `ModelingPathDecision` 读取语义，不应在调用点重复解释底层字段。
4. 后续若要把 dict 彻底替换为结果对象，应先保证 GUI、CLI、批处理结果序列化和缓存格式都有兼容迁移策略。

## Consequences

- 现有调用方继续按 dict 读取，不破坏缓存和结果输出。
- 新代码获得更小的 interface，减少对路径裁决内部字段组合的重复理解。
- 路径契约和 fallback 测试可以断言对象语义，而不是复制字段拼装细节。
- 在更多调用点迁移到 `ModelingPathDecision` 前，dict 字段仍是兼容层，不能随意删除或重命名。
