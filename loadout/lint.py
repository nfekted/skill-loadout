"""Quality checks for Markdown assets (skills, rules, roles) and SKILL.md front-matter helpers.

Advisory only: findings use the same shape as mcp_check so the UI can render both the same way.
No YAML dependency — front-matter is read as simple `key: value` lines (with indented continuations).
"""
import json
import re
from pathlib import Path

from .mcp_check import actionable, finding, sort  # noqa: F401  (re-exported for callers)

MIN_DESCRIPTION = 30
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_LINK_RE = re.compile(r"\]\(([^)\s#]+)(?:#[^)]*)?\)|`((?:\./)?(?:modules|scripts|references|assets)/[^`\s]+)`")


def slug(name: str) -> str:
    """Skill-style identifier: lowercase letters, digits and hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "untitled"


def _split(text: str):
    """(front-matter lines | None, body, error). Error is set when the block is opened but never closed."""
    lines = text.lstrip("﻿").split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text, None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:]), None
    return None, text, "Front-matter starts with `---` but is never closed."


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        try:
            return json.loads(v) if v[0] == '"' else v[1:-1]
        except json.JSONDecodeError:
            return v[1:-1]
    return v


def parse_frontmatter(text: str) -> tuple[dict | None, str, str | None]:
    """(meta, body, error). meta is None when there is no front-matter block."""
    block, body, err = _split(text)
    if block is None:
        return None, body, err
    meta: dict[str, str] = {}
    key = None
    for ln in block:
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", ln)
        if m and not ln.startswith((" ", "\t")):
            key, val = m.group(1), m.group(2).strip()
            meta[key] = "" if val in (">", "|", ">-", "|-") else _unquote(val)
        elif key and ln.strip() and ln.startswith((" ", "\t")):
            meta[key] = (meta[key] + " " + ln.strip()).strip()
        elif ln.strip() and not ln.lstrip().startswith("#"):
            return meta, body, f"Cannot read front-matter line: `{ln.strip()}`"
    return meta, body, None


def _fm_lines(name: str, description: str) -> list[str]:
    return [f"name: {slug(name)}", f"description: {json.dumps(' '.join(description.split()), ensure_ascii=False)}"]


def apply_frontmatter(text: str, name: str, description: str) -> str:
    """Insert or update `name` and `description` in the front-matter, leaving every other key untouched."""
    new = _fm_lines(name, description)
    block, body, err = _split(text)
    if err:  # broken block: don't guess, put a fresh one on top
        return "---\n" + "\n".join(new) + "\n---\n\n" + text
    if block is None:
        return "---\n" + "\n".join(new) + "\n---\n\n" + text.lstrip("\n")
    kept, skipping = [], False
    for ln in block:
        if re.match(r"^(name|description)\s*:", ln):
            skipping = True
            continue
        if skipping and ln.startswith((" ", "\t")):
            continue
        skipping = False
        kept.append(ln)
    return "---\n" + "\n".join(new + kept) + "\n---\n" + body


def _headings(body: str) -> list[str]:
    return [ln for ln in body.splitlines() if re.match(r"^#{1,6}\s+\S", ln)]


def references(body: str) -> list[str]:
    """Relative file paths a SKILL.md points to (markdown links or backticked modules/references/scripts/assets paths)."""
    out = []
    for m in _LINK_RE.finditer(body):
        ref = (m.group(1) or m.group(2) or "").strip()
        if ref and not re.match(r"^[a-z]+:|^/|^\$|^\{", ref, re.I):
            ref = ref[2:] if ref.startswith("./") else ref
            if ref not in out:
                out.append(ref)
    return out


def _broken_links(body: str, folder: Path) -> list[str]:
    seen, out = set(), []
    for m in _LINK_RE.finditer(body):
        ref = (m.group(1) or m.group(2) or "").strip()
        if not ref or ref in seen or re.match(r"^[a-z]+:|^/|^\$|^\{", ref, re.I):
            continue
        seen.add(ref)
        if not (folder / ref).exists():
            out.append(ref)
    return out


def lint(kind: str, text: str, name: str | None = None, folder: Path | None = None) -> list[dict]:
    """Findings for one Markdown asset, most severe first. `folder` enables link checks for modular skills."""
    if not text.strip():
        return [finding("error", None, "The file is empty.", "empty")]
    out: list[dict] = []
    if kind == "skills":
        meta, body, err = parse_frontmatter(text)
        if err:
            out.append(finding("error", None, err, "frontmatter-invalid"))
        elif meta is None:
            out.append(finding("warning", None, "No front-matter. Agents read `name` and `description` from a `---` "
                               "block at the top of SKILL.md to decide when to use the skill.", "frontmatter-missing"))
        else:
            if not meta.get("name"):
                out.append(finding("warning", None, "Front-matter has no `name`.", "name-missing"))
            elif not NAME_RE.match(meta["name"]):
                out.append(finding("warning", None, f"`name: {meta['name']}` should use lowercase letters, digits "
                                   "and hyphens only.", "name-format"))
            elif name and slug(name) != meta["name"]:
                out.append(finding("info", None, f"Front-matter name `{meta['name']}` differs from the asset name "
                                   f"(`{slug(name)}`).", "name-mismatch"))
            desc = meta.get("description", "")
            if not desc:
                out.append(finding("warning", None, "Front-matter has no `description`. It is what tells the agent "
                                   "when to trigger this skill.", "description-missing"))
            elif len(desc) < MIN_DESCRIPTION:
                out.append(finding("warning", None, f"`description` is very short ({len(desc)} chars). Say what the "
                                   "skill does and when to use it.", "description-short"))
        if not _headings(body):
            out.append(finding("info", None, "No headings — structure the skill into sections.", "no-headings"))
        if folder is not None:
            for ref in _broken_links(body, folder):
                out.append(finding("warning", None, f"Referenced file `{ref}` does not exist in the skill folder.",
                                   "broken-link"))
    else:
        body = text
        words = re.sub(r"^#{1,6}\s+.*$", "", body, flags=re.M).split()
        if len(words) < 5:
            out.append(finding("warning", None, "Almost no content beyond the title — add the actual "
                               f"{'rules' if kind == 'rules' else 'role description'}.", "thin"))
        if not _headings(body) and len(body) > 1500:
            out.append(finding("info", None, "Long text without headings; consider sectioning it.", "no-headings"))
    return sort(out)


def needs_frontmatter(findings: list[dict]) -> bool:
    return any(f["code"] in ("frontmatter-missing", "frontmatter-invalid", "name-missing", "description-missing",
                             "name-format", "name-mismatch") for f in findings)
