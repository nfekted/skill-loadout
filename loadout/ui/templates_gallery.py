"""Templates gallery: browse the built-in starters and jump to the matching 'Add' form pre-filled."""
import streamlit as st

from .. import templates
from . import assets, common, nav

KIND_LABEL = {"skills": "Skills", "rules": "Rules", "roles": "Roles", "mcp_configs": "MCP Configs"}
KIND_ICON = {"skills": "🧠", "rules": "📏", "roles": "🎭", "mcp_configs": "🔌"}
PER_ROW = 3


def render(data: dict) -> None:
    st.header("Templates", divider="gray")
    st.caption("Built-in starting points. “Use template” opens the Add form pre-filled — "
               "edit it freely; the template itself never changes.")
    c1, c2 = st.columns([3, 2])
    q = c1.text_input("Search templates", key="tpl_q", placeholder="Search templates…", label_visibility="collapsed",
                      icon=":material/search:")
    kinds = c2.multiselect("Type", list(KIND_LABEL), format_func=KIND_LABEL.get, key="tpl_kinds",
                           placeholder="Filter by type", label_visibility="collapsed")
    ql = q.strip().lower()
    items = [t for t in templates.all_templates()
             if (not kinds or t["kind"] in kinds)
             and (not ql or all(w in " ".join([t["name"], t["description"], *t["tags"]]).lower() for w in ql.split()))]
    if not items:
        return common.empty_state("No template matches your search", icon="🔍")
    for start in range(0, len(items), PER_ROW):
        for col, t in zip(st.columns(PER_ROW), items[start:start + PER_ROW]):
            with col:
                render_card(t, data)


def render_card(t: dict, data: dict) -> None:
    with st.container(border=True):
        st.markdown(f"**{KIND_ICON[t['kind']]} {t['name']}**")
        st.caption(KIND_LABEL[t["kind"]][:-1] + (" · modular" if templates.folder(t) else ""))
        st.write(t["description"])
        common.chips(t["tags"], data)
        with st.expander("Preview"):
            st.code(templates.raw_text(t), language="json" if t["kind"] == "mcp_configs" else "markdown",
                    wrap_lines=True, height=220)
            extra = templates.extra_files(t)
            if extra:
                st.caption("Also includes: " + ", ".join(f"`{e}`" for e in extra))
        if st.button("Use template", icon=":material/note_add:", key=f"tpl_use_{t['id']}", type="primary",
                     use_container_width=True):
            nav.go_page(nav.PAGE_OF[t["kind"]])
            assets.use_template(t["kind"], t["id"])
            st.rerun()
