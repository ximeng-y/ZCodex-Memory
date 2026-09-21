[English](README.md) | 中文

# ZCodex Memory

> **来源与许可声明**
>
> 本项目是基于 ZCode 上游 Memory 机制进行移植、改写并适配 Codex 的兼容插件，不是 ZCode 官方项目，也与 ZCode 官方无隶属、赞助或背书关系。
>
> 本项目整体采用 Apache-2.0 许可证。部分实现改编自 ZCode 上游项目，相关归属和上游 NOTICE 见 [NOTICE](NOTICE)。ZCode 名称、相关商标及上游代码权利归其各自权利人所有。
>
> 上游资源：[ZCode 仓库](https://github.com/zai-org/ZCode) · [Apache-2.0 许可证](https://github.com/zai-org/ZCode/blob/main/LICENSE) · [上游 NOTICE.md](https://github.com/zai-org/ZCode/blob/main/NOTICE.md)

这是一个面向本地 Codex 的兼容布局插件，用 Python 标准库实现 ZCode 主项目 Memory 的核心机制

如果你因各种原因弃用 ZCode ，又难以迁移 Agent 在其中累积下的 Memory ，那么本项目将下面这些核心机制在Codex中以插件形式实现：

- `MEMORY.md` 常驻索引；
- 一条记忆一个 Markdown 文件；
- 按需词法搜索，查询按空白拆分成多个词，不使用向量数据库；
- Hooks 负责会话注入、显式意图提示、直接写入标记和 Stop 后台提取；
- MCP 提供结构化读取、写入、删除和索引修复；
- Skill 约束模型何时读取、何时写入、哪些内容不应保存。

## 记忆存储位置（继承ZCode机制）

```text
~/.zcode/cli/memories/projects/<slug>-<hash16>/memory/
```

Windows 路径按 ZCode 规则转小写后计算 SHA-256，取前 16 位。

## 安装（Windows）

当前版本暂只支持 Windows 10/11，并要求：

- Python 3.10 或更高版本，且 `python` 命令已加入 `PATH`；
- Codex Desktop 或可用的 Codex CLI；
- 安装后在“设置 -> 钩子 -> ZCodex Memory”中信任全部 Hook。

### 方式一：通过 marketplace 安装（推荐）

```bash
codex plugin marketplace add ximeng-y/ZCodex-Memory --ref main
codex plugin list --available --json
codex plugin add zcodex-memory@ximeng-zcodex-memory
```

安装后重启 Codex，在 Plugins 中确认 `ZCodex Memory` 已启用，然后进入设置信任 Hook。

### 方式二：克隆后接入个人 marketplace（本地开发）

```bash
git clone https://github.com/ximeng-y/ZCodex-Memory.git
cd ZCodex-Memory
codex
```

在 Codex 中输入：

```text
$plugin-creator

当前仓库已经是一个完整的 Codex 插件：
- 已有 .codex-plugin/plugin.json
- 已有 .mcp.json
- 已有 hooks/hooks.json
- 已有 skills/zcodex-memory/SKILL.md

不要重新创建或覆盖插件源码。
请把当前目录作为现有插件接入我的个人 marketplace，
插件名使用 zcodex-memory，marketplace 名使用 ximeng-zcodex-memory。
完成后告诉我怎样安装。
```

完成后重启 Codex，在 Plugins 中从本地 marketplace 安装 `ZCodex Memory`。也可以用 CLI 确认：

```bash
codex plugin list --available --json
codex plugin add zcodex-memory@ximeng-zcodex-memory
```

### 必须信任 Hook

安装或启用插件不会自动信任 Hook。进入：

```text
设置 -> 钩子 -> ZCodex Memory
```

信任全部 Hook，否则 SessionStart、UserPromptSubmit、Stop 等行为不会完整执行。

### MCP 启动条件

当前 `.mcp.json` 使用 Windows 的 `cmd.exe` 和 `scripts/launch_mcp.cmd`，因此仅支持 Windows。系统 `PATH` 中必须有 `python`，且版本不低于 Python 3.10。

## 配置

默认配置文件：

```text
~/.zcodex-memory/config.json
```

示例：

```json
{
  "backend": "zcode-files",
  "cli_storage_root": "~/.zcode/cli",
  "auto_extract": true,
  "extract_model": null,
  "index_max_lines": 200,
  "index_max_chars": 12000
}
```

环境变量可覆盖：

- `ZCODEX_MEMORY_CONFIG`
- `ZCODEX_MEMORY_BACKEND`
- `ZCODEX_MEMORY_CLI_STORAGE_ROOT`
- `ZCODEX_MEMORY_AUTO_EXTRACT`
- `ZCODEX_MEMORY_MODEL`
- `ZCODEX_WORKSPACE_IDENTITY`

## 附带的 MCP 工具

- `memory_status`
- `memory_index`
- `memory_manifest`
- `memory_search`
- `memory_read`
- `memory_write`
- `memory_forget`
- `memory_repair_index`

## 附带的 Hook 行为

- `SessionStart`：注入紧凑的 `MEMORY.md` 索引和使用规则。
- `UserPromptSubmit`：保存当前 prompt，识别“记住/忘掉”等显式意图并提示主 Agent 调用 MCP。
- `PostToolUse`：成功的记忆写入、删除或索引修复会标记当前回合，Stop 不再重复提取。
- `Stop`：异步调用 `codex exec` 提取普通成功回合中的长期记忆。

后台提取复用当前 Codex Provider 和认证。失败时保留待处理快照，不写入半成品，也不会静默回退到 API Key。

## 已知边界

- 当前版本仅支持 Windows；MCP 启动依赖 `cmd.exe`。
- 需要 Python 3.10 或更高版本，且 `python` 命令必须位于 `PATH`。
- 不实现 Compact/Session History、Subagent Persistent Memory、全局记忆或 embedding。
- 不提供通用文件系统强制沙箱；MCP 写入和后台提取均限制在项目记忆目录内。
- 后台提取依赖 `PATH` 中的 `codex` 命令；不可用时会保留提取队列并记录错误，不影响当前回合继续执行。

## 许可证与来源

- 本项目整体采用 [Apache-2.0](LICENSE) 许可证。
- 部分实现改编自 ZCode 上游项目，相关声明见 [NOTICE](NOTICE)。
- 本项目不是 ZCode 官方项目，与 ZCode 官方无隶属、赞助或背书关系。
