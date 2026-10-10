"""Paths and constants shared across Skill Loadout."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_LIMIT_CHARS = 12_000
CHARS_PER_TOKEN = 3          # rough estimate: 1000 characters ~ 333 tokens
PROJECT_TOKEN_WARN = 20_000  # estimated tokens of attached text before a project is flagged
DEFAULT_TAG_COLORS = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6",
                      "#EC4899", "#14B8A6", "#F97316", "#6366F1", "#84CC16"]

# Entities stored in data.json (order matters for export / display).
ENTITY_KEYS = ["skills", "roles", "rules", "mcp_configs", "mcp_servers",
               "agents", "loadouts", "tags", "utilities", "projects"]


def home() -> Path:
    """Loadout storage root. Override with LOADOUT_HOME (used by tests)."""
    return Path(os.environ.get("LOADOUT_HOME", ROOT)).expanduser().resolve()


def data_file() -> Path:
    return home() / "data.json"
