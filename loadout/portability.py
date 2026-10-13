"""Backup export/import (zip) and Git clone → selective import."""
import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from . import config, files, store

MAX_UNZIPPED = 500 * 1024 * 1024
ASSET_DIRS = [k["dir"] for k in files.KINDS.values()]
TREE_SKIP = {".git", "node_modules", "__pycache__", ".venv", ".DS_Store"}


# ---- zip export / import -------------------------------------------------------
def export_zip() -> bytes:
    home = config.home()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data.json", json.dumps(store.load(), indent=2, ensure_ascii=False))
        for d in ASSET_DIRS:
            for f in sorted((home / d).rglob("*")) if (home / d).is_dir() else []:
                if f.is_file() and not f.is_symlink():
                    z.write(f, f.relative_to(home).as_posix())
    return buf.getvalue()


def _safe_name(name: str) -> bool:
    p = PurePosixPath(name)
    return (not p.is_absolute() and ".." not in p.parts and "\\" not in name
            and (name == "data.json" or (p.parts and p.parts[0] in ASSET_DIRS)))


def _read_package(blob: bytes) -> tuple[dict, dict[str, bytes]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as e:
        raise ValueError("Not a valid zip archive") from e
    infos = [i for i in z.infolist() if not i.is_dir()]
    if sum(i.file_size for i in infos) > MAX_UNZIPPED:
        raise ValueError("Archive is too large")
    members = {}
    for i in infos:
        if not _safe_name(i.filename):
            raise ValueError(f"Unsafe or unexpected path in archive: {i.filename}")
        members[i.filename] = z.read(i)
    if "data.json" not in members:
        raise ValueError("Archive has no data.json")
    try:
        data = store.normalize(json.loads(members.pop("data.json")))
    except json.JSONDecodeError as e:
        raise ValueError(f"data.json in archive is invalid: {e}") from e
    return data, members


def _unique_unit(kind: str, unit: str) -> str:
    """Return a storage-relative unit path that doesn't exist yet."""
    k = files.KINDS[kind]
    base, name = PurePosixPath(unit).parent, PurePosixPath(unit)
    stem, ext = (name.name, "") if k["folder"] else (name.stem, name.suffix)
    cand, i = unit, 2
    while (config.home() / cand).exists():
        cand, i = (base / f"{stem}_{i}{ext}").as_posix(), i + 1
    return cand


def import_zip(blob: bytes, mode: str = "merge", overwrite: bool = False) -> dict:
    """mode: 'merge' (add new, optionally overwrite same id) or 'replace' (backup, then replace all)."""
    incoming, members = _read_package(blob)
    home = config.home()
    stats = {"added": 0, "updated": 0, "skipped": 0}
    if mode == "replace":
        backup = home / ".backups" / store.backup_stamp()
        for rel in ["data.json", *ASSET_DIRS]:
            if (home / rel).exists():
                files.copy_into(home / rel, backup / rel)
        for d in ASSET_DIRS:
            shutil.rmtree(home / d, ignore_errors=True)
        for name, content in members.items():
            files.write_file(files.resolve(name), content)
        stats["added"] = sum(len(incoming[k]) for k in config.ENTITY_KEYS)
        store.save(incoming)
        return stats
    data = store.load()
    for kind in files.KINDS:
        folder = files.KINDS[kind]["folder"]
        for entry in incoming[kind]:
            cur = store.find(data, kind, entry["id"])
            if cur and not overwrite:
                stats["skipped"] += 1
                continue
            unit = str(PurePosixPath(entry["path"]).parent) if folder else entry["path"]
            names = [n for n in members if n == unit or n.startswith(unit + "/")]
            if not names:
                stats["skipped"] += 1
                continue
            new_unit = unit
            if cur:
                files.delete_asset_files(kind, cur["path"])
            elif (home / unit).exists():
                new_unit = _unique_unit(kind, unit)
            for n in names:
                files.write_file(files.resolve(new_unit + n[len(unit):]), members[n])
            entry = {**entry, "path": new_unit + entry["path"][len(unit):]}
            if cur:
                data[kind][data[kind].index(cur)] = entry
                stats["updated"] += 1
            else:
                data[kind].append(entry)
                stats["added"] += 1
    for key in ("agents", "loadouts", "utilities", "projects"):
        for entry in incoming[key]:
            cur = store.find(data, key, entry["id"])
            if cur and not overwrite:
                stats["skipped"] += 1
            elif cur:
                data[key][data[key].index(cur)] = entry
                stats["updated"] += 1
            else:
                data[key].append(entry)
                stats["added"] += 1
    have = {t["name"] for t in data["tags"]}
    data["tags"] += [t for t in incoming["tags"] if t["name"] not in have]
    store.save(data)
    return stats


# ---- git clone → temp dir ------------------------------------------------------
ALLOWED_URL = ("https://", "http://", "ssh://", "git@", "file://")


def _tmp_root() -> Path:
    return Path(tempfile.gettempdir()).resolve()


def _check_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(ALLOWED_URL):
        raise ValueError("Unsupported URL. Use https://, ssh://, git@host:path or file://")
    return url


def _check_ref(ref: str | None) -> str | None:
    ref = (ref or "").strip() or None
    if ref and (ref.startswith("-") or any(c.isspace() for c in ref)):
        raise ValueError("Invalid branch or tag name.")
    return ref


def _git(args: list[str], timeout: int = 180, cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=timeout, cwd=cwd,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("git timed out") from e
    except FileNotFoundError as e:
        raise RuntimeError("git is not installed") from e


def _err(r: subprocess.CompletedProcess, default: str) -> str:
    return r.stderr.strip().splitlines()[-1] if r.stderr.strip() else default


def clone(url: str, timeout: int = 180, ref: str | None = None, light: bool = False) -> Path:
    """Shallow-clone into a fresh temp dir; returns the repo directory (temp dir is its parent).

    `light` skips file contents and the checkout (trees only); use checkout_paths() to fetch what you need."""
    url, ref = _check_url(url), _check_ref(ref)
    tmp = Path(tempfile.mkdtemp(prefix="loadout-git-", dir=_tmp_root()))
    try:
        args = ["clone", "--depth", "1"]
        if light:
            args += ["--filter=blob:none", "--no-checkout"]
        if ref:
            args += ["--branch", ref]
        r = _git([*args, "--", url, str(tmp / "repo")], timeout)
        if r.returncode != 0:
            raise RuntimeError(_err(r, "git clone failed"))
    except BaseException:
        wipe(tmp)
        raise
    return tmp / "repo"


def ls_remote(url: str, ref: str | None = None, timeout: int = 60) -> str:
    """Latest commit of a branch (or the default branch) without downloading anything."""
    url, ref = _check_url(url), _check_ref(ref)
    r = _git(["ls-remote", url, f"refs/heads/{ref}" if ref else "HEAD"], timeout)
    if r.returncode != 0:
        raise RuntimeError(_err(r, "git ls-remote failed"))
    line = next((ln for ln in r.stdout.splitlines() if ln.strip()), "")
    if not line:
        raise RuntimeError(f"Branch '{ref}' not found in the repository." if ref else "Repository has no commits.")
    return line.split()[0]


def head_commit(repo: Path) -> str:
    r = _git(["rev-parse", "HEAD"], cwd=repo)
    if r.returncode != 0:
        raise RuntimeError(_err(r, "git rev-parse failed"))
    return r.stdout.strip()


def is_detached(repo: Path) -> bool:
    """True when the clone sits on a tag or commit rather than a branch (such sources are 'pinned')."""
    return _git(["symbolic-ref", "-q", "HEAD"], cwd=repo).returncode != 0


def rev_parse(repo: Path, path: str) -> str | None:
    """Git object id of `path` at HEAD (changes iff the content under it changes), or None if absent."""
    r = _git(["rev-parse", "--verify", "-q", f"HEAD:{path}"], cwd=repo)
    return r.stdout.strip() if r.returncode == 0 else None


def checkout_paths(repo: Path, paths: list[str]) -> None:
    """Materialize just these paths in a light clone (fetches only the needed blobs)."""
    r = _git(["checkout", "HEAD", "--", *paths], cwd=repo)
    if r.returncode != 0:
        raise RuntimeError(_err(r, "git checkout failed"))


def wipe(path: Path | str | None) -> None:
    """Delete a clone's temp dir (accepts the repo dir or its parent). Refuses anything else."""
    if not path:
        return
    p = Path(path).resolve()
    if p.name == "repo":
        p = p.parent
    if p.parent == _tmp_root() and p.name.startswith("loadout-git-"):
        shutil.rmtree(p, ignore_errors=True)


def list_tree(repo: Path, max_entries: int = 20000) -> list[dict]:
    """Flat, depth-annotated listing (dirs first) of a repo, skipping VCS/vendor folders."""
    out: list[dict] = []

    def walk(d: Path, depth: int):
        for p in sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if p.name in TREE_SKIP or len(out) >= max_entries:
                continue
            out.append({"rel": p.relative_to(repo).as_posix(), "name": p.name,
                        "is_dir": p.is_dir(), "depth": depth})
            if p.is_dir() and not p.is_symlink():
                walk(p, depth + 1)

    walk(repo, 0)
    return out


def tree_children(tree: list[dict]) -> dict[str, list[dict]]:
    """Group a flat `list_tree` result by parent folder (root is the empty string)."""
    out: dict[str, list[dict]] = {}
    for t in tree:
        out.setdefault(t["rel"].rpartition("/")[0], []).append(t)
    return out


def _marked_ancestor(rel: str, marked: set[str]) -> str | None:
    """The nearest marked path equal to `rel` or containing it."""
    while True:
        if rel in marked:
            return rel
        if "/" not in rel:
            return None
        rel = rel.rpartition("/")[0]


def node_state(rel: str, marked: set[str]) -> str:
    """'marked' (itself or an ancestor is marked), 'partial' (only some descendants are) or 'none'."""
    if _marked_ancestor(rel, marked) is not None:
        return "marked"
    prefix = rel + "/"
    return "partial" if any(m.startswith(prefix) for m in marked) else "none"


def toggle_mark(rel: str, marked: set[str], children: dict[str, list[dict]]) -> set[str]:
    """New marked set after clicking `rel`.

    Marking a node (or completing a partial folder) marks it whole and drops redundant descendants.
    Unmarking a node that is only marked through an ancestor turns that ancestor into a partial folder
    by marking every other branch down to it.
    """
    anc = _marked_ancestor(rel, marked)
    if anc is None:
        prefix = rel + "/"
        return {m for m in marked if not m.startswith(prefix)} | {rel}
    new = marked - {anc}
    cur = anc
    while cur != rel:
        nxt = cur + "/" + rel[len(cur) + 1:].split("/")[0]
        new |= {c["rel"] for c in children.get(cur, []) if c["rel"] != nxt}
        cur = nxt
    return new


def prune_selection(selected: list[str]) -> list[str]:
    """Drop items nested inside another selected directory."""
    sel = sorted(set(selected))
    return [s for s in sel if not any(s != o and s.startswith(o + "/") for o in sel)]


def guess_kind(p: Path) -> str:
    n = p.name.lower()
    if p.is_dir():
        return "skills" if (p / "SKILL.md").exists() else "rules"
    if p.suffix == ".json":
        return "mcp"
    if n == "skill.md":
        return "skills"
    if p.suffix == ".md":
        return "rules"
    return "mcp"
