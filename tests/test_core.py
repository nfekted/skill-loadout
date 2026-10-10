import json
from pathlib import Path
import subprocess
import zipfile
import io

import pytest

from loadout import config, files, frameworks, lint, portability, store, sync, tokens


def test_token_check_and_prompt():
    assert not tokens.exceeds_limit("a" * 12000)
    assert tokens.exceeds_limit("a" * 12001)
    assert "Hub & Spoke" in tokens.build_prompt()
    assert "hello" in tokens.build_prompt("hello")


def test_store_roundtrip_and_lazy_dirs(loadout_home):
    d = store.load()
    assert d["skills"] == [] and not (loadout_home / "skills").exists()
    e = store.add_asset(d, "skills", "Better Frontend", "UI", ["Skill", "frontend"], "# hi")
    assert e["path"] == "skills/better_frontend/SKILL.md"
    assert {t["name"] for t in d["tags"]} == {"skill", "frontend"}
    e2 = store.add_asset(d, "skills", "Better Frontend", "", [], "x")
    assert e2["path"] == "skills/better_frontend_2/SKILL.md"
    assert store.load()["skills"][0]["id"] == e["id"]
    store.update_asset(d, "skills", e["id"], "BF", "d", ["frontend"], content="new")
    assert files.read_text(e["path"]) == "new"
    store.delete_asset(d, "skills", e["id"])
    assert not (loadout_home / "skills" / "better_frontend").exists()


def test_corrupt_data(loadout_home):
    (loadout_home / "data.json").write_text("{nope")
    with pytest.raises(store.DataError):
        store.load()


def test_path_traversal_guard():
    with pytest.raises(ValueError):
        files.resolve("../etc/passwd")


def test_tags_and_search():
    d = store.load()
    store.add_asset(d, "rules", "Style", "formatting rules", ["code"], "x")
    store.rename_tag(d, "code", "coding")
    assert d["rules"][0]["tags"] == ["coding"]
    assert store.search(d, "format")["rules"]
    assert not store.search(d, "format", ["nope"])
    store.delete_tag(d, "coding")
    assert d["rules"][0]["tags"] == []


def make_project(tmp_path, fw="Claude"):
    p = tmp_path / "proj"
    p.mkdir()
    return {"id": "p1", "name": "P", "path": str(p), "target_model": fw, "attached_skills": [],
            "attached_rules": [], "attached_roles": [], "attached_mcp": []}, p


@pytest.mark.parametrize("fw", list(frameworks.FRAMEWORKS))
def test_sync_skills_rules_per_framework(tmp_path, fw):
    d = store.load()
    proj, root = make_project(tmp_path, fw)
    assert list(root.iterdir()) == []
    s = store.add_asset(d, "skills", "Deploy", "", [], "# deploy")
    r = store.add_asset(d, "rules", "Style", "", [], "be neat")
    cfg = frameworks.FRAMEWORKS[fw]
    sync.attach(proj, d, "skills", s)
    assert (root / cfg["skills_dir"] / "deploy" / "SKILL.md").read_text() == "# deploy"
    assert not (root / ".agents").exists() and not (root / cfg["root_file"]).exists()
    (root / cfg["root_file"]).parent.mkdir(parents=True, exist_ok=True)
    (root / cfg["root_file"]).write_text("# mine\n")
    sync.attach(proj, d, "rules", r)
    text = (root / cfg["root_file"]).read_text()
    assert text.startswith("# mine") and sync.START in text and "style.md" in text
    assert (root / ".agents/rules/style.md").exists()
    sync.detach(proj, d, "rules", r)
    assert (root / cfg["root_file"]).read_text().strip() == "# mine"
    assert not (root / ".agents").exists()
    sync.detach(proj, d, "skills", s)
    assert not (root / cfg["skills_dir"]).exists()


