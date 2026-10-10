"""Generic CRUD tab for file-backed assets (skills, roles, rules, MCP configs/servers)."""
import html
import json
import zipfile
import io
import shutil
import tempfile
import zlib
from pathlib import Path

import streamlit as st

from .. import files, lint, mcp_check, store, sync, templates, tokens, updates
from . import common, nav

# Per-kind UI behaviour.
SPECS = {
    "skills": {"label": "Skill", "upload": ["md", "zip"], "lang": "markdown",
               "hint": "Upload a .md file, a .zip (modular skill folder with SKILL.md), or paste text."},
    "roles": {"label": "Role", "upload": ["md"], "lang": "markdown", "hint": "Upload a .md file or paste text."},
    "rules": {"label": "Rule", "upload": ["md"], "lang": "markdown", "hint": "Upload a .md file or paste text."},
    "mcp_configs": {"label": "MCP Config", "upload": ["json"], "lang": "json",
                    "hint": "Upload or paste a JSON config (e.g. {\"mcpServers\": {...}})."},
    "mcp_servers": {"label": "MCP Server", "upload": ["py", "js", "ts", "mjs", "sh", "go", "rs", "json", "txt"],
                    "lang": "python", "hint": "Upload a script (.py, .js, …) or write code directly."},
}


def _validate(kind: str, text: str) -> str | None:
    if kind == "mcp_configs":
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"
    return None


def token_warning(text: str, key: str) -> None:
    if tokens.exceeds_limit(text):
        st.warning(f"**{tokens.WARNING_TITLE}:** {tokens.WARNING_TEXT}", icon="⚠️")
        with st.expander("Hub & Spoke refactoring prompt", expanded=True):
            incl = st.toggle("Append this file's content to the prompt", key=f"{key}_incl")
            prompt = tokens.build_prompt(text if incl else None)
            st.code(prompt, language="markdown", height=280)
            common.copy_button(prompt, "Copy Prompt")


