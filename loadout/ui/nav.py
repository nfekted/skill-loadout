"""Navigation helpers shared by the sidebar, search results and the command palette."""
import streamlit as st

# Where each kind of entity lives, and which tab shows it on that page.
PAGE_OF = {"skills": "Skills Library", "roles": "Rules & Roles", "rules": "Rules & Roles",
           "agents": "Rules & Roles", "loadouts": "Loadouts", "mcp_configs": "MCP Store",
           "mcp_servers": "MCP Store", "utilities": "Utilities", "projects": "Projects"}
TAB_OF = {"rules": "Rules", "roles": "Roles", "agents": "Agent Presets",
          "mcp_configs": "MCP Configs", "mcp_servers": "MCP Servers"}
# "g" then a letter jumps to a page (Gmail/GitHub style).
GOTO_KEYS = {"d": "Dashboard", "p": "Projects", "l": "Loadouts", "s": "Skills Library", "r": "Rules & Roles",
             "m": "MCP Store", "e": "Templates", "u": "Utilities", "i": "Import/Export", "t": "Settings"}


def go_page(page: str) -> None:
    """Switch page, dropping any focused item and active global search. Safe to call from any run."""
    st.session_state["page"] = page
    st.session_state["focus"] = None
    st.session_state["open_add"] = None
    st.session_state["_clear_search"] = True


def go(kind: str, id_: str) -> None:
    """Jump straight to an entity: projects are loaded, everything else is shown first and expanded."""
    go_page(PAGE_OF[kind])
    if kind == "projects":
        st.session_state["project_id"] = id_
    else:
        st.session_state["project_id"] = None
        st.session_state["focus"] = (kind, id_)


def apply_pending_search_reset() -> None:
    """Must run before the global search widgets are created."""
    if st.session_state.pop("_clear_search", False):
        st.session_state["gsearch"] = ""
        st.session_state["gtags"] = []


def focused(kind: str) -> str | None:
    f = st.session_state.get("focus")
    return f[1] if f and f[0] == kind else None


def default_tab(kinds: list[str]) -> str | None:
    f = st.session_state.get("focus")
    if f and f[0] in kinds:
        return TAB_OF.get(f[0])
    add = st.session_state.get("open_add")
    return TAB_OF.get(add) if add in kinds else None


def focus_first(kind: str, all_items: list[dict], shown: list[dict]) -> list[dict]:
    """Put the focused item first (even if filters hide it) and show a banner to clear the focus."""
    fid = focused(kind)
    if not fid:
        return shown
    item = next((a for a in all_items if a["id"] == fid), None)
    if not item:
        return shown
    c1, c2 = st.columns([5, 1], vertical_alignment="center")
    c1.info(f"Showing **{item['name']}** first.", icon=":material/my_location:")
    if c2.button("Clear", key=f"focus_clear_{kind}", use_container_width=True):
        st.session_state["focus"] = None
        st.rerun()
    return [item] + [a for a in shown if a["id"] != fid]
