import json
import logging
import html
import http.server
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tempfile
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
APP_VERSION = "2.2.9"
APPDATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "EasySaveAudio"
APPDATA.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = APPDATA / "settings.json"
DIAGNOSTIC_LOG = APPDATA / "diagnostic.log"
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


def ffprobe_path(ffmpeg=None):
    candidates = []
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates.extend(base.glob("ffprobe*.exe"))
    if ffmpeg:
        candidates.append(Path(ffmpeg).with_name("ffprobe.exe"))
    from shutil import which
    found = which("ffprobe")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None

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
        self.logger = logging.getLogger("EasySaveAudio")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        # Start each application session with a clean log; records append for the lifetime of this run.
        handler = logging.FileHandler(DIAGNOSTIC_LOG, mode="w", encoding="utf-8", delay=False)
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        self.logger.addHandler(handler)
        self.logger.propagate = False
        self.logger.info("app_started version=%s platform=windows", APP_VERSION)
        try:
            existing_log_size = DIAGNOSTIC_LOG.stat().st_size if DIAGNOSTIC_LOG.exists() else 0
            self.logger.info("diagnostic_log_storage %s", json.dumps({
                "startup_reset": True, "append_mode_within_session": True,
                "rotation_enabled": False, "size_limit_bytes": None,
                "existing_size_bytes_after_startup": existing_log_size
            }))
            for active_handler in self.logger.handlers:
                active_handler.flush()
        except OSError:
            # Keep the application available if the disk is full or the log location is unavailable.
            pass
        self.events = queue.Queue()
        self.jobs = {}
        self.job_counter = 0
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="media-job")
        self.ffmpeg = ffmpeg_path()
        self.ffprobe = ffprobe_path(self.ffmpeg)
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
        style.configure("Icon.TButton", padding=(7, 5), font=("Segoe UI Symbol", 14), width=4)
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

        # 하단 조작 버튼을 먼저 bottom에 고정해 작업 목록이 버튼을 밀어내지 않도록 합니다.
        controls = ttk.Frame(outer)
        controls.pack(side="bottom", fill="x", pady=(5, 0))
        # 하단 기능 버튼은 요청에 따라 한글 없이 아이콘만 표시합니다.
        ttk.Button(controls, text="✕", command=self.cancel_selected, style="Icon.TButton").pack(side="left", padx=(0, 5))
        ttk.Button(controls, text="▤", command=self.show_history, style="Icon.TButton").pack(side="left", padx=5)
        ttk.Button(controls, text="⌕", command=self.run_file_diagnostic, style="Icon.TButton").pack(side="left", padx=5)
        ttk.Button(controls, text="☷", command=self.show_diagnostic_log, style="Icon.TButton").pack(side="left", padx=5)
        ttk.Label(controls, text="다운로드 및 변환 작업은 각각 독립적으로 처리됩니다.", foreground="#666").pack(side="right")

        queue_header = ttk.Frame(outer)
        # 오른쪽 여백을 탭 안쪽 버튼 영역과 맞춰 버튼 끝선을 통일합니다.
        queue_header.pack(side="top", fill="x", pady=(2, 3))
        ttk.Label(queue_header, text="작업 목록").pack(side="left")
        ttk.Button(queue_header, text="완료 작업 지우기", command=self.clear_completed, style="Action.TButton", width=16).pack(side="right", padx=(0, 10))
        self.concurrent_label = ttk.Label(queue_header, text="동시 실행 0개", foreground="#666")
        self.concurrent_label.pack(side="right", padx=(12, 12))

        columns = ("source", "kind", "status", "progress")
        queue_area = ttk.Frame(outer)
        queue_area.pack(side="top", fill="both", expand=True, padx=0)
        self.tree = ttk.Treeview(queue_area, columns=columns, show="headings", height=6, selectmode="browse")
        self.tree.heading("source", text="콘텐츠 제목 / 파일명")
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

    def log_event(self, event, **fields):
        # URL query strings and credentials are deliberately excluded from diagnostics.
        safe_fields = {}
        for key, value in fields.items():
            if key in ("url", "source") and isinstance(value, str):
                parsed = urllib.parse.urlsplit(value)
                value = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            safe_fields[key] = value
        try:
            self.logger.info("%s %s", event, json.dumps(safe_fields, ensure_ascii=False, default=str))
            for handler in self.logger.handlers:
                handler.flush()
        except Exception:
            pass


    def run_file_diagnostic(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="검사할 MP3 파일 선택",
            filetypes=[("MP3 오디오", "*.mp3"), ("모든 파일", "*.*")]
        )
        if not path:
            return
        self.log_event("manual_mp3_diagnostic_started", source=path)
        self.executor.submit(self._diagnose_mp3_file, Path(path))

    def _probe_mp3_file(self, path):
        if not self.ffprobe:
            raise RuntimeError("ffprobe.exe를 찾을 수 없습니다. 앱 패키지에 진단 도구가 포함되어 있는지 확인해 주세요.")
        command = [
            self.ffprobe, "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,profile,sample_rate,channels,channel_layout,bit_rate,start_time:format=format_name,duration,bit_rate",
            "-of", "json", str(path)
        ]
        probe = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        if probe.returncode != 0:
            raise RuntimeError(probe.stderr[-2000:] or f"ffprobe 종료 코드: {probe.returncode}")
        data = json.loads(probe.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            raise RuntimeError("오디오 스트림을 찾을 수 없습니다.")
        stream = streams[0]
        fmt = data.get("format") or {}
        return {
            "codec": str(stream.get("codec_name") or "unknown").lower(),
            "sample_rate": int(stream.get("sample_rate") or 0),
            "channels": int(stream.get("channels") or 0),
            "channel_layout": str(stream.get("channel_layout") or "unknown").lower(),
            "profile": str(stream.get("profile") or "unknown"),
            "stream_bit_rate": int(stream.get("bit_rate") or 0),
            "start_time": str(stream.get("start_time") or "unknown"),
            "format_name": str(fmt.get("format_name") or "unknown"),
            "format_bit_rate": int(fmt.get("bit_rate") or 0),
            "duration": str(fmt.get("duration") or "unknown")
        }

    def _inspect_mp3_frame_header(self, path):
        """Inspect opening MP3 bytes for MPEG frame and Xing/Info header details."""
        result = {
            "file_size": 0, "id3_present": False, "id3_version": "none",
            "id3_tag_size": 0, "audio_start_offset": 0, "mpeg_sync_offset": -1,
            "mpeg_version": "unknown", "mpeg_layer": "unknown",
            "bitrate_kbps": 0, "sample_rate": 0, "channel_mode": "unknown",
            "crc_protected": False, "xing_info_offset": -1,
            "xing_info_marker": "not_checked", "xing_flags": None,
            "xing_frame_count": None, "xing_byte_count": None,
            "vbri_marker": "not_checked", "opening_bytes_hex": ""
        }
        try:
            result["file_size"] = path.stat().st_size
            with path.open("rb") as handle:
                data = handle.read(65536)
            result["opening_bytes_hex"] = data[:32].hex()
            offset = 0
            if data[:3] == b"ID3" and len(data) >= 10:
                result["id3_present"] = True
                result["id3_version"] = f"2.{data[3]}.{data[4]}"
                size_bytes = data[6:10]
                if all((byte & 0x80) == 0 for byte in size_bytes):
                    tag_size = ((size_bytes[0] & 0x7f) << 21) | ((size_bytes[1] & 0x7f) << 14) | ((size_bytes[2] & 0x7f) << 7) | (size_bytes[3] & 0x7f)
                    result["id3_tag_size"] = tag_size
                    offset = 10 + tag_size + (10 if data[5] & 0x10 else 0)
                else:
                    result["id3_tag_size"] = -1
                    result["id3_size_error"] = "invalid_synchsafe_size"
            result["audio_start_offset"] = offset
            sync_offset, header = -1, None
            for pos in range(max(0, offset), max(0, len(data) - 3)):
                candidate = int.from_bytes(data[pos:pos + 4], "big")
                if (candidate & 0xffe00000) == 0xffe00000:
                    version_bits = (candidate >> 19) & 3
                    layer_bits = (candidate >> 17) & 3
                    bitrate_index = (candidate >> 12) & 15
                    sample_index = (candidate >> 10) & 3
                    if version_bits != 1 and layer_bits == 1 and bitrate_index not in (0, 15) and sample_index != 3:
                        sync_offset, header = pos, candidate
                        break
            if header is None:
                result["xing_info_marker"] = "mpeg_frame_not_found_in_first_64kb"
                return result
            result["mpeg_sync_offset"] = sync_offset
            version_bits = (header >> 19) & 3
            bitrate_index = (header >> 12) & 15
            sample_index = (header >> 10) & 3
            protection_bit = (header >> 16) & 1
            channel_mode_bits = (header >> 6) & 3
            result["mpeg_version"] = {3: "MPEG1", 2: "MPEG2", 0: "MPEG2.5"}.get(version_bits, "reserved")
            result["mpeg_layer"] = "Layer III"
            bitrate_tables = {
                3: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
                2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
                0: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
            }
            sample_rates = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}
            result["bitrate_kbps"] = bitrate_tables.get(version_bits, [0] * 16)[bitrate_index]
            result["sample_rate"] = sample_rates.get(version_bits, [0, 0, 0])[sample_index]
            result["channel_mode"] = {0: "stereo", 1: "joint_stereo", 2: "dual_channel", 3: "mono"}.get(channel_mode_bits, "unknown")
            result["crc_protected"] = protection_bit == 0
            side_info = (17 if channel_mode_bits == 3 else 32) if version_bits == 3 else (9 if channel_mode_bits == 3 else 17)
            xing_offset = sync_offset + 4 + (2 if result["crc_protected"] else 0) + side_info
            result["xing_info_offset"] = xing_offset
            marker = data[xing_offset:xing_offset + 4]
            if marker in (b"Xing", b"Info"):
                result["xing_info_marker"] = marker.decode("ascii")
                if len(data) >= xing_offset + 8:
                    flags = int.from_bytes(data[xing_offset + 4:xing_offset + 8], "big")
                    result["xing_flags"] = flags
                    cursor = xing_offset + 8
                    if flags & 1 and len(data) >= cursor + 4:
                        result["xing_frame_count"] = int.from_bytes(data[cursor:cursor + 4], "big")
                        cursor += 4
                    if flags & 2 and len(data) >= cursor + 4:
                        result["xing_byte_count"] = int.from_bytes(data[cursor:cursor + 4], "big")
            else:
                result["xing_info_marker"] = marker.decode("ascii", errors="replace") or "absent"
            vbri_offset = sync_offset + 4 + 32
            result["vbri_marker"] = "VBRI" if data[vbri_offset:vbri_offset + 4] == b"VBRI" else "absent"
        except Exception as exc:
            result["inspection_error"] = str(exc)
        return result

    def _decode_mp3_file(self, path):
        command = [
            self.ffmpeg, "-hide_banner", "-v", "error", "-xerror", "-err_detect", "explode",
            "-i", str(path), "-map", "0:a:0", "-f", "null", os.devnull
        ]
        decoded = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=900,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        return decoded.returncode, (decoded.stderr or "")[-2500:]

    def _measure_mp3_volume(self, path):
        command = [
            self.ffmpeg, "-hide_banner", "-i", str(path), "-map", "0:a:0",
            "-af", "volumedetect", "-f", "null", os.devnull
        ]
        measured = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=900,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        match = re.search(r"mean_volume:\s*(-?inf|[-+]?\d+(?:\.\d+)?)\s*dB", measured.stderr or "", re.I)
        return match.group(1) if match else "unknown"

    def _analyze_mp3_channels(self, path):
        # Winamp 무음 사례 비교를 위해 좌우 채널별 통계와 전체 분석 결과를 기록합니다.
        command = [
            self.ffmpeg, "-hide_banner", "-i", str(path), "-map", "0:a:0",
            "-af", "astats=metadata=0:reset=0", "-f", "null", os.devnull
        ]
        analyzed = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=900,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        output = analyzed.stderr or ""
        if analyzed.returncode != 0:
            return f"astats_returncode={analyzed.returncode}; {output[-2000:]}"
        return output[-4000:] or "astats_output_empty"

    def _inspect_mp3_file(self, path):
        result = {
            "path": str(path), "size": path.stat().st_size if path.exists() else 0,
            "codec": "unknown", "sample_rate": 0, "channels": 0,
            "channel_layout": "unknown", "profile": "unknown",
            "stream_bit_rate": 0, "start_time": "unknown",
            "format_name": "unknown", "format_bit_rate": 0,
            "duration": "unknown", "mean_volume": "unknown",
            "channel_analysis": "not_run", "decode_returncode": -1,
            "frame_header_analysis": {},
            "probe_error": "", "decode_error": ""
        }
        try:
            result["frame_header_analysis"] = self._inspect_mp3_frame_header(path)
            self.log_event("mp3_frame_header_analysis", path=path.name, **result["frame_header_analysis"])
        except Exception as exc:
            result["frame_header_analysis"] = {"inspection_error": str(exc)}
            self.log_event("mp3_frame_header_analysis_failed", path=path.name, error=str(exc))
        try:
            result.update(self._probe_mp3_file(path))
        except Exception as exc:
            result["probe_error"] = str(exc)
        try:
            result["decode_returncode"], result["decode_error"] = self._decode_mp3_file(path)
        except Exception as exc:
            result["decode_error"] = str(exc)
        try:
            result["mean_volume"] = self._measure_mp3_volume(path)
        except Exception as exc:
            self.log_event("mp3_volume_measurement_warning", path=path.name, error=str(exc))
        try:
            result["channel_analysis"] = self._analyze_mp3_channels(path)
        except Exception as exc:
            result["channel_analysis"] = f"analysis_failed: {exc}"
        result["passed"] = (
            not result["probe_error"] and result["codec"] == "mp3"
            and result["sample_rate"] == 44100 and result["channels"] == 2
            and result["decode_returncode"] == 0
        )
        result["error"] = "\n".join(
            part for part in (result["probe_error"], result["decode_error"]) if part
        )
        return result

    def _diagnose_mp3_file(self, path):
        result = self._inspect_mp3_file(path)
        self.log_event("manual_mp3_diagnostic_completed", **result)
        self.root.after(0, lambda data=result: self._show_mp3_diagnostic_result(data))

    def _show_mp3_diagnostic_result(self, result):
        status = "검사 통과" if result.get("passed") else "검사에서 문제 발견"
        message = (
            f"{status}\n\n파일: {Path(result['path']).name}\n"
            f"크기: {result['size']:,} bytes\n"
            f"코덱: {result['codec']}\n"
            f"샘플레이트: {result['sample_rate']} Hz\n"
            f"채널: {result['channels']}\n"
            f"평균 음량: {result['mean_volume']} dB\n"
            f"전체 디코딩 종료 코드: {result['decode_returncode']}\n\n"
            "상세 내용은 [진단 로그]에서 확인할 수 있습니다."
        )
        if result.get("passed"):
            messagebox.showinfo("MP3 파일 진단", message, parent=self.root)
        else:
            detail = result.get("error", "")
            if detail:
                message += "\n\n오류 내용 일부:\n" + detail[-1200:]
            messagebox.showwarning("MP3 파일 진단", message, parent=self.root)

    def show_diagnostic_log(self):
        for handler in self.logger.handlers:
            handler.flush()
        win = tk.Toplevel(self.root)
        win.title("진단 로그")
        win.geometry("780x480")
        win.minsize(600, 360)
        win.transient(self.root)

        outer = ttk.Frame(win, padding=10)
        outer.pack(fill="both", expand=True)
        log_view = tk.Text(outer, wrap="word", font=("Consolas", 9), state="normal")
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=log_view.yview)
        log_view.configure(yscrollcommand=scrollbar.set)
        log_view.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        try:
            content = DIAGNOSTIC_LOG.read_text(encoding="utf-8") if DIAGNOSTIC_LOG.exists() else ""
        except Exception as exc:
            content = f"로그 파일을 읽지 못했습니다: {exc}"
        log_view.insert("1.0", content or "기록된 진단 로그가 없습니다.")
        log_view.configure(state="disabled")

        buttons = ttk.Frame(win, padding=(10, 0, 10, 10))
        buttons.pack(fill="x")

        def copy_log():
            try:
                win.clipboard_clear()
                win.clipboard_append(content)
                win.update()
                messagebox.showinfo("진단 로그", "로그 내용을 클립보드에 복사했습니다.", parent=win)
                self.log_event("diagnostic_log_copied")
            except Exception as exc:
                messagebox.showerror("로그 복사 실패", str(exc), parent=win)

        def save_log():
            try:
                destination = filedialog.asksaveasfilename(
                    parent=win, title="진단 로그 저장",
                    initialfile="Easy_Save_Audio_Video_Diagnostic_Log.txt",
                    defaultextension=".txt", filetypes=[("텍스트 파일", "*.txt")]
                )
                if not destination:
                    return
                for handler in self.logger.handlers:
                    handler.flush()
                shutil.copy2(DIAGNOSTIC_LOG, destination)
                messagebox.showinfo("진단 로그", f"로그를 저장했습니다.\n{destination}", parent=win)
                self.log_event("diagnostic_log_saved", destination=destination)
            except Exception as exc:
                messagebox.showerror("로그 저장 실패", str(exc), parent=win)

        ttk.Button(buttons, text="복사", command=copy_log, style="Action.TButton").pack(side="left")
        ttk.Button(buttons, text="저장", command=save_log, style="Action.TButton").pack(side="left", padx=8)
        ttk.Button(buttons, text="취소", command=win.destroy, style="Action.TButton").pack(side="right")
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.grab_set()
        win.focus_set()


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
            action_row, text="추출 시작",
            command=self.start_current, style="Utility.TButton", width=10
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
        if value and is_url(value):
            if not self.selected_outputs():
                messagebox.showwarning("다운로드 형식 선택", "MP3 또는 동영상 중 하나 이상 선택해 주세요.", parent=self.root)
                return
            self.stage_url(self.url_var)
            self.url_var.set("")
        elif value:
            # A dropped local file is already queued by handle_drop/add_files.
            # The entry displays either its path or a multi-file count label.
            pending_local = any(
                not job.get("submitted")
                and job.get("status") == "대기 중"
                and job.get("source_type") == "local"
                for job in self.jobs.values()
            )
            local_path = Path(value.strip('"'))
            if local_path.is_file():
                already_queued = any(
                    job.get("source_type") == "local"
                    and Path(job.get("source", "")).resolve() == local_path.resolve()
                    and not job.get("submitted")
                    and job.get("status") == "대기 중"
                    for job in self.jobs.values()
                )
                if not already_queued:
                    self.enqueue(str(local_path), "local", ["mp3"])
                    pending_local = True
            elif not pending_local:
                messagebox.showwarning(
                    "파일 또는 주소 확인",
                    "웹 주소를 입력하거나 MP4 등의 미디어 파일을 드래그해 주세요.",
                    parent=self.root
                )
                return
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
        name = Path(source).name if source_type == "local" else "제목 확인 중…"
        kind = "+".join("MP3" if x == "mp3" else "동영상" for x in outputs)
        job = {"id": job_id, "source": source, "source_type": source_type, "outputs": outputs,
               "display_name": name, "cancel": threading.Event(), "status": "대기 중", "progress": 0,
               "started": time.time(), "submitted": False}
        self.jobs[job_id] = job
        # 최신 등록 작업을 항상 목록 맨 위에 표시합니다.
        self.tree.insert("", 0, iid=job_id, values=(name, kind, "대기 중", "0%"))
        self.tree.yview_moveto(0)
        # Queue only; execution starts after the user presses [변환 시작].

    def emit(self, job_id, status=None, progress=None, detail=None, title=None):
        self.events.put((job_id, status, progress, detail, title))

    def run_job(self, job_id):
        job = self.jobs[job_id]
        try:
            self.log_event("job_started", job_id=job_id, source=job["source"], source_type=job["source_type"], outputs=job["outputs"])
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
                self.log_event("job_completed", job_id=job_id, outputs=job["outputs"])
                self.record_history(source, "완료", ", ".join(job["outputs"]))
        except Exception as exc:
            if job["cancel"].is_set():
                self.emit(job_id, "취소", None, None)
                self.record_history(job["source"], "취소", "사용자가 작업을 취소했습니다.")
            else:
                self.log_event("job_failed", job_id=job_id, error=str(exc))
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
        self.log_event("media_info_fetch_started", job_id=job_id, source=url, youtube=is_youtube)
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        self.log_event("media_info_fetch_completed", job_id=job_id, title=info.get("title"), duration=info.get("duration"))
        raw_title = str(info.get("title") or "").strip()
        title = safe_name(raw_title or "media")
        display_title = safe_name(raw_title) if raw_title else url
        self.emit(job_id, title=display_title)
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
                self.log_event("audio_download_started", job_id=job_id, source=url, format="bestaudio/best")
                with yt_dlp.YoutubeDL(opts) as ydl:
                    result = ydl.extract_info(url, download=True)
                    source_file = Path(ydl.prepare_filename(result))
                self.log_event("audio_download_completed", job_id=job_id, source_file=source_file, filesize=source_file.stat().st_size if source_file.exists() else 0)
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

        # Inspect the original audio stream, then normalize every source codec through PCM WAV.
        try:
            source_audio = self._probe_mp3_file(source)
        except Exception as exc:
            source_audio = {
                "codec": "unknown", "sample_rate": 0, "channels": 0,
                "channel_layout": "unknown", "profile": "unknown",
                "stream_bit_rate": 0, "start_time": "unknown",
                "format_name": "unknown", "format_bit_rate": 0,
                "duration": "unknown", "probe_error": str(exc)
            }
        self.log_event(
            "source_audio_stream_inspected", job_id=job_id, input_file=source,
            source_audio_codec=source_audio.get("codec", "unknown"),
            source_sample_rate=source_audio.get("sample_rate", 0),
            source_channels=source_audio.get("channels", 0),
            source_channel_layout=source_audio.get("channel_layout", "unknown"),
            source_profile=source_audio.get("profile", "unknown"),
            source_bit_rate=source_audio.get("stream_bit_rate", 0),
            source_format_name=source_audio.get("format_name", "unknown"),
            source_duration=source_audio.get("duration", "unknown"),
            source_probe_error=source_audio.get("probe_error", "")
        )

        temp_dir = APPDATA / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            prefix="easysave_pcm_", suffix=".wav", dir=str(temp_dir), delete=False
        )
        pcm_path = Path(handle.name)
        handle.close()
        try:
            if cancel.is_set():
                raise RuntimeError("사용자가 작업을 취소했습니다.")

            decode_command = [
                self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(source), "-map", "0:a:0", "-vn",
                "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
                "-f", "wav", str(pcm_path)
            ]
            self.log_event(
                "source_audio_pcm_decode_started", job_id=job_id,
                source_file=source, source_audio_codec=source_audio.get("codec", "unknown"),
                intermediate_format="pcm_s16le_wav", sample_rate=44100, channels=2
            )
            self.emit(job_id, "원본 오디오 디코딩 중", None, None)
            process = subprocess.Popen(
                decode_command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            while process.poll() is None:
                if cancel.wait(0.2):
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise RuntimeError("사용자가 작업을 취소했습니다.")
            decode_error = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
            if process.returncode != 0 or not pcm_path.exists() or pcm_path.stat().st_size < 1024:
                self.log_event(
                    "source_audio_pcm_decode_failed", job_id=job_id,
                    returncode=process.returncode, ffmpeg_error=decode_error[-3000:]
                )
                raise RuntimeError(decode_error or "원본 오디오를 PCM으로 디코딩하지 못했습니다.")
            self.log_event(
                "source_audio_pcm_decode_completed", job_id=job_id,
                intermediate_file_size=pcm_path.stat().st_size
            )

            if cancel.is_set():
                raise RuntimeError("사용자가 작업을 취소했습니다.")
            encode_command = [
                self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(pcm_path), "-map", "0:a:0", "-vn", "-map_metadata", "-1",
                "-af", "loudnorm=I=-14:TP=-1.0:LRA=11", "-codec:a", "libmp3lame",
                # Use libmp3lame's standard stereo-mode selection and emit the
                # standard Xing/Info frame for duration and seeking compatibility.
                "-b:a", "320k", "-ar", "44100", "-ac", "2",
                "-write_xing", "1", "-id3v2_version", "3", "-f", "mp3", str(target)
            ]
            self.log_event(
                "ffmpeg_encode_started", job_id=job_id, input_file=source,
                intermediate_file=pcm_path, output_file=target, bitrate="320k",
                compatibility_profile="pcm_s16le_wav_to_cbr_xing_id3v2_3_lame_default_stereo_mode",
                joint_stereo="libmp3lame_default", xing_header="enabled",
                source_audio_codec=source_audio.get("codec", "unknown")
            )
            self.emit(job_id, "MP3 인코딩 중", None, None)
            process = subprocess.Popen(
                encode_command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            while process.poll() is None:
                if cancel.wait(0.2):
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise RuntimeError("사용자가 작업을 취소했습니다.")
            error = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
            if process.returncode != 0 or not target.exists() or target.stat().st_size < 1024:
                self.log_event(
                    "mp3_encode_failed", job_id=job_id, returncode=process.returncode,
                    exists=target.exists(), size=target.stat().st_size if target.exists() else 0,
                    ffmpeg_error=error[-3000:]
                )
                raise RuntimeError(error or "MP3 변환 결과 파일을 만들지 못했습니다.")

            # Preserve the successfully encoded output even if post-encode diagnostics fail.
            inspection = self._inspect_mp3_file(target)
            validation_reasons = []
            if inspection["probe_error"]:
                validation_reasons.append("ffprobe_unavailable_or_failed")
            if inspection["codec"] != "mp3":
                validation_reasons.append("input_codec_not_mp3")
            if inspection["sample_rate"] != 44100:
                validation_reasons.append("sample_rate_not_44100")
            if inspection["channels"] != 2:
                validation_reasons.append("channel_count_not_stereo")
            if inspection["decode_returncode"] != 0:
                validation_reasons.append("full_decode_failed")
            fields = {
                "job_id": job_id, "size": inspection["size"],
                "duration": inspection["duration"], "codec": inspection["codec"],
                "sample_rate": inspection["sample_rate"], "channels": inspection["channels"],
                "channel_layout": inspection["channel_layout"], "profile": inspection["profile"],
                "stream_bit_rate": inspection["stream_bit_rate"],
                "start_time": inspection["start_time"], "format_name": inspection["format_name"],
                "format_bit_rate": inspection["format_bit_rate"], "mean_volume": inspection["mean_volume"],
                "channel_analysis": inspection["channel_analysis"],
                "decode_returncode": inspection["decode_returncode"],
                "validation_reasons": validation_reasons,
                "probe_error": inspection["probe_error"], "decode_error": inspection["decode_error"]
            }
            self.log_event("mp3_validation", **fields)
            if validation_reasons:
                self.log_event("mp3_diagnostic_warning_output_preserved", **fields)
            self.log_event(
                "ffmpeg_encode_completed", job_id=job_id, output_file=target,
                size=inspection["size"], duration=inspection["duration"],
                codec=inspection["codec"], sample_rate=inspection["sample_rate"],
                channels=inspection["channels"], mean_volume=inspection["mean_volume"],
                source_audio_codec=source_audio.get("codec", "unknown"),
                intermediate_format="pcm_s16le_wav"
            )
        finally:
            try:
                pcm_path.unlink(missing_ok=True)
                self.log_event("temporary_pcm_file_removed", job_id=job_id, path=pcm_path)
            except OSError as exc:
                self.log_event("temporary_pcm_file_cleanup_failed", job_id=job_id, path=pcm_path, error=str(exc))

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
                job_id, status, progress, detail, title = self.events.get_nowait()
                if job_id not in self.jobs:
                    continue
                job = self.jobs[job_id]
                if title is not None:
                    job["display_name"] = title
                    if self.tree.exists(job_id):
                        row_values = list(self.tree.item(job_id, "values"))
                        row_values[0] = title
                        self.tree.item(job_id, values=row_values)
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