def test_root_file_removed_when_only_managed(tmp_path):
    d = store.load()
    proj, root = make_project(tmp_path, "GitHub Copilot")
    r = store.add_asset(d, "rules", "Style", "", [], "x")
    sync.attach(proj, d, "rules", r)
    assert (root / ".github/copilot-instructions.md").exists()
    sync.detach(proj, d, "rules", r)
    assert list(root.iterdir()) == []


def test_mcp_universal_and_claude_link(tmp_path):
    d = store.load()
    proj, root = make_project(tmp_path, "Claude")
    sk = store.add_asset(d, "skills", "Deploy", "", [], "x")
    c1 = store.add_asset(d, "mcp_configs", "A", "", [], json.dumps({"mcpServers": {"a": {"command": "x"}}}))
    c2 = store.add_asset(d, "mcp_configs", "B", "", [], json.dumps({"b": {"command": "y"}}))
    srv = store.add_asset(d, "mcp_servers", "Srv", "", [], "print(1)", filename="srv.py")
    sync.attach(proj, d, "skills", sk)
    sync.attach(proj, d, "mcp_configs", c1)
    sync.attach(proj, d, "mcp_configs", c2)
    sync.attach(proj, d, "mcp_servers", srv)
    merged = json.loads((root / ".mcp/config.json").read_text())["mcpServers"]
    assert set(merged) == {"a", "b"}
    assert json.loads((root / ".claude/mcp.json").read_text())["mcpServers"].keys() == merged.keys()
    assert (root / ".mcp/servers/srv/srv.py").exists()
    assert (root / ".agents/skills/deploy/SKILL.md").exists()
    for k, a in [("mcp_configs", c1), ("mcp_configs", c2), ("mcp_servers", srv)]:
        sync.detach(proj, d, k, a)
    assert not (root / ".mcp").exists() and not (root / ".agents").exists()
    assert not (root / ".claude/mcp.json").exists()
    assert (root / ".claude/skills/deploy").exists()


def test_discover_and_import(tmp_path):
    d = store.load()
    proj, root = make_project(tmp_path)
    (root / ".claude/skills/mine").mkdir(parents=True)
    (root / ".claude/skills/mine/SKILL.md").write_text("# mine")
    (root / "CLAUDE.md").write_text("hello rules")
    found = sync.discover(proj, d)
    assert {(c["kind"], c["name"]) for c in found} == {("skills", "mine")}   # CLAUDE.md is never offered
    for c in found:
        sync.import_candidate(d, c, c["name"], "", ["imported"])
    assert len(d["skills"]) == 1 and len(d["rules"]) == 0
    assert sync.discover(proj, d) == []


def test_imported_project_skill_can_be_attached_in_place(tmp_path):
    d = store.load()
    proj, root = make_project(tmp_path)
    (root / ".claude/skills/mine").mkdir(parents=True)
    (root / ".claude/skills/mine/SKILL.md").write_text("# mine" * 100)
    (c,) = sync.discover(proj, d)
    asset = sync.import_candidate(d, c, c["name"], "", [])
    assert sync.project_health(proj, d)["counts"]["skills"] == 0   # importing alone does not attach
    sync.attach(proj, d, "skills", asset)
    assert sync.project_health(proj, d)["counts"]["skills"] == 1
    assert sync.project_tokens(proj, d)["tokens"] == tokens.estimate(600)
    assert (root / ".claude/skills/mine/SKILL.md").is_file() and sync.discover(proj, d) == []


def test_zip_roundtrip_and_zip_slip(tmp_path, loadout_home, monkeypatch):
    d = store.load()
    a = store.add_asset(d, "skills", "S", "", ["t"], "body")
    blob = portability.export_zip()
    store.delete_asset(d, "skills", a["id"])
    stats = portability.import_zip(blob)
    assert stats["added"] >= 1
    d = store.load()
    assert files.read_text(d["skills"][0]["path"]) == "body"
    stats = portability.import_zip(blob)  # same ids → skipped
    assert stats["skipped"] >= 1 and len(store.load()["skills"]) == 1
    portability.import_zip(blob, mode="replace")
    assert (loadout_home / ".backups").exists()
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("data.json", "{}")
        z.writestr("skills/../../evil.txt", "x")
    with pytest.raises(ValueError):
        portability.import_zip(bad.getvalue())


