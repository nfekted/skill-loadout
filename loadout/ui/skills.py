import streamlit as st

from . import assets


def render(data: dict) -> None:
    st.header("Skills Library", divider="gray")
    assets.render_tab("skills", data)
