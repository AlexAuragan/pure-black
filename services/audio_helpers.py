import json
import subprocess
from pprint import pprint
from typing import Any


def _pw_dump_nodes() -> list[dict[str, Any]]:
    p = subprocess.run(["pw-dump"], capture_output=True, text=True, check=True)
    data = json.loads(p.stdout)
    return data if isinstance(data, list) else []

def is_pid_playing(pid: int) -> bool | None:
    if pid <= 0:
        return

    nodes = _pw_dump_nodes()
    for node in nodes:

        # Only keep nodes that are playing sound
        if node.get("type") != "PipeWire:Interface:Node":
            continue
        info = node.get("info")
        if not isinstance(info, dict):
            continue
        props = info.get("props") or {}
        if not isinstance(props, dict):
            continue
        if props.get("media.class") != "Stream/Output/Audio":
            continue

        pprint(node)

        ppid = props.get("application.process.id", 0)
        if ppid == pid:
            return info.get("state") == "running"
        continue
    return False