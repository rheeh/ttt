"""Create a movable macOS app that runs an existing launcher without Terminal."""
from __future__ import annotations

import argparse
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def literal(value):
    if any(character in value for character in "\r\n\0"):
        raise ValueError("名称和路径不能包含换行或空字符")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_app(name, command, output, identifier):
    command = command.expanduser().resolve(strict=True)
    output = output.expanduser().absolute()
    if not command.is_file() or output.suffix != ".app":
        raise ValueError("需要有效的启动脚本和 .app 输出路径")
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", identifier):
        raise ValueError("应用标识只能包含字母、数字、点和短横线")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"目标已存在，未覆盖：{output}")
    source = f'''on run
    set appTitle to {literal(name)}
    set launcherPath to {literal(str(command))}
    set logFolder to (POSIX path of (path to library folder from user domain)) & "Logs/QuickLaunch"
    set logFile to logFolder & "/" & {literal(identifier + '.log')}
    try
        do shell script "/bin/mkdir -p " & quoted form of logFolder
        do shell script "/bin/date '+%Y-%m-%d %H:%M:%S APP_LAUNCH_START' >> " & quoted form of logFile
        do shell script "/bin/bash " & quoted form of launcherPath & " < /dev/null >> " & quoted form of logFile & " 2>&1"
        do shell script "/bin/date '+%Y-%m-%d %H:%M:%S APP_LAUNCH_OK' >> " & quoted form of logFile
    on error errorMessage number errorNumber
        set details to errorMessage
        try
            do shell script "/bin/date '+%Y-%m-%d %H:%M:%S APP_LAUNCH_FAILED' >> " & quoted form of logFile
            set details to do shell script "/usr/bin/tail -n 12 " & quoted form of logFile
        end try
        if (length of details) > 1600 then set details to text -1600 thru -1 of details
        display dialog "启动未完成：" & return & details & return & return & "完整日志：" & logFile buttons {{"好"}} default button "好" with title appTitle with icon caution
    end try
end run
'''
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".quick-launch-build-", dir=output.parent) as temp:
        app = Path(temp) / output.name
        subprocess.run(["/usr/bin/osacompile", "-o", str(app), "-"], input=source, text=True, check=True)
        plist_path = app / "Contents/Info.plist"
        metadata = plistlib.loads(plist_path.read_bytes())
        metadata.update(CFBundleName=name, CFBundleDisplayName=name, CFBundleIdentifier=identifier,
                        CFBundleShortVersionString="1.0", CFBundleVersion="1", LSUIElement=True)
        # This launcher does not use camera, microphone, contacts or other accounts.
        for key in list(metadata):
            if key.startswith("NS") and key.endswith("UsageDescription"):
                del metadata[key]
        plist_path.write_bytes(plistlib.dumps(metadata))
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(app)], check=True)
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
        app.rename(output)
    print(f"已生成：{output}\n目标脚本：{command}\n日志：~/Library/Logs/QuickLaunch/{identifier}.log")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="知行股研")
    parser.add_argument("--command", type=Path, default=ROOT / "scripts/知行股研.command")
    parser.add_argument("--output", type=Path, default=Path.home() / "Desktop/快速启动/知行股研.app")
    parser.add_argument("--identifier", default="local.zhixing.quick-launcher")
    args = parser.parse_args()
    build_app(args.name, args.command, args.output, args.identifier)
