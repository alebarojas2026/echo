"""The privacy meter: images stored on the board and bytes it sent out, measured every second.

    python -m board.privacy          # one line a person can read, from the running meter
    python -m board.privacy reset    # count bytes out from zero again (logged with the time)
    python -m board.privacy run      # the meter itself (the radio-sight-privacy unit)

Every second the meter writes /run/radio-sight-privacy/status.json; board/serve.py serves it as
GET /privacy (contract issue #620):
    {"ok": true, "images": 0, "bytes_out": 0, "since_t": <epoch ms>, "t": <epoch ms>}
    {"ok": false, "why": "..."}
ok is false whenever a number can't be read or the last reading is more than 3 s old. Then
there are no numbers: never a zero in place of an unknown.

images: image or video files present now (by name, and by their first bytes for files under
1 GB) in
- data/ in this checkout (sessions, the store, layout saves);
- ~/ArduinoApps, where App Lab keeps its apps, the camera teacher included;
- the folders holding TEACHER_HEARTBEAT, TEACHER_MODE_FILE and TEACHER_CALIB from .env (the
  folders mounted into the teacher's container);
- every folder in PRIVACY_DIRS (separated by ":"), for anything else;
- the files each running container (App Lab's) has added or changed, from Docker's API, by name.
A folder that isn't there is listed as missing, not counted as checked. Installed library
files (site-packages, dist-packages, node_modules), .git and __pycache__ are skipped:
their icons are not stored pictures.

bytes_out: the nftables counter in board/privacy.nft, on the postrouting hook, so it sees the
board's own processes and App Lab's containers as their packets leave. It counts every packet
to an address outside 192.168.77.0/24 (the cable), 10.42.0.0/24 (the sensing hotspot),
loopback, link-local, multicast and broadcast. The unit loads the table as root just before
it starts; reading the counter needs CAP_NET_ADMIN, the only privilege the unit has. The
count survives a restart of the meter (the kernel keeps it); a reboot starts it over, and
the meter says so in its journal.

Standard library only.
"""
import argparse
import datetime
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUN_DIR = Path(os.environ.get("PRIVACY_RUN_DIR", "/run/radio-sight-privacy"))
STATE_DIR = Path(os.environ.get("PRIVACY_STATE_DIR", "/var/lib/radio-sight-privacy"))
STATUS = RUN_DIR / "status.json"
DOCKER_SOCK = "/var/run/docker.sock"
FAMILY, TABLE, COUNTER = "inet", "radio_sight_privacy", "out"
MAX_AGE_MS = 3000
NOT_RUNNING = "privacy meter is not running"

IMAGE_EXT = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff",
             ".heic", ".heif", ".avif", ".ppm", ".pgm", ".pnm", ".raw", ".yuv", ".nv12", ".dng",
             ".mjpg", ".mjpeg", ".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".h264", ".h265",
             ".264", ".265", ".hevc", ".ts", ".3gp", ".flv", ".wmv", ".mpg", ".mpeg"}
SKIP_DIRS = {"site-packages", "dist-packages", "node_modules", ".git", "__pycache__"}
SNIFF_MAX_BYTES = 1 << 30


class Unreadable(Exception):
    """A number can't be read; the message says why in plain words."""


def _ms(clock=time.time) -> int:
    return int(clock() * 1000)


def _stamp(ms: int) -> str:
    return datetime.datetime.fromtimestamp(ms / 1000).astimezone().isoformat(timespec="seconds")


# ---- bytes out ----------------------------------------------------------------------------

