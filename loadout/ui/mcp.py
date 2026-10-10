import streamlit as st

from .. import mcp_check
from . import assets, common, nav


def render(data: dict) -> None:
    st.header("MCP Store", divider="gray")
    report = mcp_check.library_report(data)
    if report:
        names = {a["id"]: a["name"] for a in data["mcp_configs"]}
        total = sum(map(len, report.values()))
        with st.expander(f"Validation summary · {total} warning(s) in {len(report)} config(s)",
                         icon=":material/rule:"):
            for cid, fs in report.items():
                st.markdown(f"**{names[cid]}**")
                common.show_findings(fs)
    t1, t2 = st.tabs(["MCP Configs", "MCP Servers"], default=nav.default_tab(["mcp_configs", "mcp_servers"]))
    with t1:
        assets.render_tab("mcp_configs", data)
    with t2:
        assets.render_tab("mcp_servers", data)
