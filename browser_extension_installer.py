import os
import shutil
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
import webbrowser

APPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EasySaveAudio"
DEST = APPDATA / "browser_extension"

def resource_dir():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "browser_extension"
    return Path(__file__).resolve().parent / "browser_extension"

def main():
    root = tk.Tk()
    root.withdraw()
    source = resource_dir()
    if not source.exists():
        messagebox.showerror("확장 프로그램 설치", "설치 파일에서 확장 프로그램 폴더를 찾을 수 없습니다.")
        return
    try:
        if DEST.exists():
            shutil.rmtree(DEST)
        DEST.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, DEST)
    except Exception as exc:
        messagebox.showerror("확장 프로그램 설치", f"파일 설치에 실패했습니다.\n{exc}")
        return

    webbrowser.open("https://chrome.google.com/webstore/category/extensions")
    webbrowser.open("chrome://extensions")
    messagebox.showinfo(
        "확장 프로그램 파일 설치 완료",
        "확장 프로그램 파일을 다음 위치에 설치했습니다.\n\n"
        f"{DEST}\n\n"
        "Chrome 확장 프로그램 화면에서 개발자 모드를 켠 뒤 "
        "'압축해제된 확장 프로그램을 로드합니다'를 선택하고 위 폴더를 지정해 주세요.\n\n"
        "Chrome 정책상 이 마지막 등록 단계는 최초 1회 직접 진행해야 합니다."
    )
    try:
        os.startfile(str(DEST))
    except Exception:
        pass

if __name__ == "__main__":
    main()
