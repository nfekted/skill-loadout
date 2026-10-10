"""Physical asset storage: safe names, lazy folder creation, copy/delete helpers."""
import hashlib
import re
import shutil
from pathlib import Path

from . import config

# folder=True kinds store each asset in its own directory (path points to the main file).
KINDS = {
    "skills": {"dir": "skills", "folder": True, "ext": ".md", "main": "SKILL.md", "label": "Skill"},
    "roles": {"dir": "roles", "folder": False, "ext": ".md", "label": "Role"},
    "rules": {"dir": "rules", "folder": False, "ext": ".md", "label": "Rule"},
    "mcp_configs": {"dir": "mcp_configs", "folder": False, "ext": ".json", "label": "MCP Config"},
    "mcp_servers": {"dir": "mcp_servers", "folder": True, "ext": ".py", "label": "MCP Server"},
}
IGNORED_NAMES = (".git", "__pycache__", "node_modules", ".DS_Store")
IGNORED = shutil.ignore_patterns(*IGNORED_NAMES)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "untitled"


def safe_filename(name: str, default: str) -> str:
    name = Path(name or "").name.strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).lstrip(".")
    return name or default


def resolve(rel: str) -> Path:
    """Resolve a storage-relative path, refusing anything outside Loadout home."""
    base = config.home()
    p = (base / rel).resolve()
    if p != base and base not in p.parents:
        raise ValueError(f"Path escapes Loadout storage: {rel}")
    return p


def _rel(p: Path) -> str:
    return p.relative_to(config.home()).as_posix()


def unit_path(kind: str, rel: str) -> Path:
    """The file (or folder, for folder kinds) that physically holds an asset."""
    p = resolve(rel)
    return p.parent if KINDS[kind]["folder"] else p


def _unique_slug(kind: str, slug: str) -> str:
    k = KINDS[kind]
    base = config.home() / k["dir"]
    cand, i = slug, 2
    while (base / (cand if k["folder"] else cand + k["ext"])).exists():
        cand, i = f"{slug}_{i}", i + 1
    return cand


def ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def write_file(p: Path, content) -> None:
    ensure_parent(p)
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")


def store_new(kind: str, name: str, content, filename: str | None = None) -> str:
    """Persist a new asset's main file; returns its storage-relative path."""
    k = KINDS[kind]
    slug = _unique_slug(kind, slugify(name))
    base = config.home() / k["dir"]
    if k["folder"]:
        main = k.get("main") or safe_filename(filename, slug + k["ext"])
        target = base / slug / main
    else:
        target = base / (slug + k["ext"])
    write_file(target, content)
    return _rel(target)


def store_folder(kind: str, name: str, src: Path) -> tuple[str, bool]:
    """Copy a directory in as a folder asset. Returns (main file rel path, is_modular)."""
    k = KINDS[kind]
    slug = _unique_slug(kind, slugify(name))
    dest = config.home() / k["dir"] / slug
    ensure_parent(dest)
    shutil.copytree(src, dest, ignore=IGNORED)
    main = k.get("main")
    if main and not (dest / main).is_file():
        mds = sorted(dest.glob("*.md"))
        if not mds:
            shutil.rmtree(dest)
            raise ValueError("Folder has no markdown file to use as SKILL.md")
        main = mds[0].name
    elif not main:
        files = sorted(f for f in dest.iterdir() if f.is_file())
        if not files:
            shutil.rmtree(dest)
            raise ValueError("Folder is empty")
        main = files[0].name
    modular = sum(1 for f in dest.rglob("*") if f.is_file()) > 1
    return _rel(dest / main), modular


