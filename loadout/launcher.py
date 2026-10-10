"""Open a project folder in the OS file manager or an editor."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

EDITORS = ("code", "cursor", "codium", "subl", "idea")


def editor() -> str | None:
    return next((e for e in EDITORS if shutil.which(e)), None)


def open_folder(path: str) -> str | None:
    """Returns an error message, or None on success."""
    p = Path(path).expanduser()
    if not p.is_dir():
        return "That folder does not exist."
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))  # noqa: S606
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(p)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        return f"Could not open the folder: {e}"
    return None


def open_in_editor(path: str) -> str | None:
    exe = editor()
    if not exe:
        return "No supported editor found on PATH (code, cursor, codium, subl, idea)."
    try:
        subprocess.Popen([exe, str(Path(path).expanduser())], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        return f"Could not launch {exe}: {e}"
    return None
