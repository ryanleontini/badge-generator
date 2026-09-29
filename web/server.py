"""Local web UI for the badge generator.

    python3 web/server.py          # then open http://127.0.0.1:8000

Serves web/index.html, validates configs with badge.config (the same rules as
the CLI), and runs Blender headless for each build. Standard library only;
binds to localhost so nothing is exposed to the network.
"""

import argparse
import base64
import importlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from badge import config  # noqa: E402  (pure Python, no Blender needed)

WEB = ROOT / "web"
OUT = ROOT / "out" / "web"
ART = ROOT / "art"
MAX_UPLOAD = 5 * 1024 * 1024
BUILD_TIMEOUT = 300  # seconds
MAC_BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")
OUTPUT_KINDS = ("full", "base", "emblem", "preview")

_build_lock = threading.Lock()  # one Blender run at a time
_reload_lock = threading.Lock()


def find_blender() -> str | None:
    found = shutil.which("blender")
    if found:
        return found
    return str(MAC_BLENDER) if MAC_BLENDER.is_file() else None


def presets() -> dict[str, dict]:
    """Built-in defaults plus every configs/*.toml, as plain section dicts."""
    out = {"defaults": sections_of(config.load_config(None, ROOT))}
    for path in sorted((ROOT / "configs").glob("*.toml")):
        try:
            out[path.stem] = sections_of(config.load_config(path, ROOT))
        except config.ConfigError:
            continue  # a broken config shouldn't take the UI down
    return out


def sections_of(cfg: config.BadgeConfig) -> dict:
    return {name: asdict(getattr(cfg, name)) for name in config.SECTIONS}


def to_toml(sections: dict) -> str:
    """Serialize config sections to TOML (the value types config.py accepts)."""
    lines = []
    for name, table in sections.items():
        lines.append(f"[{name}]")
        lines += [f"{key} = {_toml_value(value)}" for key, value in table.items()]
        lines.append("")
    return "\n".join(lines)


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)  # JSON escapes are valid TOML
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"cannot write {value!r} to TOML")


def save_upload(upload: dict) -> Path:
    """Write an uploaded SVG into art/ (where the configs expect artwork)."""
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(upload.get("name", "emblem")).stem) or "emblem"
    data = base64.b64decode(upload["data"])
    if len(data) > MAX_UPLOAD:
        raise ValueError("SVG is larger than 5 MB")
    if b"<svg" not in data[:4096]:
        raise ValueError("uploaded file is not an SVG")
    ART.mkdir(exist_ok=True)
    path = ART / f"{stem}.svg"
    path.write_bytes(data)
    return path


def validate(sections: dict) -> list[str]:
    try:
        config.from_dict(sections, ROOT)
    except config.ConfigError as exc:
        return exc.errors
    return []


def build(sections: dict) -> dict:
    blender = find_blender()
    if not blender:
        return {"ok": False, "errors": ["Blender not found: install it or put `blender` on PATH"]}
    name = sections.get("badge", {}).get("name", "badge")
    run_sections = {**sections, "export": {"split_bodies": True, "single_body": True,
                                           "render_preview": True, "out_dir": str(OUT)}}
    OUT.mkdir(parents=True, exist_ok=True)
    config_path = OUT / f"{name}.toml"
    config_path.write_text(to_toml(run_sections), encoding="utf-8")

    cmd = [blender, "--background", "--factory-startup", "--quiet", "--python-exit-code", "1",
           "--python", str(ROOT / "badge_gen.py"), "--", "--config", str(config_path)]
    start = time.perf_counter()
    with _build_lock:
        try:
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                                  timeout=BUILD_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "errors": [f"build timed out after {BUILD_TIMEOUT} s"]}
    log = "\n".join(line for line in (proc.stdout + proc.stderr).splitlines()
                    if line.startswith("[badge]") or "Traceback" in line or "Error" in line)
    stamp = int(time.time() * 1000)
    files = {kind: f"/out/{name}_{kind}.{'png' if kind == 'preview' else 'stl'}?t={stamp}"
             for kind in OUTPUT_KINDS
             if (OUT / f"{name}_{kind}.{'png' if kind == 'preview' else 'stl'}").is_file()}
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "seconds": round(time.perf_counter() - start, 1),
        "log": log,
        "errors": [ln.split(": ", 1)[-1] for ln in log.splitlines() if " ERROR: " in ln],
        "files": files if proc.returncode == 0 else {},
    }


def _reload_config() -> None:
    """Pick up edits to badge/config.py without restarting the server.

    Builds always run fresh in Blender; this keeps presets and live validation
    in step with them (the module is pure Python and reloads in ~1 ms).
    """
    global config
    with _reload_lock:
        config = importlib.reload(config)


class Handler(BaseHTTPRequestHandler):
    server_version = "BadgeGenerator"

    def do_GET(self):
        _reload_config()
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            self._send_file(WEB / "index.html", "text/html; charset=utf-8")
        elif path == "/api/presets":
            self._send_json({"presets": presets(), "blender": find_blender()})
        elif path.startswith("/out/"):
            target = (OUT / path.removeprefix("/out/")).resolve()
            if target.parent != OUT.resolve() or not target.is_file():
                return self.send_error(HTTPStatus.NOT_FOUND)
            kind = "image/png" if target.suffix == ".png" else "model/stl"
            self._send_file(target, kind, download=target.suffix != ".png")
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        _reload_config()
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD * 2:
            return self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/upload":
                path = save_upload(payload)
                return self._send_json({"svg_path": str(path.relative_to(ROOT))})
            if self.path == "/api/validate":
                return self._send_json({"errors": validate(payload.get("config", {}))})
            if self.path == "/api/build":
                sections = payload.get("config", {})
                errors = validate(sections)
                return self._send_json(build(sections) if not errors
                                       else {"ok": False, "errors": errors})
        except (ValueError, KeyError, TypeError) as exc:
            return self._send_json({"ok": False, "errors": [str(exc)]}, HTTPStatus.BAD_REQUEST)
        self.send_error(HTTPStatus.NOT_FOUND)

    def _send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str, download: bool = False):
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if download:
            self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # quieter console: only errors
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Badge generator UI at {url}  (Ctrl+C to stop)")
    print(f"Blender: {find_blender() or 'NOT FOUND'}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