def unit_hash(kind: str, rel: str) -> str:
    """Content hash of an asset's file or folder (used to detect local edits)."""
    unit = unit_path(kind, rel)
    h = hashlib.sha256()
    if unit.is_dir():
        for f in sorted(unit.rglob("*")):
            r = f.relative_to(unit)
            if f.is_file() and not set(r.parts) & set(IGNORED_NAMES):
                h.update(r.as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
    elif unit.is_file():
        h.update(unit.read_bytes())
    return h.hexdigest()


def replace_unit(kind: str, rel: str, src: Path) -> tuple[str, bool]:
    """Overwrite an existing asset's files in place from `src`. Returns (main file rel path, is_modular).

    Folder assets are staged next to the old one and swapped only once the new copy is valid."""
    k = KINDS[kind]
    unit, main_name = unit_path(kind, rel), Path(rel).name
    if not k["folder"]:
        if src.is_dir():
            parts = [p.read_text(encoding="utf-8", errors="replace") for p in sorted(src.rglob("*.md"))]
            if not parts:
                raise ValueError("Upstream folder has no markdown files")
            write_file(unit, "\n\n---\n\n".join(parts))
        else:
            write_file(unit, src.read_bytes())
        return rel, False
    stage = unit.with_name(unit.name + ".new")
    shutil.rmtree(stage, ignore_errors=True)
    try:
        if src.is_dir():
            shutil.copytree(src, stage, ignore=IGNORED)
            main = k.get("main")
            if main and not (stage / main).is_file():
                mds = sorted(stage.glob("*.md"))
                if not mds:
                    raise ValueError("Upstream folder has no markdown file to use as SKILL.md")
                main = mds[0].name
            elif not main:
                names = sorted(f.name for f in stage.iterdir() if f.is_file())
                if not names:
                    raise ValueError("Upstream folder is empty")
                main = main_name if main_name in names else names[0]
        else:
            main = k.get("main") or main_name
            write_file(stage / main, src.read_bytes())
        modular = sum(1 for f in stage.rglob("*") if f.is_file()) > 1
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    shutil.rmtree(unit, ignore_errors=True)
    stage.rename(unit)
    return _rel(unit / main), modular


# ---- files inside a folder asset (modular skills) ----------------------------------
def unit_files(kind: str, rel: str) -> list[str]:
    """Every file of a folder asset as posix paths relative to its folder, main file first."""
    unit = unit_path(kind, rel)
    if not unit.is_dir():
        return [Path(rel).name]
    main = Path(rel).name
    out = sorted(f.relative_to(unit).as_posix() for f in unit.rglob("*")
                 if f.is_file() and not set(f.relative_to(unit).parts) & set(IGNORED_NAMES))
    return sorted(out, key=lambda n: (n != main, n))


def member_path(kind: str, rel: str, member: str) -> Path:
    """A file inside a folder asset; refuses absolute paths, `..` and anything outside the folder."""
    unit = unit_path(kind, rel)
    parts = [p for p in member.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or ".." in parts or set(parts) & set(IGNORED_NAMES) or member.startswith("/"):
        raise ValueError(f"Invalid file path: {member!r}")
    p = (unit / Path(*parts)).resolve()
    if unit.resolve() not in p.parents:
        raise ValueError(f"Invalid file path: {member!r}")
    return p


def member_path_in(folder: Path, member: str) -> Path:
    """Like member_path, for a plain directory that is not yet a stored asset."""
    parts = [p for p in member.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or ".." in parts or member.startswith("/"):
        raise ValueError(f"Invalid file path: {member!r}")
    p = (folder / Path(*parts)).resolve()
    if folder.resolve() not in p.parents:
        raise ValueError(f"Invalid file path: {member!r}")
    return p


def delete_member(kind: str, rel: str, member: str) -> None:
    p = member_path(kind, rel, member)
    if p == resolve(rel):
        raise ValueError("The main file cannot be deleted.")
    if p.is_file():
        p.unlink()
        prune_empty(p.parent, unit_path(kind, rel))


def zip_unit(kind: str, rel: str) -> bytes:
    """The asset as a zip (folder assets keep their structure under a top-level folder)."""
    import io
    import zipfile
    unit = unit_path(kind, rel)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if unit.is_dir():
            for n in unit_files(kind, rel):
                z.write(unit / n, f"{unit.name}/{n}")
        else:
            z.write(unit, unit.name)
    return buf.getvalue()


def read_text(rel: str) -> str:
    return resolve(rel).read_text(encoding="utf-8", errors="replace")


def delete_asset_files(kind: str, rel: str) -> None:
    unit = unit_path(kind, rel)
    base = config.home() / KINDS[kind]["dir"]
    if unit == base or base not in unit.parents:
        raise ValueError("Refusing to delete outside asset directory")
    if unit.is_dir():
        shutil.rmtree(unit, ignore_errors=True)
    elif unit.exists():
        unit.unlink()
    prune_empty(base, config.home())


def copy_into(src: Path, dst: Path) -> None:
    """Copy file or directory to dst, creating parents lazily."""
    ensure_parent(dst)
    if src.is_dir():
        shutil.copytree(src, dst, ignore=IGNORED, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)


def remove_path(p: Path) -> None:
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p, ignore_errors=True)


def prune_empty(start: Path, stop: Path) -> None:
    """Remove `start` and empty parents up to (not including) `stop`."""
    p = start
    while p != stop and stop in p.parents and p.is_dir() and not any(p.iterdir()):
        p.rmdir()
        p = p.parent
