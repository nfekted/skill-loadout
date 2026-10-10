"""Backup export/import and Git clone → selective import."""
from pathlib import Path

import streamlit as st

import time

from .. import portability, store, sync, updates
from . import common

GIT_KINDS = {"Skill": "skills", "Rule": "rules", "Role": "roles", "MCP": "mcp"}


def render(data: dict) -> None:
    st.header("Import / Export", divider="gray")
    t1, t2, t3 = st.tabs(["Backup (.zip)", "Import from Git", "Git updates"])
    with t1:
        backup(data)
    with t2:
        git_import(data)
    with t3:
        git_updates(data)


def backup(data: dict) -> None:
    st.subheader("Export")
    st.caption("Downloads `data.json` and every stored asset file as one structured zip.")
    if st.button("Prepare backup", icon="📦"):
        with st.status("Building archive…") as s:
            st.session_state["_backup"] = portability.export_zip()
            s.update(label="Archive ready", state="complete")
    if blob := st.session_state.get("_backup"):
        st.download_button("Download backup", blob, "skill-loadout-backup.zip", "application/zip",
                           icon="⬇️", type="primary")
    st.subheader("Import")
    up = st.file_uploader("Loadout backup (.zip)", type=["zip"], key="imp_zip")
    mode = st.radio("Mode", ["Merge into current library", "Replace everything (a backup is kept)"], key="imp_mode")
    over = st.checkbox("Overwrite items that already exist (same ID)", disabled=mode.startswith("Replace"))
    if st.button("Import backup", icon="📥", type="primary", disabled=not up):
        try:
            with st.status("Importing…") as s:
                stats = portability.import_zip(up.getvalue(), "replace" if mode.startswith("Replace") else "merge", over)
                s.update(label="Import complete", state="complete")
            common.done(f"Imported: {stats['added']} added, {stats['updated']} updated, {stats['skipped']} skipped.")
        except (ValueError, OSError) as e:
            common.fail(str(e))


# ---- git workflow: clone → select → classify each → commit → wipe -------------
def _g() -> dict:
    return st.session_state.setdefault("git", {"stage": "url"})


def _clear_selection() -> None:
    for k in [k for k in st.session_state if str(k).startswith("gsel_")]:
        del st.session_state[k]


def _reset() -> None:
    portability.wipe(st.session_state.get("git", {}).get("repo"))
    st.session_state.pop("git", None)
    _clear_selection()


def git_import(data: dict) -> None:
    g = _g()
    if g["stage"] != "url":
        _, c = st.columns([5, 1])
        if c.button("Cancel", icon="✖️", key="git_cancel"):
            _reset()
            common.done("Import cancelled. Temporary files removed.", "🧹")
    {"url": stage_url, "select": stage_select, "classify": stage_classify}[g["stage"]](data, g)


def _use_recent() -> None:
    st.session_state["git_url"] = st.session_state.get("git_recent", "") or st.session_state.get("git_url", "")


def stage_url(data, g):
    st.caption("Clone a repository into a temporary folder, pick what to keep, then register each item. "
               "Each imported asset remembers where it came from, so you can check for updates later.")
    recent = sorted({a["source"]["url"] for _, a in updates.tracked(data)})
    if recent:
        st.selectbox("Previously used repositories", ["", *recent], key="git_recent", on_change=_use_recent,
                     format_func=lambda u: u or "—")
    c1, c2 = st.columns([3, 1])
    url = c1.text_input("Git repository URL", placeholder="https://github.com/owner/repo.git", key="git_url")
    ref = c2.text_input("Branch or tag (optional)", key="git_ref", placeholder="default branch")
    if st.button("Clone repository", icon="🌐", type="primary", disabled=not url.strip()):
        try:
            with st.status("Cloning…", expanded=True) as s:
                repo = portability.clone(url, ref=ref)
                g.update(commit=portability.head_commit(repo), pinned=portability.is_detached(repo))
                s.update(label="Repository cloned", state="complete")
        except (ValueError, RuntimeError) as e:
            return common.fail(f"Clone failed: {e}")
        g.update(stage="select", repo=str(repo), url=url.strip(), ref=ref.strip() or None)
        st.rerun()


