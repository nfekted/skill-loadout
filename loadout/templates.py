"""Built-in starter templates for skills, rules, roles and MCP configs (files under loadout/templates/)."""
import json
from pathlib import Path

from . import lint

ROOT = Path(__file__).resolve().parent / "templates"
KINDS = ("skills", "rules", "roles", "mcp_configs")


def all_templates() -> list[dict]:
    return json.loads((ROOT / "index.json").read_text(encoding="utf-8"))


def for_kind(kind: str) -> list[dict]:
    return [t for t in all_templates() if t["kind"] == kind]


def get(kind: str, id_: str) -> dict | None:
    return next((t for t in for_kind(kind) if t["id"] == id_), None)


def folder(t: dict) -> Path | None:
    """The template directory for modular skills, else None."""
    p = ROOT / t["path"]
    return p if p.is_dir() else None


def raw_text(t: dict) -> str:
    p = ROOT / t["path"]
    return ((p / "SKILL.md") if p.is_dir() else p).read_text(encoding="utf-8")


def render(t: dict, name: str | None = None) -> str:
    """Template text with {{name}} (skill identifier) and {{title}} (display name) filled in."""
    title = (name or t["name"]).strip() or t["name"]
    return raw_text(t).replace("{{name}}", lint.slug(title)).replace("{{title}}", title)


def extra_files(t: dict) -> list[str]:
    """Other files shipped with a modular template (relative paths)."""
    d = folder(t)
    if not d:
        return []
    return sorted(f.relative_to(d).as_posix() for f in d.rglob("*") if f.is_file() and f.name != "SKILL.md")