class NftCounter:
    """Bytes counted by board/privacy.nft's counter, read with `nft -j`."""

    def __init__(self, nft=None, run=subprocess.run):
        self.nft = nft or os.environ.get("NFT") or shutil.which("nft") or "/usr/sbin/nft"
        self.run = run

    def read(self) -> int:
        try:
            r = self.run([self.nft, "-j", "list", "counter", FAMILY, TABLE, COUNTER],
                         capture_output=True, text=True, timeout=2)
        except FileNotFoundError:
            raise Unreadable("nft is not installed (sudo apt install nftables)") from None
        except subprocess.TimeoutExpired:
            raise Unreadable("nft did not answer within 2 s") from None
        if r.returncode != 0:
            err = (r.stderr or "").strip().splitlines()
            err = err[0] if err else f"exit {r.returncode}"
            if "not permitted" in err.lower():
                raise Unreadable("no permission to read the counter (the unit gives CAP_NET_ADMIN)")
            if "no such file" in err.lower():
                raise Unreadable("the counter isn't loaded (sudo nft -f board/privacy.nft, or restart the unit)")
            raise Unreadable(f"nft failed: {err}")
        try:
            for item in json.loads(r.stdout)["nftables"]:
                n = item.get("counter", {}).get("bytes") if isinstance(item, dict) else None
                if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
                    return n
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
        raise Unreadable("nft's answer has no byte count")


# ---- images stored ------------------------------------------------------------------------

def _looks_like_image(head: bytes) -> bool:
    return (head.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a",
                             b"\x1a\x45\xdf\xa3", b"II*\x00", b"MM\x00*", b"\x00\x00\x00\x01\x67",
                             b"\x00\x00\x00\x01\x40"))
            or head[4:8] == b"ftyp"
            or (head[:4] == b"RIFF" and head[8:12] in (b"WEBP", b"AVI ")))


def is_image_name(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in IMAGE_EXT


def default_folders(env=None, home=None) -> list:
    env = os.environ if env is None else env
    home = Path(home) if home else Path.home()
    folders = [REPO / "data", home / "ArduinoApps"]
    for var in ("TEACHER_HEARTBEAT", "TEACHER_MODE_FILE", "TEACHER_CALIB"):
        if env.get(var):
            folders.append(Path(env[var]).expanduser().parent)
    folders += [Path(p).expanduser() for p in env.get("PRIVACY_DIRS", "").split(":") if p.strip()]
    out = []
    for f in folders:
        f = Path(os.path.abspath(f))
        if f not in out:
            out.append(f)
    return out


class FolderScan:
    """Counts image and video files under folders; a file's first bytes are read once per change."""

    def __init__(self, folders):
        self.folders = [Path(f) for f in folders]
        self.missing = []
        self._sniffed = {}

    def count(self) -> int:
        n, seen, self.missing = 0, set(), []
        for top in self.folders:
            if not top.is_dir():
                self.missing.append(str(top))
                continue
            n += self._walk(top, seen)
        self._sniffed = {k: v for k, v in self._sniffed.items() if k in seen}
        return n

    def _walk(self, top: Path, seen: set) -> int:
        def fail(e):
            raise Unreadable(f"can't read {e.filename or top}: {e.strerror or e}")

        n = 0
        for root, dirs, files in os.walk(top, onerror=fail):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                path = os.path.join(root, name)
                if path in seen:
                    continue
                seen.add(path)
                if is_image_name(name) or self._sniff(path):
                    n += 1
        return n

    def _sniff(self, path: str) -> bool:
        try:
            st = os.stat(path, follow_symlinks=False)
        except FileNotFoundError:
            return False  # gone between listing and looking
        except OSError as e:
            raise Unreadable(f"can't read {path}: {e.strerror}") from None
        if not os.path.isfile(path) or os.path.islink(path) or st.st_size < 8 or st.st_size > SNIFF_MAX_BYTES:
            return False
        key = (st.st_size, st.st_mtime_ns)
        cached = self._sniffed.get(path)
        if cached and cached[0] == key:
            return cached[1]
        try:
            with open(path, "rb") as f:
                verdict = _looks_like_image(f.read(16))
        except FileNotFoundError:
            return False
        except OSError as e:
            raise Unreadable(f"can't read {path}: {e.strerror}") from None
        self._sniffed[path] = (key, verdict)
        return verdict


class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path, timeout=2):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


