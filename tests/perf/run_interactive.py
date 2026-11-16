# -*- coding: utf-8 -*-
"""以当前用户的普通交互权限运行 Windows 原生验收，不提升管理员权限。"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--tag", default="run")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout 必须大于 0")
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("需要指定仓库内的 Python 测试脚本")
    return args


def _script(command):
    path = (ROOT / command[0]).resolve()
    if not path.is_relative_to(ROOT) or path.suffix != ".py" or not path.is_file():
        raise ValueError("只允许运行仓库内现有的 Python 脚本")
    return path


def _child(args):
    script = _script(args.command)
    result_path = Path(str(args.log) + ".result.json")
    result = {"pid": os.getpid(), "command": [str(script), *args.command[1:]]}
    with args.log.open("w", encoding="utf-8") as stream:
        try:
            completed = subprocess.run(
                [sys.executable, str(script), *args.command[1:]], cwd=ROOT,
                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                stdout=stream, stderr=subprocess.STDOUT, timeout=args.timeout)
            result["returncode"] = completed.returncode
        except subprocess.TimeoutExpired:
            result["returncode"] = 124
            result["timeout"] = True
        except Exception as exc:
            result["returncode"] = 1
            result["error"] = repr(exc)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result["returncode"]


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _start_task(args, source_sha):
    safe_tag = "".join(char if char.isalnum() or char in "_.-" else "_"
                       for char in args.tag)
    destination = ROOT / "temp" / "performance" / source_sha / "interactive"
    destination.mkdir(parents=True, exist_ok=True)
    log = destination / f"{safe_tag}.log"
    result = Path(str(log) + ".result.json")
    result.unlink(missing_ok=True)
    arguments = subprocess.list2cmdline([
        str(ROOT / "tests" / "perf" / "run_interactive.py"), "--child",
        "--log", str(log), "--timeout", str(args.timeout), "--", *args.command,
    ])
    name = f"InstructionX_UIKit_Validation_{os.getpid()}"
    command = (
        f"$action = New-ScheduledTaskAction -Execute {_quote(sys.executable)} "
        f"-Argument {_quote(arguments)} -WorkingDirectory {_quote(ROOT)}; "
        "$principal = New-ScheduledTaskPrincipal "
        "-UserId \"$env:USERDOMAIN\\$env:USERNAME\" "
        "-LogonType Interactive -RunLevel Limited; "
        "$task = New-ScheduledTask -Action $action -Principal $principal; "
        f"try {{ Register-ScheduledTask -TaskName {_quote(name)} "
        "-InputObject $task -Force -ErrorAction Stop; "
        f"Start-ScheduledTask -TaskName {_quote(name)} -ErrorAction Stop }} "
        f"finally {{ Unregister-ScheduledTask -TaskName {_quote(name)} "
        "-Confirm:$false -ErrorAction SilentlyContinue }"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(f"普通交互任务启动失败: {completed.stdout}\n{completed.stderr}")
    return result


def main():
    args = _arguments()
    _script(args.command)
    if args.child:
        if args.log is None:
            raise ValueError("子进程模式需要 --log")
        return _child(args)
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "uniform_style"], cwd=ROOT, text=True).strip()
    result_path = _start_task(args, source_sha)
    deadline = time.perf_counter() + args.timeout + 30
    while not result_path.exists():
        if time.perf_counter() >= deadline:
            raise TimeoutError(f"交互测试没有返回退出结果: {result_path}")
        time.sleep(0.1)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())
