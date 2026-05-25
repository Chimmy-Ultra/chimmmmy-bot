---
description: Claude Code 用量配速表（每週五 15:00 重置，看一小時該用多少 %）
argument-hint: "[目前用量%，可省略，例 45]"
allowed-tools: Bash(python3:*)
---

以下是目前的 Claude Code 用量配速表（可在指令後帶上目前用量 %，例 `/pace 45`，會多算超前/落後與用完預估）。請把輸出**原樣呈現**給我，不要改寫、不要加任何解讀或註解：

!`python3 "$HOME/.claude/commands/pace.py" $ARGUMENTS 2>/dev/null || python3 "${CLAUDE_PROJECT_DIR:-.}/.claude/commands/pace.py" $ARGUMENTS`