def test_git_clone_select_and_wipe(tmp_path):
    repo = tmp_path / "src"
    (repo / "skill-a").mkdir(parents=True)
    (repo / "skill-a/SKILL.md").write_text("# a")
    (repo / "rules.md").write_text("r")
    run = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b", "-c", "user.name=n", *a], check=True, capture_output=True)
    run("init", "-q")
    run("add", ".")
    run("commit", "-qm", "x")
    with pytest.raises(ValueError):
        portability.clone("/etc/passwd")
    clone = portability.clone(f"file://{repo}")
    tree = portability.list_tree(clone)
    assert {t["rel"] for t in tree} == {"skill-a", "skill-a/SKILL.md", "rules.md"}
    assert portability.prune_selection(["skill-a", "skill-a/SKILL.md", "rules.md"]) == ["rules.md", "skill-a"]
    assert portability.guess_kind(clone / "skill-a") == "skills"
    d = store.load()
    store.import_from_path(d, "skills", clone / "skill-a", "A", "", [])
    tmp = clone.parent
    portability.wipe(clone)
    assert not tmp.exists()
    assert (config.home() / "skills/a/SKILL.md").exists()


def test_loadout_attach_expands_agents(tmp_path):
    d = store.load()
    proj, root = make_project(tmp_path)
    s1 = store.add_asset(d, "skills", "One", "", [], "1")
    s2 = store.add_asset(d, "skills", "Two", "", [], "2")
    r1 = store.add_asset(d, "rules", "R", "", [], "r")
    cfg = store.add_asset(d, "mcp_configs", "M", "", [], json.dumps({"mcpServers": {"m": {"command": "x"}}}))
    agent = store.add_entity(d, "agents", {"name": "X", "description": "", "rules": [r1["id"]], "roles": [],
                                           "skills": [s2["id"]]})
    lo = store.add_entity(d, "loadouts", {"name": "Front", "description": "", "tags": ["fe"],
                                          "skills": [s1["id"], s2["id"]], "mcp_configs": [cfg["id"]],
                                          "agents": [agent["id"]]})
    assert len(sync.loadout_items(d, lo)) == 4  # s2 and agent members de-duplicated
    assert sync.attach_loadout(proj, d, lo) == (4, 0)
    assert (root / ".claude/skills/one/SKILL.md").exists() and (root / ".claude/skills/two/SKILL.md").exists()
    assert (root / ".agents/rules/r.md").exists() and (root / ".mcp/config.json").exists()
    assert sync.attach_loadout(proj, d, lo) == (0, 4)
    store.delete_asset(d, "skills", s1["id"])
    assert s1["id"] not in d["loadouts"][0]["skills"]
    store.delete_entity(d, "agents", agent["id"])
    assert d["loadouts"][0]["agents"] == []
    assert store.search(d, "front")["loadouts"]


# ---- status / diff / dry-run -------------------------------------------------
def test_item_status_diff_and_plan(tmp_path):
    d = store.load()
    proj, root = make_project(tmp_path)
    d["projects"].append(proj)
    sk = store.add_asset(d, "skills", "Alpha", "", [], "v1")
    rule = store.add_asset(d, "rules", "Style", "", [], "r1")
    assert [op for op, _ in sync.plan_attach(proj, d, "skills", sk)] == ["create"]
    sync.attach(proj, d, "skills", sk)
    sync.attach(proj, d, "rules", rule)
    assert sync.item_status(proj, d, "skills", sk) == "ok"
    assert not sync.plan_attach(proj, d, "skills", sk)

    store.update_asset(d, "skills", sk["id"], "Alpha", "", [], content="v2")
    assert sync.item_status(proj, d, "skills", sk) == "outdated"
    diff = sync.diff_item(proj, d, "skills", sk)
    assert diff[0]["state"] == "changed" and "+v2" in diff[0]["diff"]
    health = sync.project_health(proj, d)
    assert [(k, s) for k, _, s in health["stale"]] == [("skills", "outdated")]
    assert health["counts"]["skills"] == 1 and health["counts"]["rules"] == 1

    assert sync.resync_stale(proj, d) == 1
    assert sync.item_status(proj, d, "skills", sk) == "ok"

    import shutil
    shutil.rmtree(root / ".claude")
    assert sync.item_status(proj, d, "skills", sk) == "missing"
    assert ("delete", ".agents/rules/style.md") in sync.plan_detach(proj, "rules", rule)


