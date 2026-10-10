"""Projects page: register projects, attach assets, discover & import, path validation."""
import time
from pathlib import Path

import streamlit as st

from .. import config, frameworks, launcher, mcp_check, store, sync, tokens
from . import common

KIND_LABELS = {"skills": "Skills", "rules": "Rules", "roles": "Roles",
               "mcp_configs": "MCP Configs", "mcp_servers": "MCP Servers"}
SINGULAR = {"skills": "Skill", "rules": "Rule", "roles": "Role", "mcp_configs": "MCP Config",
            "mcp_servers": "MCP Server", None: "Asset"}


IMG_DIR = Path(__file__).resolve().parent.parent.parent / "img"
AGENT_IMAGES = {"Claude": "claude.webp", "ChatGPT Codex": "chatgpt.png", "Antigravity": "antigravity.png",
                "Cursor": "cursor.png", "GitHub Copilot": "githubcopilot.png"}
CARDS_PER_ROW = 3


SORTS = ["Name (A–Z)", "Recently opened", "Most assets", "Needs attention"]
STATUS_ICON = {"outdated": "🔄", "missing": "❓"}


def render(data: dict) -> None:
    ids = [p["id"] for p in data["projects"]]
    if st.session_state.get("project_id") not in ids:
        st.session_state.pop("project_id", None)
    project = store.find(data, "projects", st.session_state["project_id"]) if "project_id" in st.session_state else None
    if project:
        return render_loaded(project, data)
    st.header("Projects", divider="gray")
    render_add(data)
    if not data["projects"]:
        if not st.session_state.get("show_add_project"):
            common.empty_state("No projects yet", "Use “Add project” to register a project folder.", "📁")
        return
    render_bulk(data)
    render_cards(data)


def load_project(data: dict, project: dict) -> None:
    project["last_opened"] = time.time()
    store.save(data)
    st.session_state["project_id"] = project["id"]
    st.rerun()


def render_loaded(project: dict, data: dict) -> None:
    if st.button("Back to projects", icon=":material/arrow_back:", key="proj_back"):
        st.session_state.pop("project_id", None)
        st.rerun()
    st.header(project["name"], divider="gray")
    if not sync.path_exists(project):
        return missing_path_dialog(project["id"])
    render_project(project, data)


def _summary(health: dict) -> str:
    c = health["counts"]
    parts = [(c["skills"], "skill"), (c["rules"], "rule"), (c["roles"], "role"),
             (c["mcp_configs"] + c["mcp_servers"], "MCP")]
    return " · ".join(f"{n} {w}{'s' if n != 1 and w != 'MCP' else ''}" for n, w in parts if n) or "No assets attached"


def _sorted(projects: list[dict], sort: str, health: dict) -> list[dict]:
    keys = {
        "Name (A–Z)": lambda p: p["name"].lower(),
        "Recently opened": lambda p: -p.get("last_opened", 0),
        "Most assets": lambda p: -health[p["id"]]["total"],
        "Needs attention": lambda p: (health[p["id"]]["path_ok"], -len(health[p["id"]]["stale"])),
    }
    # Python's sort is stable: sort by the chosen key, then pull favorites to the top.
    out = sorted(projects, key=keys[sort])
    return sorted(out, key=lambda p: not p.get("favorite"))


def render_cards(data: dict) -> None:
    health = {p["id"]: sync.project_health(p, data) for p in data["projects"]}
    c1, c2, c3 = st.columns([3, 2, 2])
    q = c1.text_input("Search projects", key="pj_q", placeholder="Search by name or folder…",
                      label_visibility="collapsed", icon=":material/search:")
    agents = c2.multiselect("Agent", list(frameworks.FRAMEWORKS), key="pj_agents", placeholder="Filter by agent",
                            label_visibility="collapsed")
    sort = c3.selectbox("Sort", SORTS, key="pj_sort", label_visibility="collapsed")
    ql = q.strip().lower()
    projects = [p for p in data["projects"]
                if (not agents or p["target_model"] in agents)
                and (not ql or ql in p["name"].lower() or ql in p["path"].lower())]
    if not projects:
        return common.empty_state("No project matches your filters", icon="🔍")
    projects = _sorted(projects, sort, health)
    for start in range(0, len(projects), CARDS_PER_ROW):
        cols = st.columns(CARDS_PER_ROW)
        for col, p in zip(cols, projects[start:start + CARDS_PER_ROW]):
            with col:
                render_card(p, data, health[p["id"]])


