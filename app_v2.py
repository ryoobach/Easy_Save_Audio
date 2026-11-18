import json
import html
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import imageio_ffmpeg
import yt_dlp
try:
    from tkinterdnd2 import TkinterDnD
except ImportError:
    TkinterDnD = None

APP_NAME = "Easy Save Audio & Video"
APP_VERSION = "2.0.4"
APPDATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "EasySaveAudio"
APPDATA.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = APPDATA / "settings.json"
MAX_HISTORY = 200
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpeg", ".mpg"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff"}

def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            # Migrate 1.x settings without discarding the user's previous MP3 folder or history.
            if "last_mp3_dir" not in data and data.get("last_save_dir"):
                data["last_mp3_dir"] = data["last_save_dir"]
            data.setdefault("last_video_dir", str(Path.home() / "Videos"))
            data.setdefault("last_mp3_dir", str(Path.home() / "Music"))
            old_history = data.get("history", [])
            if isinstance(old_history, list):
                for item in old_history:
                    if isinstance(item, dict) and "source" not in item and "url" in item:
                        item["source"] = item.get("url", "")
            return data
    except Exception:
        pass
    music = str(Path.home() / "Music")
    videos = str(Path.home() / "Videos")
    return {"last_mp3_dir": music, "last_video_dir": videos, "history": []}

def save_settings(data):
    temp = SETTINGS_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(SETTINGS_FILE)

def safe_name(value):
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(value or "")).strip(" .")
    return (value or "media")[:150]

def ffmpeg_path():
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        found = list(base.glob("ffmpeg*.exe"))
        if found:
            return str(found[0])
    return imageio_ffmpeg.get_ffmpeg_exe()

def is_url(value):
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)

class EasySaveApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME}  {APP_VERSION}")
        self.root.geometry("860x640")
        self.root.minsize(720, 540)
        self.settings = load_settings()
        self.events = queue.Queue()
        self.jobs = {}
        self.job_counter = 0
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="media-job")
        self.ffmpeg = ffmpeg_path()
        self.closing = False
        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll_events)

    def build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Utility.TButton", padding=(10, 6))
        style.configure("About.TButton", padding=(10, 6))
        style.configure("Start.TButton", padding=(16, 10), font=("Malgun Gothic", 10, "bold"))
        outer = ttk.Frame(self.root, padding=(18, 14))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 10))
        icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "easy_save_audio.png"
        brand = ttk.Frame(header)
        brand.pack(side="left", fill="x", expand=True)
        try:
            self.header_image = tk.PhotoImage(file=str(icon_path))
            self.header_image = self.header_image.subsample(3, 3)
            ttk.Label(brand, image=self.header_image).pack(side="left", padx=(0, 10))
            self.root.iconphoto(True, self.header_image)
        except Exception:
            pass
        title_area = ttk.Frame(brand)
        title_area.pack(side="left", fill="x", expand=True)
        title_row = ttk.Frame(title_area)
        title_row.pack(anchor="w", fill="x")
        ttk.Label(title_row, text=APP_NAME, font=("Malgun Gothic", 18, "bold")).pack(side="left")
        ttk.Label(title_row, text=APP_VERSION, font=("Segoe UI", 11, "bold"), foreground="#b51f32").pack(side="left", padx=(10, 0))
        ttk.Button(header, text="앱 정보", command=self.show_about, style="Utility.TButton", width=16).pack(side="right", padx=(10, 0), pady=2)

        self.tabs = ttk.Notebook(title_area)
        self.tabs.pack(anchor="w", fill="x", pady=(3, 0))
        self.mp3_tab = ttk.Frame(self.tabs, padding=14)
        self.video_tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(self.mp3_tab, text="MP3 다운로드")
        self.tabs.add(self.video_tab, text="동영상 다운로드")
        self.build_tab(self.mp3_tab, "mp3")
        self.build_tab(self.video_tab, "video")

        queue_header = ttk.Frame(outer)
        queue_header.pack(fill="x", pady=(4, 6))
        ttk.Label(queue_header, text="작업 목록", font=("Malgun Gothic", 12, "bold")).pack(side="left")
        ttk.Button(queue_header, text="완료 작업 지우기", command=self.clear_completed, style="Utility.TButton", width=16).pack(side="right")
        ttk.Label(queue_header, text="동시 실행 2개", foreground="#666").pack(side="right", padx=12)

        columns = ("source", "kind", "status", "progress")
        queue_area = ttk.Frame(outer)
        queue_area.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(queue_area, columns=columns, show="headings", height=10, selectmode="browse")
        self.tree.heading("source", text="파일 / URL")
        self.tree.heading("kind", text="작업")
        self.tree.heading("status", text="상태")
        self.tree.heading("progress", text="진행률")
        self.tree.column("source", width=440, anchor="w")
        self.tree.column("kind", width=110, anchor="center")
        self.tree.column("status", width=120, anchor="center")
        self.tree.column("progress", width=100, anchor="center")
        queue_scroll = ttk.Scrollbar(queue_area, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=queue_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        queue_scroll.pack(side="right", fill="y")
        self.tree.bind("<Delete>", lambda _e: self.cancel_selected())

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(8, 0))
        ttk.Button(controls, text="선택 작업 취소", command=self.cancel_selected).pack(side="left")
        ttk.Button(controls, text="작업 기록", command=self.show_history).pack(side="left", padx=8)
        ttk.Label(controls, text="다운로드 및 변환 작업은 각각 독립적으로 처리됩니다.", foreground="#666").pack(side="right")

    def build_tab(self, tab, mode):
        # Reference layout: options first, then one address row, then save folder/actions.
        options = ttk.Frame(tab)
        options.pack(fill="x", pady=(0, 8))
        both = tk.BooleanVar(value=False)
        other_label = "동영상" if mode == "mp3" else "MP3"
        ttk.Checkbutton(options, text=other_label, variable=both).pack(side="left", padx=(168, 18))
        self.browser_drag_var = getattr(self, "browser_drag_var", tk.BooleanVar(value=False))
        ttk.Checkbutton(
            options, text="드래그 앤 드롭으로 주소 자동 입력",
            variable=self.browser_drag_var
        ).pack(side="left", padx=(0, 0))

        input_row = ttk.Frame(tab)
        input_row.pack(fill="x", pady=(0, 12))
        ttk.Label(input_row, text="주소", font=("Malgun Gothic", 11)).pack(side="left", padx=(0, 32))
        url_var = tk.StringVar()
        entry = ttk.Entry(input_row, textvariable=url_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self.stage_url(mode, url_var, both))
        ttk.Button(
            input_row, text="붙여넣기", command=lambda: self.paste_url(url_var, entry),
            style="Utility.TButton", width=10
        ).pack(side="left", padx=(8, 0))
        self.bind_entry_menu(entry, url_var)

        save_label = "MP3 저장 폴더" if mode == "mp3" else "동영상 저장 폴더"
        folder = tk.StringVar(value=self.settings.get(
            "last_mp3_dir" if mode == "mp3" else "last_video_dir", str(Path.home())
        ))
        folder_row = ttk.Frame(tab)
        folder_row.pack(fill="x", pady=(2, 0))
        ttk.Label(folder_row, text=save_label + ":").pack(side="left")
        ttk.Label(folder_row, textvariable=folder, foreground="#555").pack(side="left", padx=6)
        folder_actions = ttk.Frame(folder_row)
        folder_actions.pack(side="right")
        ttk.Button(
            folder_actions, text="변경", command=lambda: self.choose_folder(mode, folder),
            style="Utility.TButton", width=10
        ).pack(side="left")
        ttk.Button(
            folder_actions, text="다운로드 시작", command=lambda: self.start_current(mode, url_var, both),
            style="Start.TButton", width=16
        ).pack(side="left", padx=(8, 0), pady=2)

        if mode == "mp3":
            self.mp3_folder = folder
            self.mp3_url = url_var
        else:
            self.video_folder = folder
            self.video_url = url_var

        ttk.Label(
            tab, text="파일을 이 영역으로 드래그해 추가할 수도 있습니다(Windows 파일 드롭 지원).",
            foreground="#777"
        ).pack(anchor="w", pady=(8, 0))

        # Register browser payload formats as well as Windows file drops.
        try:
            import tkinterdnd2 as tkdnd
            drop_types = [
                getattr(tkdnd, "DND_FILES", "DND_Files"),
                getattr(tkdnd, "DND_TEXT", "DND_Text"),
                getattr(tkdnd, "DND_HTML", "DND_HTML"),
                getattr(tkdnd, "DND_URL", "DND_URL"),
            ]
            for widget in (tab, entry):
                try:
                    widget.drop_target_register(*drop_types)
                except Exception:
                    widget.drop_target_register(
                        getattr(tkdnd, "DND_FILES", "DND_Files"),
                        getattr(tkdnd, "DND_TEXT", "DND_Text")
                    )
                widget.dnd_bind("<<Drop>>", lambda e, m=mode, b=both, v=url_var: self.handle_drop(e, m, b, v))
        except Exception as exc:
            self.dnd_error = str(exc)
            ttk.Label(tab, text="드래그 앤 드롭을 사용할 수 없습니다. 초기화 상태를 확인해 주세요.",
                      foreground="#b51f32").pack(anchor="w", pady=(4, 0))

    def choose_folder(self, mode, folder_var):
        selected = filedialog.askdirectory(parent=self.root, initialdir=folder_var.get() or str(Path.home()))
        if selected:
            folder_var.set(selected)
            key = "last_mp3_dir" if mode == "mp3" else "last_video_dir"
            self.settings[key] = selected
            save_settings(self.settings)

    def paste_url(self, url_var, entry):
        try:
            value = self.root.clipboard_get().strip()
        except tk.TclError:
            messagebox.showinfo("붙여넣기", "클립보드에 주소가 없습니다.", parent=self.root)
            return
        url_var.set(value)
        entry.focus_set()
        entry.icursor(tk.END)

    def bind_entry_menu(self, entry, url_var):
        menu = tk.Menu(entry, tearoff=0)
        menu.add_command(label="잘라내기", command=lambda: entry.event_generate("<<Cut>>"))
        menu.add_command(label="복사", command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label="붙여넣기", command=lambda: self.paste_url(url_var, entry))
        menu.add_separator()
        menu.add_command(label="모두 선택", command=lambda: (entry.select_range(0, tk.END), entry.icursor(tk.END)))
        menu.add_command(label="삭제", command=lambda: url_var.set(""))
        entry.bind("<Button-3>", lambda e: (menu.tk_popup(e.x_root, e.y_root), "break"))
        entry.bind("<Control-v>", lambda e: (self.paste_url(url_var, entry), "break")[1])
        entry.bind("<Control-V>", lambda e: (self.paste_url(url_var, entry), "break")[1])
        entry.bind("<Shift-Insert>", lambda e: (self.paste_url(url_var, entry), "break")[1])

    def stage_url(self, mode, url_var, both=None):
        url = url_var.get().strip()
        if not is_url(url):
            messagebox.showwarning("주소 확인", "http:// 또는 https://로 시작하는 주소를 입력해 주세요.", parent=self.root)
            return
        include_other = bool(both.get()) if both is not None else False
        outputs = ["mp3", "video"] if include_other else [mode]
        self.enqueue(url, "url", outputs)

    def add_files(self, mode, url_var=None):
        files = filedialog.askopenfilenames(parent=self.root, title="미디어 파일 선택")
        if not files:
            return
        if url_var is not None:
            url_var.set(files[0] if len(files) == 1 else f"{len(files)}개 파일 선택")
        for filename in files:
            ext = Path(filename).suffix.lower()
            if ext in VIDEO_EXTENSIONS or ext in AUDIO_EXTENSIONS:
                self.enqueue(filename, "local", ["mp3"])
            else:
                messagebox.showwarning("지원하지 않는 파일", f"지원하지 않는 미디어 파일입니다.\n{filename}", parent=self.root)

    def handle_drop(self, event, mode, both, url_var):
        raw_data = html.unescape(str(event.data or "")).strip()

        # Browser drag formats differ: plain text, URI list, CF_HTML, or URL + title.
        if self.browser_drag_var.get():
            candidates = []
            candidates.extend(re.findall(
                r"""(?i)href\s*=\s*["']([^"']+)["']""", raw_data
            ))
            candidates.extend(re.findall(
                r"""(?i)(?:SourceURL|URL)\s*:\s*(https?://[^\s]+)""", raw_data
            ))
            candidates.extend(re.findall(
                r"""https?://[^\s<>"']+""", raw_data, flags=re.IGNORECASE
            ))
            try:
                candidates.extend(self.root.tk.splitlist(event.data))
            except Exception:
                pass

            cleaned = []
            for candidate in candidates:
                value = html.unescape(str(candidate)).strip().strip(" \t\r\n\\\"'<>(),;")
                value = value.splitlines()[0].strip() if value else ""
                value = value.rstrip(".,;)")
                if is_url(value) and value not in cleaned:
                    cleaned.append(value)

            # Prefer the YouTube page URL over a thumbnail/image URL.
            selected = next(
                (u for u in cleaned if re.search(
                    r"(?i)^https?://(?:(?:www|m)\.)?(?:youtube\.com|youtu\.be)/", u
                )),
                cleaned[0] if cleaned else None
            )
            if selected:
                url_var.set(selected)
                try:
                    event.widget.focus_set()
                    if isinstance(event.widget, ttk.Entry):
                        event.widget.icursor(tk.END)
                except Exception:
                    pass
                return "break"

        try:
            dropped = self.root.tk.splitlist(event.data)
        except Exception:
            dropped = [event.data]
        files = [str(item).strip().strip("{}").strip() for item in dropped if str(item).strip()]
        files = [item for item in files if not is_url(item)]
        media_files = [
            item for item in files
            if Path(item).suffix.lower() in VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
        ]
        if media_files:
            url_var.set(media_files[0] if len(media_files) == 1 else f"{len(media_files)}개 파일 선택")
            for filename in media_files:
                self.enqueue(filename, "local", ["mp3"])
            return "break"

        if self.browser_drag_var.get():
            messagebox.showinfo(
                "주소 자동 입력",
                "드롭한 항목에서 웹 주소를 찾지 못했습니다.\n\n"
                "유튜브 영상 화면 자체가 아니라 영상 제목이나 공유 링크를 드래그해 "
                "주소 입력란에 놓아 주세요. 브라우저가 영상 화면 드래그에 주소를 "
                "제공하지 않는 경우에는 주소 자동 입력이 불가능합니다.",
                parent=self.root
            )
        return "break"

    def start_current(self, mode, url_var, both):
        value = url_var.get().strip()
        if value:
            if not is_url(value):
                messagebox.showwarning("주소 확인", "올바른 http:// 또는 https:// 주소를 입력해 주세요.", parent=self.root)
                return
            self.stage_url(mode, url_var, both)
            url_var.set("")
        self.start_pending()

    def start_pending(self):
        pending = [job_id for job_id, job in self.jobs.items()
                   if not job.get("submitted") and job["status"] == "대기 중"]
        if not pending:
            messagebox.showinfo("변환 시작", "실행할 작업이 없습니다. 주소를 붙여넣거나 파일을 선택해 주세요.", parent=self.root)
            return
        for job_id in pending:
            self.jobs[job_id]["submitted"] = True
            self.executor.submit(self.run_job, job_id)

    def enqueue(self, source, source_type, outputs):
        if source_type == "local":
            path = Path(source)
            if not path.exists() or not path.is_file():
                messagebox.showwarning("파일 확인", f"파일을 찾을 수 없습니다.\n{source}", parent=self.root)
                return
            ext = path.suffix.lower()
            if "mp3" in outputs and ext not in VIDEO_EXTENSIONS | AUDIO_EXTENSIONS:
                messagebox.showwarning("지원하지 않는 파일", f"지원 여부를 확인할 수 없는 파일입니다.\n{path.name}", parent=self.root)
                return
            if "video" in outputs and ext not in VIDEO_EXTENSIONS:
                messagebox.showwarning("동영상 파일 확인", f"동영상 파일이 아닙니다.\n{path.name}", parent=self.root)
                return
        self.job_counter += 1
        job_id = str(self.job_counter)
        name = Path(source).name if source_type == "local" else source
        kind = "+".join("MP3" if x == "mp3" else "동영상" for x in outputs)
        job = {"id": job_id, "source": source, "source_type": source_type, "outputs": outputs,
               "cancel": threading.Event(), "status": "대기 중", "progress": 0,
               "started": time.time(), "submitted": False}
        self.jobs[job_id] = job
        self.tree.insert("", "end", iid=job_id, values=(name, kind, "대기 중", "0%"))
        self.tree.see(job_id)
        # Queue only; execution starts after the user presses [변환 시작].

    def emit(self, job_id, status=None, progress=None, detail=None):
        self.events.put((job_id, status, progress, detail))

    def run_job(self, job_id):
        job = self.jobs[job_id]
        try:
            self.emit(job_id, "처리 중", 0, None)
            source = job["source"]
            source_type = job["source_type"]
            if source_type == "url":
                self.process_url(job_id, source, job["outputs"], job["cancel"])
            else:
                self.process_local(job_id, Path(source), job["outputs"], job["cancel"])
            if job["cancel"].is_set():
                self.emit(job_id, "취소", None, None)
            else:
                self.emit(job_id, "완료", 100, None)
                self.record_history(source, "완료", ", ".join(job["outputs"]))
        except Exception as exc:
            if job["cancel"].is_set():
                self.emit(job_id, "취소", None, None)
                self.record_history(job["source"], "취소", "사용자가 작업을 취소했습니다.")
            else:
                self.emit(job_id, "오류", None, str(exc))
                self.record_history(job["source"], "오류", str(exc))

    def output_folder(self, kind):
        key = "last_mp3_dir" if kind == "mp3" else "last_video_dir"
        folder = Path(self.settings.get(key, str(Path.home())))
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def process_url(self, job_id, url, outputs, cancel):
        if cancel.is_set():
            return
        is_youtube = urllib.parse.urlparse(url).netloc.lower().endswith(("youtube.com", "youtu.be"))
        info_opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        title = safe_name(info.get("title") or "media")
        if cancel.is_set():
            return
        video_file = None
        if "video" in outputs:
            folder = self.output_folder("video")
            outtmpl = str(folder / (title + ".%(ext)s"))
            opts = {"format": "bv*+ba/b", "outtmpl": outtmpl, "merge_output_format": "mp4",
                    "ffmpeg_location": self.ffmpeg,
                    "quiet": True, "no_warnings": True, "noplaylist": True,
                    "progress_hooks": [lambda d: self.ytdlp_progress(job_id, d, cancel)],
                    "retries": 3, "fragment_retries": 3}
            with yt_dlp.YoutubeDL(opts) as ydl:
                result = ydl.extract_info(url, download=True)
                video_file = Path(ydl.prepare_filename(result))
                if not video_file.exists():
                    matches = list(folder.glob(title + ".*"))
                    video_file = next((p for p in matches if p.suffix.lower() in VIDEO_EXTENSIONS), None)
            if cancel.is_set():
                return
        if "mp3" in outputs:
            folder = self.output_folder("mp3")
            target = folder / (title + ".mp3")
            if video_file and video_file.exists():
                source_file = video_file
            else:
                temp_dir = APPDATA / "temp"
                temp_dir.mkdir(exist_ok=True)
                template = str(temp_dir / (title + ".%(ext)s"))
                opts = {"format": "bestaudio/best", "outtmpl": template, "quiet": True,
                        "no_warnings": True, "noplaylist": True,
                        "progress_hooks": [lambda d: self.ytdlp_progress(job_id, d, cancel)],
                        "retries": 3, "fragment_retries": 3}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    result = ydl.extract_info(url, download=True)
                    source_file = Path(ydl.prepare_filename(result))
                if not source_file.exists():
                    candidates = list(temp_dir.glob(title + ".*"))
                    source_file = next((p for p in candidates if p.is_file()), None)
                if source_file is None or not source_file.exists():
                    raise RuntimeError("오디오 다운로드 결과 파일을 찾을 수 없습니다.")
            self.encode_mp3(job_id, source_file, target, cancel)
            if not video_file and source_file.parent == APPDATA / "temp":
                try:
                    source_file.unlink(missing_ok=True)
                except Exception:
                    pass

    def ytdlp_progress(self, job_id, data, cancel):
        if cancel.is_set():
            raise yt_dlp.utils.DownloadError("작업이 취소되었습니다.")
        if data.get("status") == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            done = data.get("downloaded_bytes", 0)
            pct = int(done * 100 / total) if total else None
            self.emit(job_id, "다운로드 중", pct, None)
        elif data.get("status") == "finished":
            self.emit(job_id, "다운로드 완료 · 후처리 중", 100, None)

    def encode_mp3(self, job_id, source, target, cancel):
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = target.with_name(target.stem + "_" + datetime.now().strftime("%H%M%S") + target.suffix)
        command = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
                   "-vn", "-af", "loudnorm=I=-14:TP=-1.0:LRA=11", "-codec:a", "libmp3lame",
                   "-b:a", "320k", str(target)]
        self.emit(job_id, "MP3 인코딩 중", None, None)
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        while process.poll() is None:
            if cancel.wait(0.2):
                process.terminate()
                raise RuntimeError("사용자가 작업을 취소했습니다.")
        if process.returncode != 0 or not target.exists() or target.stat().st_size == 0:
            error = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
            raise RuntimeError(error or "MP3 변환에 실패했습니다.")

    def process_local(self, job_id, source, outputs, cancel):
        if cancel.is_set():
            return
        ext = source.suffix.lower()
        if "mp3" in outputs:
            if ext not in VIDEO_EXTENSIONS | AUDIO_EXTENSIONS:
                raise RuntimeError("지원하지 않는 오디오/동영상 파일 형식입니다.")
            target = self.output_folder("mp3") / (safe_name(source.stem) + ".mp3")
            self.encode_mp3(job_id, source, target, cancel)
        if "video" in outputs:
            if ext not in VIDEO_EXTENSIONS:
                raise RuntimeError("동영상 탭에는 지원되는 동영상 파일을 넣어 주세요.")
            folder = self.output_folder("video")
            target = folder / (safe_name(source.stem) + "_copy" + ext)
            shutil.copy2(source, target)
            self.emit(job_id, "동영상 파일 복사 완료", 100, None)

    def poll_events(self):
        try:
            while True:
                job_id, status, progress, detail = self.events.get_nowait()
                if job_id not in self.jobs:
                    continue
                job = self.jobs[job_id]
                if status:
                    job["status"] = status
                if progress is not None:
                    job["progress"] = max(0, min(100, int(progress)))
                if self.tree.exists(job_id):
                    values = list(self.tree.item(job_id, "values"))
                    values[2] = status or job["status"]
                    values[3] = f"{job['progress']}%" if progress is not None else ("…" if status and status.endswith("중") else values[3])
                    self.tree.item(job_id, values=values)
                if detail:
                    self.tree.set(job_id, "status", "오류")
                    messagebox.showerror("작업 실패", f"{values[0]}\n\n{detail}", parent=self.root)
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(100, self.poll_events)

    def cancel_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        job = self.jobs.get(selected[0])
        if job and job["status"] not in ("완료", "오류", "취소"):
            job["cancel"].set()
            self.emit(selected[0], "취소 요청", None, None)

    def clear_completed(self):
        for job_id, job in list(self.jobs.items()):
            if job["status"] in ("완료", "오류", "취소"):
                if self.tree.exists(job_id):
                    self.tree.delete(job_id)
                del self.jobs[job_id]

    def record_history(self, source, result, detail):
        history = self.settings.get("history", [])
        history.insert(0, {"time": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                           "source": str(source), "result": result, "detail": detail})
        self.settings["history"] = history[:MAX_HISTORY]
        save_settings(self.settings)

    def show_history(self):
        win = tk.Toplevel(self.root)
        win.title("작업 기록")
        win.geometry("850x420")
        cols = ("time", "source", "result", "detail")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for col, title, width in [("time", "작업 시각", 150), ("source", "파일 / URL", 360),
                                  ("result", "결과", 80), ("detail", "내용", 220)]:
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor="w")
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        for row in self.settings.get("history", []):
            tree.insert("", "end", values=(row.get("time", ""), row.get("source", ""),
                                           row.get("result", ""), row.get("detail", "")))

    def show_about(self):
        messagebox.showinfo("앱 정보", f"{APP_NAME}\n버전 {APP_VERSION}\nWindows 64비트\n\nRyoo jaesang & 최피디", parent=self.root)

    def on_close(self):
        self.closing = True
        for job in self.jobs.values():
            if job["status"] not in ("완료", "오류", "취소"):
                job["cancel"].set()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

if __name__ == "__main__":
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    app = EasySaveApp(root)
    root.mainloop()
