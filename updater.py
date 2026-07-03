"""updater.exe — 替换运行中的 exe 并启动新版本
用法: updater.exe <old_exe>|<new_exe>
"""
import sys
import os
import time
import subprocess


def main():
    old, new = sys.argv[1].split("|", 1)

    # 等主程序完全退出
    time.sleep(1.5)

    # 重命名旧 exe → .old
    backup = old + ".old"
    for _ in range(10):
        try:
            if os.path.exists(backup):
                os.remove(backup)
            os.rename(old, backup)
            break
        except OSError:
            time.sleep(0.5)
    else:
        return 1

    # 复制新 exe 到旧位置
    with open(new, "rb") as src, open(old, "wb") as dst:
        while True:
            chunk = src.read(8192)
            if not chunk:
                break
            dst.write(chunk)

    # 启动新版本
    flags = subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0
    subprocess.Popen([old], creationflags=flags)

    # 清理备份
    try:
        os.remove(backup)
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
