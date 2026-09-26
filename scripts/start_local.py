"""Start or reuse this checkout, then open the verified local workbench."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "apps/desktop"
API = "http://127.0.0.1:8765"
HTTP = build_opener(ProxyHandler({}))


def get(url):
    with HTTP.open(url, timeout=2) as response:
        return response.read().decode("utf-8")


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def owned_by(port, directory):
    """A matching title alone is insufficient: require this checkout's cwd."""
    try:
        pids = subprocess.check_output(
            ["/usr/sbin/lsof", "-t", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], text=True).split()
        for pid in set(pids):
            cwd = subprocess.check_output(
                ["/usr/sbin/lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], text=True)
            if f"n{directory}\n" not in cwd:
                return False
        return bool(pids)
    except subprocess.CalledProcessError:
        return False


def verify_api(url, database):
    health = json.loads(get(url + "/api/health"))
    if health.get("status") != "ok" or health.get("storage") != "local-sqlite" or health.get("database") != str(database):
        raise RuntimeError("接口未连接预期的本地数据库")


def verify_frontend(url, database):
    if "<title>知行股研</title>" not in get(url):
        raise RuntimeError("该端口不是知行股研页面")
    verify_api(url, database)  # Verify Vite's API proxy, not only its HTML.


def start(command, cwd, logfile, env, probe):
    with logfile.open("ab") as output:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"服务启动退出，请查看 {logfile}")
        try:
            probe()
            return
        except (OSError, ValueError, RuntimeError):
            time.sleep(.25)
    raise RuntimeError(f"服务未在30秒内就绪，请查看 {logfile}；可再次双击检查")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="仅核对路径和依赖")
    parser.add_argument("--no-open", action="store_true", help="启动并核对服务，不打开浏览器")
    args = parser.parse_args()
    python = ROOT / ".venv/bin/python"
    vite = FRONTEND / "node_modules/vite/bin/vite.js"
    node = shutil.which("node")
    if not python.is_file() or not vite.is_file() or not node:
        raise RuntimeError("运行依赖不完整，请先按 README 执行 bootstrap.sh；快捷入口不会自动安装依赖")
    sys.path.insert(0, str(ROOT / "services/desktop-api"))
    from app.settings import get_settings
    settings = get_settings()
    print(f"项目：{ROOT}\n数据：{settings.data_dir}", flush=True)
    if args.check:
        print("启动路径和依赖检查通过")
        return
    logs = settings.data_dir / "launcher"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "launch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        env = dict(os.environ, PYTHONPATH=str(ROOT / "services/desktop-api"))
        if listening(8765):
            if not owned_by(8765, ROOT):
                raise RuntimeError("8765端口被其他项目占用，请先检查占用程序")
            verify_api(API, settings.database_path)
            print("复用已运行的研究接口", flush=True)
        else:
            start([str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8765"],
                  ROOT, logs / "backend.log", env, lambda: verify_api(API, settings.database_path))
            print("研究接口已启动", flush=True)
        available, frontend_port = [], None
        for port in range(5173, 5200):
            if not listening(port):
                available.append(port)
            elif owned_by(port, FRONTEND):
                verify_frontend(f"http://127.0.0.1:{port}", settings.database_path)
                frontend_port = port
                print("复用已运行的研究页面", flush=True)
                break
        if frontend_port is None:
            if not available:
                raise RuntimeError("5173至5199没有可用的网页端口")
            frontend_port = available[0]
            start([node, str(vite), "--host", "127.0.0.1", "--port", str(frontend_port), "--strictPort"],
                  FRONTEND, logs / "frontend.log", env,
                  lambda: verify_frontend(f"http://127.0.0.1:{frontend_port}", settings.database_path))
            print("研究页面已启动", flush=True)
        url = f"http://127.0.0.1:{frontend_port}"
        if not args.no_open:
            opener = ["/usr/bin/open"]
            if Path("/Applications/Tabbit Browser.app").exists():
                opener += ["-a", "Tabbit Browser"]
            subprocess.run([*opener, url], check=True)
        print(f"知行股研已就绪：{url}\n可关闭此终端窗口；服务在后台运行，重复双击会复用。", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        sys.exit(1)
