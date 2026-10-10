import streamlit as st

from . import agents, assets, nav


def render(data: dict) -> None:
    st.header("Rules & Roles", divider="gray")
    t1, t2, t3 = st.tabs(["Rules", "Roles", "Agent Presets"], default=nav.default_tab(["rules", "roles", "agents"]))
    with t1:
        assets.render_tab("rules", data)
    with t2:
        assets.render_tab("roles", data)
    with t3:
        agents.render(data)
