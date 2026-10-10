"""Open the operating system's native folder chooser (Loadout runs locally, so this is the user's desktop)."""
import shutil
import subprocess
import sys

_TK = ("import tkinter as t,tkinter.filedialog as f;r=t.Tk();r.withdraw();r.attributes('-topmost',True);"
       "print(f.askdirectory(title='Select project folder') or '')")
_PS = ("Add-Type -AssemblyName System.Windows.Forms;$d=New-Object System.Windows.Forms.FolderBrowserDialog;"
       "if($d.ShowDialog() -eq 'OK'){$d.SelectedPath}")


def _commands() -> list[list[str]]:
    cmds = []
    if sys.platform == "darwin":
        cmds.append(["osascript", "-e", 'POSIX path of (choose folder with prompt "Select project folder")'])
    elif sys.platform.startswith("win"):
        cmds.append(["powershell", "-NoProfile", "-Command", _PS])
    else:
        if shutil.which("zenity"):
            cmds.append(["zenity", "--file-selection", "--directory", "--title=Select project folder"])
        if shutil.which("kdialog"):
            cmds.append(["kdialog", "--getexistingdirectory", "."])
    cmds.append([sys.executable, "-c", _TK])
    return cmds


def pick_folder() -> tuple[str | None, str | None]:
    """Returns (path, error). path is None when cancelled or unavailable; error explains unavailability."""
    for cmd in _commands():
        if not shutil.which(cmd[0]) and cmd[0] != sys.executable:
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired):
            continue
        out = r.stdout.strip()
        if r.returncode == 0 and out:
            return out.rstrip("/\\") or out, None
        if r.returncode == 1 and not r.stderr.strip():  # user cancelled
            return None, None
    return None, "No folder dialog is available on this system. Type or paste the path instead."
