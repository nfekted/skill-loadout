"""Project synchronization: attach/detach assets, managed block, MCP files, discovery."""
import difflib
import hashlib
import json
import os
import re
from pathlib import Path

from . import files, frameworks, lint, store, tokens

START = "<!-- LOADOUT:START -->"
END = "<!-- LOADOUT:END -->"
_BLOCK_RE = re.compile(re.escape(START) + r".*?" + re.escape(END) + r"\n?", re.S)
ATTACHABLE = ["skills", "roles", "rules", "mcp_configs", "mcp_servers"]


def root(project: dict) -> Path:
    return Path(project["path"]).expanduser()


def path_exists(project: dict) -> bool:
    return root(project).is_dir()


def _fw(project: dict) -> dict:
    return frameworks.framework(project.get("target_model", ""))


def _rel_posix(target: Path, start: Path) -> str:
    return Path(os.path.relpath(target, start)).as_posix()


def attached(project: dict, data: dict, kind: str | None = None) -> list[tuple[str, dict]]:
    kinds = [kind] if kind else ATTACHABLE
    out = []
    for k in kinds:
        ids = project.get(store.PROJECT_LISTS[k], [])
        out += [(k, e) for e in data[k] if e["id"] in ids]
    return out


def has_mcp(project: dict) -> bool:
    return bool(project.get("attached_mcp"))


# ---- destinations ---------------------------------------------------------
def dest(project: dict, kind: str, asset: dict, universal: bool = False) -> Path:
    r = root(project)
    unit = files.unit_path(kind, asset["path"])
    if kind == "skills":
        if universal:
            return r / frameworks.AGENTS_DIR / "skills" / unit.name
        return r / _fw(project)["skills_dir"] / unit.name
    if kind in ("rules", "roles"):
        return r / frameworks.AGENTS_DIR / kind / unit.name
    if kind == "mcp_servers":
        return r / frameworks.MCP_SERVERS_DIR / unit.name
    raise ValueError(kind)


