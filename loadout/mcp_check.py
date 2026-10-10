"""Static checks for MCP configs. Advisory only: nothing here blocks saving or attaching.

The server is never started — checks read the JSON and consult the local system (PATH, environment).
"""
import json
import os
import re
import shutil
from pathlib import Path

from . import files

LEVELS = ("error", "warning", "info")
KNOWN_KEYS = {"command", "args", "env", "url", "type", "transport", "headers", "cwd", "timeout", "disabled",
              "enabled", "autoApprove", "alwaysAllow", "description", "trust", "envFile", "oauth",
              "includeTools", "excludeTools", "disabledTools", "startup_timeout_ms", "serverUrl", "httpUrl"}
REMOTE_KEYS = ("url", "serverUrl", "httpUrl")
_SECRET_NAME = re.compile(r"(token|secret|password|passwd|api[_-]?key|private[_-]?key|credential|auth)", re.I)
_SECRET_VALUE = re.compile(
    r"(ghp_|gho_|ghu_|ghs_|github_pat_|glpat-|sk-|sk_live_|xox[abprs]-|AKIA[0-9A-Z]{8}|AIza[0-9A-Za-z_-]{10}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.)")
_URL_CREDS = re.compile(r"://[^/\s:@]+:[^/\s@]+@|[?&](api[_-]?key|token|access_token|key)=[^&\s${]+", re.I)
_PLACEHOLDER = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)(?::[-?][^}]*)?\}?")
_WHOLE_PLACEHOLDER = re.compile(r"^\s*\$\{?[A-Za-z_][A-Za-z0-9_]*(?::[-?][^}]*)?\}?\s*$")


def finding(level: str, server: str | None, message: str, code: str = "") -> dict:
    return {"level": level, "server": server, "message": message, "code": code}


def _servers(j) -> dict:
    if isinstance(j, dict) and isinstance(j.get("mcpServers"), dict):
        return j["mcpServers"]
    return j if isinstance(j, dict) else {}


def _is_literal(v: str) -> bool:
    return bool(v.strip()) and not _WHOLE_PLACEHOLDER.match(v)


def _looks_secret(name: str, value: str) -> bool:
    if not _is_literal(value):
        return False
    if _SECRET_VALUE.search(value):
        return True
    return bool(_SECRET_NAME.search(name)) and len(value.strip()) >= 8 and not value.strip().lower().startswith(("http", "/", "./"))


def _check_command(name: str, cmd: str, out: list) -> None:
    if not isinstance(cmd, str) or not cmd.strip():
        out.append(finding("error", name, "`command` must be a non-empty string.", "command-type"))
        return
    cmd = cmd.strip()
    if _PLACEHOLDER.search(cmd) and cmd.startswith("$"):
        return  # resolved at runtime
    if "/" in cmd or "\\" in cmd or cmd.startswith("~"):
        p = Path(cmd).expanduser()
        if p.is_absolute() and not p.exists():
            out.append(finding("warning", name, f"Command path `{cmd}` does not exist on this machine.", "command-missing"))
        return  # relative paths depend on the project folder
    if not shutil.which(cmd):
        out.append(finding("warning", name, f"Command `{cmd}` was not found in PATH on this machine "
                           "(it may still exist where the agent runs).", "command-missing"))


def _check_env_refs(name: str, label: str, mapping: dict, out: list) -> None:
    for key, val in mapping.items():
        if not isinstance(val, str):
            continue
        for var in _PLACEHOLDER.findall(val):
            if var not in os.environ:
                out.append(finding("warning", name, f"`{label}.{key}` references `${var}`, which is not set in "
                                   "the environment.", "env-unset"))


def _check_secrets(name: str, label: str, mapping: dict, out: list) -> None:
    for key, val in mapping.items():
        if isinstance(val, str) and _looks_secret(key, val):
            out.append(finding("warning", name, f"`{label}.{key}` looks like a secret written in plain text. This file "
                               f"is copied into the project; use a reference such as `${{{_suggest(key)}}}` instead.",
                               "secret"))


