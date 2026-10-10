"""Loadouts: reusable bundles of skills, rules, roles, MCP and agent presets, attachable to a project at once."""
import streamlit as st

from .. import store, sync
from . import common, nav

FIELDS = [("skills", "Skills"), ("rules", "Rules"), ("roles", "Roles"), ("mcp_configs", "MCP Configs"),
          ("mcp_servers", "MCP Servers"), ("agents", "Agent Presets")]


def _maps(data):
    return {k: {a["id"]: a["name"] for a in data[k]} for k, _ in FIELDS}


def _pickers(data, maps, prefix, current=None):
    sel = {}
    cols = st.columns(2)
    for n, (k, label) in enumerate(FIELDS):
        m = maps[k]
        default = [i for i in (current or {}).get(k, []) if i in m]
        sel[k] = cols[n % 2].multiselect(label, list(m), default=default, format_func=m.get,
                                         key=f"{prefix}_{k}", placeholder=f"Pick {label.lower()}")
    return sel


def render(data: dict) -> None:
    st.header("Loadouts", divider="gray")
    st.caption("A Loadout is a named bundle (e.g. “Front-end standard”). Attach it to a project and everything "
               "inside — skills, rules, roles, MCP and agent presets — is added at once.")
    maps = _maps(data)
    if not any(maps.values()):
        return common.empty_state("Your library is empty", "Add skills, rules, MCP or agents first, then bundle them here.", "🗂️")
    with st.expander("Create Loadout", icon="➕", expanded=not data["loadouts"]):
        n = st.session_state.setdefault("lo_nonce", 0)
        c1, c2 = st.columns(2)
        name = c1.text_input("Name", key=f"lo_name_{n}", placeholder="e.g. Front-end standard")
        desc = c2.text_input("Description", key=f"lo_desc_{n}")
        tags = common.tag_input("Tags", data, f"lo_tags_{n}")
        sel = _pickers(data, maps, f"lo_new_{n}")
        if st.button("Save Loadout", icon="💾", type="primary", key=f"lo_save_{n}"):
            if not name.strip():
                common.fail("Name is required.")
            elif not any(sel.values()):
                common.fail("Pick at least one item for the loadout.")
            else:
                store.add_entity(data, "loadouts", {"name": name.strip(), "description": desc.strip(),
                                                    "tags": tags, **sel})
                st.session_state["lo_nonce"] += 1
                common.done("Loadout saved!")
    q, tags = common.filter_bar("lo", data)
    items = nav.focus_first("loadouts", data["loadouts"], [lo for lo in data["loadouts"] if store.matches(lo, q, tags)])
    if not data["loadouts"]:
        return common.empty_state("No loadouts yet", "Create your first bundle above.", "🎒")
    if not items:
        return common.empty_state("Nothing matches your filters", icon="🔍")
    for lo in items:
        render_item(lo, data, maps)


def render_item(lo: dict, data: dict, maps: dict) -> None:
    total = len(sync.loadout_items(data, lo))
    with st.expander(f"🎒 {lo['name']}  ·  {total} asset(s)", expanded=lo["id"] == nav.focused("loadouts")):
        common.chips(lo.get("tags", []), data)
        if lo.get("description"):
            st.write(lo["description"])
        for k, label in FIELDS:
            names = [maps[k][i] for i in lo.get(k, []) if i in maps[k]]
            if names:
                st.markdown(f"**{label}:** " + ", ".join(names))
        with st.form(f"lo_edit_{lo['id']}"):
            c1, c2 = st.columns(2)
            name = c1.text_input("Name", lo["name"])
            desc = c2.text_input("Description", lo.get("description", ""))
            tags = common.tag_input("Tags", data, f"lo_{lo['id']}_tags", lo.get("tags", []))
            sel = _pickers(data, maps, f"lo_{lo['id']}", lo)
            if st.form_submit_button("Save changes", icon="💾"):
                if not name.strip():
                    common.fail("Name is required.")
                else:
                    store.update_entity(data, "loadouts", lo["id"], name=name.strip(), description=desc.strip(),
                                        tags=tags, **sel)
                    common.done("Loadout updated!")
        if data["projects"]:
            with st.container(border=True):
                st.write("**Apply to projects**")
                pm = {p["id"]: p["name"] for p in data["projects"]}
                c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
                pids = c1.multiselect("Projects", list(pm), format_func=pm.get, key=f"lo_{lo['id']}_proj",
                                      label_visibility="collapsed", placeholder="Pick one or more projects")
                if c2.button("Attach", icon="🚀", key=f"lo_{lo['id']}_apply", use_container_width=True,
                             disabled=not (total and pids)):
                    new = already = 0
                    skipped = []
                    for pid in pids:
                        project = store.find(data, "projects", pid)
                        if not sync.path_exists(project):
                            skipped.append(project["name"])
                            continue
                        n, a = sync.attach_loadout(project, data, lo)
                        new, already = new + n, already + a
                    store.save(data)
                    if skipped:
                        common.notify("Folder not found, skipped: " + ", ".join(skipped), "⚠️")
                    common.done(f"Loadout attached to {len(pids) - len(skipped)} project(s) "
                                f"({new} new, {already} already present).")
        with st.popover("Delete", icon="🗑️"):
            st.write("Deletes only the bundle. The assets themselves are kept.")
            if st.button("Confirm delete", type="primary", key=f"lo_del_{lo['id']}"):
                store.delete_entity(data, "loadouts", lo["id"])
                common.done("Loadout deleted.", "🗑️")