def render_card(p: dict, data: dict, h: dict) -> None:
    with st.container(border=True):
        img = IMG_DIR / AGENT_IMAGES.get(p["target_model"], "")
        c1, c2, c3 = st.columns([1, 3, 1], vertical_alignment="center")
        if img.is_file():
            c1.image(str(img), width=48)
        c2.markdown(f"**{p['name']}**")
        c2.caption(p["target_model"])
        fav = p.get("favorite")
        if c3.button("", icon=":material/star:" if fav else ":material/star_border:", type="tertiary",
                     key=f"fav_{p['id']}", help="Unpin" if fav else "Pin to top"):
            store.update_entity(data, "projects", p["id"], favorite=not fav)
            st.rerun()
        st.caption(f"`{p['path']}`")
        st.caption(_summary(h))
        st.caption(f"Estimated context: **~{tokens.fmt(sync.project_tokens(p, data)['tokens'])} tokens**")
        if not h["path_ok"]:
            st.markdown(":red[⚠ Folder not found]")
        elif h["stale"]:
            n = len(h["stale"])
            st.markdown(f":orange[🔄 {n} asset{'s' if n != 1 else ''} out of date]")
        b1, b2 = st.columns([4, 1])
        if b1.button("Load project", icon=":material/folder_open:", key=f"load_{p['id']}",
                     use_container_width=True):
            load_project(data, p)
        with b2.popover("", icon=":material/more_horiz:", help="Quick actions"):
            quick_actions(p, data)


def quick_actions(p: dict, data: dict) -> None:
    ok = sync.path_exists(p)
    if st.button("Open folder", icon=":material/folder:", key=f"qa_open_{p['id']}", disabled=not ok,
                 use_container_width=True):
        err = launcher.open_folder(p["path"])
        common.fail(err) if err else st.toast("Opening folder…", icon="📂")
    if st.button("Open in editor", icon=":material/code:", key=f"qa_edit_{p['id']}", disabled=not ok or not launcher.editor(),
                 use_container_width=True, help=None if launcher.editor() else "No supported editor found on PATH"):
        err = launcher.open_in_editor(p["path"])
        common.fail(err) if err else st.toast("Opening editor…", icon="🧑‍💻")
    if st.button("Duplicate…", icon=":material/content_copy:", key=f"qa_dup_{p['id']}", use_container_width=True):
        duplicate_dialog(p["id"])
    st.caption("Copy path")
    st.code(p["path"], language=None)


@st.dialog("Duplicate project")
def duplicate_dialog(project_id: str) -> None:
    data = store.load()
    src = store.find(data, "projects", project_id)
    if not src:
        return st.rerun()
    st.caption("Creates a new project with the same attached assets, synced for the chosen agent.")
    name = st.text_input("New project name", f"{src['name']} copy", key="dup_name")
    fws = list(frameworks.FRAMEWORKS)
    fw = st.selectbox("Target agent framework", fws, index=fws.index(src["target_model"])
                      if src["target_model"] in fws else 0, key="dup_fw")
    path = common.path_input("Project folder", "dup_path", src["path"])
    if st.button("Duplicate", icon="📑", type="primary", key="dup_go"):
        p = Path(path.strip()).expanduser()
        if not name.strip():
            common.fail("Project name is required.")
        elif not p.is_dir():
            common.fail("That folder does not exist.")
        else:
            new = store.add_entity(data, "projects", {
                "name": name.strip(), "path": str(p.resolve()), "target_model": fw, "favorite": False,
                "last_opened": 0, "attached_skills": [], "attached_rules": [], "attached_roles": [],
                "attached_mcp": []})
            n = 0
            for kind, a in sync.attached(src, data):
                sync.attach(new, data, kind, a)
                n += 1
            store.save(data)
            for k in ("dup_name", "dup_fw", "dup_path"):
                st.session_state.pop(k, None)
            common.done(f"Project duplicated ({n} asset(s) attached).")