def test_mcp_status_and_usage(tmp_path):
    d = store.load()
    proj, root = make_project(tmp_path)
    d["projects"].append(proj)
    cfg = store.add_asset(d, "mcp_configs", "Srv", "", [], json.dumps({"mcpServers": {"a": {"command": "x"}}}))
    unused = store.add_asset(d, "skills", "Unused", "", [], "x")
    sync.attach(proj, d, "mcp_configs", cfg)
    assert sync.item_status(proj, d, "mcp_configs", cfg) == "ok"
    store.update_asset(d, "mcp_configs", cfg["id"], "Srv", "", [],
                       content=json.dumps({"mcpServers": {"a": {"command": "y"}}}))
    assert sync.item_status(proj, d, "mcp_configs", cfg) == "outdated"
    assert sync.diff_item(proj, d, "mcp_configs", cfg)
    use = sync.usage_counts(d)
    assert use[("mcp_configs", cfg["id"])] == 1 and use[("skills", unused["id"])] == 0


def test_used_by_and_project_tokens(tmp_path):
    d = store.load()
    proj, _ = make_project(tmp_path)
    d["projects"].append(proj)
    sk = store.add_asset(d, "skills", "Big", "", [], "x" * 4001)
    rl = store.add_asset(d, "rules", "Small", "", [], "y" * 40)
    ag = store.add_entity(d, "agents", {"name": "Preset", "description": "", "rules": [rl["id"]], "roles": [],
                                        "skills": [sk["id"]]})
    lo = store.add_entity(d, "loadouts", {"name": "Std", "description": "", "tags": [], "agents": [ag["id"]]})
    store.add_entity(d, "loadouts", {"name": "Direct", "description": "", "tags": [], "rules": [rl["id"]]})
    sync.attach(proj, d, "skills", sk)
    sync.attach(proj, d, "rules", rl)

    refs = sync.used_by(d, "skills", sk["id"])
    assert [p["id"] for p in refs["projects"]] == ["p1"] and [a["id"] for a in refs["agents"]] == [ag["id"]]
    assert [(l["name"], v["name"]) for l, v in refs["loadouts"]] == [("Std", "Preset")]
    refs = sync.used_by(d, "rules", rl["id"])
    assert sorted((l["name"], v and v["name"]) for l, v in refs["loadouts"]) == [("Direct", None), ("Std", "Preset")]
    assert sync.used_by_count(sync.used_by(d, "roles", "nope")) == 0
    assert [l["id"] for l in sync.agent_used_by(d, ag["id"])] == [lo["id"]]

    ctx = sync.project_tokens(proj, d)
    assert [i["asset"]["name"] for i in ctx["items"]] == ["Big", "Small"]
    assert ctx["tokens"] == tokens.estimate(4001) + tokens.estimate(40) == 1334 + 14
    assert tokens.estimate(1000) == 334 and tokens.estimate(999) == 333
    assert tokens.fmt(1500) == "1.5k" and tokens.fmt(999) == "999"