# ---- managed block --------------------------------------------------------
def _write_block(project: dict, root_file: Path, body: str | None) -> None:
    text = root_file.read_text(encoding="utf-8") if root_file.exists() else ""
    block = f"{START}\n{body}\n{END}\n" if body else ""
    if _BLOCK_RE.search(text):
        new = _BLOCK_RE.sub(lambda _m: block, text, count=1)
    elif block:
        new = text + ("" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")) + block
    else:
        return
    if not new.strip():
        if root_file.exists():
            root_file.unlink()
            files.prune_empty(root_file.parent, root(project))
        return
    files.write_file(root_file, new)


def rebuild_block(project: dict, data: dict) -> None:
    root_file = root(project) / _fw(project)["root_file"]
    sections = []
    for kind, title in (("roles", "Roles"), ("rules", "Rules")):
        items = attached(project, data, kind)
        if not items:
            continue
        lines = [f"### {title}"]
        for _, a in items:
            target = dest(project, kind, a)
            lines.append(f"- @{_rel_posix(target, root_file.parent)}  <!-- {a['name']} -->")
        sections.append("\n".join(lines))
    body = None
    if sections:
        body = ("## Loadout Roles & Rules\n_Managed by Skill Loadout. Edits between the markers are overwritten._\n\n"
                + "\n\n".join(sections))
    _write_block(project, root_file, body)


# ---- MCP ------------------------------------------------------------------
def _servers_of(cfg_path: Path) -> dict:
    j = json.loads(cfg_path.read_text(encoding="utf-8"))
    if isinstance(j, dict) and isinstance(j.get("mcpServers"), dict):
        return j["mcpServers"]
    return j if isinstance(j, dict) else {}


def rebuild_mcp(project: dict, data: dict) -> None:
    r = root(project)
    cfg = r / frameworks.MCP_CONFIG
    link = r / frameworks.CLAUDE_MCP
    merged: dict = {}
    for _, a in attached(project, data, "mcp_configs"):
        merged.update(_servers_of(files.resolve(a["path"])))
    if link.is_symlink() or link.exists():
        link.unlink()
    if not merged:
        if cfg.exists():
            cfg.unlink()
        files.prune_empty(link.parent, r)
        files.prune_empty(cfg.parent, r)
        return
    files.write_file(cfg, json.dumps({"mcpServers": merged}, indent=2))
    if project.get("target_model") == "Claude":
        files.ensure_parent(link)
        try:
            link.symlink_to(os.path.join("..", frameworks.MCP_CONFIG))
        except OSError:
            files.write_file(link, cfg.read_text(encoding="utf-8"))


def _reconcile_universal(project: dict, data: dict) -> None:
    """Mirror skills into .agents/skills only while MCP assets are attached."""
    uni = has_mcp(project)
    for _, a in attached(project, data, "skills"):
        d = dest(project, "skills", a, universal=True)
        if uni:
            files.copy_into(files.unit_path("skills", a["path"]), d)
        elif d.exists():
            files.remove_path(d)
            files.prune_empty(d.parent, root(project))


# ---- attach / detach ------------------------------------------------------
def attach(project: dict, data: dict, kind: str, asset: dict) -> None:
    lst = store.PROJECT_LISTS[kind]
    ids = project.setdefault(lst, [])
    if asset["id"] not in ids:
        ids.append(asset["id"])
    _apply(project, data, kind, asset)


def _apply(project, data, kind, asset):
    src = files.unit_path(kind, asset["path"])
    if kind == "skills":
        files.copy_into(src, dest(project, kind, asset))
    elif kind in ("rules", "roles"):
        files.copy_into(src, dest(project, kind, asset))
        rebuild_block(project, data)
    elif kind == "mcp_servers":
        files.copy_into(src, dest(project, kind, asset))
    elif kind == "mcp_configs":
        rebuild_mcp(project, data)
    _reconcile_universal(project, data)


def detach(project: dict, data: dict, kind: str, asset: dict) -> None:
    lst = store.PROJECT_LISTS[kind]
    project[lst] = [i for i in project.get(lst, []) if i != asset["id"]]
    r = root(project)
    if kind in ("skills", "rules", "roles", "mcp_servers"):
        for uni in (False, True):
            if kind != "skills" and uni:
                continue
            d = dest(project, kind, asset, uni)
            if d.exists():
                files.remove_path(d)
                files.prune_empty(d.parent, r)
    if kind in ("rules", "roles"):
        rebuild_block(project, data)
    elif kind == "mcp_configs":
        rebuild_mcp(project, data)
    _reconcile_universal(project, data)


def loadout_items(data: dict, loadout: dict) -> list[tuple[str, dict]]:
    """Every asset a loadout resolves to (agent presets expanded), without duplicates."""
    out, seen = [], set()

    def add(kind, id_):
        a = store.find(data, kind, id_)
        if a and (kind, id_) not in seen:
            seen.add((kind, id_))
            out.append((kind, a))

    for kind in ATTACHABLE:
        for i in loadout.get(kind, []):
            add(kind, i)
    for aid in loadout.get("agents", []):
        agent = store.find(data, "agents", aid)
        for kind in ("rules", "roles", "skills"):
            for i in (agent or {}).get(kind, []):
                add(kind, i)
    return out


def attach_loadout(project: dict, data: dict, loadout: dict) -> tuple[int, int]:
    """Attach everything in a loadout. Returns (newly attached, already attached)."""
    new = already = 0
    for kind, a in loadout_items(data, loadout):
        if a["id"] in project.get(store.PROJECT_LISTS[kind], []):
            already += 1
        else:
            new += 1
        attach(project, data, kind, a)
    return new, already


def resync(project: dict, data: dict) -> int:
    n = 0
    for kind, a in attached(project, data):
        _apply(project, data, kind, a)
        n += 1
    return n


def clear(project: dict, data: dict) -> None:
    for kind, a in attached(project, data):
        detach(project, data, kind, a)


def delete_asset_everywhere(data: dict, kind: str, id_: str) -> None:
    """Detach from every project that uses it, then delete from Loadout."""
    a = store.find(data, kind, id_)
    if a:
        for p in data["projects"]:
            if id_ in p.get(store.PROJECT_LISTS[kind], []) and path_exists(p):
                detach(p, data, kind, a)
    store.delete_asset(data, kind, id_)


# ---- status, diff & dry-run -------------------------------------------------
def _pairs(src: Path, dst: Path) -> list[tuple[str, Path, Path]]:
    """(relative name, source file, destination file) for a file or folder unit."""
    if not src.is_dir():
        return [(dst.name, src, dst)]
    out = []
    for f in sorted(src.rglob("*")):
        rel = f.relative_to(src)
        if f.is_file() and not set(rel.parts) & set(files.IGNORED_NAMES):
            out.append((rel.as_posix(), f, dst / rel))
    return out


def _same(a: Path, b: Path) -> bool:
    return b.is_file() and a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()


def _targets(project: dict, kind: str, asset: dict) -> list[tuple[Path, Path]]:
    src = files.unit_path(kind, asset["path"])
    out = [(src, dest(project, kind, asset))]
    if kind == "skills" and has_mcp(project):
        out.append((src, dest(project, kind, asset, universal=True)))
    return out


def _merged_mcp(project: dict, data: dict) -> dict:
    merged: dict = {}
    for _, a in attached(project, data, "mcp_configs"):
        try:
            merged.update(_servers_of(files.resolve(a["path"])))
        except (OSError, ValueError):
            pass
    return merged


def item_status(project: dict, data: dict, kind: str, asset: dict) -> str:
    """'ok' | 'outdated' (copy differs from Loadout) | 'missing' (copy not in the project)."""
    try:
        if kind == "mcp_configs":
            cfg = root(project) / frameworks.MCP_CONFIG
            if not cfg.is_file():
                return "missing"
            have, merged = _servers_of(cfg), _merged_mcp(project, data)
            want = _servers_of(files.resolve(asset["path"]))
            if want and not any(k in have for k in want):
                return "missing"
            return "ok" if all(have.get(k) == merged.get(k) for k in want) else "outdated"
        miss = differ = total = 0
        for src, dst in _targets(project, kind, asset):
            for _, s, d in _pairs(src, dst):
                total += 1
                if not d.is_file():
                    miss += 1
                elif not _same(s, d):
                    differ += 1
        if total and miss == total:
            return "missing"
        return "outdated" if miss or differ else "ok"
    except (OSError, ValueError):
        return "missing"


def project_health(project: dict, data: dict) -> dict:
    """Counts per kind plus the attached assets whose project copy is stale or absent."""
    counts = {k: len(attached(project, data, k)) for k in ATTACHABLE}
    stale = []
    if path_exists(project):
        for kind, a in attached(project, data):
            st_ = item_status(project, data, kind, a)
            if st_ != "ok":
                stale.append((kind, a, st_))
    return {"counts": counts, "total": sum(counts.values()), "stale": stale, "path_ok": path_exists(project)}


def resync_stale(project: dict, data: dict) -> int:
    n = 0
    for kind, a, _ in project_health(project, data)["stale"]:
        _apply(project, data, kind, a)
        n += 1
    return n


def resync_item(project: dict, data: dict, kind: str, asset: dict) -> None:
    _apply(project, data, kind, asset)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def _udiff(old: str, new: str, name: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        f"project/{name}", f"loadout/{name}"))