def render_bulk(data: dict) -> None:
    with st.expander("Bulk actions", icon=":material/library_add_check:"):
        pm = {p["id"]: p["name"] for p in data["projects"]}
        sel = st.multiselect("Projects", list(pm), format_func=pm.get, key="bulk_sel", placeholder="Pick projects")
        targets = [store.find(data, "projects", i) for i in sel]
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        lm = {lo["id"]: lo["name"] for lo in data["loadouts"]}
        lid = c1.selectbox("Loadout", list(lm), format_func=lm.get, key="bulk_lo", disabled=not lm,
                           placeholder="No loadouts yet") if lm else None
        if c2.button("Attach loadout", icon="🎒", key="bulk_attach", use_container_width=True,
                     disabled=not (targets and lid)):
            lo = store.find(data, "loadouts", lid)
            ok, skipped, new = bulk(data, targets, lambda p: sync.attach_loadout(p, data, lo)[0])
            common.done(f"Loadout attached to {ok} project(s), {new} new asset(s)"
                        + (f"; {skipped} skipped (folder missing)" if skipped else "") + ".")
        b1, b2, _ = st.columns([1, 1, 2])
        if b1.button("Re-sync selected", icon="🔄", key="bulk_resync", use_container_width=True, disabled=not targets):
            ok, skipped, n = bulk(data, targets, lambda p: sync.resync(p, data))
            common.done(f"Re-synced {n} asset(s) in {ok} project(s)" + (f"; {skipped} skipped" if skipped else "") + ".", "🔄")
        if b2.button("Re-sync all outdated", icon="🔁", key="bulk_stale", use_container_width=True,
                     help="Refresh only the stale or missing copies in every project"):
            ok, skipped, n = bulk(data, data["projects"], lambda p: sync.resync_stale(p, data))
            common.done(f"Refreshed {n} outdated asset(s) across {ok} project(s).", "🔁")


def bulk(data: dict, projects: list[dict], fn) -> tuple[int, int, int]:
    """Run fn on every project whose folder exists. Returns (projects done, skipped, sum of fn results)."""
    ok = skipped = total = 0
    with st.status("Working…", expanded=False) as s:
        for p in projects:
            if not sync.path_exists(p):
                skipped += 1
                continue
            total += fn(p)
            ok += 1
        store.save(data)
        s.update(label=f"{ok} project(s) done", state="complete")
    return ok, skipped, total


def render_add(data: dict) -> None:
    if not st.session_state.get("show_add_project"):
        if st.button("Add project", icon="➕", type="primary", key="pr_show"):
            st.session_state["show_add_project"] = True
            st.rerun()
        return
    with st.container(border=True):
        n = st.session_state.setdefault("proj_nonce", 0)
        c1, c2 = st.columns(2)
        name = c1.text_input("Project name", key=f"pr_name_{n}")
        fw = c2.selectbox("Target agent framework", list(frameworks.FRAMEWORKS), key=f"pr_fw_{n}")
        path = common.path_input("Project folder", f"pr_path_{n}", placeholder="/home/me/code/my-project")
        b1, b2, _ = st.columns([1, 1, 4])
        if b2.button("Cancel", key=f"pr_cancel_{n}"):
            st.session_state["show_add_project"] = False
            st.session_state["proj_nonce"] += 1
            st.rerun()
        if b1.button("Add Project", icon="💾", type="primary", key=f"pr_add_{n}"):
            p = Path(path.strip()).expanduser()
            if not name.strip():
                common.fail("Project name is required.")
            elif not p.is_dir():
                common.fail("That folder does not exist.")
            else:
                store.add_entity(data, "projects", {
                    "name": name.strip(), "path": str(p.resolve()), "target_model": fw,
                    "favorite": False, "last_opened": 0, "attached_skills": [], "attached_rules": [], "attached_roles": [], "attached_mcp": []})
                st.session_state["show_add_project"] = False
                st.session_state["proj_nonce"] += 1
                common.done("Project added!")