def test_palette_matching():
    from loadout.ui import nav, palette
    d = store.load()
    store.add_asset(d, "skills", "Better Frontend", "", [], "x")
    store.add_entity(d, "projects", {"name": "Frontend app", "path": "/x", "target_model": "Claude"})
    cmds = palette.commands(["Dashboard", "Projects"])
    assert [c[0] for c in palette.match_commands(cmds, "go proj")] == ["Go to Projects"]
    assert palette.match_commands(cmds, "re-sync")
    ents = palette.match_entities(d, "frontend")
    assert set(ents) == {"skills", "projects"}
    assert nav.GOTO_KEYS["p"] == "Projects"


# ---- MCP validation -----------------------------------------------------------
def test_mcp_validate_findings(monkeypatch):
    from loadout import mcp_check
    monkeypatch.delenv("NOPE_TOKEN_VAR", raising=False)
    monkeypatch.setenv("SET_VAR", "1")
    bad = json.dumps({"mcpServers": {
        "gh": {"command": "definitely-not-a-cmd", "env": {"GITHUB_TOKEN": "ghp_abcdefghijklmnopqrst",
                                                          "OK": "${SET_VAR}", "MISSING": "${NOPE_TOKEN_VAR}",
                                                          "API_KEY": "${API_KEY_REF}"}},
        "typo": {"comand": "x"},
        "remote": {"url": "https://x.io/mcp?api_key=abcdef123456"}}})
    fs = mcp_check.validate(bad)
    codes = {(f["server"], f["code"]) for f in fs}
    assert ("gh", "command-missing") in codes and ("gh", "secret") in codes and ("gh", "env-unset") in codes
    assert ("typo", "no-target") in codes and ("typo", "unknown-key") in codes
    assert ("remote", "secret") in codes
    assert fs[0]["level"] == "error"                       # sorted most severe first
    assert not any("ghp_abc" in f["message"] for f in fs)  # secrets are never echoed
    assert sum(f["code"] == "env-unset" for f in fs) == 2   # SET_VAR is fine; the other two are not
    ok = json.dumps({"mcpServers": {"fs": {"command": "python3", "args": ["-m", "x"], "env": {"K": "${SET_VAR}"}}}})
    assert mcp_check.validate(ok) == []
    assert mcp_check.validate("{nope")[0]["code"] == "json"
    assert mcp_check.validate("{}")[0]["code"] == "empty"


def test_mcp_conflicts_and_library_report(tmp_path):
    from loadout import mcp_check
    d = store.load()
    proj, _ = make_project(tmp_path)
    d["projects"].append(proj)
    a = store.add_asset(d, "mcp_configs", "A", "", [], json.dumps({"mcpServers": {"s": {"command": "python3"}}}))
    b = store.add_asset(d, "mcp_configs", "B", "", [], json.dumps({"mcpServers": {"s": {"command": "python3", "args": ["x"]}}}))
    sync.attach(proj, d, "mcp_configs", a)
    sync.attach(proj, d, "mcp_configs", b)
    chk = mcp_check.check_project(proj, d)
    assert [f["code"] for f in chk["conflicts"]] == ["conflict"] and "“B” wins" in chk["conflicts"][0]["message"]
    assert mcp_check.library_report(d) == {}              # clean configs are not reported
    c = store.add_asset(d, "mcp_configs", "C", "", [], json.dumps({"mcpServers": {"t": {"command": "python3",
                                                                                          "env": {"PASSWORD": "hunter2hunter2"}}}}))
    assert list(mcp_check.library_report(d)) == [c["id"]]
    # advisory only: attaching a config with warnings still works
    sync.attach(proj, d, "mcp_configs", c)
    assert sync.item_status(proj, d, "mcp_configs", c) == "ok"


