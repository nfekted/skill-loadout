"""Target agent frameworks and where each expects its files."""

FRAMEWORKS = {
    "Claude": {"root_file": "CLAUDE.md", "skills_dir": ".claude/skills"},
    "ChatGPT Codex": {"root_file": "AGENTS.md", "skills_dir": ".codex/skills"},
    "Antigravity": {"root_file": "ANTIGRAVITY.md", "skills_dir": ".antigravity/skills"},
    "Cursor": {"root_file": ".cursorrules", "skills_dir": ".cursor/skills"},
    "GitHub Copilot": {"root_file": ".github/copilot-instructions.md", "skills_dir": ".github/skills"},
}
DEFAULT_FRAMEWORK = "Claude"

# Universal pattern (created lazily when MCP assets are attached).
MCP_CONFIG = ".mcp/config.json"
MCP_SERVERS_DIR = ".mcp/servers"
AGENTS_DIR = ".agents"          # .agents/rules, .agents/roles, .agents/skills
CLAUDE_MCP = ".claude/mcp.json"  # points to ../.mcp/config.json


def framework(name: str) -> dict:
    return FRAMEWORKS.get(name) or FRAMEWORKS[DEFAULT_FRAMEWORK]
