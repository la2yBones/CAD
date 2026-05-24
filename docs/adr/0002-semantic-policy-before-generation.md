# 在语义生成前引入语义裁决 module

> 修正：ADR-0013 已重新划定语义裁决边界。`SemanticPolicy` 不应继续扩张为本地确定性语义决策层，而应逐步收缩为证据整理、候选生成和安全校验边界；复杂视图、尺寸和特征角色由大模型基于图纸证据包裁决。

当前智能重建流程会把完整 `reconstruction_context` 直接交给 LLM 做语义生成。该上下文同时包含尺寸标注值、图形实体坐标、视图统计和局部关系。实践中，LLM 会在同一次结果里混用不同尺寸来源：例如口头声明“按标注建模”，却又把从实体坐标反算出的几何测量值写入关键尺寸，导致后续建模脚本比例失真。

这个问题不是某个零件的局部规则缺失，而是 reconstruction seam 太浅：语义生成 module 既要解释零件，又要自己决定哪些输入可被信任、何时需要追问。尺寸裁决、特征证据门槛和追问触发逻辑散落在 prompt、schema 校验和上层 pipeline 中，缺少 locality。

## Considered Options

**A. 继续在 prompt 和 validator 中追加局部约束。**
可以快速拦住单个案例，但会不断把新的例外塞回语义生成 module。LLM 仍直接面对未经裁决的原始上下文，caller 也仍需理解哪些失败应该重试、哪些应该追问。module 继续保持 shallow。

**B. 引入一个仅做 deterministic 校验的前置 module，追问仍由上层 pipeline 决定。**
这能集中一部分规则，但“无法安全裁决”与“该向用户问什么”被拆到两个地方。两者共享同一批知识，拆开会再次损失 locality。

**C. 在语义生成前引入深的“语义裁决” module。**
该 module 先对尺寸来源、尺寸绑定和特征证据做 deterministic 判断；能安全继续时产出裁决后的上下文和 assumptions，无法安全继续时直接产出结构化追问清单。后续语义生成只消费 `adjudicated_context`，不再读取未经裁决的原始混合输入。选中。

## Decision

在 reconstruction 流程中新增 **语义裁决** module，位于 `reconstruction_context` 与 `PartSemanticGenerator` 之间。

语义裁决的首批职责：

1. 判定尺寸来源：`annotation`、`geometry` 或 `unresolved`。
2. 建立尺寸绑定：把可用尺寸绑定到长度、厚度、对边、对角、孔径等语义角色。
3. 对减材特征施加证据门槛：隐藏线、同心圆或孤立投影不足以单独升级为孔、槽、切除。
4. 当冲突不会改变关键拓扑时，选择一个安全来源继续，并显式记录 assumptions。
5. 当冲突会改变关键尺寸或拓扑时，产出结构化追问清单，而不是继续自由推断。

首批会触发追问的确定性场景：

- 同一关键尺寸角色（如 `profile_length`、`profile_height`、`depth`）出现多个不同标注值；
- 多视图重建缺少主视图水平总尺寸绑定，且当前只剩裸线性尺寸可供选择。

追问不是主要理解机制。语义裁决应优先使用 `DIMENSION.definition_points` 建立线性尺寸区间，识别局部段、相邻尺寸链和组合总尺寸。只有尺寸区间拓扑仍无法裁决时，才把问题交给用户。

语义裁决对下游输出 `dimension_plan`：

- `allowed_dimensions`：允许进入 `key_dimensions` 的已裁决尺寸，可包含由标注尺寸链组合得到的派生总尺寸；
- `construction_dimensions`：构造尺寸，可作为组合尺寸证据、局部分段尺寸、局部特征尺寸或重复特征尺寸，用于建模构造步骤，但不能被单独命名为总长、深度、对边、对角等主体关键语义。构造尺寸按通用角色族表达，例如 `linear_segment`、`feature_size`、`feature_count_size`、`chain_component` 和 `candidate_binding`；可附带 `feature_kind` 作为特征上下文，但不得引入按具体图纸或具体零件命名的特殊角色；
- `unresolved_dimensions`：尚未裁决的裸尺寸，不得被 LLM 擅自命名或用于关键几何；
- `rules`：下游语义生成和建模指令必须遵守的尺寸使用纪律。

`construction_dimensions` 默认进入建模任务载荷而不是主体关键尺寸池；只有在名称保留具体构造语义时才能进入 `key_dimensions`，例如 `thread_length`、`head_length`、`fillet_radius`。它不得以 `total_length`、`depth`、`hole_diameter`、`across_flats` 等主体关键名出现。`unresolved_dimensions` 永远不得进入 `key_dimensions`。

迁移时不保留旧 `segment_dimensions` 兼容读取；新产物、新缓存和新测试统一使用 `construction_dimensions`。如果旧分析缓存中仍存在 `segment_dimensions`，应通过清空或重新生成缓存解决，而不是在运行时代码中长期保留双字段分支。

投影视图外形尺寸使用中性角色表达，例如 `projected_profile_horizontal_extent` 和 `projected_profile_vertical_extent`。这些角色只说明“某个正交投影视图中的外形水平/竖直尺寸”，不直接声明它是深度、对边、对角或某个特定零件特征。

倒角标注使用保守外角语义：`1x45°`、`2x45°` 等只表示外部尖角削除形成斜面。若无法定位倒角所在外部边，应跳过并写入 warning；不得将倒角建成内陷槽、凹坑、沉孔或向实体内部新增的负形特征。
半径标注使用圆弧/圆角语义。对六角头螺栓头部侧面的 `R15`，它表示绕螺栓轴线形成的圆弧面/承面；若已被语义裁决定位，建模阶段应优先尝试用圆弧轮廓回转或回转切除表达，而不是作为普通 edge fillet 风险直接跳过。

预期 interface：

```python
policy_result = SemanticPolicy.evaluate(reconstruction_context)

policy_result = {
    "dimension_source": "annotation | geometry | unresolved",
    "dimension_bindings": [...],
    "feature_constraints": {...},
    "clarification_questions": [...],
    "assumptions": [...],
    "adjudicated_context": {...},
}
```

`SemanticReconstructionPipeline` 调用 `SemanticPolicy.evaluate()` 后：

- 若存在 `clarification_questions`，流程进入 `needs_clarification`；
- 否则将 `adjudicated_context` 传给 `PartSemanticGenerator`；
- `PartSemanticGenerator` 不再直接读取未经裁决的原始上下文。

## Consequences

- 语义生成 module 的 interface 变小：它只负责解释已经裁决过的输入，不再同时承担尺寸可信度判断。
- 尺寸冲突、追问触发、减材特征升级门槛获得更强 locality，可在 deterministic tests 中验证。
- 对于标注与图形测量冲突但仍可安全继续的图纸，系统可以继续自动化，同时显式记录 assumptions，而不是默认把用户拖入审批流。
- 对于会改变拓扑或关键尺寸的冲突，系统会更早进入 `needs_clarification`，减少错误模型生成。
- prompt 与 validator 中现有的部分尺寸纪律会逐步迁移到语义裁决 module，避免长期重复维护。
- 未来 architecture review 不应再建议把这类裁决规则继续追加回 prompt；除非重新讨论本 ADR。
