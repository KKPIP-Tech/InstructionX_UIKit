# -*- coding: utf-8 -*-
"""PresentMon 启动权限预检；不自动提权，不生成或替代帧数据。"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    executable = ROOT / "temp" / "tools" / "PresentMon-2.6.0.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"未提供 PresentMon 可执行文件: {executable}")
    source_sha = subprocess.check_output(["git", "rev-parse", "uniform_style"],
                                         cwd=ROOT, text=True).strip()
    destination = ROOT / "temp" / "performance" / source_sha / "presentmon"
    destination.mkdir(parents=True, exist_ok=True)
    target = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"], cwd=ROOT)
    command = [
        str(executable), "--process_id", str(target.pid), "--timed", "1",
        "--terminate_after_timed", "--no_console_stats",
        "--session_name", "InstructionX_UIKit_Preflight",
        "--output_file", str(destination / "preflight.csv"),
    ]
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=15)
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    finally:
        target.wait(timeout=5)
    report = {
        "source_sha": source_sha,
        "test_sha": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                             cwd=ROOT, text=True).strip(),
        "source_dirty": subprocess.run(
            ["git", "diff", "--quiet", source_sha, "--", "InstructionX_UIKit", "demo"],
            cwd=ROOT).returncode != 0,
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "python": sys.version,
        "scope": "仅检查 PresentMon 跟踪启动权限；无图形负载，不是帧数据验收",
        "command": command, "returncode": returncode,
        "stdout": stdout, "stderr": stderr,
        "trace_started": returncode == 0,
        "pass": returncode == 0,
        "elevation_attempted": False,
    }
    if returncode != 0 and "Performance Log Users" in stderr:
        report["blocked_by"] = "需要管理员权限或 Performance Log Users 用户组"
    path = destination / "preflight.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    print(f"原始报告：{path}", flush=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