def diff_item(project: dict, data: dict, kind: str, asset: dict) -> list[dict]:
    """Per-file differences between Loadout (source of truth) and the project copy."""
    out = []
    if kind == "mcp_configs":
        cfg = root(project) / frameworks.MCP_CONFIG
        want = _servers_of(files.resolve(asset["path"]))
        have = _servers_of(cfg) if cfg.is_file() else {}
        merged = _merged_mcp(project, data)
        a = json.dumps({k: have[k] for k in want if k in have}, indent=2)
        b = json.dumps({k: merged[k] for k in want if k in merged}, indent=2)
        if a != b:
            out.append({"file": frameworks.MCP_CONFIG, "state": "changed" if have else "new",
                        "diff": _udiff(a if have else "", b, frameworks.MCP_CONFIG)})
        return out
    for src, dst in _targets(project, kind, asset):
        for rel, s, d in _pairs(src, dst):
            if _same(s, d):
                continue
            shown = _rel_posix(d, root(project))
            try:
                diff = _udiff(_read(d), s.read_text(encoding="utf-8"), rel)
            except UnicodeDecodeError:
                diff = "(binary file)"
            out.append({"file": shown, "state": "changed" if d.is_file() else "new", "diff": diff})
    return out


def plan_attach(project: dict, data: dict, kind: str, asset: dict) -> list[tuple[str, str]]:
    """Dry-run: what attaching (or re-syncing) this asset would write. Nothing touches disk."""
    plan = [("create" if d["state"] == "new" else "update", d["file"]) for d in diff_item(project, data, kind, asset)]
    if kind in ("rules", "roles"):
        plan.append(("update", _fw(project)["root_file"] + " (managed block)"))
    elif kind == "mcp_configs" and not plan:
        plan.append(("create", frameworks.MCP_CONFIG))
    return plan


