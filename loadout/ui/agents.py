"""Agent presets: named bundles of rules, roles and skills."""
import streamlit as st

from .. import store, sync
from . import common, nav


def _names(data, key):
    return {a["id"]: a["name"] for a in data[key]}


def render(data: dict) -> None:
    st.caption("Group existing rules, roles and skills into one reusable preset, then attach it to a project in one click.")
    maps = {k: _names(data, k) for k in ("rules", "roles", "skills")}
    with st.expander("Create Agent Preset", icon="➕", expanded=not data["agents"]):
        n = st.session_state.setdefault("agent_nonce", 0)
        name = st.text_input("Name", key=f"ag_name_{n}", placeholder="e.g. Fullstack Agent")
        desc = st.text_input("Description", key=f"ag_desc_{n}")
        sel = {k: st.multiselect(k.capitalize(), list(m), format_func=m.get, key=f"ag_{k}_{n}")
               for k, m in maps.items()}
        if st.button("Save Agent Preset", icon="💾", type="primary", key=f"ag_save_{n}"):
            if not name.strip():
                common.fail("Name is required.")
            else:
                store.add_entity(data, "agents", {"name": name.strip(), "description": desc.strip(), **sel})
                st.session_state["agent_nonce"] += 1
                common.done("Agent preset saved!")
    q = st.text_input("Search presets", key="ag_q", placeholder="Search presets…", label_visibility="collapsed",
                      icon=":material/search:")
    shown = nav.focus_first("agents", data["agents"], [a for a in data["agents"] if store.matches(a, q)])
    if not data["agents"]:
        common.empty_state("No agent presets yet", icon="🤖")
    for a in shown:
        with st.expander(a["name"], expanded=a["id"] == nav.focused("agents")):
            if a.get("description"):
                st.write(a["description"])
            with st.form(f"ag_edit_{a['id']}"):
                name = st.text_input("Name", a["name"])
                desc = st.text_input("Description", a.get("description", ""))
                sel = {}
                for k, m in maps.items():
                    sel[k] = st.multiselect(k.capitalize(), list(m), default=[i for i in a.get(k, []) if i in m],
                                            format_func=m.get, key=f"ag_{a['id']}_{k}")
                if st.form_submit_button("Save changes", icon="💾"):
                    store.update_entity(data, "agents", a["id"], name=name.strip() or a["name"],
                                        description=desc.strip(), **sel)
                    common.done("Preset updated!")
            with st.popover("Delete", icon="🗑️"):
                los = sync.agent_used_by(data, a["id"])
                if los:
                    st.warning("Will be removed from loadouts: " + ", ".join(lo["name"] for lo in los))
                if st.button("Confirm delete", type="primary", key=f"ag_del_{a['id']}"):
                    store.delete_entity(data, "agents", a["id"])
                    common.done("Preset deleted.", "🗑️")
