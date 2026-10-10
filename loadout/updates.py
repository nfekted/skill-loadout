"""Check Git-imported assets for upstream updates (manual) and apply them.

Each imported asset carries `source = {url, ref, path, commit, object, hash, pinned, ...}`:
  commit  repository commit at import / last sync       -> cheap "did anything change?" via ls-remote
  object  Git object id of `path` at that commit        -> "did *this* path change?"
  hash    content hash of the local copy right after sync -> "did I edit it locally?"
Nothing here runs unless the user asks for a check; nothing is overwritten without an explicit call.
"""
import difflib
import time
from pathlib import Path

from . import files, portability, store

STATUSES = ("update", "conflict", "removed", "error", "pinned", "up_to_date")


def tracked(data: dict) -> list[tuple[str, dict]]:
    return [(k, a) for k in files.KINDS for a in data[k] if a.get("source")]


def make_source(url: str, ref: str | None, path: str, commit: str, obj: str | None, pinned: bool) -> dict:
    return {"url": url.strip(), "ref": (ref or "").strip() or None, "path": path, "commit": commit,
            "object": obj, "pinned": pinned, "imported_at": time.time(), "checked_at": time.time()}


def _item(kind: str, a: dict, status: str, message: str = "", **extra) -> dict:
    return {"kind": kind, "id": a["id"], "name": a["name"], "status": status, "message": message, **extra}


def check(data: dict) -> dict:
    """Compare every tracked asset with its repository. One ls-remote per repo, plus one trees-only clone
    for repos whose commit moved. Returns a report whose clones stay on disk until discard()/apply."""
    groups: dict[tuple, list] = {}
    for kind, a in tracked(data):
        groups.setdefault((a["source"]["url"], a["source"].get("ref")), []).append((kind, a))
    now = time.time()
    items: list[dict] = []
    repos: list[str] = []
    for (url, ref), members in groups.items():
        live = []
        for kind, a in members:
            if a["source"].get("pinned"):
                items.append(_item(kind, a, "pinned", "Imported from a tag or commit; it is not tracked."))
            else:
                live.append((kind, a))
        if not live:
            continue
        try:
            remote = portability.ls_remote(url, ref)
        except (RuntimeError, ValueError) as e:
            items += [_item(k, a, "error", str(e)) for k, a in live]
            continue
        moved = []
        for kind, a in live:
            if a["source"].get("commit") == remote:
                a["source"]["checked_at"] = now
                items.append(_item(kind, a, "up_to_date"))
            else:
                moved.append((kind, a))
        if not moved:
            continue
        try:
            repo = portability.clone(url, ref=ref, light=True)
        except (RuntimeError, ValueError) as e:
            items += [_item(k, a, "error", str(e)) for k, a in moved]
            continue
        pending = []
        for kind, a in moved:
            s = a["source"]
            obj = portability.rev_parse(repo, s["path"])
            if obj is None:
                items.append(_item(kind, a, "removed", f"`{s['path']}` no longer exists in the repository."))
            elif obj == s.get("object"):  # the repo moved on, but not this path
                s.update(commit=remote, checked_at=now)
                items.append(_item(kind, a, "up_to_date"))
            else:
                pending.append((kind, a, obj))
        if pending:
            try:
                portability.checkout_paths(repo, [a["source"]["path"] for _, a, _ in pending])
            except RuntimeError as e:
                items += [_item(k, a, "error", str(e)) for k, a, _ in pending]
                pending = []
        for kind, a, obj in pending:
            edited = files.unit_hash(kind, a["path"]) != a["source"].get("hash")
            items.append(_item(kind, a, "conflict" if edited else "update",
                               "You edited this asset locally and the repository changed too." if edited else "",
                               repo=str(repo), remote_commit=remote, object=obj))
        if pending:
            repos.append(str(repo))
        else:
            portability.wipe(repo)
    store.save(data)
    return {"items": items, "repos": repos, "checked_at": now}


def discard(report: dict | None) -> None:
    for r in (report or {}).get("repos", []):
        portability.wipe(r)


def upstream_path(item: dict, data: dict) -> Path:
    a = store.find(data, item["kind"], item["id"])
    p = Path(item["repo"]) / a["source"]["path"]
    if not p.exists():
        raise FileNotFoundError("The downloaded copy is gone. Run “Check for updates” again.")
    return p


# ---- diff -----------------------------------------------------------------------
def _texts(p: Path) -> dict[str, str]:
    if p.is_dir():
        return {f.relative_to(p).as_posix(): f.read_text(encoding="utf-8", errors="replace")
                for f in sorted(p.rglob("*")) if f.is_file() and not set(f.relative_to(p).parts) & set(files.IGNORED_NAMES)}
    return {p.name: p.read_text(encoding="utf-8", errors="replace")}


def diff(item: dict, data: dict) -> list[dict]:
    """Per-file differences, local (project 'before') vs repository ('after')."""
    a = store.find(data, item["kind"], item["id"])
    local_unit = files.unit_path(item["kind"], a["path"])
    local = _texts(local_unit)
    up_src = upstream_path(item, data)
    up = _texts(up_src)
    if not up_src.is_dir() and local_unit.is_dir():          # single file → folder asset (SKILL.md)
        up = {Path(a["path"]).name: next(iter(up.values()))}
    elif up_src.is_dir() and not local_unit.is_dir():        # folder → single joined file
        up = {local_unit.name: "\n\n---\n\n".join(t for n, t in up.items() if n.endswith(".md"))}
    out = []
    for name in sorted(set(local) | set(up)):
        old, new = local.get(name), up.get(name)
        if old == new:
            continue
        state = "new in repository" if old is None else "removed in repository" if new is None else "changed"
        text = "".join(difflib.unified_diff((old or "").splitlines(True), (new or "").splitlines(True),
                                            f"mine/{name}", f"repository/{name}"))
        out.append({"file": name, "state": state, "diff": text})
    return out


# ---- actions --------------------------------------------------------------------
def _refresh_source(a: dict, item: dict, take_upstream: bool) -> None:
    s = a["source"]
    s.update(commit=item["remote_commit"], object=item["object"], checked_at=time.time())
    if take_upstream:
        s["hash"] = files.unit_hash(item["kind"], a["path"])


def apply_update(data: dict, item: dict) -> None:
    """Overwrite the local asset with the repository version."""
    a = store.find(data, item["kind"], item["id"])
    store.replace_asset(data, item["kind"], item["id"], upstream_path(item, data))
    _refresh_source(a, item, take_upstream=True)
    store.save(data)


def keep_mine(data: dict, item: dict) -> None:
    """Acknowledge the new upstream version but keep the local edits (no more nagging until it changes again)."""
    a = store.find(data, item["kind"], item["id"])
    _refresh_source(a, item, take_upstream=False)
    store.save(data)


def save_as_new(data: dict, item: dict) -> dict:
    """Keep the local asset untouched and register the repository version next to it."""
    a = store.find(data, item["kind"], item["id"])
    s = a["source"]
    new_src = dict(s, commit=item["remote_commit"], object=item["object"], checked_at=time.time())
    new_src.pop("hash", None)
    new = store.import_from_path(data, item["kind"], upstream_path(item, data), f"{a['name']} (repository)",
                                 a.get("description", ""), a.get("tags", []), source=new_src)
    _refresh_source(a, item, take_upstream=False)
    store.save(data)
    return new


def unlink(data: dict, kind: str, id_: str) -> None:
    a = store.find(data, kind, id_)
    if a:
        a.pop("source", None)
        store.save(data)