def plan_detach(project: dict, kind: str, asset: dict) -> list[tuple[str, str]]:
    plan = []
    for uni in (False, True):
        if uni and kind != "skills":
            continue
        d = dest(project, kind, asset, uni) if kind != "mcp_configs" else None
        if d is not None and d.exists():
            plan.append(("delete", _rel_posix(d, root(project)) + ("/" if d.is_dir() else "")))
    if kind in ("rules", "roles"):
        plan.append(("update", _fw(project)["root_file"] + " (managed block)"))
    elif kind == "mcp_configs":
        plan.append(("update", frameworks.MCP_CONFIG))
    return plan


# ---- dependency map & context size -------------------------------------------
def used_by(data: dict, kind: str, id_: str) -> dict[str, list]:
    """Everything that references an asset: projects, agent presets, loadouts (direct or via a preset)."""
    projects = [p for p in data["projects"] if id_ in p.get(store.PROJECT_LISTS[kind], [])]
    agents = [a for a in data["agents"] if id_ in a.get(kind, [])] if kind in ("rules", "roles", "skills") else []
    agent_ids = {a["id"] for a in agents}
    loadouts = []
    for lo in data["loadouts"]:
        if id_ in lo.get(kind, []):
            loadouts.append((lo, None))
        else:
            via = next((a for a in agents if a["id"] in lo.get("agents", [])), None)
            if via:
                loadouts.append((lo, via))
    return {"projects": projects, "agents": agents, "loadouts": loadouts, "agent_ids": agent_ids}


def used_by_count(refs: dict) -> int:
    return len(refs["projects"]) + len(refs["agents"]) + len(refs["loadouts"])


def agent_used_by(data: dict, agent_id: str) -> list[dict]:
    return [lo for lo in data["loadouts"] if agent_id in lo.get("agents", [])]


CONTEXT_KINDS = ("skills", "rules", "roles")


def project_tokens(project: dict, data: dict) -> dict:
    """Estimated context cost of the text assets attached to a project (skills count their entry file)."""
    items = []
    for kind, a in attached(project, data):
        if kind not in CONTEXT_KINDS:
            continue
        try:
            chars = len(files.read_text(a["path"]))
        except (OSError, ValueError):
            chars = 0
        items.append({"kind": kind, "asset": a, "chars": chars, "tokens": tokens.estimate(chars)})
    items.sort(key=lambda i: -i["tokens"])
    rt = root_info(project)
    return {"items": items, "root": rt, "tokens": sum(i["tokens"] for i in items) + rt["tokens"],
            "chars": sum(i["chars"] for i in items) + rt["chars"]}


# ---- project instructions file (CLAUDE.md, AGENTS.md, …) --------------------------
def root_path(project: dict) -> Path:
    return root(project) / _fw(project)["root_file"]


def ensure_root_file(project: dict) -> bool:
    """Create the framework's instructions file (empty) if the project does not have one. True if created."""
    rf = root_path(project)
    if not path_exists(project) or rf.exists():
        return False
    files.write_file(rf, "")
    return True


