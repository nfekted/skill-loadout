"""Global search results."""
import streamlit as st

from .. import store
from . import common, nav

LABELS = {"skills": "Skills", "roles": "Roles", "rules": "Rules", "mcp_configs": "MCP Configs",
          "mcp_servers": "MCP Servers", "agents": "Agent Presets", "loadouts": "Loadouts", "utilities": "Utilities", "projects": "Projects"}
PAGES = nav.PAGE_OF


def render(data: dict, query: str, tags: list[str]) -> None:
    res = store.search(data, query, tags)
    st.subheader(f"Search results ({sum(map(len, res.values()))})")
    if not res:
        return common.empty_state("No results", "Try a different term or fewer tags.", "🔍")
    for kind, items in res.items():
        st.markdown(f"**{LABELS[kind]}** · {len(items)}  <span class='muted'>→ {PAGES[kind]}</span>",
                    unsafe_allow_html=True)
        for e in items:
            c1, c2, c3 = st.columns([2, 3, 1], vertical_alignment="center")
            c1.write(e["name"])
            if c3.button("Open", icon=":material/arrow_forward:", key=f"sr_{kind}_{e['id']}", use_container_width=True,
                         help=f"Go to {PAGES[kind]}"):
                nav.go(kind, e["id"])
                st.rerun()
            with c2:
                st.markdown(common.chips_html(e.get("tags", []), data) or "<span class='muted'>no tags</span>",
                            unsafe_allow_html=True)
                if e.get("description"):
                    st.caption(e["description"])
        st.divider()
