# 问题跟踪器：GitHub

本仓库的问题与 PRD 统一放在 GitHub Issues 中。所有相关操作默认使用 `gh` CLI。

## 约定

- **创建 issue**：`gh issue create --title "..." --body "..."`
- **读取 issue**：`gh issue view <number> --comments`
- **列出 issue**：使用 `gh issue list`，并按需附加 `--label`、`--state` 等过滤条件
- **评论 issue**：`gh issue comment <number> --body "..."`
- **增删标签**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **关闭 issue**：`gh issue close <number> --comment "..."`

仓库由当前工作目录中的 `git remote -v` 推断；在 clone 内执行时，`gh` 会自动识别目标仓库。

## 技能术语映射

- 当某个技能说“发布到 issue tracker”时：创建一个 GitHub Issue。
- 当某个技能说“读取相关 ticket”时：执行 `gh issue view <number> --comments`。