# ---- lint & templates ----------------------------------------------------------
def test_frontmatter_parse_and_apply():
    from loadout import lint
    t = "---\nname: Foo\ndescription: >\n  long text\n  more\nextra: 1\n---\n# Hi\nbody"
    meta, body, err = lint.parse_frontmatter(t)
    assert meta == {"name": "Foo", "description": "long text more", "extra": "1"} and body.startswith("# Hi") and not err
    out = lint.apply_frontmatter(t, "My Skill", "Does: a thing")
    meta, body, err = lint.parse_frontmatter(out)
    assert meta["name"] == "my-skill" and meta["description"] == "Does: a thing" and meta["extra"] == "1"
    assert out.count("description") == 1 and body.startswith("# Hi")
    fresh = lint.apply_frontmatter("# x", "A B", "d")
    assert fresh.startswith("---\nname: a-b\n") and fresh.rstrip().endswith("# x")
    assert lint.apply_frontmatter(fresh, "A B", "d2").count("---") == 2           # idempotent shape
    assert lint.parse_frontmatter("---\nname: x\nno close")[2]                     # unterminated


def test_lint_rules(tmp_path):
    from loadout import lint
    codes = lambda kind, text, **kw: {f["code"] for f in lint.lint(kind, text, **kw)}   # noqa: E731
    assert codes("skills", "  ") == {"empty"}
    assert "frontmatter-missing" in codes("skills", "# Title\nbody")
    good = "---\nname: my-skill\ndescription: \"Does a useful thing. Use when the user asks for the useful thing.\"\n---\n# T\nx"
    assert codes("skills", good, name="My Skill") == set()
    assert "name-mismatch" in codes("skills", good, name="Other")
    assert "description-short" in codes("skills", good.replace("Does a useful thing. Use when the user asks for the useful thing.", "short"))
    assert "description-missing" in codes("skills", "---\nname: x\n---\n# T\nbody")
    assert "name-format" in codes("skills", "---\nname: Bad Name\ndescription: " + "d" * 40 + "\n---\n# T")
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / "a.md").write_text("x")
    linked = good + "\nSee `modules/a.md` and [b](modules/b.md) and [web](https://x.io) and [anchor](#top)\n"
    found = lint.lint("skills", linked, folder=tmp_path)
    assert [f["code"] for f in found] == ["broken-link"] and "modules/b.md" in found[0]["message"]
    assert "thin" in codes("rules", "# Only a title")
    assert codes("roles", "# Role\nYou are a careful reviewer who explains reasoning.") == set()
    assert lint.needs_frontmatter(lint.lint("skills", "# x"))


def test_builtin_templates_are_valid_and_clean():
    from loadout import lint, mcp_check, templates
    ts = templates.all_templates()
    assert {t["kind"] for t in ts} == set(templates.KINDS)
    assert len({t["id"] for t in ts}) == len(ts)
    for t in ts:
        text = templates.render(t, "My Thing")
        assert "{{" not in text, t["id"]
        if t["kind"] == "mcp_configs":
            assert not [f for f in mcp_check.validate(text) if f["level"] == "error"], t["id"]
            assert not any(f["code"] == "secret" for f in mcp_check.validate(text)), t["id"]
        else:
            fs = lint.lint(t["kind"], text, name="My Thing", folder=templates.folder(t))
            assert not lint.actionable(fs), (t["id"], fs)
    hub = templates.get("skills", "skill-hub-spoke")
    assert templates.extra_files(hub) == ["modules/01-analyze.md", "modules/02-implement.md", "modules/03-verify.md"]
    assert "name: my-thing" in templates.render(templates.get("skills", "skill-basic"), "My Thing")


# ---- git updates ---------------------------------------------------------------
def _git_repo(tmp_path):
    repo = tmp_path / "upstream"
    (repo / "skill-a" / "modules").mkdir(parents=True)
    (repo / "skill-a/SKILL.md").write_text("# a v1")
    (repo / "skill-a/modules/m.md").write_text("m1")
    (repo / "rules.md").write_text("rule v1 " * 3)
    (repo / "other.md").write_text("unrelated")

    def git(*a):
        return subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b", "-c", "user.name=n", *a],
                              check=True, capture_output=True, text=True).stdout

    git("init", "-q", "-b", "main")
    git("add", ".")
    git("commit", "-qm", "v1")

    def commit(msg="change"):
        git("add", "-A")
        git("commit", "-qm", msg)

    return repo, commit


