# Sourced by the VHS agent tape: the sandbox environment, plus a Claude Code
# alias that makes every reply end with a step marker, so the recorder can tell
# one step of the transcript from the next.
#
#   source scripts/demo/agent-shell.sh
source scripts/demo/env.demo
unset CLAUDECODE CLAUDE_CODE_CHILD_SESSION
MARKER_RULE='Every user message starts with a tag like [step 2]. End every reply with one final line reading exactly: -- step 2 done -- using that tag number. Keep replies compact: short tables, no long prose.'
alias claude="claude --allowedTools Bash,Read,Grep,Glob --strict-mcp-config --mcp-config '{\"mcpServers\":{}}' --append-system-prompt '$MARKER_RULE'"