def own_text(project: dict) -> str:
    """What the user (not Loadout's managed block) put in the instructions file."""
    rf = root_path(project)
    if not rf.is_file():
        return ""
    return _BLOCK_RE.sub("", rf.read_text(encoding="utf-8", errors="replace")).strip()


def root_info(project: dict) -> dict:
    own = own_text(project)
    return {"name": _fw(project)["root_file"], "path": root_path(project), "text": own, "empty": not own,
            "chars": len(own), "tokens": tokens.estimate(len(own)) if own else 0}


def seed_root_from_skill(project: dict, data: dict, skill: dict) -> None:
    """Copy a skill's instructions (without its front-matter) into an EMPTY instructions file; never overwrites."""
    if not path_exists(project):
        raise ValueError("The project folder does not exist.")
    if own_text(project):
        raise ValueError(f"{_fw(project)['root_file']} already has content; it can only be seeded while empty.")
    raw = files.read_text(skill["path"])
    meta, body, err = lint.parse_frontmatter(raw)
    text = (body if meta is not None and not err else raw).strip()
    if not text:
        raise ValueError("That skill has no content to copy.")
    rf = root_path(project)
    rest = rf.read_text(encoding="utf-8", errors="replace").strip() if rf.is_file() else ""
    files.write_file(rf, text + "\n" + (f"\n{rest}\n" if rest else ""))


# ---- usage stats -------------------------------------------------------------
def usage_counts(data: dict) -> dict[tuple[str, str], int]:
    """How many projects each attachable asset is attached to."""
    use = {(k, a["id"]): 0 for k in ATTACHABLE for a in data[k]}
    for p in data["projects"]:
        for kind in ATTACHABLE:
            for i in p.get(store.PROJECT_LISTS[kind], []):
                if (kind, i) in use:
                    use[(kind, i)] += 1
    return use


# ---- discovery ------------------------------------------------------------
def _sha(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8", "replace")).hexdigest()


def _known_hashes(data: dict) -> set[str]:
    out = set()
    for k in ("skills", "roles", "rules"):
        for a in data[k]:
            try:
                out.add(_sha(files.read_text(a["path"])))
            except OSError:
                pass
    return out


def _main_text(p: Path) -> str | None:
    if p.is_dir():
        for n in ("SKILL.md",):
            if (p / n).is_file():
                return (p / n).read_text(encoding="utf-8", errors="replace")
        mds = sorted(p.glob("*.md"))
        return mds[0].read_text(encoding="utf-8", errors="replace") if mds else None
    if p.suffix.lower() == ".md":
        return p.read_text(encoding="utf-8", errors="replace")
    return None


def discover(project: dict, data: dict) -> list[dict]:
    """Find skills/rules/roles in the project that Loadout doesn't know yet."""
    r = root(project)
    known = _known_hashes(data)
    synced = set()
    for kind, a in attached(project, data):
        if kind in ("skills", "rules", "roles"):
            synced.add(dest(project, kind, a))
            if kind == "skills":
                synced.add(dest(project, kind, a, True))
    found, seen = [], set()
    scan = [("skills", r / _fw(project)["skills_dir"]), ("skills", r / frameworks.AGENTS_DIR / "skills"),
            ("rules", r / frameworks.AGENTS_DIR / "rules"), ("roles", r / frameworks.AGENTS_DIR / "roles")]
    for kind, d in scan:
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p in synced or p.name.startswith(".") or (kind != "skills" and p.is_dir()):
                continue
            text = _main_text(p)
            if text is None or _sha(text) in known or (kind, p.name) in seen:
                continue
            seen.add((kind, p.name))
            found.append({"kind": kind, "name": p.stem if p.is_file() else p.name, "path": p,
                          "is_dir": p.is_dir(), "chars": len(text)})
    return found


def import_candidate(data: dict, c: dict, name: str, description: str, tags: list[str]) -> dict:
    if c.get("text") is not None:
        return store.add_asset(data, c["kind"], name, description, tags, c["text"])
    return store.import_from_path(data, c["kind"], c["path"], name, description, tags)