def _suggest(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").upper() or "SECRET"


def check_server(name: str, cfg) -> list[dict]:
    out: list[dict] = []
    if not isinstance(cfg, dict):
        return [finding("error", name, "Server definition must be an object.", "shape")]
    remote = next((k for k in REMOTE_KEYS if cfg.get(k)), None)
    if "command" in cfg:
        _check_command(name, cfg["command"], out)
    elif not remote:
        out.append(finding("error", name, "Needs a `command` (local server) or a `url` (remote server).", "no-target"))
    args = cfg.get("args")
    if args is not None:
        if not isinstance(args, list) or not all(isinstance(a, (str, int, float)) for a in args):
            out.append(finding("error", name, "`args` must be a list of strings.", "args-type"))
        else:
            for a in map(str, args):
                if _SECRET_VALUE.search(a) or re.match(r"--?[\w-]*(token|secret|password|api[-_]?key)[\w-]*=\S{8,}", a, re.I):
                    if _is_literal(a.split("=", 1)[-1]):
                        out.append(finding("warning", name, "An argument looks like a secret written in plain text.", "secret"))
                        break
    for field in ("env", "headers"):
        m = cfg.get(field)
        if m is None:
            continue
        if not isinstance(m, dict):
            out.append(finding("error", name, f"`{field}` must be an object of strings.", f"{field}-type"))
            continue
        _check_env_refs(name, field, m, out)
        _check_secrets(name, field, m, out)
    if remote and isinstance(cfg[remote], str):
        url = cfg[remote]
        if not url.startswith(("http://", "https://", "${", "$")):
            out.append(finding("warning", name, f"`{remote}` should start with http:// or https://.", "url-scheme"))
        if _URL_CREDS.search(url):
            out.append(finding("warning", name, f"`{remote}` embeds credentials in the URL; move them to `headers` "
                               "with an environment reference.", "secret"))
    for k in cfg:
        if k not in KNOWN_KEYS:
            out.append(finding("info", name, f"Unknown key `{k}` (typo?).", "unknown-key"))
    return out


def validate(text: str) -> list[dict]:
    """Findings for the JSON text of one MCP config, most severe first."""
    try:
        j = json.loads(text)
    except json.JSONDecodeError as e:
        return [finding("error", None, f"Invalid JSON: {e}", "json")]
    servers = _servers(j)
    if not servers:
        return [finding("warning", None, "No servers defined (expected a `mcpServers` object).", "empty")]
    out = []
    for name, cfg in servers.items():
        out += check_server(str(name), cfg)
    return sort(out)


def sort(fs: list[dict]) -> list[dict]:
    return sorted(fs, key=lambda f: LEVELS.index(f["level"]))


def actionable(fs: list[dict]) -> list[dict]:
    """Findings worth surfacing as badges: everything except purely informational ones."""
    return [f for f in fs if f["level"] != "info"]


def check_asset(asset: dict) -> list[dict]:
    try:
        return validate(files.read_text(asset["path"]))
    except (OSError, ValueError):
        return [finding("error", None, "The stored config file could not be read.", "unreadable")]


def conflicts(configs: list[tuple[str, dict]]) -> list[dict]:
    """Servers defined by several configs with different values. configs: (config name, servers) in merge order."""
    seen: dict[str, tuple[str, object]] = {}
    out = []
    for cname, servers in configs:
        for sname, cfg in servers.items():
            if sname in seen and seen[sname][1] != cfg:
                out.append(finding("warning", sname, f"Defined differently in “{seen[sname][0]}” and “{cname}”. "
                                   f"When merged into the project, “{cname}” wins.", "conflict"))
            seen[sname] = (cname, cfg)
    return out


def check_project(project: dict, data: dict) -> dict:
    """{'configs': {config id: findings}, 'conflicts': findings} for the MCP configs attached to a project."""
    attached = [a for a in data["mcp_configs"] if a["id"] in project.get("attached_mcp", [])]
    per, parsed = {}, []
    for a in attached:
        per[a["id"]] = check_asset(a)
        try:
            parsed.append((a["name"], _servers(json.loads(files.read_text(a["path"])))))
        except (OSError, ValueError):
            pass
    return {"configs": per, "conflicts": conflicts(parsed)}


def library_report(data: dict) -> dict[str, list[dict]]:
    """Actionable findings for every MCP config in the library (id → findings), skipping clean ones."""
    out = {}
    for a in data["mcp_configs"]:
        fs = actionable(check_asset(a))
        if fs:
            out[a["id"]] = fs
    return out
