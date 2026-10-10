"""data.json persistence and entity CRUD (metadata only; bytes live in files.py)."""
import json
import os
import time
import uuid
from pathlib import Path

from . import config, files


class DataError(Exception):
    pass


ASSET_KINDS = list(files.KINDS)
LOADOUT_KINDS = ["skills", "rules", "roles", "mcp_configs", "mcp_servers", "agents"]
PROJECT_LISTS = {"skills": "attached_skills", "rules": "attached_rules", "roles": "attached_roles",
                 "mcp_configs": "attached_mcp", "mcp_servers": "attached_mcp"}


def empty() -> dict:
    return {k: [] for k in config.ENTITY_KEYS}


def load() -> dict:
    f = config.data_file()
    if not f.exists():
        return empty()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("root must be an object")
    except (json.JSONDecodeError, ValueError) as e:
        raise DataError(f"data.json is corrupted ({e}). Fix or remove it: {f}") from e
    return normalize(data)


def normalize(data: dict) -> dict:
    for k in config.ENTITY_KEYS:
        if not isinstance(data.get(k), list):
            data[k] = []
    for p in data["projects"]:
        for lst in set(PROJECT_LISTS.values()):
            p.setdefault(lst, [])
        p.setdefault("target_model", "Claude")
        p.setdefault("favorite", False)
        p.setdefault("last_opened", 0)
    for lo in data["loadouts"]:
        for k in LOADOUT_KINDS:
            lo.setdefault(k, [])
        lo.setdefault("tags", [])
    return data


def save(data: dict) -> None:
    f = config.data_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)


def new_id() -> str:
    return str(uuid.uuid4())


def find(data: dict, key: str, id_: str) -> dict | None:
    return next((e for e in data[key] if e["id"] == id_), None)


# ---- tags ---------------------------------------------------------------
def tag_color(data: dict, name: str) -> str:
    t = next((t for t in data["tags"] if t["name"] == name), None)
    return t["color"] if t else "#6B7280"


def ensure_tags(data: dict, names: list[str]) -> list[str]:
    clean = []
    for n in names:
        n = n.strip().lower()
        if n and n not in clean:
            clean.append(n)
    existing = {t["name"] for t in data["tags"]}
    for n in clean:
        if n not in existing:
            color = config.DEFAULT_TAG_COLORS[len(data["tags"]) % len(config.DEFAULT_TAG_COLORS)]
            data["tags"].append({"name": n, "color": color})
            existing.add(n)
    return clean


def _tagged_lists(data: dict):
    for k in ASSET_KINDS + ["utilities", "loadouts"]:
        yield from data[k]


def rename_tag(data: dict, old: str, new: str) -> None:
    new = new.strip().lower()
    if not new or new == old:
        return
    if any(t["name"] == new for t in data["tags"]):
        raise ValueError(f"Tag '{new}' already exists")
    for t in data["tags"]:
        if t["name"] == old:
            t["name"] = new
    for e in _tagged_lists(data):
        e["tags"] = [new if x == old else x for x in e.get("tags", [])]


def delete_tag(data: dict, name: str) -> None:
    data["tags"] = [t for t in data["tags"] if t["name"] != name]
    for e in _tagged_lists(data):
        e["tags"] = [x for x in e.get("tags", []) if x != name]


def tag_usage(data: dict) -> dict[str, int]:
    use = {t["name"]: 0 for t in data["tags"]}
    for e in _tagged_lists(data):
        for t in e.get("tags", []):
            use[t] = use.get(t, 0) + 1
    return use


# ---- assets -------------------------------------------------------------
def _entry(kind, name, description, tags, path, data):
    e = {"id": new_id(), "name": name.strip(), "description": description.strip(),
         "tags": ensure_tags(data, tags), "path": path}
    if kind == "skills":
        e["is_modular"] = False
    return e


def add_asset(data: dict, kind: str, name: str, description: str, tags: list[str],
              content, filename: str | None = None) -> dict:
    if not name.strip():
        raise ValueError("Name is required")
    path = files.store_new(kind, name, content, filename)
    e = _entry(kind, name, description, tags, path, data)
    data[kind].append(e)
    save(data)
    return e


