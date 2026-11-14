"""Finds a bash for the shell-script tests (Git Bash on Windows)."""
import os
import shutil
from pathlib import Path


def find_bash():
    if os.name != "nt":
        return shutil.which("bash")
    # Git for Windows keeps bash in <Git>/bin, with git in <Git>/cmd or <Git>/mingw64/bin.
    # A bare "bash" on Windows may be the WSL launcher, so don't use that.
    git = shutil.which("git")
    for up in Path(git).resolve().parents[:3] if git else []:
        if (up / "bin" / "bash.exe").exists() and (up / "bin" / "git.exe").exists():
            return str(up / "bin" / "bash.exe")
    return None


def posix(path) -> str:
    """A path as bash sees it: C:/x on Windows becomes /c/x."""
    p = Path(path).as_posix()
    if os.name == "nt" and len(p) > 1 and p[1] == ":":
        p = "/" + p[0].lower() + p[2:]
    return p


BASH = find_bash()
