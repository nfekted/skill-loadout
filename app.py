"""SKILL LOADOUT — manage AI-agent skills, rules, roles and MCP assets, and sync them into projects."""
import streamlit as st

from loadout import config, store
from loadout.ui import common, dashboard, import_export, loadouts, mcp, nav, palette, projects, rules_roles, search, settings, skills, templates_gallery, utilities

st.set_page_config(page_title="Skill Loadout", page_icon="🎒", layout="wide")
st.markdown(common.CSS, unsafe_allow_html=True)
common.flush_toasts()

PAGES = {
    "Dashboard": ("📊", dashboard.render),
    "Projects": ("📁", projects.render),
    "Loadouts": ("🎒", loadouts.render),
    "Templates": ("📋", templates_gallery.render),
    "Skills Library": ("🧠", skills.render),
    "Rules & Roles": ("📏", rules_roles.render),
    "MCP Store": ("🔌", mcp.render),
    "Utilities": ("🔗", utilities.render),
    "Import/Export": ("📦", import_export.render),
    "Settings": ("⚙️", settings.render),
}

try:
    data = store.load()
except store.DataError as e:
    st.error(str(e), icon="❌")
    st.stop()

with st.sidebar:
    st.title("🎒 Skill Loadout")
    st.caption("Your AI agent asset library")
    st.session_state.setdefault("page", next(iter(PAGES)))
    for name, (icon, _) in PAGES.items():
        active = st.session_state["page"] == name
        if st.button(name, icon=icon, key=f"nav_{name}", use_container_width=True,
                     type="primary" if active else "tertiary"):
            nav.go_page(name)
            st.rerun()
    page = st.session_state["page"]
    st.divider()
    if st.button("Command palette", icon=":material/terminal:", key="open_palette", use_container_width=True,
                 help="Ctrl/⌘ + K"):
        palette.dialog(list(PAGES))
    palette.install_shortcuts(list(PAGES))
    st.caption(f"{len(data['skills'])} skills · {len(data['rules']) + len(data['roles'])} rules/roles · "
               f"{len(data['mcp_configs']) + len(data['mcp_servers'])} MCP · {len(data['projects'])} projects")
    st.caption(f"Storage: `{config.home()}`")

nav.apply_pending_search_reset()
c1, c2 = st.columns([3, 2])
query = c1.text_input("Global search", key="gsearch", placeholder="Search everything by name, description or tag…",
                      label_visibility="collapsed", icon=":material/search:")
gtags = c2.multiselect("Tags", [t["name"] for t in data["tags"]], key="gtags", placeholder="Filter by tags",
                       label_visibility="collapsed")

if query.strip() or gtags:
    search.render(data, query, gtags)
else:
    PAGES[page][1](data)