def _import(d, repo, kind, rel, name):
    from loadout import updates
    clone = portability.clone(f"file://{repo}")
    src = updates.make_source(f"file://{repo}", None, rel, portability.head_commit(clone),
                              portability.rev_parse(clone, rel), portability.is_detached(clone))
    a = store.import_from_path(d, kind, clone / rel, name, "", [], source=src)
    portability.wipe(clone)
    return a


def _status(report, a):
    return next(i for i in report["items"] if i["id"] == a["id"])


def test_git_updates_full_cycle(tmp_path):
    from loadout import updates
    repo, commit = _git_repo(tmp_path)
    d = store.load()
    skill = _import(d, repo, "skills", "skill-a", "A")
    rule = _import(d, repo, "rules", "rules.md", "R")
    assert skill["source"]["hash"] == files.unit_hash("skills", skill["path"])
    assert len(updates.tracked(d)) == 2
    first_commit = skill["source"]["commit"]

    # 1) nothing changed
    rep = updates.check(d)
    assert {i["status"] for i in rep["items"]} == {"up_to_date"} and not rep["repos"]

    # 2) repo moves, but only on a file we did not import → still up to date, commit refreshed (no re-check noise)
    (repo / "other.md").write_text("changed")
    commit("unrelated")
    rep = updates.check(d)
    assert {i["status"] for i in rep["items"]} == {"up_to_date"}
    assert d["skills"][0]["source"]["commit"] != first_commit
    updates.discard(rep)

    # 3) imported skill changes upstream, untouched locally → update; rule changes + edited locally → conflict
    (repo / "skill-a/SKILL.md").write_text("# a v2")
    (repo / "skill-a/modules/m.md").write_text("m2")
    (repo / "rules.md").write_text("rule v2 upstream")
    commit("v2")
    store.update_asset(d, "rules", rule["id"], "R", "", [], content="my local edit of the rule")
    rep = updates.check(d)
    assert _status(rep, skill)["status"] == "update" and _status(rep, rule)["status"] == "conflict"
    diff = updates.diff(_status(rep, skill), d)
    assert {x["file"] for x in diff} == {"SKILL.md", "modules/m.md"} and "+# a v2" in diff[0]["diff"]

    # conflict: nothing is overwritten unless apply_update is called explicitly
    assert files.read_text(rule["path"]) == "my local edit of the rule"
    updates.keep_mine(d, _status(rep, rule))
    assert files.read_text(rule["path"]) == "my local edit of the rule"
    assert d["rules"][0]["source"]["object"] == _status(rep, rule)["object"]

    updates.apply_update(d, _status(rep, skill))
    assert files.read_text(skill["path"]) == "# a v2"
    assert (config.home() / "skills/a/modules/m.md").read_text() == "m2"
    assert d["skills"][0]["source"]["hash"] == files.unit_hash("skills", skill["path"])
    updates.discard(rep)
    assert all(not Path(r).exists() for r in rep["repos"])

    # 4) applied/kept items no longer show as pending
    rep = updates.check(d)
    assert {i["status"] for i in rep["items"]} == {"up_to_date"}

    # 5) conflict → overwrite, and → save as new
    (repo / "rules.md").write_text("rule v3 upstream")
    commit("v3")
    rep = updates.check(d)
    item = _status(rep, rule)
    assert item["status"] == "conflict"
    new = updates.save_as_new(d, item)
    assert files.read_text(new["path"]) == "rule v3 upstream" and new["name"] == "R (repository)"
    assert files.read_text(rule["path"]) == "my local edit of the rule"
    (repo / "rules.md").write_text("rule v4 upstream")
    commit("v4")
    updates.discard(rep)
    rep = updates.check(d)
    item = _status(rep, rule)
    updates.apply_update(d, item)
    assert files.read_text(rule["path"]) == "rule v4 upstream"
    updates.discard(rep)

    # 6) removed upstream
    (repo / "rules.md").unlink()
    commit("rm")
    rep = updates.check(d)
    assert _status(rep, rule)["status"] == "removed"
    updates.unlink(d, "rules", rule["id"])
    assert "source" not in d["rules"][0]