def docker_get(path: str, sock=DOCKER_SOCK):
    """GET from the Docker Engine API on its unix socket; None when Docker isn't on this machine."""
    if not os.path.exists(sock):
        return None
    conn = _UnixHTTP(sock)
    try:
        conn.request("GET", path)
        r = conn.getresponse()
        body = r.read()
        if r.status != 200:
            raise Unreadable(f"Docker answered {r.status} for {path}")
        return json.loads(body)
    except PermissionError:
        raise Unreadable("can't read App Lab's containers (the user needs to be in the docker group)") from None
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise Unreadable(f"can't read App Lab's containers: {e}") from None
    finally:
        conn.close()


class ContainerScan:
    """Image or video files each running container has added or changed (Docker's /changes)."""

    def __init__(self, get=docker_get):
        self.get = get
        self.containers = 0

    def count(self) -> int:
        listing = self.get("/containers/json")
        if listing is None:
            self.containers = 0
            return 0
        n = 0
        try:
            for c in listing:
                for ch in self.get(f"/containers/{c['Id']}/changes") or []:
                    path = ch.get("Path", "")
                    if ch.get("Kind") in (0, 1) and is_image_name(path) and \
                            not SKIP_DIRS.intersection(path.split("/")):
                        n += 1
        except (KeyError, TypeError, AttributeError):
            raise Unreadable("Docker's list of containers isn't what was expected") from None
        self.containers = len(listing)
        return n


# ---- the meter ----------------------------------------------------------------------------

def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def _write_json(path: Path, doc: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc))
    os.replace(tmp, path)


class Meter:
    """One reading per tick(); status.json in run_dir, the starting point in state_dir."""

    def __init__(self, counter, folders, containers, run_dir=RUN_DIR, state_dir=STATE_DIR,
                 clock=time.time, boot=boot_id, log=None):
        self.counter, self.folders, self.containers = counter, folders, containers
        self.run_dir, self.state_dir = Path(run_dir), Path(state_dir)
        self.clock, self.boot = clock, boot
        self.log = log or (lambda msg: print(f"privacy: {msg}", file=sys.stderr, flush=True))
        self.start = self._load_start()

    def _load_start(self):
        try:
            s = json.loads((self.state_dir / "start.json").read_text())
            if s["boot"] == self.boot() and all(isinstance(s[k], int) for k in ("base", "since_t", "last")):
                return s
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _restart_count(self, now: int, base: int, why: str) -> None:
        self.start = {"boot": self.boot(), "base": base, "since_t": now, "last": base}
        self._save()
        self.log(f"{why}; counting bytes out from 0 at {_stamp(now)}")

    def _save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _write_json(self.state_dir / "start.json", self.start)

    def tick(self) -> dict:
        now = _ms(self.clock)
        try:
            counted = self.counter.read()
            images = self.folders.count() + self.containers.count()
        except Unreadable as e:
            doc = {"ok": False, "why": str(e), "t": now}
        else:
            # With no starting point for this boot, everything the kernel counted is kept: the unit
            # loads the table moments before the first tick, and counting too much is never a lie.
            if self.start is None:
                self._restart_count(now, 0, "started on this boot")
            elif counted < self.start["last"]:
                self._restart_count(now, 0, "the kernel's counter went down (the table was reloaded)")
            if counted != self.start["last"]:  # written only when bytes went out
                self.start["last"] = counted
                self._save()
            self._take_reset(now, counted)
            doc = {"ok": True, "images": images, "bytes_out": counted - self.start["base"],
                   "since_t": self.start["since_t"], "t": now,
                   "missing": self.folders.missing, "folders": len(self.folders.folders),
                   "containers": self.containers.containers}
        self.run_dir.mkdir(parents=True, exist_ok=True)
        _write_json(self.run_dir / "status.json", doc)
        return doc

    def _take_reset(self, now: int, counted: int) -> None:
        req = self.run_dir / "reset"
        if not req.exists():
            return
        was = counted - self.start["base"]
        line = f"{_stamp(now)} reset by the operator: it was {was} bytes out since {_stamp(self.start['since_t'])}"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_dir / "resets.log", "a") as f:
            f.write(line + "\n")
        self._restart_count(now, counted, line)
        req.unlink(missing_ok=True)

    def run(self, every_s=1.0) -> None:
        self.log("checking " + ", ".join(str(f) for f in self.folders.folders) + " and running containers")
        last_why = None
        while True:
            doc = self.tick()
            why = doc.get("why")
            if why != last_why:
                self.log(f"not counting: {why}" if why else "counting")
                last_why = why
            time.sleep(max(0.0, every_s - (time.time() - doc["t"] / 1000)))


