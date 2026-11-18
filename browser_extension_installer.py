import os
import shutil
import subprocess
import sys
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

APPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EasySaveAudio"
DEST = APPDATA / "browser_extension"

BROWSERS = [
    ("Chrome", "chrome.exe", "chrome://extensions"),
    ("Microsoft Edge", "msedge.exe", "edge://extensions"),
    ("네이버 웨일", "whale.exe", "whale://extensions"),
]

def resource_dir():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "browser_extension"
    return Path(__file__).resolve().parent / "browser_extension"

def registry_browser(exe_name):
    try:
        import winreg
        keys = [
            (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"),
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"),
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"),
        ]
        for hive, key_path in keys:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    value, _ = winreg.QueryValueEx(key, None)
                    candidate = Path(value)
                    if candidate.is_file():
                        return str(candidate)
            except OSError:
                continue
    except ImportError:
        pass
    return None

def find_browser(exe_name):
    from shutil import which
    candidate = which(exe_name)
    if candidate:
        return candidate
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    program_files = [Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
                     Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))]
    roots = {
        "chrome.exe": [local / "Google/Chrome/Application/chrome.exe"] +
                      [p / "Google/Chrome/Application/chrome.exe" for p in program_files],
        "msedge.exe": [local / "Microsoft/Edge/Application/msedge.exe"] +
                      [p / "Microsoft/Edge/Application/msedge.exe" for p in program_files],
        "whale.exe": [local / "Naver/Naver Whale/Application/whale.exe"] +
                     [p / "Naver/Naver Whale/Application/whale.exe" for p in program_files],
    }
    registered = registry_browser(exe_name)
    if registered:
        return registered
    for path in roots.get(exe_name, []):
        if path.is_file():
            return str(path)
    return None

def main():
    root = tk.Tk()
    root.withdraw()
    source = resource_dir()
    if not source.is_dir() or not (source / "manifest.json").is_file():
        messagebox.showerror("Right Click 설치", "설치 파일에서 확장 프로그램 구성 파일을 찾을 수 없습니다.")
        return
    try:
        DEST.parent.mkdir(parents=True, exist_ok=True)
        if DEST.exists():
            shutil.rmtree(DEST)
        shutil.copytree(source, DEST)
    except Exception as exc:
        messagebox.showerror("Right Click 설치", f"확장 프로그램 파일 설치에 실패했습니다.\n{exc}")
        return

    detected = []
    for display_name, exe_name, extension_url in BROWSERS:
        executable = find_browser(exe_name)
        if executable:
            detected.append(display_name)
            try:
                subprocess.Popen([executable, extension_url])
            except OSError:
                pass

    if detected:
        browser_text = ", ".join(detected)
        message = (
            "확장 프로그램 파일을 준비했습니다.\n\n"
            f"검색된 브라우저: {browser_text}\n"
            f"설치 폴더: {DEST}\n\n"
            "열린 각 브라우저의 확장 프로그램 화면에서 개발자 모드를 켜고 "
            "'압축해제된 확장 프로그램을 로드합니다'를 한 번 선택한 뒤 위 폴더를 지정해 주세요.\n\n"
            "브라우저 보안정책상 최초 등록 승인만 직접 필요합니다. JS·JSON 파일을 각각 열거나 선택하지 마세요."
        )
    else:
        message = (
            "확장 프로그램 파일을 준비했습니다.\n\n"
            f"설치 폴더: {DEST}\n\n"
            "Chrome, Edge 또는 네이버 웨일을 찾지 못했습니다. 브라우저 설치 후 확장 프로그램 화면에서 "
            "개발자 모드를 켜고 '압축해제된 확장 프로그램을 로드합니다'를 선택해 위 폴더를 지정해 주세요."
        )
    messagebox.showinfo("Right Click 설치", message)

if __name__ == "__main__":
    main()
