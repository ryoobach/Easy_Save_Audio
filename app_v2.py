import json
import html
import http.server
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

import yt_dlp
try:
    from tkinterdnd2 import TkinterDnD
except ImportError:
    TkinterDnD = None

APP_NAME = "Easy Save Audio & Video"
APP_VERSION = "2.1.3"
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
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

def is_url(value):
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)

class EasySaveApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME}  {APP_VERSION}")
        self.root.geometry("800x520")
        self.root.minsize(680, 460)
        self.settings = load_settings()
        self.events = queue.Queue()
        self.jobs = {}
        self.job_counter = 0
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="media-job")
        self.ffmpeg = ffmpeg_path()
        self.closing = False
        self.dnd_error = None
        self.build_ui()
        # The root window is also a drop target, so files/links can be dropped
        # anywhere in the application, not only on the URL entry or tab frame.
        self.register_drop_target(self.root, self.handle_window_drop)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll_events)

    def build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Utility.TButton", padding=(10, 6))
        style.configure("Action.TButton", padding=(10, 6), font=("Malgun Gothic", 9))
        style.configure("About.TButton", padding=(4, 0), font=("Segoe UI", 18, "bold"))
        outer = ttk.Frame(self.root, padding=(16, 10))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 6))
        icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "easy_save_audio.png"
        brand = ttk.Frame(header)
        brand.pack(side="left", fill="x", expand=True)
        try:
            self.header_image = tk.PhotoImage(file=str(icon_path))
            self.header_image = self.header_image.subsample(3, 3)
            self.root.iconphoto(True, self.header_image)
        except Exception:
            pass
        title_area = ttk.Frame(brand)
        title_area.pack(side="left", fill="x", expand=True)
        title_row = ttk.Frame(title_area)
        title_row.pack(anchor="w", fill="x")
        if hasattr(self, "header_image"):
            ttk.Label(title_row, image=self.header_image).pack(side="left", padx=(0, 10), pady=(1, 0))
        ttk.Label(title_row, text=APP_NAME, font=("Malgun Gothic", 18, "bold")).pack(side="left")
        ttk.Label(title_row, text=APP_VERSION, font=("Segoe UI", 11, "bold"), foreground="#b51f32").pack(side="left", padx=(10, 0))
        # 앱 정보 버튼은 기준 이미지처럼 창 상단 오른쪽에 배치합니다.
        ttk.Button(header, text="?", command=self.show_about, style="About.TButton", width=3).pack(
            side="right", anchor="center", padx=(10, 14), pady=0
        )

        self.build_main_panel(outer)

        queue_header = ttk.Frame(outer)
        # 오른쪽 여백을 탭 안쪽 버튼 영역과 맞춰 버튼 끝선을 통일합니다.
        queue_header.pack(fill="x", pady=(2, 3))
        ttk.Label(queue_header, text="작업 목록").pack(side="left")
        ttk.Button(queue_header, text="완료 작업 지우기", command=self.clear_completed, style="Action.TButton", width=16).pack(side="right", padx=(0, 10))
        self.concurrent_label = ttk.Label(queue_header, text="동시 실행 0개", foreground="#666")
        self.concurrent_label.pack(side="right", padx=(12, 12))

        columns = ("source", "kind", "status", "progress")
        queue_area = ttk.Frame(outer)
        queue_area.pack(fill="both", expand=True, padx=0)
        self.tree = ttk.Treeview(queue_area, columns=columns, show="headings", height=6, selectmode="browse")
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
        controls.pack(fill="x", pady=(5, 0))
        ttk.Button(controls, text="선택 작업 취소", command=self.cancel_selected).pack(side="left")
        ttk.Button(controls, text="작업 기록", command=self.show_history).pack(side="left", padx=8)
        ttk.Label(controls, text="다운로드 및 변환 작업은 각각 독립적으로 처리됩니다.", foreground="#666").pack(side="right")

    def register_drop_target(self, widget, callback):
        try:
            # 다양한 브라우저 링크 드래그 형식을 받습니다.
            from tkinterdnd2 import DND_ALL
            widget.drop_target_register(DND_ALL)
            widget.dnd_bind("<<Drop>>", callback)
            return True
        except Exception as exc:
            # 일부 환경에서는 파일/텍스트 형식으로 대체합니다.
            try:
                from tkinterdnd2 import DND_FILES, DND_TEXT
                widget.drop_target_register(DND_FILES, DND_TEXT)
                widget.dnd_bind("<<Drop>>", callback)
                return True
            except Exception as fallback_exc:
                self.dnd_error = f"{exc}; 대체 등록 실패: {fallback_exc}"
                return False

    def build_main_panel(self, outer):
        panel = ttk.Frame(outer, padding=10)
        panel.pack(fill="x", pady=(2, 0))

        options = ttk.Frame(panel)
        options.pack(fill="x", pady=(0, 8))
        self.mp3_var = tk.BooleanVar(value=True)
        self.video_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="MP3", variable=self.mp3_var).pack(side="left", padx=(0, 22))
        ttk.Checkbutton(options, text="동영상", variable=self.video_var).pack(side="left")

        input_row = ttk.Frame(panel)
        input_row.pack(fill="x", pady=(0, 8))
        ttk.Label(input_row, text="주소", font=("Malgun Gothic", 11)).pack(side="left", padx=(0, 32))
        self.url_var = tk.StringVar()
        entry = ttk.Entry(input_row, textvariable=self.url_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self.stage_url(self.url_var))
        ttk.Button(
            input_row, text="주소 붙여넣기",
            command=lambda: self.paste_url(self.url_var, entry),
            style="Action.TButton", width=16
        ).pack(side="left", padx=(8, 0))
        self.bind_entry_menu(entry, self.url_var)

        self.mp3_folder = tk.StringVar(value=self.settings.get("last_mp3_dir", str(Path.home() / "Music")))
        self.video_folder = tk.StringVar(value=self.settings.get("last_video_dir", str(Path.home() / "Videos")))

        mp3_row = ttk.Frame(panel)
        mp3_row.pack(fill="x", pady=(2, 2))
        ttk.Label(mp3_row, text="MP3 저장 위치:").pack(side="left")
        ttk.Label(mp3_row, textvariable=self.mp3_folder, foreground="#555").pack(side="left", padx=6)
        ttk.Button(
            mp3_row, text="변경",
            command=lambda: self.choose_folder("mp3", self.mp3_folder),
            style="Utility.TButton", width=10
        ).pack(side="right")

        video_row = ttk.Frame(panel)
        video_row.pack(fill="x", pady=(2, 2))
        ttk.Label(video_row, text="동영상 저장 위치:").pack(side="left")
        ttk.Label(video_row, textvariable=self.video_folder, foreground="#555").pack(side="left", padx=6)
        ttk.Button(
            video_row, text="변경",
            command=lambda: self.choose_folder("video", self.video_folder),
            style="Utility.TButton", width=10
        ).pack(side="right")

        action_row = ttk.Frame(panel)
        action_row.pack(fill="x", pady=(5, 0))
        ttk.Button(
            action_row, text="다운로드 시작",
            command=self.start_current, style="Action.TButton", width=16
        ).pack(side="right")

        for widget in (panel, options, input_row, entry, mp3_row, video_row):
            self.register_drop_target(widget, lambda e, v=self.url_var: self.handle_drop(e, v))

    def handle_window_drop(self, event):
        return self.handle_drop(event, self.url_var)

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
            messagebox.showinfo("주소 붙여넣기", "클립보드에 주소가 없습니다.", parent=self.root)
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

    def selected_outputs(self):
        outputs = []
        if self.mp3_var.get():
            outputs.append("mp3")
        if self.video_var.get():
            outputs.append("video")
        return outputs

    def stage_url(self, url_var):
        url = url_var.get().strip()
        if not is_url(url):
            messagebox.showwarning("주소 확인", "http:// 또는 https://로 시작하는 주소를 입력해 주세요.", parent=self.root)
            return
        outputs = self.selected_outputs()
        if not outputs:
            messagebox.showwarning("다운로드 형식 선택", "MP3 또는 동영상 중 하나 이상 선택해 주세요.", parent=self.root)
            return
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

    def handle_drop(self, event, url_var):
        raw_data = html.unescape(str(event.data or "")).strip()

        # Browser drag formats differ: plain text, URI list, CF_HTML, or URL + title.
        # Accept title-link drags unconditionally; no browser extension is required.
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
            outputs = self.selected_outputs() or ["mp3"]
            for filename in media_files:
                self.enqueue(filename, "local", outputs)
            return "break"

        messagebox.showinfo(
            "주소 자동 입력",
            "드롭한 항목에서 웹 주소를 찾지 못했습니다.\n\n"
            "유튜브 동영상 화면이 아니라 동영상 제목을 드래그해 놓아 주세요.",
            parent=self.root
        )
        return "break"

    def start_current(self):
        value = self.url_var.get().strip()
        if value:
            if not is_url(value):
                messagebox.showwarning("주소 확인", "올바른 http:// 또는 https:// 주소를 입력해 주세요.", parent=self.root)
                return
            if not self.selected_outputs():
                messagebox.showwarning("다운로드 형식 선택", "MP3 또는 동영상 중 하나 이상 선택해 주세요.", parent=self.root)
                return
            self.stage_url(self.url_var)
            self.url_var.set("")
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
        # 최신 등록 작업을 항상 목록 맨 위에 표시합니다.
        self.tree.insert("", 0, iid=job_id, values=(name, kind, "대기 중", "0%"))
        self.tree.yview_moveto(0)
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

    def update_concurrency_label(self):
        terminal = {"완료", "오류", "취소"}
        running = sum(
            1 for job in self.jobs.values()
            if job.get("submitted") and job.get("status") not in terminal
            and job.get("status") not in ("대기 중", "취소 요청")
        )
        self.concurrent_label.configure(text=f"동시 실행 {running}개")

    def poll_events(self):
        try:
            while True:
                job_id, status, progress, detail = self.events.get_nowait()
                if job_id not in self.jobs:
                    continue
                job = self.jobs[job_id]
                if status:
                    job["status"] = status
                self.update_concurrency_label()
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
        win = tk.Toplevel(self.root)
        win.title("앱 정보")
        win.geometry("500x225")
        win.minsize(460, 210)
        win.transient(self.root)
        win.resizable(False, False)

        outer = ttk.Frame(win, padding=(20, 14))
        outer.pack(fill="both", expand=True)

        title_row = ttk.Frame(outer)
        title_row.pack(anchor="w", fill="x", pady=(0, 6))
        if hasattr(self, "header_image"):
            ttk.Label(title_row, image=self.header_image).pack(side="left", padx=(0, 10), pady=(0, 1))
        ttk.Label(
            title_row, text=APP_NAME,
            font=("Malgun Gothic", 15, "bold")
        ).pack(side="left")
        ttk.Label(
            title_row, text=APP_VERSION,
            font=("Segoe UI", 11, "bold"), foreground="#b51f32"
        ).pack(side="left", padx=(9, 0))

        details = ttk.Frame(outer)
        details.pack(fill="x", padx=2)
        ttk.Label(
            details, text="Windows 64비트",
            font=("Malgun Gothic", 10)
        ).pack(anchor="w", pady=(0, 5))
        ttk.Label(
            details, text="2026년 11월 18일",
            font=("Malgun Gothic", 10)
        ).pack(anchor="w", pady=(0, 12))
        ttk.Label(
            outer, text="Ryoo jaesang & 최피디",
            font=("Malgun Gothic", 10)
        ).pack(anchor="w", padx=2)

        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.grab_set()
        win.focus_set()

    def on_close(self):
        self.closing = True
        for job in self.jobs.values():
            if job["status"] not in ("완료", "오류", "취소"):
                job["cancel"].set()
        self.executor.shutdown(wait=False, cancel_futures=True)
        try:
            self.browser_server.shutdown()
            self.browser_server.server_close()
        except Exception:
            pass
        self.root.destroy()

if __name__ == "__main__":
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    app = EasySaveApp(root)
    root.mainloop()
