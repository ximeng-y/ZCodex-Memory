[中文](README.zh-CN.md) | English

# ZCodex Memory

> **Source and License Notice**
>
> This project is a Codex-compatible plugin derived from, adapted from, and rewritten based on the upstream ZCode project's Memory mechanism. It is not an official ZCode project and is not affiliated with, sponsored by, or endorsed by the ZCode project.
>
> The project as a whole is distributed under the Apache-2.0 license. Some implementation is adapted from the upstream ZCode project. Attribution and the upstream NOTICE are available in [NOTICE](NOTICE). The ZCode name, related trademarks, and upstream code rights belong to their respective owners.
>
> Upstream resources: [ZCode repository](https://github.com/zai-org/ZCode) · [Apache-2.0 license](https://github.com/zai-org/ZCode/blob/main/LICENSE) · [Upstream NOTICE.md](https://github.com/zai-org/ZCode/blob/main/NOTICE.md)

This is a compatibility plugin for local Codex that implements the core Memory mechanisms of the main ZCode project using only the Python standard library.

If you have stopped using ZCode for any reason but have difficulty migrating the Memory accumulated by your agents, this project implements the following core mechanisms in Codex as a plugin:

- A persistent `MEMORY.md` index.
- One Markdown file per memory.
- On-demand lexical search, with queries split on whitespace and no vector database.
- Hooks for session injection, explicit-intent hints, direct-write marking, and background extraction at Stop.
- MCP tools for structured reading, writing, deletion, and index repair.
- Skill constraints that define when the model should read, when it should write, and what should not be saved.

## Memory Storage Location (Inherited from ZCode)

```text
~/.zcode/cli/memories/projects/<slug>-<hash16>/memory/
```

On Windows, the path is converted to lowercase according to ZCode rules before SHA-256 is calculated; the first 16 characters are used.

## Installation (Windows)

The current version supports Windows 10/11 only and requires:

- Python 3.10 or later, with the `python` command available on `PATH`.
- Codex Desktop or a working Codex CLI.
- After installation, trust all hooks under "Settings -> Hooks -> ZCodex Memory".

### Option 1: Install Through a Marketplace (Recommended)

```bash
codex plugin marketplace add ximeng-y/ZCodex-Memory --ref main
codex plugin list --available --json
codex plugin add zcodex-memory@ximeng-zcodex-memory
```

After installation, restart Codex, confirm that `ZCodex Memory` is enabled under Plugins, and then trust the hooks in Settings.

### Option 2: Clone and Add to Your Personal Marketplace (Local Development)

```bash
git clone https://github.com/ximeng-y/ZCodex-Memory.git
cd ZCodex-Memory
codex
```

Enter the following in Codex:

```text
$plugin-creator

This repository is already a complete Codex plugin:
- .codex-plugin/plugin.json already exists
- .mcp.json already exists
- hooks/hooks.json already exists
- skills/zcodex-memory/SKILL.md already exists

Do not recreate or overwrite the plugin source.
Register the current directory as an existing plugin in my personal marketplace.
Use zcodex-memory as the plugin name and ximeng-zcodex-memory as the marketplace name.
When finished, tell me how to install it.
```

After it finishes, restart Codex and install `ZCodex Memory` from the local marketplace under Plugins. You can also verify it with the CLI:

```bash
codex plugin list --available --json
codex plugin add zcodex-memory@ximeng-zcodex-memory
```

### You Must Trust the Hooks

Installing or enabling the plugin does not automatically trust its hooks. Open:

```text
Settings -> Hooks -> ZCodex Memory
```

Trust all hooks. Otherwise, behaviors such as SessionStart, UserPromptSubmit, and Stop will not run completely.

### MCP Startup Requirements

The current `.mcp.json` uses Windows `cmd.exe` and `scripts/launch_mcp.cmd`, so it supports Windows only. The system `PATH` must contain `python`, and its version must be Python 3.10 or later.

## Configuration

Default configuration file:

```text
~/.zcodex-memory/config.json
```

Example:

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

Environment variables can override these values:

- `ZCODEX_MEMORY_CONFIG`
- `ZCODEX_MEMORY_BACKEND`
- `ZCODEX_MEMORY_CLI_STORAGE_ROOT`
- `ZCODEX_MEMORY_AUTO_EXTRACT`
- `ZCODEX_MEMORY_MODEL`
- `ZCODEX_WORKSPACE_IDENTITY`

## Included MCP Tools

- `memory_status`
- `memory_index`
- `memory_manifest`
- `memory_search`
- `memory_read`
- `memory_write`
- `memory_forget`
- `memory_repair_index`

## Included Hook Behavior

- `SessionStart`: injects a compact `MEMORY.md` index and usage rules.
- `UserPromptSubmit`: saves the current prompt, detects explicit intents such as "remember" and "forget", and prompts the main agent to call MCP.
- `PostToolUse`: marks the current turn after successful memory writes, deletions, or index repair so that Stop does not extract again.
- `Stop`: asynchronously calls `codex exec` to extract long-term memory from ordinary successful turns.

Background extraction reuses the current Codex Provider and authentication. On failure, it keeps a pending snapshot, does not write partial results, and does not silently fall back to an API key.

## Known Limitations

- The current version supports Windows only; MCP startup depends on `cmd.exe`.
- Python 3.10 or later is required, and the `python` command must be on `PATH`.
- It does not implement Compact/Session History, Subagent Persistent Memory, global memory, or embeddings.
- It does not provide a general-purpose enforced filesystem sandbox; MCP writes and background extraction are limited to the project memory directory.
- Background extraction depends on the `codex` command on `PATH`; if it is unavailable, the extraction queue is retained and errors are logged without blocking the current turn.

## License and Source

- The project as a whole is distributed under the [Apache-2.0](LICENSE) license.
- Some implementation is adapted from the upstream ZCode project; see [NOTICE](NOTICE) for the related attribution.
- This project is not an official ZCode project and is not affiliated with, sponsored by, or endorsed by the ZCode project.