def stage_select(data, g):
    repo = Path(g["repo"])
    tree = portability.list_tree(repo)
    st.write(f"**{g['url']}**")
    st.caption("Tick files or folders to keep. A ticked folder is imported as a single asset (e.g. a whole skill).")
    if not tree:
        common.empty_state("The repository is empty", icon="📭")
    done = {a["source"]["path"] for _, a in updates.tracked(data) if a["source"]["url"] == g["url"]}
    if g.get("pinned"):
        st.caption("This is a tag or commit: imported assets will be marked as pinned and not checked for updates.")
    picked = []
    # Streamlit forbids nested expanders, so each top-level folder gets one expander with an indented list.
    tops = [t for t in tree if t["depth"] == 0]
    for top in tops:
        group = [t for t in tree if t["rel"] == top["rel"] or t["rel"].startswith(top["rel"] + "/")]
        if top["is_dir"]:
            with st.expander(f"📁 {top['name']}  ({len(group) - 1} items)"):
                for t in group:
                    if _row(t, done):
                        picked.append(t["rel"])
        else:
            if _row(top, done):
                picked.append(top["rel"])
    sel = portability.prune_selection(picked)
    st.info(f"{len(sel)} item(s) selected")
    if st.button("Continue", icon="➡️", type="primary", disabled=not sel):
        g.update(stage="classify", queue=sel, idx=0, results=[])
        st.rerun()


def _row(t: dict, done: set) -> bool:
    pad, col = st.columns([t["depth"] * 0.08 + 0.001 if t["depth"] else 0.001, 1])
    label = ("📁 " if t["is_dir"] else "📄 ") + t["name"] + ("  ✅ imported" if t["rel"] in done else "")
    return col.checkbox(label, key=f"gsel_{t['rel']}")


def stage_classify(data, g):
    repo, queue, i = Path(g["repo"]), g["queue"], g["idx"]
    if i >= len(queue):
        return finish(data, g)
    rel = queue[i]
    src = repo / rel
    st.progress(i / len(queue), text=f"Item {i + 1} of {len(queue)}")
    st.write(f"**`{rel}`** {'(folder)' if src.is_dir() else ''}")
    if src.is_file() and src.stat().st_size < 4000:
        with st.expander("Preview"):
            st.code(src.read_text(encoding="utf-8", errors="replace"))
    guess = portability.guess_kind(src)
    names = list(GIT_KINDS)
    with st.form(f"git_item_{i}"):
        kind = st.selectbox("Asset type", names, index=list(GIT_KINDS.values()).index(guess))
        c1, c2 = st.columns(2)
        name = c1.text_input("Name", src.stem if src.is_file() else src.name)
        desc = c2.text_input("Description")
        tags = common.tag_input("Tags", data, f"git_tags_{i}")
        b1, b2 = st.columns(2)
        add = b1.form_submit_button("Add & Next", icon="➡️", type="primary")
        skip = b2.form_submit_button("Skip", icon="⏭️")
    if add or skip:
        if add:
            if not name.strip():
                return common.fail("Name is required.")
            k = GIT_KINDS[kind]
            if k == "mcp":
                k = "mcp_configs" if src.is_file() and src.suffix == ".json" else "mcp_servers"
            g["results"].append({"kind": k, "rel": rel, "name": name, "desc": desc, "tags": tags})
        g["idx"] += 1
        st.rerun()


def finish(data, g):
    repo, results = Path(g["repo"]), g["results"]
    ok, errors = 0, []
    with st.status("Importing selected assets…", expanded=True) as s:
        for r in results:
            try:
                src = updates.make_source(g["url"], g.get("ref"), r["rel"], g["commit"],
                                          portability.rev_parse(repo, r["rel"]), g.get("pinned", False))
                store.import_from_path(data, r["kind"], repo / r["rel"], r["name"], r["desc"], r["tags"], source=src)
                ok += 1
            except (ValueError, OSError) as e:
                errors.append(f"{r['rel']}: {e}")
        portability.wipe(repo)
        s.update(label=f"Imported {ok} asset(s); temporary files removed", state="complete")
    st.session_state.pop("git", None)
    _clear_selection()
    for e in errors:
        st.warning(e)
    if errors:
        common.notify(f"{ok} imported, {len(errors)} failed", "⚠️")
        st.button("Done", on_click=lambda: None)
    else:
        common.done(f"{ok} asset(s) imported from Git!")


# ---- git updates: manual check → review → apply ----------------------------------
STATUS_LABEL = {"update": "🟢 Update available", "conflict": "🟠 Conflict — edited locally and upstream",
                "removed": "🔴 Removed from repository", "error": "⚠️ Could not check"}
KIND_LABEL = {"skills": "Skill", "rules": "Rule", "roles": "Role", "mcp_configs": "MCP Config",
              "mcp_servers": "MCP Server"}


def _drop(report: dict, item: dict) -> None:
    report["items"] = [i for i in report["items"] if i["id"] != item["id"]]


