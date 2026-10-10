"""Dashboard: what needs attention across projects and the library."""
import streamlit as st

from .. import files, lint, mcp_check, store, sync, tokens
from . import common, projects

LABELS = {"skills": "Skill", "rules": "Rule", "roles": "Role", "mcp_configs": "MCP Config", "mcp_servers": "MCP Server"}


def oversized_skills(data: dict) -> list[dict]:
    out = []
    for a in data["skills"]:
        try:
            if tokens.exceeds_limit(files.read_text(a["path"])):
                out.append(a)
        except (OSError, ValueError):
            pass
    return out


def quality_report(data: dict) -> list[tuple[str, dict, list[dict]]]:
    """Skills, rules and roles with actionable lint findings: (kind, asset, findings)."""
    out = []
    for kind in lint_kinds():
        for a in data[kind]:
            try:
                text = files.read_text(a["path"])
                folder = files.unit_path(kind, a["path"]) if a.get("is_modular") else None
            except (OSError, ValueError):
                continue
            fs = lint.actionable(lint.lint(kind, text, name=a["name"], folder=folder))
            if fs:
                out.append((kind, a, fs))
    return out


def lint_kinds() -> tuple[str, ...]:
    return ("skills", "rules", "roles")


def open_project(project_id: str) -> None:
    st.session_state["page"] = "Projects"
    st.session_state["project_id"] = project_id
    st.rerun()


def render(data: dict) -> None:
    st.header("Dashboard", divider="gray")
    health = {p["id"]: sync.project_health(p, data) for p in data["projects"]}
    usage = sync.usage_counts(data)
    orphans = [(k, a) for k in sync.ATTACHABLE for a in data[k] if usage[(k, a["id"])] == 0]
    big = oversized_skills(data)
    stale_total = sum(len(h["stale"]) for h in health.values())
    broken = [p for p in data["projects"] if not health[p["id"]]["path_ok"]]

    mcp_report = mcp_check.library_report(data)
    quality = quality_report(data)
    cols = st.columns(4)
    cols[0].metric("Projects", len(data["projects"]))
    cols[1].metric("Outdated copies", stale_total)
    cols[2].metric("Missing folders", len(broken))
    cols[3].metric("Unused assets", len(orphans))
    cols = st.columns(4)
    cols[0].metric("Oversized skills", len(big))
    cols[1].metric("MCP with warnings", len(mcp_report))
    cols[2].metric("Quality warnings", len(quality))
    if not (data["projects"] or any(data[k] for k in sync.ATTACHABLE)):
        return common.empty_state("Nothing here yet", "Add skills to your library and register a project to get started.", "📊")

    attention = [p for p in data["projects"] if health[p["id"]]["stale"] or not health[p["id"]]["path_ok"]]
    with st.container(border=True):
        st.subheader("Needs attention")
        if not attention:
            st.caption("✅ Every project is in sync with your library.")
        for p in attention:
            h = health[p["id"]]
            c1, c2, c3 = st.columns([3, 3, 1], vertical_alignment="center")
            c1.write(f"**{p['name']}**  ·  {p['target_model']}")
            c2.markdown(":red[⚠ Folder not found]" if not h["path_ok"]
                        else f":orange[🔄 {len(h['stale'])} outdated or missing]")
            if c3.button("Open", icon=":material/folder_open:", key=f"dash_open_{p['id']}", use_container_width=True):
                open_project(p["id"])
        if stale_total and st.button("Re-sync all outdated", icon="🔁", type="primary", key="dash_resync"):
            ok, _, n = projects.bulk(data, data["projects"], lambda p: sync.resync_stale(p, data))
            common.done(f"Refreshed {n} outdated asset(s) across {ok} project(s).", "🔁")

    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.subheader("Most used")
        ranked = sorted(((n, k, i) for (k, i), n in usage.items() if n), key=lambda t: -t[0])[:8]
        if not ranked:
            st.caption("No asset is attached to a project yet.")
        top = ranked[0][0] if ranked else 1
        for n, k, i in ranked:
            a = store.find(data, k, i)
            st.markdown(f"**{a['name']}** <span class='muted'>{LABELS[k]} · {n} project(s)</span>",
                        unsafe_allow_html=True)
            st.progress(n / top)
    with c2, st.container(border=True):
        st.subheader("Unused assets")
        if not orphans:
            st.caption("Every asset is attached to at least one project.")
        for k, a in orphans[:12]:
            st.markdown(f"**{a['name']}** <span class='muted'>{LABELS[k]}</span>", unsafe_allow_html=True)
        if len(orphans) > 12:
            st.caption(f"…and {len(orphans) - 12} more.")
    if quality:
        with st.container(border=True):
            st.subheader("Quality warnings")
            st.caption("Skills, rules and roles with advisory findings — fix them in the library.")
            for kind, a, fs in quality:
                with st.expander(f"{a['name']} · {LABELS[kind]} · {len(fs)} warning(s)"):
                    common.show_findings(fs)
    if mcp_report:
        with st.container(border=True):
            st.subheader("MCP configs with warnings")
            names = {a["id"]: a["name"] for a in data["mcp_configs"]}
            for cid, fs in mcp_report.items():
                with st.expander(f"{names[cid]} · {len(fs)} warning(s)"):
                    common.show_findings(fs)
    if big:
        with st.container(border=True):
            st.subheader("Oversized skills")
            st.caption("Over 12,000 characters — consider a Hub & Spoke refactor in the Skills Library.")
            for a in big:
                st.markdown(f"- **{a['name']}**")
