"""Static guard against image/video output in repository source."""

import ast
from pathlib import Path
import re


MEDIA_SUFFIX = re.compile(r"\.(?:png|jpe?g|webp|bmp|tiff?|gif|mp4|avi|mov|mkv|webm)$", re.I)
WRITERS = {"imwrite", "imsave", "mimsave", "mimwrite", "VideoWriter", "savefig",
           "write_videofile", "write_gif", "write_images", "write_frames", "write_image", "tofile"}
SAVE_MODULES = ("PIL", "matplotlib", "imageio", "skimage", "cv2", "moviepy")
SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", ".pytest_cache"}


def qualified(node, aliases):
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return qualified(node.value, aliases) + "." + node.attr
    if isinstance(node, ast.Call):
        return qualified(node.func, aliases)
    return ""


def python_violations(source, path):
    tree = ast.parse(source, filename=str(path))
    aliases, findings = {}, []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                aliases[name.asname or name.name.split(".")[0]] = name.name
        elif isinstance(node, ast.ImportFrom):
            for name in node.names:
                aliases[name.asname or name.name] = (node.module or "") + "." + name.name
    # Track ordinary aliases and image objects, including Image.open(...).save(...).
    for _ in range(3):
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                name = qualified(node.value, aliases)
                if name:
                    for target in targets:
                        if isinstance(target, ast.Name):
                            aliases[target.id] = name
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = qualified(node.func, aliases)
        terminal = name.rsplit(".", 1)[-1]
        reason = None
        if terminal in WRITERS:
            reason = "image/video writer: " + name
        elif terminal == "save" and name.startswith(SAVE_MODULES):
            reason = "image save: " + name
        elif name.startswith("numpy.") and terminal in {"save", "savez", "savez_compressed", "savetxt"}:
            names = [x.id.lower() for a in node.args for x in ast.walk(a) if isinstance(x, ast.Name)]
            names += [x.id.lower() for a in node.keywords for x in ast.walk(a.value) if isinstance(x, ast.Name)]
            if any(re.search(r"(?:frame|image|pixels)", n) for n in names):
                reason = "raw image array output"
        elif terminal in {"run", "Popen", "call", "check_call", "check_output", "system"}:
            if any(isinstance(x, ast.Constant) and isinstance(x.value, str)
                   and re.search(r"\b(?:ffmpeg|avconv)\b", x.value) for x in ast.walk(node)):
                reason = "external video writer"
        if reason is None and terminal in {"write", "write_bytes", "write_text", "open", "save"}:
            strings = [x.value for x in ast.walk(node) if isinstance(x, ast.Constant) and isinstance(x.value, str)]
            if any(MEDIA_SUFFIX.search(s) for s in strings):
                # Opening a file for read is allowed; image writing is not.
                if terminal != "open" or any(re.search(r"[wax+]", s) for s in strings if len(s) <= 4):
                    reason = "media file output"
            if terminal in {"write", "write_bytes"}:
                names = [x.id.lower() for a in node.args for x in ast.walk(a) if isinstance(x, ast.Name)]
                if any(re.search(r"(?:frame|image|pixels|jpeg|png)", n) for n in names):
                    reason = "raw frame/image output"
        if reason:
            findings.append(f"{path}:{node.lineno}: {reason}")
    return findings


def violations(source, path):
    path = Path(path)
    if path.suffix == ".py":
        return python_violations(source, path.as_posix())
    findings = []
    patterns = [r"\b(?:ffmpeg|avconv)\b", r"\b(?:imwrite|imsave|savefig|writeVideo|toFile)\s*\(",
                r"\b(?:writeFile|writeFileSync|createWriteStream)\s*\([^\n]*\.(?:png|jpe?g|mp4|avi|webm)"]
    for number, line in enumerate(source.splitlines(), 1):
        if line.lstrip().startswith(("#", "//", "*")):
            continue
        if any(re.search(pattern, line) for pattern in patterns):
            findings.append(f"{path.as_posix()}:{number}: image/video output")
    return findings


def scan(root):
    findings = []
    for path in Path(root).rglob("*"):
        relative = path.relative_to(root)
        if any(part in SKIP for part in relative.parts) or path.is_symlink():
            continue
        if path.is_file() and path.suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".cjs", ".mjs", ".cts", ".mts"}:
            findings.extend(violations(path.read_text(encoding="utf-8"), relative.as_posix()))
    return findings