# ---- reading it back (board/serve.py and the command line) --------------------------------

def _count(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def status(path=STATUS, now_ms=None, extra=False) -> dict:
    """GET /privacy's answer from the meter's status file (contract issue #620)."""
    now = _ms() if now_ms is None else now_ms
    try:
        doc = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {"ok": False, "why": NOT_RUNNING}
    except (OSError, ValueError):
        return {"ok": False, "why": "the privacy meter's reading can't be read"}
    if not isinstance(doc, dict) or not _count(doc.get("t")):
        return {"ok": False, "why": "the privacy meter's reading can't be read"}
    age = now - doc["t"]
    if age > MAX_AGE_MS:
        return {"ok": False, "why": f"privacy meter stopped updating ({age / 1000:.0f} s ago)"}
    if doc.get("ok") is not True:
        why = doc.get("why")
        return {"ok": False, "why": why if isinstance(why, str) and why else "privacy meter can't count"}
    if not all(_count(doc.get(k)) for k in ("images", "bytes_out", "since_t")):
        return {"ok": False, "why": "the privacy meter's reading can't be read"}
    out = {"ok": True, "images": doc["images"], "bytes_out": doc["bytes_out"],
           "since_t": doc["since_t"], "t": doc["t"]}
    if extra:
        out.update({k: doc.get(k) for k in ("missing", "folders", "containers")})
    return out


def _span(ms: int) -> str:
    s = max(0, ms // 1000)
    if s < 120:
        return f"{s} s"
    if s < 7200:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60} min"


def line(doc: dict) -> str:
    """One line a person can read."""
    if not doc.get("ok"):
        why = doc.get("why")
        return "privacy meter not running" if why == NOT_RUNNING else f"privacy meter can't count: {why}"
    images = doc["images"]
    text = (f"{images} image{'s' if images != 1 else ''} stored, {doc['bytes_out']} bytes sent out, "
            f"counting for {_span(doc['t'] - doc['since_t'])} (since "
            f"{datetime.datetime.fromtimestamp(doc['since_t'] / 1000):%H:%M:%S})")
    if doc.get("folders") is not None:
        checked = doc["folders"] - len(doc.get("missing") or [])
        text += f"; checked {checked} folders and {doc.get('containers') or 0} containers"
        if doc.get("missing"):
            text += "; not there: " + ", ".join(doc["missing"])
    return text


def reset(status_path=STATUS, wait_s=4.0, clock=time.time, sleep=time.sleep) -> int:
    before = status(status_path, extra=True)
    if not before["ok"]:
        print(line(before) + "; nothing reset", file=sys.stderr)
        return 1
    req = Path(status_path).parent / "reset"
    req.write_text(f"{_stamp(_ms(clock))} by {os.environ.get('USER', '?')}\n")
    deadline = clock() + wait_s
    while clock() < deadline:
        sleep(0.2)
        after = status(status_path, extra=True)
        if after["ok"] and after["since_t"] != before["since_t"]:
            print(f"reset: it was {before['bytes_out']} bytes out; now {line(after)}")
            return 0
    print("reset asked, but the meter hasn't taken it yet; run python -m board.privacy to check", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="The privacy meter: images stored, bytes sent out")
    ap.add_argument("what", nargs="?", default="show", choices=("show", "reset", "run"))
    ap.add_argument("--status", default=str(STATUS), help="the meter's status file")
    args = ap.parse_args(argv)
    if args.what == "run":
        status_path = Path(args.status)
        Meter(NftCounter(), FolderScan(default_folders()), ContainerScan(),
              run_dir=status_path.parent).run()
        return 0
    if args.what == "reset":
        return reset(args.status)
    doc = status(args.status, extra=True)
    print(line(doc))
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
