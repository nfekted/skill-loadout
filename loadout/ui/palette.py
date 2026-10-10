"""Command palette (Ctrl/Cmd+K) and keyboard shortcuts."""
import streamlit as st

from .. import store, sync
from . import common, nav

KIND_LABEL = {"skills": "Skill", "roles": "Role", "rules": "Rule", "mcp_configs": "MCP Config",
              "mcp_servers": "MCP Server", "agents": "Agent preset", "loadouts": "Loadout",
              "utilities": "Utility", "projects": "Project"}
KIND_ICON = {"skills": "🧠", "roles": "🎭", "rules": "📏", "mcp_configs": "🔌", "mcp_servers": "🔌",
             "agents": "🤖", "loadouts": "🎒", "utilities": "🔗", "projects": "📁"}
PER_KIND = 4
SHORTCUTS = [("Ctrl/⌘ + K", "Open the command palette"), ("/", "Focus global search"),
             ("g then d / p / l / e / s / r / m / u / i / t", "Go to Dashboard / Projects / Loadouts / Templates / Skills / "
              "Rules & Roles / MCP / Utilities / Import-Export / Settings")]


def _add_project() -> None:
    nav.go_page("Projects")
    st.session_state["project_id"] = None
    st.session_state["show_add_project"] = True


def _resync_outdated() -> None:
    data = store.load()
    n = sum(sync.resync_stale(p, data) for p in data["projects"] if sync.path_exists(p))
    store.save(data)
    common.notify(f"Refreshed {n} outdated asset(s).", "🔁")


def commands(pages: list[str]) -> list[tuple[str, str, object]]:
    """(label, icon, action) — actions only mutate session state, so the caller reruns afterwards."""
    cmds = [(f"Go to {p}", "➡️", (lambda p=p: nav.go_page(p))) for p in pages]
    cmds += [("Add project", "➕", _add_project),
             ("Browse templates", "📋", lambda: nav.go_page("Templates")),
             ("Check Git updates", "🌐", lambda: nav.go_page("Import/Export")),
             ("Validate MCP configs", "🔌", lambda: nav.go_page("MCP Store")),
             ("Re-sync all outdated copies", "🔁", _resync_outdated)]
    return cmds


def match_commands(cmds: list, query: str) -> list:
    words = query.lower().split()
    return [c for c in cmds if all(w in c[0].lower() for w in words)]


def match_entities(data: dict, query: str) -> dict[str, list[dict]]:
    res = store.search(data, query)
    return {k: v[:PER_KIND] for k, v in res.items()}


@st.dialog("Command palette", width="large")
def dialog(pages: list[str]) -> None:
    data = store.load()
    q = st.text_input("Command or search", key="palette_q", placeholder="Type a command, or search skills, rules, projects…",
                      label_visibility="collapsed", icon=":material/terminal:")
    cmds = match_commands(commands(pages), q)
    ents = match_entities(data, q) if q.strip() else {}
    if not q.strip():
        cmds = cmds[:6]
    if cmds:
        st.caption("COMMANDS")
        for i, (label, icon, action) in enumerate(cmds):
            if st.button(label, icon=icon, key=f"pal_cmd_{i}", use_container_width=True, type="tertiary"):
                action()
                st.session_state.pop("palette_q", None)
                st.rerun()
    for kind, items in ents.items():
        st.caption(KIND_LABEL[kind].upper() + "S")
        for e in items:
            if st.button(e["name"], icon=KIND_ICON[kind], key=f"pal_{kind}_{e['id']}", use_container_width=True,
                         type="tertiary", help=e.get("description") or None):
                nav.go(kind, e["id"])
                st.session_state.pop("palette_q", None)
                st.rerun()
    if q.strip() and not cmds and not ents:
        common.empty_state("No matches", "Try another word.", "🔍")
    if not q.strip():
        st.divider()
        for keys, what in SHORTCUTS:
            st.caption(f"`{keys}` — {what}")


def install_shortcuts(pages: list[str]) -> None:
    """Keyboard shortcuts: JS clicks the real Streamlit buttons, so all logic stays in Python."""
    idx = {k: pages.index(p) for k, p in nav.GOTO_KEYS.items() if p in pages}
    st.html(f"""<script>
(() => {{
  const map = {idx!r};
  const st = window.__loadoutKeys || (window.__loadoutKeys = {{g: 0}});
  st.map = map;
  if (st.bound) return;
  st.bound = true;
  const typing = (t) => t && (['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.isContentEditable);
  const click = (sel, n = 0) => {{ const b = document.querySelectorAll(sel)[n]; if (b) b.click(); }};
  document.addEventListener('keydown', (e) => {{
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {{
      e.preventDefault(); click('.st-key-open_palette button'); return;
    }}
    if (typing(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === '/') {{
      const i = document.querySelector('input[aria-label="Global search"]');
      if (i) {{ e.preventDefault(); i.focus(); }}
      return;
    }}
    const k = e.key.toLowerCase();
    if (st.g && Date.now() - st.g < 1500) {{
      st.g = 0;
      if (k in st.map) {{ e.preventDefault(); click('[class*="st-key-nav_"] button', st.map[k]); }}
      return;
    }}
    if (k === 'g') st.g = Date.now();
  }});
}})();
</script>""", unsafe_allow_javascript=True)
