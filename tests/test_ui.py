"""Smoke tests driving the real Streamlit script with AppTest."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from loadout import files, store, sync

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def run():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception, at.exception
    return at


def test_all_pages_render_empty():
    at = run()
    for btn in list(at.sidebar.button):
        at.sidebar.button(key=btn.key).click().run()
        assert not at.exception, (page, at.exception)


def test_add_skill_and_token_warning():
    at = run()
    at.sidebar.button(key="nav_Skills Library").click().run()
    at.text_input(key="skills_add_0_name").set_value("Big").run()
    at.radio(key="skills_add_0_mode").set_value("Paste text").run()
    at.text_area(key="skills_add_0_text").set_value("x" * 12001).run()
    assert any("High Token Consumption Detected" in w.value for w in at.warning)
    at.button(key="skills_add_0_save").click().run()
    assert not at.exception
    assert store.load()["skills"][0]["name"] == "Big"


def test_missing_project_path_dialog(tmp_path):
    d = store.load()
    store.add_entity(d, "projects", {"name": "Gone", "path": str(tmp_path / "nope"), "target_model": "Claude",
                                     "attached_skills": [], "attached_rules": [], "attached_roles": [],
                                     "attached_mcp": []})
    at = run()
    assert not at.exception


def test_loadouts_page_with_data():
    d = store.load()
    s = store.add_asset(d, "skills", "One", "", [], "x")
    store.add_entity(d, "loadouts", {"name": "Front", "description": "", "tags": [], "skills": [s["id"]]})
    at = run()
    at.sidebar.button(key="nav_Loadouts").click().run()
    assert not at.exception, at.exception
    assert any("Front" in e.label for e in at.expander)


def _seed(tmp_path, n=2):
    d = store.load()
    sk = store.add_asset(d, "skills", "Alpha", "", [], "v1")
    pids = []
    for i in range(n):
        folder = tmp_path / f"proj{i}"
        folder.mkdir()
        p = store.add_entity(d, "projects", {
            "name": f"P{i}", "path": str(folder), "target_model": "Claude" if i == 0 else "Cursor",
            "favorite": False, "last_opened": 0, "attached_skills": [], "attached_rules": [],
            "attached_roles": [], "attached_mcp": []})
        pids.append(p["id"])
    sync.attach(store.find(d, "projects", pids[0]), d, "skills", sk)
    store.save(d)
    return d, sk, pids


def test_dashboard_cards_favorite_and_load(tmp_path):
    d, sk, pids = _seed(tmp_path)
    store.update_asset(d, "skills", sk["id"], "Alpha", "", [], content="v2")  # makes P0 outdated
    at = run()
    assert any("Outdated copies" in m.label and m.value == "1" for m in at.metric)
    at.sidebar.button(key="nav_Projects").click().run()
    assert not at.exception, at.exception
    at.button(key=f"fav_{pids[1]}").click().run()
    assert store.load()["projects"][1]["favorite"] is True
    at.button(key=f"load_{pids[0]}").click().run()
    assert not at.exception, at.exception
    assert store.load()["projects"][0]["last_opened"] > 0
    assert any("differ" in w.value for w in at.warning)
    at.button(key="resync_stale").click().run()
    assert not at.exception
    assert not at.warning


def test_projects_filter_and_bulk(tmp_path):
    d, sk, pids = _seed(tmp_path)
    at = run()
    at.sidebar.button(key="nav_Projects").click().run()
    at.multiselect(key="pj_agents").set_value(["Cursor"]).run()
    assert not at.exception
    assert [b.key for b in at.button if b.key and b.key.startswith("load_")] == [f"load_{pids[1]}"]
    at.multiselect(key="bulk_sel").set_value(pids).run()
    at.button(key="bulk_resync").click().run()
    assert not at.exception, at.exception


def test_attach_preview(tmp_path):
    d, sk, pids = _seed(tmp_path)
    s2 = store.add_asset(d, "rules", "Style", "", [], "r")
    at = run()
    at.session_state["project_id"] = pids[1]
    at.sidebar.button(key="nav_Projects").click().run()
    at.multiselect(key=f"att_{pids[1]}_rules").set_value([s2["id"]]).run()
    assert not at.exception, at.exception
    assert any("Preview changes" in e.label for e in at.expander)


def test_used_by_and_context_in_ui(tmp_path):
    d, sk, pids = _seed(tmp_path)
    at = run()
    at.sidebar.button(key="nav_Skills Library").click().run()
    assert not at.exception, at.exception
    assert not any(e.label.startswith("Used by") for e in at.expander)   # cards first, editor on demand
    at.button(key=f"skills_{sk['id']}_edit").click().run()
    assert not at.exception, at.exception
    assert any(e.label.startswith("Used by 1 project") for e in at.expander)
    at.button(key="skills_back").click().run()
    assert at.button(key=f"skills_{sk['id']}_edit")
    at.sidebar.button(key="nav_Projects").click().run()
    at.button(key=f"load_{pids[0]}").click().run()
    assert not at.exception, at.exception
    assert any(m.label == "Estimated context" for m in at.metric)


def test_search_result_opens_item_directly(tmp_path):
    d = store.load()
    store.add_asset(d, "skills", "Alpha", "", [], "a")
    r = store.add_asset(d, "roles", "Reviewer", "", [], "r")
    at = run()
    at.text_input(key="gsearch").set_value("review").run()
    assert not at.exception, at.exception
    at.button(key=f"sr_roles_{r['id']}").click().run()
    assert not at.exception, at.exception
    assert at.session_state["page"] == "Rules & Roles"
    assert at.text_input(key="gsearch").value == ""          # search cleared, page content visible
    assert any(e.label.startswith("Reviewer") and e.proto.expanded for e in at.expander)
    assert any("Showing" in i.value for i in at.info)


def test_search_result_opens_project(tmp_path):
    d, sk, pids = _seed(tmp_path)
    at = run()
    at.text_input(key="gsearch").set_value("P1").run()
    at.button(key=f"sr_projects_{pids[1]}").click().run()
    assert not at.exception, at.exception
    assert at.session_state["page"] == "Projects" and at.session_state["project_id"] == pids[1]
    assert any(h.value == "P1" for h in at.header)


def test_palette_button_and_shortcut_script_render():
    at = run()
    assert any(b.key == "open_palette" for b in at.sidebar.button)
    at.sidebar.button(key="open_palette").click().run()
    assert not at.exception, at.exception


def test_mcp_warnings_in_ui(tmp_path):
    import json
    d = store.load()
    store.add_asset(d, "mcp_configs", "Leaky", "", [], json.dumps(
        {"mcpServers": {"s": {"command": "python3", "env": {"API_TOKEN": "abcdefghijklmnop"}}}}))
    at = run()
    assert any(m.label == "MCP with warnings" and m.value == "1" for m in at.metric)
    at.sidebar.button(key="nav_MCP Store").click().run()
    assert not at.exception, at.exception
    assert any(e.label.startswith("Validation summary") for e in at.expander)
    assert any("⚠ 1" in e.label for e in at.expander)


def test_template_prefills_form_and_modular_save():
    from loadout import files
    at = run()
    at.sidebar.button(key="nav_Skills Library").click().run()
    at.selectbox(key="skills_add_0_tpl").set_value("skill-hub-spoke").run()
    assert not at.exception, at.exception
    assert at.text_input(key="skills_add_0_name").value == "Modular workflow (Hub & Spoke)"
    assert "name: modular-workflow-hub-spoke" in at.text_area(key="skills_add_0_text").value
    at.button(key="skills_add_0_save").click().run()
    assert not at.exception, at.exception
    skill = store.load()["skills"][0]
    assert skill["is_modular"] is True
    assert (files.unit_path("skills", skill["path"]) / "modules" / "02-implement.md").is_file()


def test_generate_frontmatter_button():
    from loadout import lint
    at = run()
    at.sidebar.button(key="nav_Skills Library").click().run()
    at.text_input(key="skills_add_0_name").set_value("My Skill").run()
    at.text_input(key="skills_add_0_desc").set_value("Does a very useful thing when asked.").run()
    at.radio(key="skills_add_0_mode").set_value("Paste text").run()
    at.text_area(key="skills_add_0_text").set_value("# Title\nbody").run()
    at.button(key="skills_add_0_text_fm").click().run()
    assert not at.exception, at.exception
    meta, body, err = lint.parse_frontmatter(at.text_area(key="skills_add_0_text").value)
    assert meta == {"name": "my-skill", "description": "Does a very useful thing when asked."} and not err
    assert not any(b.key == "skills_add_0_text_fm" for b in at.button)   # finding is gone


def test_gallery_use_template_opens_prefilled_form():
    at = run()
    at.sidebar.button(key="nav_Templates").click().run()
    assert not at.exception, at.exception
    at.button(key="tpl_use_rule-testing").click().run()
    assert not at.exception, at.exception
    assert at.session_state["page"] == "Rules & Roles"
    assert at.text_input(key="rules_add_0_name").value == "Testing"
    assert "# Testing" in at.text_area(key="rules_add_0_text").value


def test_edit_asset_saves_and_shows_quality_badge():
    d = store.load()
    a = store.add_asset(d, "rules", "Thin", "", [], "# Only a title")
    at = run()
    at.sidebar.button(key="nav_Rules & Roles").click().run()
    assert any(e.label.startswith("Thin") and "⚠ 1" in e.label for e in at.expander)
    k = f"rules_{a['id']}"
    at.text_input(key=f"{k}_ename").set_value("Thicker").run()
    text_key = next(t.key for t in at.text_area if t.key and t.key.startswith(f"{k}_content_"))
    at.text_area(key=text_key).set_value("# Thicker\nAlways explain the reasoning behind each rule clearly.").run()
    at.button(key=f"{k}_save_edit").click().run()
    assert not at.exception, at.exception
    saved = store.load()["rules"][0]
    assert saved["name"] == "Thicker" and "reasoning" in files_text(saved)


def files_text(a):
    from loadout import files
    return files.read_text(a["path"])


def _tracked_rule(tmp_path):
    import subprocess
    from loadout import portability, updates
    repo = tmp_path / "up"
    repo.mkdir()
    (repo / "rules.md").write_text("version one of the rule text")
    git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b", "-c", "user.name=n", *a],  # noqa: E731
                                    check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("add", ".")
    git("commit", "-qm", "v1")
    d = store.load()
    clone = portability.clone(f"file://{repo}")
    src = updates.make_source(f"file://{repo}", None, "rules.md", portability.head_commit(clone),
                              portability.rev_parse(clone, "rules.md"), False)
    a = store.import_from_path(d, "rules", clone / "rules.md", "Upstream rule", "", [], source=src)
    portability.wipe(clone)
    return repo, git, a


def test_git_updates_ui_apply_and_conflict_confirmation(tmp_path):
    from loadout import files
    repo, git, a = _tracked_rule(tmp_path)
    at = run()
    at.sidebar.button(key="nav_Import/Export").click().run()
    assert not at.exception, at.exception
    at.button(key="upd_check").click().run()
    assert not at.exception, at.exception
    assert any("1 up to date" in i.value for i in at.info)

    (repo / "rules.md").write_text("version two of the rule text")
    git("commit", "-qam", "v2")
    at.button(key="upd_check").click().run()
    assert any("Update available" in e.label for e in at.expander)
    at.button(key=f"upd_{a['id']}_apply").click().run()
    assert not at.exception, at.exception
    assert files.read_text(a["path"]) == "version two of the rule text"

    # conflict: local edit + new upstream change → nothing is overwritten until confirmed
    store.update_asset(store.load(), "rules", a["id"], "Upstream rule", "", [], content="my local edit")
    (repo / "rules.md").write_text("version three of the rule text")
    git("commit", "-qam", "v3")
    at.button(key="upd_check").click().run()
    assert any("Conflict" in e.label for e in at.expander)
    assert files.read_text(a["path"]) == "my local edit"
    at.button(key=f"upd_{a['id']}_over").click().run()
    assert not at.exception, at.exception
    assert files.read_text(a["path"]) == "version three of the rule text"
    at.button(key="upd_discard").click().run()
    assert not at.exception


def test_source_shown_in_library(tmp_path):
    repo, git, a = _tracked_rule(tmp_path)
    at = run()
    at.sidebar.button(key="nav_Rules & Roles").click().run()
    assert not at.exception, at.exception
    assert any("From file://" in c.value for c in at.caption)


def test_modular_skill_subfiles_in_ui(tmp_path):
    d, sk, pids = _seed(tmp_path)
    at = run()
    at.sidebar.button(key="nav_Skills Library").click().run()
    at.button(key=f"skills_{sk['id']}_edit").click().run()
    assert any(e.label.startswith("Sub-files · none") for e in at.expander)
    k = f"skills_{sk['id']}"
    at.text_input(key=f"{k}_subnew_0").set_value("hooks").run()
    at.button(key=f"{k}_subcreate").click().run()
    assert not at.exception, at.exception
    d = store.load()
    a = store.find(d, "skills", sk["id"])
    assert a["is_modular"] and files.unit_files("skills", a["path"])[1:] == ["references/hooks.md"]
    assert "(references/hooks.md)" in files.read_text(a["path"])
    assert any(e.label.startswith("Sub-files · 1") for e in at.expander)


def test_add_skill_with_subfiles(tmp_path):
    _seed(tmp_path)
    at = run()
    at.sidebar.button(key="nav_Skills Library").click().run()
    k = "skills_add_0"
    at.text_input(key=f"{k}_name").set_value("Split me").run()
    at.radio(key=f"{k}_mode").set_value("Paste text").run()
    at.text_area(key=f"{k}_text").set_value("# Split\n[x](references/x.md)").run()
    at.toggle(key=f"{k}_split").set_value(True).run()
    at.text_input(key=f"{k}_sub_new").set_value("x").run()
    at.button(key=f"{k}_sub_add").click().run()
    at.text_area(key=f"{k}_subc_references/x.md").set_value("# X body").run()
    at.button(key=f"{k}_save").click().run()
    assert not at.exception, at.exception
    a = next(s for s in store.load()["skills"] if s["name"] == "Split me")
    assert a["is_modular"]
    assert files.read_text(a["path"]).startswith("# Split")
    assert (files.unit_path("skills", a["path"]) / "references/x.md").read_text() == "# X body"


def test_empty_instructions_file_is_created_and_seeded_from_skill(tmp_path):
    d, sk, pids = _seed(tmp_path)
    proj = store.find(d, "projects", pids[0])
    root_file = Path(proj["path"]) / "CLAUDE.md"
    root_file.unlink(missing_ok=True)
    at = run()
    at.sidebar.button(key="nav_Projects").click().run()
    at.button(key=f"load_{pids[0]}").click().run()
    assert not at.exception, at.exception
    assert root_file.is_file() and root_file.read_text() == ""
    k = f"seed_{pids[0]}"
    at.selectbox(key=f"{k}_pick").set_value(sk["id"]).run()
    at.button(key=f"{k}_go").click().run()
    assert not at.exception, at.exception
    assert root_file.read_text().strip()
    assert not [b for b in at.button if b.key == f"{k}_go"]   # locked now
