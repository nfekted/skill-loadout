"""Settings page + Tags Manager."""
import re

import streamlit as st

from .. import config, store
from . import common


def render(data: dict) -> None:
    st.header("Settings", divider="gray")
    t1, t2 = st.tabs(["Tags Manager", "Storage"])
    with t1:
        render_tags(data)
    with t2:
        c = st.columns(4)
        c[0].metric("Skills", len(data["skills"]))
        c[1].metric("Rules / Roles", f"{len(data['rules'])} / {len(data['roles'])}")
        c[2].metric("MCP items", len(data["mcp_configs"]) + len(data["mcp_servers"]))
        c[3].metric("Projects", len(data["projects"]))
        st.write("**Storage location**")
        st.code(str(config.home()), language=None)
        st.caption("Metadata lives in `data.json`; asset files live in `skills/`, `rules/`, `roles/`, "
                   "`mcp_configs/` and `mcp_servers/` next to it.")
        if st.button("Reload data from disk", icon="🔄"):
            st.rerun()


def render_tags(data: dict) -> None:
    st.caption("Create tags and pick a custom color. Tags also appear automatically when you type new ones on an asset.")
    with st.form("tag_add", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 1, 1])
        name = c1.text_input("Tag name", placeholder="e.g. frontend")
        color = c2.color_picker("Color", "#3B82F6")
        c3.write("")
        c3.write("")
        if c3.form_submit_button("Add Tag", icon="➕", type="primary"):
            n = name.strip().lower()
            if not n:
                common.fail("Tag name is required.")
            elif any(t["name"] == n for t in data["tags"]):
                common.fail(f"Tag '{n}' already exists.")
            else:
                data["tags"].append({"name": n, "color": color})
                store.save(data)
                common.done("Tag created!")
    if not data["tags"]:
        return common.empty_state("No tags yet", "Create your first tag above.", "🏷️")
    use = store.tag_usage(data)
    for t in list(data["tags"]):
        c = st.columns([2, 1, 1, 1, 1])
        c[0].markdown(common.chips_html([t["name"]], data) + f" <span class='muted'>{use.get(t['name'], 0)} use(s)</span>",
                      unsafe_allow_html=True)
        new_name = c[1].text_input("Rename", t["name"], key=f"tn_{t['name']}", label_visibility="collapsed")
        new_color = c[2].color_picker("Color", t["color"], key=f"tc_{t['name']}", label_visibility="collapsed")
        if c[3].button("Save", icon="💾", key=f"ts_{t['name']}"):
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", new_color):
                common.fail("Color must be a hex code like #3B82F6.")
            else:
                try:
                    t["color"] = new_color
                    store.rename_tag(data, t["name"], new_name)
                    store.save(data)
                    common.done("Tag updated!")
                except ValueError as e:
                    common.fail(str(e))
        if c[4].button("Delete", icon="🗑️", key=f"td_{t['name']}"):
            store.delete_tag(data, t["name"])
            common.done("Tag deleted.", "🗑️")
