# CADProcessResult 从布尔成功/失败迁移到流程 status 枚举

`CADProcessResult` 原本用 `success: bool` 表示处理结果。智能模式语义分析失败时需要一个中间状态——模型未生成但不是永久失败，用户提供额外信息后可以继续——布尔值无法表达。引入 `status` 枚举作为真实状态源，`success` 降级为兼容字段。

## Considered Options

**A. 在 `CADProcessResult` 上加 `needs_clarification: bool` 字段。**
`success=False` 时靠额外 bool 区分"真失败"和"需要用户输入"。调用方需要检查两个字段，每加一个新状态就要加一个新 bool，退化成一堆 flag。

**B. 新建独立的 `PipelineState` 对象，与 `CADProcessResult` 并行。**
两个对象各自表达不同维度，但消费者（CLI/GUI）同时需要两者，最终还是会拼在一起。增加了不必要的概念数量。

**C. `status` 枚举替代 `success` 布尔，同时保留 `success` 作为兼容字段。**
新代码用 `status`，旧 CLI/测试/批处理统计继续用 `success`，两者不冲突。`needs_clarification` 映射到 `success=False`，逻辑自洽。选中。

## Decision

`CADProcessResult` 新增 `status: PipelineStatus` 枚举字段：

| status | success | 含义 |
|--------|---------|------|
| `completed` | `True` | 正常完成 |
| `partial_completed` | `True` | 生成了部分建模成果，模型主体可用但部分细节被跳过 |
| `failed` | `False` | 不可恢复的失败 |
| `needs_clarification` | `False` | 语义不足，等待用户输入后可继续 |
| `stopped_by_user` | `False` | 用户在阶段确认点主动停止处理 |

`success` 字段保留不变——旧调用方不关心原因，只关心是否成功的情况下无需改动。新流程（GUI追问面板、CLI区分退出码）使用 `status`。

## Consequences

- GUI 检测到 `needs_clarification` 时不显示"处理失败"，而是进入追问面板，展示 `clarification_questions` 列表。
- GUI 检测到 `stopped_by_user` 时显示"已停止"，不弹失败对话框。
- CLI 检测到 `needs_clarification` 时打印问题清单，以区分于普通失败的退出码返回。
- `process_with_intelligent_analysis()` 的返回值语义从两态变成三态，所有调用方需要至少处理 `status` 或在看到 `success=False` 时检查 `status` 判断是否可继续。
- 纯批处理模式下（无交互渠道），`needs_clarification` 等同于 `failed`。
