---
description: Claude Code 用量配速表（每週五 15:00 重置，看一小時該用多少 %）
allowed-tools: Bash(python3:*)
---

以下是目前的 Claude Code 用量配速表。請把它**原樣輸出**給我，不要改寫、不要加任何解讀或註解：

!`python3 "$HOME/.claude/commands/pace.py" 2>/dev/null || python3 "${CLAUDE_PROJECT_DIR:-.}/.claude/commands/pace.py"`