@st.dialog("Project path not found")
def missing_path_dialog(project_id: str) -> None:
    data = store.load()
    project = store.find(data, "projects", project_id)
    if not project:
        return st.rerun()
    st.error(f"The folder for **{project['name']}** no longer exists:")
    st.code(project["path"], language=None)
    st.write("**Option A — Update Path**")
    new = common.path_input("New project folder", "np_path", placeholder="/new/location/of/project")
    if st.button("Update Path", icon="📂", type="primary"):
        p = Path(new.strip()).expanduser()
        if p.is_dir():
            store.update_entity(data, "projects", project_id, path=str(p.resolve()))
            common.done("Project path updated!")
        else:
            common.fail("That folder does not exist.")
    st.divider()
    st.write("**Option B — Delete Project Reference**")
    st.caption("Removes the project from Loadout only. Nothing on disk is touched.")
    if st.button("Delete Project Reference", icon="🗑️"):
        store.delete_entity(data, "projects", project_id)
        st.session_state.pop("project_id", None)
        common.done("Project reference deleted.", "🗑️")


def render_project(project: dict, data: dict) -> None:
    sync.ensure_root_file(project)
    st.caption(f"`{project['path']}` · target: **{project['target_model']}**")
    t1, t2, t3, t4 = st.tabs(["Overview", "Attach Assets", "Discover & Import", "Project Settings"])
    with t1:
        overview(project, data)
    with t2:
        attach_tab(project, data)
    with t3:
        discover_tab(project, data)
    with t4:
        settings_tab(project, data)


def overview(project: dict, data: dict) -> None:
    fw = frameworks.framework(project["target_model"])
    cols = st.columns(5)
    for c, k in zip(cols, KIND_LABELS):
        c.metric(KIND_LABELS[k], len(sync.attached(project, data, k)))
    st.write(f"Instructions file: `{fw['root_file']}` · Skills folder: `{fw['skills_dir']}/`")
    instructions_card(project, data)
    items = sync.attached(project, data)
    if not items:
        return common.empty_state("Nothing attached yet", "Use the Attach Assets tab.", "🧩")
    context_card(project, data)
    mcp_card(project, data)
    status = {(k, a["id"]): sync.item_status(project, data, k, a) for k, a in items}
    stale = sum(v != "ok" for v in status.values())
    if stale:
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        c1.warning(f"{stale} attached asset(s) differ from the Loadout library or are missing in the project.", icon="🔄")
        if c2.button("Re-sync outdated", icon="🔄", type="primary", key="resync_stale", use_container_width=True):
            n = sync.resync_stale(project, data)
            common.done(f"Refreshed {n} outdated asset(s).", "🔄")
    for kind, a in items:
        stt = status[(kind, a["id"])]
        c1, c2, c3 = st.columns([2, 3, 2], vertical_alignment="center")
        c1.write(f"**{a['name']}**" + (f" {STATUS_ICON[stt]} _{stt}_" if stt != "ok" else ""))
        c2.markdown(f"<span class='muted'>{SINGULAR[kind]}</span> " + common.chips_html(a.get("tags", []), data),
                    unsafe_allow_html=True)
        b1, b2, b3 = c3.columns(3)
        if stt != "ok":
            with b1.popover("", icon=":material/difference:", help="View differences"):
                show_diff(project, data, kind, a)
            if b2.button("", icon=":material/sync:", key=f"rs_{kind}_{a['id']}", help="Re-sync this asset"):
                sync.resync_item(project, data, kind, a)
                common.done(f"{a['name']} re-synced.", "🔄")
        if b3.button("", icon=":material/link_off:", key=f"det_{kind}_{a['id']}", help="Detach"):
            sync.detach(project, data, kind, a)
            store.save(data)
            common.done(f"{a['name']} detached from project.")
    if st.button("Re-sync all files", icon="🔄", help="Re-copy every attached asset from Loadout storage"):
        with st.status("Syncing…", expanded=False) as s:
            n = sync.resync(project, data)
            s.update(label=f"Synced {n} asset(s)", state="complete")
        common.notify(f"Re-synced {n} asset(s)", "🔄")


