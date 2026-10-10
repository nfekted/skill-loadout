"""Link bank & prompt repository."""
import streamlit as st

from .. import store
from . import common, nav


def render(data: dict) -> None:
    st.header("Utilities", divider="gray")
    st.caption("Keep useful links and reusable prompts/notes in one place.")
    with st.expander("Add Utility", icon="➕", expanded=not data["utilities"]):
        n = st.session_state.setdefault("util_nonce", 0)
        c1, c2 = st.columns(2)
        name = c1.text_input("Name", key=f"u_name_{n}")
        url = c2.text_input("URL (optional)", key=f"u_url_{n}", placeholder="https://…")
        desc = st.text_input("Description", key=f"u_desc_{n}")
        text = st.text_area("Prompt / note (optional)", key=f"u_text_{n}", height=140)
        tags = common.tag_input("Tags", data, f"u_tags_{n}")
        if st.button("Save Utility", icon="💾", type="primary", key=f"u_save_{n}"):
            if not name.strip():
                common.fail("Name is required.")
            elif not url.strip() and not text.strip():
                common.fail("Provide a URL, a text note, or both.")
            elif url.strip() and not url.strip().lower().startswith(("http://", "https://")):
                common.fail("URL must start with http:// or https://")
            else:
                store.add_entity(data, "utilities", {"name": name.strip(), "description": desc.strip(),
                                                      "url": url.strip(), "text": text, "tags": tags})
                st.session_state["util_nonce"] += 1
                common.done("Utility saved!")
    q, tags = common.filter_bar("util", data)
    items = nav.focus_first("utilities", data["utilities"], [u for u in data["utilities"] if store.matches(u, q, tags)])
    if not data["utilities"]:
        return common.empty_state("No utilities yet", "Add a link or a prompt above.", "🔗")
    if not items:
        return common.empty_state("Nothing matches your filters", icon="🔍")
    for u in items:
        render_item(u, data)


def render_item(u: dict, data: dict) -> None:
    with st.expander(("🔗 " if u.get("url") else "📝 ") + u["name"], expanded=u["id"] == nav.focused("utilities")):
        common.chips(u.get("tags", []), data)
        if u.get("description"):
            st.write(u["description"])
        if u.get("url"):
            st.link_button("Open Link", u["url"], icon="🔗")  # opens in a new tab
        if u.get("text"):
            st.code(u["text"], language="markdown", wrap_lines=True)
        with st.form(f"u_edit_{u['id']}"):
            c1, c2 = st.columns(2)
            name = c1.text_input("Name", u["name"])
            url = c2.text_input("URL", u.get("url", ""))
            desc = st.text_input("Description", u.get("description", ""))
            text = st.text_area("Prompt / note", u.get("text", ""), height=140)
            tags = common.tag_input("Tags", data, f"u_{u['id']}_tags", u.get("tags", []))
            if st.form_submit_button("Save changes", icon="💾"):
                if not name.strip() or not (url.strip() or text.strip()):
                    common.fail("A name and either a URL or text are required.")
                elif url.strip() and not url.strip().lower().startswith(("http://", "https://")):
                    common.fail("URL must start with http:// or https://")
                else:
                    store.update_entity(data, "utilities", u["id"], name=name.strip(), url=url.strip(),
                                        description=desc.strip(), text=text, tags=tags)
                    common.done("Utility updated!")
        with st.popover("Delete", icon="🗑️"):
            if st.button("Confirm delete", type="primary", key=f"u_del_{u['id']}"):
                store.delete_entity(data, "utilities", u["id"])
                common.done("Utility deleted.", "🗑️")