def _after_apply(data: dict, item: dict, msg: str) -> None:
    n = len(sync.used_by(data, item["kind"], item["id"])["projects"])
    common.notify(msg + (f" {n} project(s) use it and now show as outdated — re-sync them from Projects." if n else ""))


def git_updates(data: dict) -> None:
    st.caption("Checks are manual: nothing contacts the network until you press the button. "
               "Only the assets you imported are compared — other files in the repositories are ignored.")
    tr = updates.tracked(data)
    if not tr:
        return common.empty_state("No Git-imported assets", "Import something from a repository first; "
                                  "its origin is remembered automatically.", "🌐")
    report = st.session_state.get("upd_report")
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Check for updates", icon="🔄", type="primary", key="upd_check"):
        updates.discard(report)
        with st.status("Checking repositories…", expanded=False) as s:
            report = st.session_state["upd_report"] = updates.check(data)
            s.update(label="Check complete", state="complete")
    if report and c2.button("Discard results", icon="🧹", key="upd_discard"):
        updates.discard(report)
        st.session_state.pop("upd_report")
        st.rerun()
    if not report:
        st.markdown(f"**{len(tr)}** tracked asset(s):")
        for kind, a in tr:
            s = a["source"]
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["checked_at"])) if s.get("checked_at") else "never"
            st.markdown(f"- **{a['name']}** <span class='muted'>{KIND_LABEL[kind]} · {s['url']} · `{s['path']}` · "
                        f"last checked {when}{' · pinned' if s.get('pinned') else ''}</span>", unsafe_allow_html=True)
        return
    items = report["items"]
    actionable = [i for i in items if i["status"] in STATUS_LABEL]
    ok = sum(i["status"] == "up_to_date" for i in items)
    pinned = sum(i["status"] == "pinned" for i in items)
    st.info(f"{len(actionable)} need attention · {ok} up to date" + (f" · {pinned} pinned (not tracked)" if pinned else ""),
            icon=":material/fact_check:")
    for item in actionable:
        render_update(data, report, item)


def render_update(data: dict, report: dict, item: dict) -> None:
    key = f"upd_{item['id']}"
    with st.expander(f"{item['name']} · {KIND_LABEL[item['kind']]} · {STATUS_LABEL[item['status']]}",
                     expanded=item["status"] == "conflict"):
        a = store.find(data, item["kind"], item["id"])
        if not a:
            return st.caption("This asset no longer exists.")
        st.caption(f"`{a['source']['path']}` · {a['source']['url']}")
        if item["message"]:
            (st.warning if item["status"] == "conflict" else st.caption)(item["message"])
        if item["status"] in ("error", "removed"):
            if item["status"] == "removed" and st.button("Unlink from repository", icon="🔗", key=f"{key}_unlink"):
                updates.unlink(data, item["kind"], item["id"])
                _drop(report, item)
                common.done("Unlinked. The asset stays in your library.")
            return
        try:
            diffs = updates.diff(item, data)
        except (OSError, FileNotFoundError) as e:
            return st.error(str(e))
        for d in diffs:
            st.markdown(f"**{d['file']}** · _{d['state']}_")
            st.code(d["diff"] or "(empty)", language="diff")
        try:
            if item["status"] == "update":
                if st.button("Apply update", icon="⬇️", type="primary", key=f"{key}_apply"):
                    updates.apply_update(data, item)
                    _drop(report, item)
                    _after_apply(data, item, f"{item['name']} updated from the repository.")
                    st.rerun()
                return
            b1, b2, b3 = st.columns(3)
            with b1.popover("Overwrite with repository…", icon="⬇️", use_container_width=True):
                st.warning("This replaces your local edits with the repository version. It cannot be undone.")
                if st.button("Yes, overwrite my changes", type="primary", key=f"{key}_over"):
                    updates.apply_update(data, item)
                    _drop(report, item)
                    _after_apply(data, item, f"{item['name']} overwritten with the repository version.")
                    st.rerun()
            if b2.button("Keep my version", icon="✋", key=f"{key}_keep", use_container_width=True,
                         help="Remember this upstream version as seen; keep your edits"):
                updates.keep_mine(data, item)
                _drop(report, item)
                common.done(f"Kept your version of {item['name']}.")
            if b3.button("Save repository version as new", icon="➕", key=f"{key}_new", use_container_width=True,
                         help="Registers the repository version as a separate asset; yours is untouched"):
                updates.save_as_new(data, item)
                _drop(report, item)
                common.done("Repository version saved as a new asset.")
        except (OSError, ValueError, FileNotFoundError) as e:
            st.error(str(e))