def instructions_card(project: dict, data: dict) -> None:
    """The project's own CLAUDE.md/AGENTS.md: seedable from a skill while empty, then read-only + token count."""
    info = sync.root_info(project)
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="center")
        c1.markdown(f"**{info['name']}** <span class='muted'>project instructions</span>", unsafe_allow_html=True)
        c2.metric("Characters", f"{info['chars']:,}")
        c3.metric("Tokens", f"~{tokens.fmt(info['tokens'])}",
                  help=f"Characters ÷ {config.CHARS_PER_TOKEN}. Counted in the project's estimated context.")
        if info["empty"]:
            st.caption(f"`{info['name']}` is empty. You can fill it once with a skill (e.g. a default for all your "
                       "front-end projects); after that it is locked here and only counted.")
            skills = data["skills"]
            if not skills:
                return st.caption("Create a skill in the Skills Library first.")
            k = f"seed_{project['id']}"
            d1, d2 = st.columns([3, 1], vertical_alignment="bottom")
            pick = d1.selectbox("Use a skill as the content", [s["id"] for s in skills], key=f"{k}_pick",
                                format_func=lambda i: store.find(data, "skills", i)["name"], index=None,
                                placeholder="Choose a skill…")
            if d2.button(f"Use as {info['name']}", icon=":material/input:", key=f"{k}_go", disabled=not pick,
                         type="primary", use_container_width=True):
                try:
                    sync.seed_root_from_skill(project, data, store.find(data, "skills", pick))
                except (ValueError, OSError) as e:
                    return common.fail(str(e))
                common.done(f"{info['name']} filled from the skill.")
        else:
            st.caption(":material/lock: Locked — it already has content. Edit the file directly in the project if you "
                       "need to change it.")
            with st.expander("View content", icon=":material/description:"):
                st.code(info["text"], language="markdown", wrap_lines=True)


def context_card(project: dict, data: dict) -> None:
    ctx = sync.project_tokens(project, data)
    if not ctx["items"] and not ctx["root"]["tokens"]:
        return
    heavy = ctx["tokens"] > config.PROJECT_TOKEN_WARN
    with st.container(border=True):
        c1, c2 = st.columns([1, 3], vertical_alignment="center")
        c1.metric("Estimated context", f"~{tokens.fmt(ctx['tokens'])} tokens", help=
                  f"{ctx['chars']:,} characters of skills, rules, roles and the instructions file at ~{config.CHARS_PER_TOKEN} chars/token. "
                  "Skills count their entry file only; modules load on demand.")
        if heavy:
            c2.warning(f"Attached text exceeds ~{tokens.fmt(config.PROJECT_TOKEN_WARN)} tokens. "
                       "Consider detaching heavy assets or modularizing skills.", icon="⚠️")
        with st.expander("Breakdown by asset", icon=":material/data_usage:", expanded=heavy):
            top = max([i["tokens"] for i in ctx["items"]] + [ctx["root"]["tokens"], 1])
            if ctx["root"]["tokens"]:
                share = ctx["root"]["tokens"] / ctx["tokens"] if ctx["tokens"] else 0
                st.markdown(f"**{ctx['root']['name']}** <span class='muted'>project instructions · "
                            f"~{tokens.fmt(ctx['root']['tokens'])} tokens · {share:.0%}</span>", unsafe_allow_html=True)
                st.progress(ctx["root"]["tokens"] / top)
            for i in ctx["items"]:
                share = i["tokens"] / ctx["tokens"] if ctx["tokens"] else 0
                st.markdown(f"**{i['asset']['name']}** <span class='muted'>{SINGULAR[i['kind']]} · "
                            f"~{tokens.fmt(i['tokens'])} tokens · {share:.0%}</span>", unsafe_allow_html=True)
                st.progress(i["tokens"] / top)