def test_git_updates_errors_and_pinned(tmp_path):
    from loadout import updates
    repo, commit = _git_repo(tmp_path)
    d = store.load()
    a = _import(d, repo, "rules", "rules.md", "R")
    a["source"]["pinned"] = True
    assert {i["status"] for i in updates.check(d)["items"]} == {"pinned"}
    a["source"]["pinned"] = False
    a["source"]["url"] = f"file://{tmp_path}/does-not-exist"
    res = updates.check(d)["items"]
    assert res[0]["status"] == "error" and res[0]["message"]
    with pytest.raises(ValueError):
        portability.ls_remote("/etc/passwd")
    with pytest.raises(ValueError):
        portability.clone(f"file://{repo}", ref="--upload-pack=evil")


def test_subfile_helpers(tmp_path):
    d = store.load()
    sk = store.add_asset(d, "skills", "Big", "", [], "# Big\n[a](references/a.md)\n")
    assert files.unit_files("skills", sk["path"]) == ["SKILL.md"] and not sk["is_modular"]
    store.write_member(d, "skills", sk["id"], "references/a.md", "# A")
    assert sk["is_modular"] and files.unit_files("skills", sk["path"]) == ["SKILL.md", "references/a.md"]
    assert lint.references("see [a](references/a.md) and `scripts/x.sh` and [w](https://x.io)") == [
        "references/a.md", "scripts/x.sh"]
    for bad in ("../x.md", "/etc/passwd", ".git/config", ""):
        with pytest.raises(ValueError):
            store.write_member(d, "skills", sk["id"], bad, "x")
    with pytest.raises(ValueError):
        store.delete_member(d, "skills", sk["id"], "SKILL.md")
    import io
    import zipfile
    assert set(zipfile.ZipFile(io.BytesIO(files.zip_unit("skills", sk["path"]))).namelist()) == {
        "big/SKILL.md", "big/references/a.md"}
    store.delete_member(d, "skills", sk["id"], "references/a.md")
    assert not sk["is_modular"] and not (files.unit_path("skills", sk["path"]) / "references").exists()


def test_instructions_file_create_count_and_seed_once(tmp_path):
    d = store.load()
    proj, root = make_project(tmp_path)
    rf = root / "CLAUDE.md"
    assert not rf.exists() and sync.ensure_root_file(proj) and rf.read_text() == ""
    assert not sync.ensure_root_file(proj)
    info = sync.root_info(proj)
    assert info["empty"] and info["tokens"] == 0
    sk = store.add_asset(d, "skills", "claude-front", "", [],
                         "---\nname: claude-front\ndescription: " + "d" * 30 + "\n---\n# Front\n" + "x" * 294)
    sync.seed_root_from_skill(proj, d, sk)
    assert rf.read_text().startswith("# Front") and "description:" not in rf.read_text()
    info = sync.root_info(proj)
    assert not info["empty"] and info["chars"] == len("# Front\n" + "x" * 294) and info["tokens"] == tokens.estimate(info["chars"])
    assert sync.project_tokens(proj, d)["tokens"] == info["tokens"]
    with pytest.raises(ValueError):          # locked once it has content
        sync.seed_root_from_skill(proj, d, sk)
    rl = store.add_asset(d, "rules", "R", "", [], "r")
    sync.attach(proj, d, "rules", rl)        # the managed block is not counted as the user's own text
    assert sync.root_info(proj)["chars"] == info["chars"] and "LOADOUT:START" in rf.read_text()
    assert sync.discover(proj, d) == []
