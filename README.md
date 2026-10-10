# 🎒 Skill Loadout

Create and manage a local library of AI-agent assets — **skills, rules, roles, MCP configs/servers, agent presets, and utilities** — then sync them into your projects for Claude, ChatGPT Codex, Antigravity, Cursor or GitHub Copilot. Clone skills straight from Git and have them ready to attach in seconds.

The UI is 100% English and built with Streamlit.

## Features

| Area | What you get |
|---|---|
| **Skills Library** | CRUD, search, tag filter. Upload `.md`, upload a `.zip` (modular skill folder) or paste text. File names are auto-generated (`skills/<slug>/SKILL.md`). |
| **Token check** | Skills over **12,000 characters** show a *High Token Consumption Detected* banner plus a pre-filled Hub & Spoke refactoring prompt with a one-click **Copy Prompt** button (optionally with your file content appended). |
| **Rules & Roles** | Same CRUD (upload `.md` or paste). Includes **Agent Presets** — named bundles of rules, roles and skills. |
| **MCP Store** | MCP Configs (JSON, validated on save) and MCP Servers (upload `.py/.js/…` or write code directly). |
| **Utilities** | Link bank and prompt repository: items with a URL get an **Open Link** button (new tab); text-only prompts/notes get a copyable code block. |
| **Tags Manager** | Rename, delete and assign custom hex colors; tags render as colored chips everywhere. Renames/deletes propagate to all assets. |
| **Projects** | Register project folders, pick the target framework, attach/detach assets or whole presets, re-sync, and discover assets already present in the project. |
| **Dashboard** | Outdated/missing copies across projects, missing folders, unused assets, most-used assets and oversized skills, with one-click *Re-sync all outdated*. |
| **Drift detection** | Project copies are compared with the Loadout library: 🔄 *outdated* / ❓ *missing* badges, per-asset diff and re-sync, plus a *Preview changes* dry-run before *Apply to Project*. |
| **Project cards** | Search, agent filter and sorting (name, recently opened, most assets, needs attention); pin favorites; quick actions (open folder/editor, copy path, duplicate to another agent); bulk attach a loadout or re-sync several projects at once. |
| **Command palette & shortcuts** | `Ctrl/⌘+K` opens a palette to run commands (go to a page, add a project, re-sync outdated) or search any skill, rule, project… and jump straight to it. `/` focuses the global search; `g` then `d p l s r m u i t` navigates pages. Global search results have an **Open** button that lands on the item, expanded. |
| **MCP validation** | Advisory static checks on MCP configs (never blocks saving or attaching, never starts a server): structure, command found in `PATH`, unset `${ENV}` references, plain-text secrets (secret values are never echoed), and servers defined differently in several configs of one project. Shown while editing, on each config, in a project's Overview, in the MCP Store summary and on the Dashboard. |
| **Markdown editor & quality check** | Skills, rules and roles are edited with *Edit / Preview* tabs, a character/token counter and an advisory quality check (front-matter, `name`/`description`, broken `modules/…` links, thin content). A **Generate front-matter** button writes `name` and `description` from the form fields into SKILL.md without touching other keys. |
| **Templates** | 17 built-in starters (skills incl. a modular Hub & Spoke one, rules, roles, MCP configs) in `loadout/templates/`. Pick one in any *Add* form, or browse the **Templates** gallery and press *Use template* — the form is pre-filled and fully editable; the built-in file never changes. |
| **Git updates** | Assets imported from Git remember their origin (repo, branch, path, commit). *Import / Export → Git updates* has a manual **Check for updates** button: one `git ls-remote` per repo, then a trees-only clone just for repos that moved, comparing only the paths you imported. Review a diff and **Apply update**; if you edited the asset locally too, you are asked before anything is overwritten (*Overwrite…*, *Keep my version* or *Save repository version as new*). Tags/commits are pinned and not tracked. |
| **Skill cards & sub-files** | Skills Library shows cards (name, description, tags, size) with **Edit / Download / Delete**. A skill with more than one file is *modular*: the card shows `📁 N files`, and the editor has a **Sub-files** section listing each file as linked or not linked from SKILL.md, plus create / edit / delete (new files can be linked from SKILL.md automatically). *Add Skill → Split into sub-files* creates them up front. Modular skills download as a `.zip`. |
| **Project instructions file** | Every project gets its framework's instructions file (`CLAUDE.md`, `AGENTS.md`, …) created empty when loaded, and it is never offered by *Discover & Import*. While empty, the Overview lets you fill it once from a library skill (front-matter stripped), e.g. a default for all front-ends. After that it is locked in the app and only counted: its characters and tokens (chars ÷ 3) are part of the project's estimated context. |
| **Loadouts** | Named bundles of skills, rules, roles, MCP configs/servers and agent presets. Attach one to a project (from the Loadouts page or the project's *Attach Assets* tab) and everything inside is added at once; agent presets are expanded and duplicates skipped. |
| **Global search** | Live search bar across every entity by name, description or tag. |
| **Import / Export** | Full `.zip` backup (data.json + all asset files), merge or replace import, and a Git clone → selective import wizard. |

### Project synchronization

| Framework | Instructions file | Skills folder |
|---|---|---|
| Claude | `CLAUDE.md` | `.claude/skills/` (+ `.claude/mcp.json` → `../.mcp/config.json`) |
| ChatGPT Codex | `AGENTS.md` | `.codex/skills/` |
| Antigravity | `ANTIGRAVITY.md` | `.antigravity/skills/` |
| Cursor | `.cursorrules` | `.cursor/skills/` |
| GitHub Copilot | `.github/copilot-instructions.md` | `.github/skills/` |

Universal pattern, created lazily: `.agents/rules/`, `.agents/roles/`, `.agents/skills/` (skills are mirrored here only while MCP assets are attached), `.mcp/config.json` (all attached MCP configs merged under `mcpServers`) and `.mcp/servers/`.

Behaviors worth knowing:

- **Files are copied**, not symlinked, so projects stay portable. Use *Re-sync all files* to refresh copies after editing an asset in Loadout. (The one exception is `.claude/mcp.json`, a relative symlink to `../.mcp/config.json`; it falls back to a copy where symlinks aren't permitted.)
- **Rules and roles** are copied to `.agents/rules|roles/` and referenced from a managed block in the instructions file:
  `<!-- LOADOUT:START --> … <!-- LOADOUT:END -->`. Anything you wrote outside the markers is never touched; detaching the last item removes the block (and the file, if Loadout created it).
- **Lazy folder creation:** no empty folders are ever created in a project. Directories appear when an item is attached and are pruned when the last item is detached.
- **Path validation:** selecting a project whose folder no longer exists opens a dialog — *Update Path* or *Delete Project Reference*.
- **Discover & Import:** scans the project for skills/rules/roles (and your own instructions-file content) that Loadout doesn't have, with an **Import to Loadout** button.

### Git import workflow

1. Enter a repository URL (`https://`, `ssh://`, `git@…`, `file://`) — it is shallow-cloned into a temporary `loadout-git-*` folder in the system temp dir (`/tmp`).
2. Tick files/folders to keep in the tree selector (a ticked folder is one asset, e.g. a whole skill).
3. For each selected item, choose its type (Skill, Rule, Role, MCP) and give it a name, description and tags.
4. On finish, items are copied into Loadout, registered in `data.json`, and the temp directory is wiped. *Cancel* wipes it too.

## Architecture

```
app.py                  Streamlit entry: sidebar nav, global search, routing
loadout/
  config.py             Paths (LOADOUT_HOME override), constants
  store.py              data.json load/save (atomic), entity CRUD, tags, search
  files.py              Physical asset storage, safe names, path-traversal guard, lazy dirs
  tokens.py             12k-char check and the Hub & Spoke prompt
  frameworks.py         Target framework → file locations map
  sync.py               attach/detach, managed block, MCP merge, discover/import
  portability.py        zip export/import (zip-slip safe), git clone, tree listing, wipe
  ui/                   One module per page (+ common.py, generic assets.py CRUD)
tests/                  pytest: core logic + AppTest UI smoke tests
```

Storage layout (next to the app, git-ignored):

```
data.json               All metadata
skills/<slug>/SKILL.md  (+ modules/, scripts/ for modular skills)
rules/<slug>.md   roles/<slug>.md
mcp_configs/<slug>.json
mcp_servers/<slug>/<file>
.backups/<timestamp>/   Created only when an import replaces your library
```

### `data.json` schema

Top-level lists: `skills`, `roles`, `rules`, `mcp_configs`, `mcp_servers`, `agents`, `loadouts`, `tags`, `utilities`, `projects`.

- Assets: `{id, name, description, tags[], path}` (skills also have `is_modular`).
- Agents: `{id, name, description, rules[], roles[], skills[]}`.
- Loadouts: `{id, name, description, tags[], skills[], rules[], roles[], mcp_configs[], mcp_servers[], agents[]}`.
- Tags: `{name, color}`. Utilities: `{id, name, description, url, text, tags[]}`.
- Projects: `{id, name, path, target_model, attached_skills[], attached_rules[], attached_roles[], attached_mcp[]}` (`attached_mcp` holds both MCP config and server ids).

Writes are atomic (temp file + `os.replace`). A corrupted `data.json` is reported, never silently overwritten.

## Installation

Requires Python 3.10+ and `git` (for Git import).

```bash
./run.sh            # creates .venv, installs requirements, launches the app
```

or manually:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Set `LOADOUT_HOME=/path/to/dir` to keep your library somewhere other than the app folder.

## Usage guide

1. **Tags** (Settings → Tags Manager) — optional; tags can also be typed on any asset.
2. **Add assets** in Skills Library, Rules & Roles, MCP Store and Utilities.
3. Optionally build an **Agent Preset** (Rules & Roles → Agent Presets).
4. **Projects → Add Project**, choose its target framework, then use **Attach Assets** (or attach a preset) and **Apply to Project**.
5. Use **Discover & Import** to pull pre-existing project assets into Loadout.
6. Use **Import/Export** for backups or to import from a Git repo.

## Tests

```bash
.venv/bin/pytest -q
```

## Roadmap ideas

Drift detection between Loadout and project copies, asset versioning, SKILL.md frontmatter parsing to prefill names, and secret masking for MCP configs.
