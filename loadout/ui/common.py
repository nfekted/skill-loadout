"""Shared UI helpers: toasts, tag chips, empty states, filter bar, copy button."""
import html
import json

import streamlit as st
import streamlit.components.v1 as components

from .. import folder_picker, store

CSS = """
<style>
.block-container {padding-top: 4.5rem; padding-bottom: 2rem; max-width: 1200px;}
.chip {display:inline-block; padding:1px 9px; margin:0 4px 2px 0; border-radius:999px;
       font-size:0.74rem; font-weight:600; line-height:1.5; letter-spacing:.01em;}
.card-title {font-size:1.25rem; font-weight:700; line-height:1.3; margin:0 0 .15rem 0; word-break:break-word;}
.card-desc {opacity:.8; font-size:.9rem; margin:.2rem 0 .5rem 0; display:-webkit-box; -webkit-line-clamp:3;
            -webkit-box-orient:vertical; overflow:hidden; min-height:3.9em;}
.muted {color: var(--text-color); opacity:.6; font-size:.85rem;}
div[data-testid="stExpander"] summary p {font-weight:600;}
[data-testid="stSidebar"] .stButton button {justify-content:flex-start; text-align:left; padding:.45rem .75rem;}
[data-testid="stSidebar"] .stButton button[kind="tertiary"]:hover {background: rgba(128,128,128,.15);}
.stDeployButton, [data-testid="stAppDeployButton"] {display:none !important;}
</style>
"""


def _text_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#fff"
    return "#111" if (0.299 * r + 0.587 * g + 0.114 * b) > 160 else "#fff"


def chips_html(tags: list[str], data: dict) -> str:
    out = []
    for t in tags:
        c = store.tag_color(data, t)
        out.append(f'<span class="chip" style="background:{html.escape(c)};color:{_text_color(c)}">{html.escape(t)}</span>')
    return "".join(out)


def chips(tags: list[str], data: dict) -> None:
    if tags:
        st.markdown(chips_html(tags, data), unsafe_allow_html=True)


# Toasts queued before st.rerun() would be lost, so they are flushed at the top of each run.
def notify(msg: str, icon: str = "✅") -> None:
    st.session_state.setdefault("_toasts", []).append((msg, icon))


def flush_toasts() -> None:
    for msg, icon in st.session_state.pop("_toasts", []):
        st.toast(msg, icon=icon)


def done(msg: str, icon: str = "✅") -> None:
    notify(msg, icon)
    st.rerun()


def fail(msg: str) -> None:
    st.error(msg, icon="❌")
    st.toast(msg, icon="❌")


LEVEL_ICON = {"error": "🔴", "warning": "🟠", "info": "🔵"}


def findings_md(findings: list[dict]) -> str:
    lines = []
    for f in findings:
        who = f"**{f['server']}** — " if f.get("server") else ""
        lines.append(f"- {LEVEL_ICON[f['level']]} {who}{f['message']}")
    return "\n".join(lines)


def show_findings(findings: list[dict]) -> None:
    if findings:
        st.markdown(findings_md(findings))


def empty_state(title: str, hint: str = "", icon: str = "📭") -> None:
    st.markdown(f"<div style='text-align:center;padding:2rem 0;opacity:.75'><div style='font-size:2rem'>{icon}</div>"
                f"<b>{html.escape(title)}</b><br><span class='muted'>{html.escape(hint)}</span></div>",
                unsafe_allow_html=True)


def filter_bar(key: str, data: dict, placeholder: str = "Search by name, description or tag…"):
    c1, c2 = st.columns([3, 2])
    q = c1.text_input("Search", key=f"{key}_q", placeholder=placeholder, label_visibility="collapsed",
                      icon=":material/search:")
    tags = c2.multiselect("Filter by tags", [t["name"] for t in data["tags"]], key=f"{key}_tags",
                          placeholder="Filter by tags", label_visibility="collapsed")
    return q, tags


def tag_input(label: str, data: dict, key: str, default: list[str] | None = None,
              extra: list[str] | None = None) -> list[str]:
    """`extra` adds selectable options without selecting them (e.g. tags pre-filled through session state)."""
    opts = sorted({t["name"] for t in data["tags"]} | set(default or []) | set(extra or []))
    return st.multiselect(label, opts, default=default or [], key=key, accept_new_options=True,
                          placeholder="Pick or type new tags")


def copy_button(text: str, label: str = "Copy Prompt") -> None:
    """One-click clipboard button (Streamlit has no native clipboard API)."""
    payload = json.dumps(text).replace("</", "<\\/")
    components.html(f"""
<button id="b" style="font:600 14px system-ui;padding:6px 14px;border-radius:8px;border:1px solid #8884;
background:#8881;cursor:pointer;color:inherit">📋 {label}</button>
<script>
const t = {payload}, b = document.getElementById('b');
function fallback(){{const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();
  try{{document.execCommand('copy');}}catch(e){{}}document.body.removeChild(a);}}
b.onclick = async () => {{
  try {{ await navigator.clipboard.writeText(t); }} catch(e) {{ fallback(); }}
  b.textContent = '✅ Copied!'; setTimeout(() => b.textContent = '📋 {label}', 1800);
}};
</script>""", height=44)


def path_input(label: str, key: str, value: str = "", placeholder: str = "") -> str:
    """Text input with a Browse… button that opens the OS folder chooser."""
    if key not in st.session_state:
        st.session_state[key] = value
    c1, c2 = st.columns([5, 1], vertical_alignment="bottom")

    def browse():
        path, err = folder_picker.pick_folder()
        if path:
            st.session_state[key] = path
        elif err:
            notify(err, "⚠️")

    c2.button("Browse…", icon="📂", key=f"{key}_browse", on_click=browse, use_container_width=True,
              help="Open the system folder chooser")
    return c1.text_input(label, key=key, placeholder=placeholder)
