---
name: zcodex-memory
description: 使用 ZCodex Memory 的项目级长期记忆。用户要求记住或忘掉信息、询问历史偏好与项目约束，或需要检查已有记忆时使用。
metadata:
  short-description: ZCodex Memory 项目记忆的读取、写入和删除约定
---

# ZCodex Memory

所有调用都必须传当前工作区的绝对路径 `project_root`。

## 何时读取

- 任务涉及用户偏好、项目长期约束、历史决策或过去反馈时，先调用 `memory_search` 或 `memory_manifest`。
- `SessionStart` 已注入 `MEMORY.md` 摘要；不要无条件读取所有记忆。
- 需要正文时调用 `memory_read`，不要猜测记忆内容。

## 何时写入

用户明确说“记住”“记下”“以后按这个来”“remember”时：

1. 先用 `memory_search` 检查同义记忆。
2. 已有记忆用 `memory_write` 的 `update` 或 `upsert`，不要重复创建。
3. 新记忆用 `create`，确保 `name` 是小写 kebab-case。
4. `description` 必须是一行、可用于判断召回的摘要。
5. `feedback` 和 `project` 类型优先在正文包含 `**Why:**` 与 `**How to apply:**`。

用户说“忘掉”“忘记”“forget”时：

1. 先用 `memory_search` 确定目标。
2. 目标明确时调用 `memory_forget`；匹配多条时先让用户选择，不要批量删除。

## 记忆类型

- `user`：用户身份、稳定偏好、专业背景。
- `feedback`：用户对工作方式的纠正或确认。
- `project`：无法从代码、Git 或 AGENTS.md 推导的项目目标、约束、长期方向。
- `reference`：外部资源、链接、面板、票据。

## 不应保存

- 代码结构、文件清单、Git 历史、已有 AGENTS.md 内容。
- 只对当前对话有效的信息、临时任务状态、容易过期且没有长期价值的细节。
- 未经用户确认的敏感信息。

## 维护原则

- 一条记忆一个文件，`MEMORY.md` 只保存一行指针。
- 删除进入 `.trash`，不要使用 shell 直接删除记忆文件。
- 发现索引异常时先 `memory_repair_index(dry_run=true)`，确认后再执行修复。
- 不把记忆正文复制进 `MEMORY.md`。