def mcp_card(project: dict, data: dict) -> None:
    chk = mcp_check.check_project(project, data)
    names = {a["id"]: a["name"] for a in data["mcp_configs"]}
    rows = [dict(f, server=f"{names[i]} › {f['server']}" if f.get("server") else names[i])
            for i, fs in chk["configs"].items() for f in mcp_check.actionable(fs)]
    rows += chk["conflicts"]
    if rows:
        with st.expander(f"MCP validation · {len(rows)} warning(s)", icon=":material/rule:"):
            st.caption("Advisory only — attached configs are still synced as-is.")
            common.show_findings(mcp_check.sort(rows))


def show_diff(project: dict, data: dict, kind: str, asset: dict) -> None:
    diffs = sync.diff_item(project, data, kind, asset)
    if not diffs:
        return st.caption("No file differences found.")
    for d in diffs:
        st.markdown(f"**{d['file']}** · _{d['state']}_")
        st.code(d["diff"] or "(empty file)", language="diff")


def attach_tab(project: dict, data: dict) -> None:
    if data["loadouts"]:
        with st.container(border=True):
            st.write("**Attach a Loadout**")
            m = {lo["id"]: lo["name"] for lo in data["loadouts"]}
            c1, c2 = st.columns([3, 1])
            lid = c1.selectbox("Loadout", list(m), format_func=m.get, label_visibility="collapsed", key="loadout_sel")
            lo = store.find(data, "loadouts", lid)
            n = len(sync.loadout_items(data, lo))
            c1.caption(f"Includes {n} asset(s), with agent presets expanded.")
            if c2.button("Attach loadout", icon="🎒", use_container_width=True, disabled=not n):
                with st.status("Attaching loadout…", expanded=False) as s:
                    new, already = sync.attach_loadout(project, data, lo)
                    store.save(data)
                    s.update(label=f"{new} attached, {already} already present", state="complete")
                common.done(f"Loadout '{lo['name']}' attached ({new} new, {already} already present).")
    if data["agents"]:
        with st.container(border=True):
            st.write("**Attach an Agent Preset**")
            m = {a["id"]: a["name"] for a in data["agents"]}
            c1, c2 = st.columns([3, 1])
            pid = c1.selectbox("Preset", list(m), format_func=m.get, label_visibility="collapsed", key="preset_sel")
            if c2.button("Attach preset", icon="🤖", use_container_width=True):
                agent = store.find(data, "agents", pid)
                n = 0
                for kind in ("rules", "roles", "skills"):
                    for i in agent.get(kind, []):
                        a = store.find(data, kind, i)
                        if a and i not in project.get(store.PROJECT_LISTS[kind], []):
                            sync.attach(project, data, kind, a)
                            n += 1
                store.save(data)
                common.done(f"Preset attached ({n} new asset(s)).")
    if not any(data[k] for k in KIND_LABELS):
        return common.empty_state("Your library is empty", "Add skills, rules, roles or MCP assets first.", "🗂️")
    q, tags = common.filter_bar("att", data)
    chosen = {}
    for kind, label in KIND_LABELS.items():
        pool = [a for a in data[kind] if store.matches(a, q, tags) or a["id"] in project[store.PROJECT_LISTS[kind]]]
        if not data[kind]:
            continue
        cur = [i for i in project[store.PROJECT_LISTS[kind]] if store.find(data, kind, i)]
        opts = {a["id"]: a["name"] for a in pool}
        chosen[kind] = st.multiselect(label, list(opts), default=[i for i in cur if i in opts],
                                      format_func=opts.get, key=f"att_{project['id']}_{kind}")
    added, removed = selection_changes(project, data, chosen, q, tags)
    plan = preview_plan(project, data, added, removed)
    if plan:
        with st.expander(f"Preview changes · {len(plan)} file operation(s)", icon=":material/preview:"):
            icons = {"create": "🟢", "update": "🟡", "delete": "🔴"}
            st.markdown("\n".join(f"- {icons[act]} `{act}` {path}" for act, path in plan))
    elif added or removed:
        st.caption("Selected changes touch no files.")
    if st.button("Apply to Project", icon="🚀", type="primary", disabled=not (added or removed)):
        with st.status("Applying changes…", expanded=False) as s:
            for kind, a in added:
                sync.attach(project, data, kind, a)
            for kind, a in removed:
                sync.detach(project, data, kind, a)
            store.save(data)
            s.update(label=f"{len(added)} attached, {len(removed)} detached", state="complete")
        common.done(f"Asset(s) linked to project ({len(added)} added, {len(removed)} removed).")