def _zip_members(raw: bytes) -> tuple[zipfile.ZipFile, str]:
    """Open a zip and return it with the common top-level prefix ('' or 'folder/')."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = [n for n in z.namelist() if not n.startswith("__MACOSX") and not n.endswith("/")]
    tops = {n.split("/")[0] for n in names}
    prefix = f"{tops.pop()}/" if len(tops) == 1 and all("/" in n for n in names) else ""
    return z, prefix


def _zip_preview(raw: bytes) -> str:
    z, prefix = _zip_members(raw)
    for n in (prefix + "SKILL.md", *sorted(x for x in z.namelist() if x.startswith(prefix) and x.endswith(".md"))):
        if n in z.namelist():
            return z.read(n).decode("utf-8", "replace")
    return ""


def _import_zip(data: dict, kind: str, raw: bytes, name: str, desc: str, tags: list[str]) -> None:
    z, prefix = _zip_members(raw)
    with tempfile.TemporaryDirectory(prefix="loadout-zip-") as tmp:
        root = Path(tmp).resolve()
        for i in z.infolist():
            t = (root / i.filename).resolve()
            if root not in t.parents and t != root:
                raise ValueError(f"Unsafe path in zip: {i.filename}")
        z.extractall(root)
        store.import_from_path(data, kind, root / prefix.rstrip("/") if prefix else root, name, desc, tags)


MD_KINDS = ("skills", "rules", "roles")


def _fix_frontmatter(ckey: str, name_key: str, desc_key: str) -> None:
    ss = st.session_state
    ss[ckey] = lint.apply_frontmatter(ss.get(ckey, ""), ss.get(name_key, ""), ss.get(desc_key, ""))


def render_preview(kind: str, text: str) -> None:
    if not text.strip():
        return st.caption("Nothing to preview yet.")
    if kind == "skills":
        meta, body, err = lint.parse_frontmatter(text)
        if meta is not None and not err:
            st.caption(f"**{meta.get('name') or '(no name)'}** — {meta.get('description') or '(no description)'}")
            st.divider()
            return st.markdown(body)
    st.markdown(text)


def content_editor(kind: str, ckey: str, initial: str, name_key: str | None = None, desc_key: str | None = None,
                   folder: Path | None = None, height: int = 260, allow_fix: bool = True) -> str:
    """Markdown editor with Edit/Preview tabs, size stats and an advisory quality check."""
    st.session_state.setdefault(ckey, initial)
    t_edit, t_prev = st.tabs(["Edit", "Preview"])
    with t_edit:
        text = st.text_area("Content", key=ckey, height=height, label_visibility="collapsed")
    with t_prev:
        render_preview(kind, text)
    st.caption(f"{len(text):,} characters · ~{tokens.fmt(tokens.estimate(len(text)))} tokens")
    show_quality(kind, text, st.session_state.get(name_key, "") if name_key else None, folder,
                 ckey, name_key, desc_key, allow_fix)
    return text


def show_quality(kind, text, name, folder, ckey=None, name_key=None, desc_key=None, allow_fix=False) -> None:
    fs = lint.lint(kind, text, name=name, folder=folder) if text.strip() else []
    if not fs:
        return
    with st.expander(f"Quality · {len(fs)} finding(s) — advisory", icon=":material/fact_check:",
                     expanded=bool(lint.actionable(fs))):
        common.show_findings(fs)
        if kind == "skills" and lint.needs_frontmatter(fs):
            if allow_fix and ckey and name_key and desc_key:
                st.button("Generate front-matter from Name & Description", icon=":material/auto_fix_high:",
                          key=f"{ckey}_fm", on_click=_fix_frontmatter, args=(ckey, name_key, desc_key),
                          disabled=not st.session_state.get(name_key, "").strip(),
                          help="Inserts or updates `name` and `description` at the top of SKILL.md" if
                          st.session_state.get(name_key, "").strip() else "Fill in the Name field first")
            else:
                st.caption("Switch to “Paste text” to generate the front-matter automatically.")


# ---- templates --------------------------------------------------------------
def _apply_template(kind: str, k: str) -> None:
    ss = st.session_state
    t = templates.get(kind, ss.get(f"{k}_tpl") or "")
    if not t:
        return
    ss[f"{k}_name"] = t["name"]
    ss[f"{k}_desc"] = t["description"]
    ss[f"{k}_tags"] = list(t["tags"])
    ss[f"{k}_tpl_tags"] = list(t["tags"])
    ss[f"{k}_mode"] = "Paste text"
    ss[f"{k}_text"] = templates.render(t)


def use_template(kind: str, template_id: str) -> None:
    """Pre-fill the 'Add' form of a library tab from a template (used by the Templates gallery)."""
    ss = st.session_state
    k = f"{kind}_add_{ss.setdefault(f'{kind}_nonce', 0)}"
    ss[f"{k}_tpl"] = template_id
    _apply_template(kind, k)
    ss["open_add"] = kind


def template_picker(kind: str, k: str) -> dict | None:
    ts = templates.for_kind(kind)
    if not ts:
        return None
    by_id = {t["id"]: t for t in ts}
    st.selectbox("Start from a template", ["", *by_id], key=f"{k}_tpl", on_change=_apply_template, args=(kind, k),
                 format_func=lambda i: "Blank — start from scratch" if not i else by_id[i]["name"])
    t = by_id.get(st.session_state.get(f"{k}_tpl") or "")
    if t:
        extra = templates.extra_files(t)
        st.caption(t["description"] + (f"  Includes {len(extra)} extra file(s): " + ", ".join(f"`{e}`" for e in extra)
                                       if extra else "") + "  Edit freely below; the template itself is never changed.")
    return t


SUB_DIR = "references"


def _add_sub(k: str) -> None:
    ss = st.session_state
    path = (ss.get(f"{k}_sub_new") or "").strip().replace("\\", "/")
    if not path:
        return
    if "/" not in path:
        path = f"{SUB_DIR}/{path}"
    if not Path(path).suffix:
        path += ".md"
    try:
        files.member_path_in(Path("x"), path)
    except ValueError as e:
        ss[f"{k}_sub_err"] = str(e)
        return
    ss.pop(f"{k}_sub_err", None)
    subs = ss.setdefault(f"{k}_subs", [])
    if path not in subs and path != "SKILL.md":
        subs.append(path)
    ss[f"{k}_sub_new"] = ""


def sub_files_editor(k: str) -> dict[str, str]:
    """Create extra files next to SKILL.md while adding a skill. Returns {relative path: content}."""
    ss = st.session_state
    ss.setdefault(f"{k}_subs", [])
    with st.container(border=True):
        st.markdown("**Sub-files** · split a big skill into smaller files that SKILL.md points to")
        st.caption(f"Link them from SKILL.md, e.g. `[hooks]({SUB_DIR}/hooks.md)`, so the agent loads them only when needed.")
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        c1.text_input("New file", key=f"{k}_sub_new", placeholder=f"{SUB_DIR}/hooks.md",
                      help="Folders are created for you. A bare name goes into the references/ folder.")
        c2.button("Add file", icon=":material/note_add:", key=f"{k}_sub_add", on_click=_add_sub, args=(k,),
                  use_container_width=True)
        if ss.get(f"{k}_sub_err"):
            st.error(ss[f"{k}_sub_err"], icon="❌")
        out = {}
        for path in list(ss[f"{k}_subs"]):
            with st.expander(path, expanded=True):
                out[path] = st.text_area("Content", key=f"{k}_subc_{path}", height=140, label_visibility="collapsed",
                                         placeholder="# Title\n\nDetails the agent reads only when SKILL.md points here.")
                if st.button("Remove", icon=":material/delete:", key=f"{k}_subx_{path}"):
                    ss[f"{k}_subs"].remove(path)
                    st.rerun()
    return out


def render_add(kind: str, data: dict) -> None:
    spec = SPECS[kind]
    nonce = st.session_state.setdefault(f"{kind}_nonce", 0)
    k = f"{kind}_add_{nonce}"
    st.caption(spec["hint"])
    tpl = template_picker(kind, k)
    c1, c2 = st.columns([1, 1])
    name = c1.text_input("Name", key=f"{k}_name", placeholder=f"e.g. My {spec['label']}")
    desc = c2.text_input("Description", key=f"{k}_desc")
    tags = common.tag_input("Tags", data, f"{k}_tags", extra=st.session_state.get(f"{k}_tpl_tags"))
    mode = st.radio("Source", ["Upload file", "Paste text"], horizontal=True, key=f"{k}_mode")
    content, filename, is_zip, subs = None, None, False, {}
    if mode == "Upload file":
        up = st.file_uploader("File", type=spec["upload"], key=f"{k}_file")
        if up:
            content, filename = up.getvalue(), up.name
            is_zip = up.name.lower().endswith(".zip")
    else:
        if kind == "mcp_servers":
            filename = st.text_input("Filename", key=f"{k}_fn", placeholder="server.py")
        if kind in MD_KINDS:
            content = content_editor(kind, f"{k}_text", "", f"{k}_name", f"{k}_desc",
                                     folder=templates.folder(tpl) if tpl else None, height=220)
        else:
            content = st.text_area("Content", key=f"{k}_text", height=220)
        if kind == "skills":
            if st.toggle("Split into sub-files", key=f"{k}_split", help="Creates a modular skill: SKILL.md plus a folder of files it links to."):
                subs = sub_files_editor(k)
    text = content.decode("utf-8", "replace") if isinstance(content, bytes) else (content or "")
    if is_zip:
        try:
            text = _zip_preview(content)
        except zipfile.BadZipFile:
            return common.fail("That file is not a valid zip archive.")
    if kind == "skills" and text:
        if mode == "Upload file":
            st.caption(f"{len(text):,} characters")
            show_quality(kind, text, name)
        token_warning(text, k)
    elif mode == "Upload file" and kind in MD_KINDS and text:
        show_quality(kind, text, name)
    if kind == "mcp_configs" and text.strip():
        fs = mcp_check.validate(text)
        if fs:
            with st.expander(f"Validation · {len(fs)} finding(s) — advisory, saving is not blocked",
                             icon=":material/rule:", expanded=True):
                common.show_findings(fs)
    if st.button(f"Save {spec['label']}", icon="💾", type="primary", key=f"{k}_save"):
        if not name.strip():
            return common.fail("Name is required.")
        if not text.strip():
            return common.fail("Provide a file or some content.")
        err = None if is_zip else _validate(kind, text)
        if err:
            return common.fail(err)
        try:
            tdir = templates.folder(tpl) if tpl and mode == "Paste text" else None
            if is_zip:
                _import_zip(data, kind, content, name, desc, tags)
            elif tdir or subs:  # modular: template extras and/or sub-files, with the (edited) SKILL.md on top
                with tempfile.TemporaryDirectory(prefix="loadout-tpl-") as tmp:
                    dst = Path(tmp) / "skill"
                    if tdir:
                        shutil.copytree(tdir, dst)
                    dst.mkdir(exist_ok=True)
                    (dst / "SKILL.md").write_text(text, encoding="utf-8")
                    for rel, body in subs.items():
                        files.write_file(files.member_path_in(dst, rel), body or f"# {Path(rel).stem}\n")
                    store.import_from_path(data, kind, dst, name, desc, tags)
            else:
                store.add_asset(data, kind, name, desc, tags, content, filename)
        except (ValueError, OSError) as e:
            return common.fail(str(e))
        st.session_state[f"{kind}_nonce"] += 1
        st.session_state["open_add"] = None
        common.done(f"{spec['label']} saved successfully!")


def render_used_by(refs: dict) -> None:
    n = sync.used_by_count(refs)
    if not n:
        return st.caption("Not used anywhere yet.")
    parts = [(len(refs["projects"]), "project"), (len(refs["agents"]), "preset"), (len(refs["loadouts"]), "loadout")]
    with st.expander("Used by " + " · ".join(f"{c} {w}{'s' if c != 1 else ''}" for c, w in parts if c),
                     icon=":material/account_tree:"):
        if refs["projects"]:
            st.markdown("**Projects:** " + ", ".join(f"{p['name']} _({p['target_model']})_" for p in refs["projects"]))
        if refs["agents"]:
            st.markdown("**Agent presets:** " + ", ".join(a["name"] for a in refs["agents"]))
        if refs["loadouts"]:
            st.markdown("**Loadouts:** " + ", ".join(
                lo["name"] + (f" _(via preset {via['name']})_" if via else "") for lo, via in refs["loadouts"]))


def render_item(kind: str, a: dict, data: dict, expanded: bool = False) -> None:
    spec = SPECS[kind]
    try:
        text = files.read_text(a["path"])
    except OSError:
        text = None
    over = kind == "skills" and text is not None and tokens.exceeds_limit(text)
    fs = mcp_check.check_asset(a) if kind == "mcp_configs" else []
    folder = files.unit_path(kind, a["path"]) if a.get("is_modular") else None
    is_bin = text is not None and "\x00" in text
    if kind in MD_KINDS and text is not None and not is_bin:
        fs = lint.lint(kind, text, name=a["name"], folder=folder)
    warn = mcp_check.actionable(fs)
    title = (f"{a['name']}" + ("  ⚠️" if over else "") + (f"  · ⚠ {len(warn)}" if warn else "")
             + ("  · modular" if a.get("is_modular") else ""))
    with st.expander(title, expanded=expanded):
        common.chips(a.get("tags", []), data)
        if a.get("description"):
            st.write(a["description"])
        st.caption(f"`{a['path']}`" + (f" · {len(text):,} chars" if text is not None else ""))
        if text is None:
            st.error("The stored file is missing from disk.")
        k = f"{kind}_{a['id']}"
        if a.get("source"):
            src = a["source"]
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            c1.caption(f":material/commit: From {src['url']} · `{src['path']}` @ `{(src.get('commit') or '')[:7]}`"
                       + (" · pinned" if src.get("pinned") else ""))
            with c2.popover("Unlink", icon=":material/link_off:", use_container_width=True):
                st.write("Stops tracking the repository. The asset stays in your library.")
                if st.button("Unlink source", key=f"{k}_unlink"):
                    updates.unlink(data, kind, a["id"])
                    common.done("Source unlinked.")
        refs = sync.used_by(data, kind, a["id"])
        render_used_by(refs)
        if fs and kind == "mcp_configs":
            with st.expander(f"Validation · {len(fs)} finding(s)", icon=":material/rule:", expanded=bool(warn)):
                common.show_findings(fs)
        if over:
            token_warning(text, k)
        c1, c2 = st.columns(2)
        name = c1.text_input("Name", a["name"], key=f"{k}_ename")
        desc = c2.text_input("Description", a.get("description", ""), key=f"{k}_edesc")
        tags = common.tag_input("Tags", data, f"{k}_tags", a.get("tags", []))
        new_text = None
        if text is not None and not is_bin:
            ckey = f"{k}_content_{zlib.crc32(text.encode('utf-8', 'replace')):x}"  # new file content → fresh editor
            if kind in MD_KINDS:
                new_text = content_editor(kind, ckey, text, f"{k}_ename", f"{k}_edesc", folder=folder)
            else:
                new_text = st.text_area("Content", text, height=260, key=ckey)
        if st.button("Save changes", icon="💾", key=f"{k}_save_edit"):
            err = _validate(kind, new_text) if new_text is not None else None
            if err:
                common.fail(err)
            else:
                try:
                    store.update_asset(data, kind, a["id"], name, desc, tags, new_text)
                    common.done("Changes saved!")
                except ValueError as e:
                    common.fail(str(e))
        if kind == "skills":
            sub_files_section(a, data, text, k)
        b1, b2, _ = st.columns([1, 1, 4])
        if text is not None:
            with b1:
                download_button(kind, a, k)
        with b2:
            delete_popover(kind, a, data, k, refs)


def download_button(kind: str, a: dict, k: str, **kw) -> None:
    """Single files download as-is; folder assets (skills with sub-files) download as a zip."""
    if a.get("is_modular") and files.unit_path(kind, a["path"]).is_dir():
        st.download_button("Download", files.zip_unit(kind, a["path"]), icon="⬇️", key=f"{k}_dl", mime="application/zip",
                           file_name=f"{files.unit_path(kind, a['path']).name}.zip", **kw)
    else:
        try:
            body = files.read_text(a["path"])
        except OSError:
            return st.button("Download", icon="⬇️", key=f"{k}_dl", disabled=True, **kw)
        st.download_button("Download", body, file_name=Path(a["path"]).name, icon="⬇️", key=f"{k}_dl", **kw)


def delete_popover(kind: str, a: dict, data: dict, k: str, refs: dict, **kw) -> None:
    with st.popover("Delete", icon="🗑️", **kw):
        if refs["projects"]:
            st.warning("Will also be removed from projects: " + ", ".join(p["name"] for p in refs["projects"]))
        if refs["agents"] or refs["loadouts"]:
            st.warning("Will be dropped from: " + ", ".join(
                [f"preset {x['name']}" for x in refs["agents"]]
                + [f"loadout {lo['name']}" for lo, _ in refs["loadouts"] if _ is None]))
        st.write("This permanently deletes the asset and its files.")
        if st.button("Confirm delete", type="primary", key=f"{k}_del"):
            sync.delete_asset_everywhere(data, kind, a["id"])
            if st.session_state.get(f"{kind}_edit") == a["id"]:
                st.session_state[f"{kind}_edit"] = None
            common.done(f"{SPECS[kind]['label']} deleted.", "🗑️")


# ---- sub-files of a modular skill -----------------------------------------------
def sub_files_section(a: dict, data: dict, main_text: str | None, k: str) -> None:
    names = files.unit_files("skills", a["path"])
    subs = [n for n in names if n != names[0]]
    refs = set(lint.references(lint.parse_frontmatter(main_text or "")[1] or main_text or ""))
    broken = sorted(r for r in refs if r not in names and not files.unit_path("skills", a["path"]).joinpath(r).exists())
    orphans = [n for n in subs if n not in refs]
    label = f"Sub-files · {len(subs)}" if subs else "Sub-files · none"
    with st.expander(label, icon=":material/folder_open:", expanded=bool(broken)):
        if not subs:
            st.caption("This skill is a single file. Add sub-files to split a big SKILL.md into smaller pieces "
                       "that it links to.")
        for n in subs:
            ok = n in refs
            st.markdown(f"{'🔗' if ok else '⚠️'} `{n}` <span class='muted'>"
                        f"{'linked from SKILL.md' if ok else 'not linked from SKILL.md — the agent will not find it'}</span>",
                        unsafe_allow_html=True)
        for r in broken:
            st.markdown(f"❌ `{r}` <span class='muted'>linked from SKILL.md but missing</span>", unsafe_allow_html=True)
        nonce = st.session_state.setdefault(f"{k}_subn", 0)
        editable = [n for n in subs if "\x00" not in files.member_path("skills", a["path"], n).read_text(errors="replace")]
        if editable:
            sel = st.selectbox("Edit a sub-file", editable, key=f"{k}_subsel_{nonce}")
            body = files.member_path("skills", a["path"], sel).read_text(encoding="utf-8", errors="replace")
            new = st.text_area("Content", body, height=240, key=f"{k}_subbody_{sel}_{zlib.crc32(body.encode('utf-8', 'replace')):x}",
                               label_visibility="collapsed")
            st.caption(f"{len(new):,} characters · ~{tokens.fmt(tokens.estimate(len(new)))} tokens")
            c1, c2, _ = st.columns([1, 1, 3])
            if c1.button("Save file", icon="💾", key=f"{k}_subsave"):
                store.write_member(data, "skills", a["id"], sel, new)
                common.done(f"{sel} saved.")
            if c2.button("Delete file", icon="🗑️", key=f"{k}_subdel"):
                store.delete_member(data, "skills", a["id"], sel)
                st.session_state[f"{k}_subn"] = nonce + 1
                common.done(f"{sel} deleted.", "🗑️")
        st.divider()
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        newp = c1.text_input("New sub-file", key=f"{k}_subnew_{nonce}", placeholder=f"{SUB_DIR}/hooks.md",
                             help="A bare name goes into the references/ folder; folders are created for you.")
        link = st.checkbox("Also link it from SKILL.md", value=True, key=f"{k}_sublink_{nonce}")
        if c2.button("Create file", icon=":material/note_add:", key=f"{k}_subcreate", use_container_width=True):
            path = newp.strip().replace("\\", "/")
            if not path:
                return common.fail("Give the new file a name.")
            path = path if "/" in path else f"{SUB_DIR}/{path}"
            path += "" if Path(path).suffix else ".md"
            try:
                if files.member_path("skills", a["path"], path).exists():
                    return common.fail(f"{path} already exists.")
                store.write_member(data, "skills", a["id"], path, f"# {Path(path).stem.replace('-', ' ').replace('_', ' ').title()}\n\n")
                if link:
                    cur = files.read_text(a["path"])
                    sep = "" if cur.endswith("\n") else "\n"
                    head = "" if "\n## References" in cur or cur.startswith("## References") else "\n## References\n\n"
                    store.update_asset(data, "skills", a["id"], a["name"], a.get("description", ""), a.get("tags", []),
                                       f"{cur}{sep}{head}- [{Path(path).stem}]({path})\n")
            except (ValueError, OSError) as e:
                return common.fail(str(e))
            st.session_state[f"{k}_subn"] = nonce + 1
            st.session_state[f"{k}_subsel_{nonce + 1}"] = path
            common.done(f"{path} created.")


# ---- skill cards -----------------------------------------------------------------
CARDS_PER_ROW = 3


def _edit(kind: str, id_: str | None) -> None:
    st.session_state[f"{kind}_edit"] = id_


def render_skill_card(a: dict, data: dict) -> None:
    kind, k = "skills", f"skills_{a['id']}"
    try:
        text = files.read_text(a["path"])
    except OSError:
        text = None
    n_files = len(files.unit_files(kind, a["path"])) if text is not None else 0
    badges = []
    if n_files > 1:
        badges.append(f"📁 {n_files} files")
    if text is not None and tokens.exceeds_limit(text):
        badges.append("⚠️ too large")
    if text is None:
        badges.append("❌ file missing")
    if a.get("source"):
        badges.append("🔗 git")
    with st.container(border=True):
        st.markdown(f"<div class='card-title'>{html.escape(a['name'])}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='card-desc'>{html.escape(a.get('description') or 'No description')}</div>",
                    unsafe_allow_html=True)
        common.chips(a.get("tags", []), data)
        st.caption(" · ".join(badges + ([f"~{tokens.fmt(tokens.estimate(len(text)))} tokens"] if text is not None else [])) or " ")
        b1, b2, b3 = st.columns(3)
        b1.button("Edit", icon=":material/edit:", key=f"{k}_edit", on_click=_edit, args=(kind, a["id"]),
                  use_container_width=True)
        with b2:
            download_button(kind, a, k, use_container_width=True)
        with b3:
            delete_popover(kind, a, data, k, sync.used_by(data, kind, a["id"]), use_container_width=True)


def render_skill_cards(items: list[dict], data: dict) -> None:
    for start in range(0, len(items), CARDS_PER_ROW):
        cols = st.columns(CARDS_PER_ROW)
        for col, a in zip(cols, items[start:start + CARDS_PER_ROW]):
            with col:
                render_skill_card(a, data)


def render_tab(kind: str, data: dict) -> None:
    spec = SPECS[kind]
    if kind == "skills":
        fid = nav.focused(kind)
        if fid:   # opened from search / palette: go straight to the editor
            _edit(kind, fid)
            st.session_state["focus"] = None
        editing = next((a for a in data[kind] if a["id"] == st.session_state.get(f"{kind}_edit")), None)
        if editing:
            st.button("All skills", icon=":material/arrow_back:", key="skills_back", on_click=_edit, args=(kind, None))
            return render_item(kind, editing, data, expanded=True)
    with st.expander(f"Add {spec['label']}", icon="➕",
                     expanded=not data[kind] or st.session_state.get("open_add") == kind):
        render_add(kind, data)
    q, tags = common.filter_bar(kind, data)
    items = [a for a in data[kind] if store.matches(a, q, tags)]
    items = nav.focus_first(kind, data[kind], items)
    st.caption(f"{len(items)} of {len(data[kind])} {spec['label'].lower()}(s)")
    if not data[kind]:
        common.empty_state(f"No {spec['label'].lower()}s yet", "Add your first one above.", "🗂️")
    elif not items:
        common.empty_state("Nothing matches your filters", icon="🔍")
    if kind == "skills":
        return render_skill_cards(items, data)
    for a in items:
        render_item(kind, a, data, expanded=a["id"] == nav.focused(kind))