def import_from_path(data: dict, kind: str, src: Path, name: str, description: str,
                     tags: list[str], source: dict | None = None) -> dict:
    """Copy a file/folder from disk into Loadout storage and register it.

    `source` records where it came from (Git origin) so updates can be checked later."""
    if not name.strip():
        raise ValueError("Name is required")
    is_modular = False
    if files.KINDS[kind]["folder"]:
        if src.is_dir():
            path, is_modular = files.store_folder(kind, name, src)
        else:
            path = files.store_new(kind, name, src.read_bytes(), src.name)
    else:
        if src.is_dir():  # rules/roles from a folder: join its markdown files
            parts = [p.read_text(encoding="utf-8", errors="replace") for p in sorted(src.rglob("*.md"))]
            if not parts:
                raise ValueError("Folder has no markdown files")
            content = "\n\n---\n\n".join(parts)
        else:
            content = src.read_bytes()
        path = files.store_new(kind, name, content)
    e = _entry(kind, name, description, tags, path, data)
    if kind == "skills":
        e["is_modular"] = is_modular
    if source:
        e["source"] = {**source, "hash": files.unit_hash(kind, path)}
    data[kind].append(e)
    save(data)
    return e


def replace_asset(data: dict, kind: str, id_: str, src: Path) -> dict:
    """Overwrite an asset's files in place from `src`, keeping its id, name and attachments."""
    e = find(data, kind, id_)
    if not e:
        raise KeyError(id_)
    e["path"], modular = files.replace_unit(kind, e["path"], src)
    if kind == "skills":
        e["is_modular"] = modular
    save(data)
    return e


def update_asset(data: dict, kind: str, id_: str, name: str, description: str,
                 tags: list[str], content=None) -> None:
    e = find(data, kind, id_)
    if not e:
        raise KeyError(id_)
    if not name.strip():
        raise ValueError("Name is required")
    if content is not None:
        files.write_file(files.resolve(e["path"]), content)
    e.update(name=name.strip(), description=description.strip(), tags=ensure_tags(data, tags))
    save(data)


def sync_modular(data: dict, kind: str, id_: str) -> bool:
    """Recompute `is_modular` from disk after files were added to / removed from a folder asset."""
    e = find(data, kind, id_)
    e["is_modular"] = len(files.unit_files(kind, e["path"])) > 1
    save(data)
    return e["is_modular"]


def write_member(data: dict, kind: str, id_: str, member: str, content: str) -> None:
    """Create or overwrite a file inside a folder asset (e.g. `references/hooks.md` in a skill)."""
    e = find(data, kind, id_)
    files.write_file(files.member_path(kind, e["path"], member), content)
    sync_modular(data, kind, id_)


def delete_member(data: dict, kind: str, id_: str, member: str) -> None:
    e = find(data, kind, id_)
    files.delete_member(kind, e["path"], member)
    sync_modular(data, kind, id_)


def delete_asset(data: dict, kind: str, id_: str) -> None:
    e = find(data, kind, id_)
    if not e:
        return
    files.delete_asset_files(kind, e["path"])
    data[kind] = [x for x in data[kind] if x["id"] != id_]
    agent_key = {"mcp_configs": None, "mcp_servers": None}.get(kind, kind)
    if agent_key:
        for a in data["agents"]:
            a[agent_key] = [i for i in a.get(agent_key, []) if i != id_]
    for lo in data["loadouts"]:
        lo[kind] = [i for i in lo.get(kind, []) if i != id_]
    lst = PROJECT_LISTS[kind]
    for p in data["projects"]:
        p[lst] = [i for i in p.get(lst, []) if i != id_]
    save(data)


# ---- generic entities (agents, utilities, projects) -----------------------
def add_entity(data: dict, key: str, entry: dict) -> dict:
    entry = {"id": new_id(), **entry}
    if "tags" in entry:
        entry["tags"] = ensure_tags(data, entry["tags"])
    data[key].append(entry)
    save(data)
    return entry


def update_entity(data: dict, key: str, id_: str, **fields) -> None:
    e = find(data, key, id_)
    if not e:
        raise KeyError(id_)
    if "tags" in fields:
        fields["tags"] = ensure_tags(data, fields["tags"])
    e.update(fields)
    save(data)


def delete_entity(data: dict, key: str, id_: str) -> None:
    data[key] = [e for e in data[key] if e["id"] != id_]
    if key == "agents":
        for lo in data["loadouts"]:
            lo["agents"] = [i for i in lo.get("agents", []) if i != id_]
    save(data)


# ---- search -------------------------------------------------------------
def matches(entry: dict, query: str = "", tags: list[str] | None = None) -> bool:
    if tags and not set(tags) <= set(entry.get("tags", [])):
        return False
    q = query.strip().lower()
    if not q:
        return True
    hay = " ".join([entry.get("name", ""), entry.get("description", ""), *entry.get("tags", [])]).lower()
    return all(w in hay for w in q.split())


def search(data: dict, query: str = "", tags: list[str] | None = None) -> dict[str, list[dict]]:
    out = {}
    for k in ASSET_KINDS + ["agents", "loadouts", "utilities", "projects"]:
        hits = [e for e in data[k] if matches(e, query, tags)]
        if hits:
            out[k] = hits
    return out


def backup_stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")