def selection_changes(project: dict, data: dict, chosen: dict, q: str, tags: list[str]):
    """Assets the current multiselect state would attach and detach (only among visible ones)."""
    added, removed = [], []
    for kind, sel in chosen.items():
        cur = set(project[store.PROJECT_LISTS[kind]])
        shown = {a["id"] for a in data[kind] if store.matches(a, q, tags)} | cur
        for a in data[kind]:
            if a["id"] not in shown:
                continue
            if a["id"] in sel and a["id"] not in cur:
                added.append((kind, a))
            elif a["id"] not in sel and a["id"] in cur:
                removed.append((kind, a))
    return added, removed


def preview_plan(project: dict, data: dict, added: list, removed: list) -> list[tuple[str, str]]:
    """Dry-run of file operations, de-duplicated (several rules share one instructions file)."""
    plan: list[tuple[str, str]] = []
    for kind, a in added:
        plan += sync.plan_attach(project, data, kind, a)
    for kind, a in removed:
        plan += sync.plan_detach(project, kind, a)
    return list(dict.fromkeys(plan))


def discover_tab(project: dict, data: dict) -> None:
    st.caption("Scans this project for skills, rules and roles that Loadout doesn't know about yet.")
    found = sync.discover(project, data)
    if not found:
        return common.empty_state("Nothing new found", "Everything in this project is already in Loadout.", "✅")
    for i, c in enumerate(found):
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{c['name']}**  ·  {SINGULAR[c['kind']]}  ·  {c['chars']:,} chars")
            c1.caption(str(Path(c["path"]).relative_to(sync.root(project))))
            tags = common.tag_input("Tags", data, f"imp_tags_{i}")
            c2.write("")
            if c2.button("Import to Loadout", icon="📥", key=f"imp_{i}"):
                try:
                    asset = sync.import_candidate(data, c, c["name"], "Imported from " + project["name"], tags)
                    if c.get("text") is None:   # a file already inside the project: link it to the project too
                        sync.attach(project, data, c["kind"], asset)
                        store.save(data)
                        common.done(f"{c['name']} imported and attached to this project!")
                    common.done(f"{c['name']} imported to Loadout! "
                                f"Attach it from the Attach Assets tab (it was text inside {Path(c['path']).name}).")
                except (ValueError, OSError) as e:
                    common.fail(str(e))


def settings_tab(project: dict, data: dict) -> None:
    path = common.path_input("Project folder", f"ps_path_{project['id']}", project["path"])
    with st.form("proj_edit"):
        name = st.text_input("Name", project["name"])
        fws = list(frameworks.FRAMEWORKS)
        fw = st.selectbox("Target agent framework", fws, index=fws.index(project["target_model"])
                          if project["target_model"] in fws else 0)
        st.caption("Changing the framework moves attached files to the new framework's folders.")
        if st.form_submit_button("Save changes", icon="💾"):
            p = Path(path.strip()).expanduser()
            if not name.strip() or not p.is_dir():
                common.fail("A name and an existing folder are required.")
            else:
                if fw != project["target_model"]:
                    snapshot = {k: list(project[v]) for k, v in store.PROJECT_LISTS.items()}
                    sync.clear(project, data)
                    project.update(path=str(p.resolve()), target_model=fw)
                    for kind in sync.ATTACHABLE:
                        for i in snapshot[kind]:
                            a = store.find(data, kind, i)
                            if a:
                                sync.attach(project, data, kind, a)
                else:
                    project["path"] = str(p.resolve())
                project["name"] = name.strip()
                store.save(data)
                common.done("Project updated!")
    with st.popover("Delete project reference", icon="🗑️"):
        st.write("Removes the project from Loadout. Files already synced stay in the project folder.")
        if st.button("Confirm delete", type="primary", key="proj_del"):
            store.delete_entity(data, "projects", project["id"])
            st.session_state.pop("project_id", None)
            common.done("Project reference deleted.", "🗑️")
