"""Read-only inventory of media files in the teacher's host and container storage."""
import http.client
import inspect
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import time
from urllib.parse import quote
from urllib.request import build_opener, ProxyHandler

from teacher.privacy import MEDIA_SUFFIX

def media_files(paths, exclude=()):
    """Follow links safely, count each physical regular file once, and never read pixels."""
    pending, directories, found = list(map(Path,paths)), set(), set()
    excluded = [Path(p).resolve() for p in exclude]
    while pending:
        path = pending.pop()
        try:
            resolved = path.resolve()
            if any(resolved==p or p in resolved.parents for p in excluded): continue
            info = path.stat()
            identity = (info.st_dev,info.st_ino)
            if stat.S_ISDIR(info.st_mode):
                if identity in directories: continue
                directories.add(identity)
                with os.scandir(path) as entries:
                    pending.extend(Path(e.path) for e in entries)
            elif stat.S_ISREG(info.st_mode) and (MEDIA_SUFFIX.search(path.name) or MEDIA_SUFFIX.search(path.resolve().name)):
                found.add(identity)
        except OSError as error:
            raise ValueError(f"required audit path cannot be inspected: {path}: {error}") from error
    return found


class Docker:
    def request(self, method, path):
        conn = http.client.HTTPConnection("localhost",timeout=10)
        try:
            conn.sock = socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            conn.sock.settimeout(10)
            conn.sock.connect("/var/run/docker.sock")
            conn.request(method,path)
            reply = conn.getresponse()
            if reply.status != 200: raise ValueError(f"required container cannot be inspected: Docker {reply.status} {path}")
            return json.loads(reply.read())
        except (OSError,TypeError,ValueError,http.client.HTTPException) as error:
            raise ValueError(f"Docker audit failed: {error}") from error
        finally: conn.close()

    def scan(self, container, exclude):
        script = ("import os,stat,re,sys\nfrom pathlib import Path\nMEDIA_SUFFIX=re.compile(sys.argv[1],re.I)\n"
                  +inspect.getsource(media_files)+"\nprint(len(media_files(['/'],sys.argv[2:])))\n")
        try:
            output = subprocess.check_output(["docker","exec","--user","0",container,"python3","-c",script,
                                              MEDIA_SUFFIX.pattern,*exclude],text=True)
            if not output.strip().isdigit(): raise ValueError("invalid container inventory output")
            return int(output.strip())
        except (OSError,subprocess.CalledProcessError) as error:
            raise ValueError("required teacher container must be running and fully inspectable") from error


def default_folders(repo,apps=None):
    repo = Path(repo)
    if apps is None:
        import pwd
        apps = Path(pwd.getpwuid(repo.stat().st_uid).pw_dir)/"ArduinoApps"
    return [repo/"data",repo/"teacher/applab",Path(apps)]


def audit(folders, container, docker=None):
    if not container: raise ValueError("select the running teacher container with --teacher-container (docker ps)")
    folders = [Path(p).resolve() for p in folders]
    if not folders: raise ValueError("required host audit folders are missing")
    for path in folders:
        if not path.is_dir(): raise ValueError(f"required audit folder is missing: {path}")
    docker = docker or Docker()
    prefix = "/containers/"+quote(container,safe="")
    info = docker.request("GET",prefix+"/json")
    if not isinstance(info,dict) or not isinstance(info.get("Mounts"),list): raise ValueError("invalid Docker inspection")
    files, mounts, destinations = [], [], []
    for mount in info["Mounts"]:
        source, destination = mount.get("Source"), mount.get("Destination")
        if not source and destination and mount.get("Type")=="tmpfs": continue
        if not source or not destination: raise ValueError("container mount scope is unknown")
        source = Path(source).resolve()
        if source.is_dir(): mounts.append(source)
        elif source.exists(): files.append(source)
        else: raise ValueError(f"required mounted path is missing: {source}")
        destinations.append(destination.rstrip("/") or "/")
    checked = list(dict.fromkeys(folders+mounts))
    stored = media_files(checked+files)
    count = docker.scan(container,["/proc","/sys","/dev",*destinations])
    if type(count) is not int or count<0: raise ValueError("container inventory is unknown")
    return {"count":len(stored)+count,"folders":[str(p) for p in checked],"files":[str(p) for p in files],
            "containers":[container],"method":"teacher/privacy.py suffixes; all host files and container filesystem; virtual /proc, /sys, /dev excluded; mounts counted on host",
            "meter_images_agree":None}


def check_meter(count, fetch=None, clock=time.time):
    if fetch is None:
        def fetch():
            with build_opener(ProxyHandler({})).open("http://127.0.0.1:8080/privacy",timeout=5) as reply: return json.load(reply)
    value = fetch()
    if value.get("ok") is not True or type(value.get("images")) is not int or type(value.get("t")) is not int:
        raise ValueError("live privacy meter is unavailable or unknown")
    age = clock()*1000-value["t"]
    if not 0<=age<=3000 or value["images"] != count: raise ValueError("live privacy meter is stale or disagrees with storage audit")
    return True
