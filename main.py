import json, os, re, subprocess, threading, queue, urllib.parse, sys, tempfile
import yt_dlp
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import imageio_ffmpeg
import tempfile
import shutil
import yt_dlp

APP="Easy Save Audio"
VERSION="1.0.8"
APPDATA=Path(os.environ.get("APPDATA", str(Path.home()))) / "EasySaveAudio"
APPDATA.mkdir(parents=True, exist_ok=True)
SETTINGS=APPDATA/"settings.json"

def ffmpeg_binary():
    if getattr(sys, "frozen", False):
        base=Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        matches=list(base.glob("ffmpeg*.exe"))
        if matches: return str(matches[0])
    return imageio_ffmpeg.get_ffmpeg_exe()

def load_settings():
    try:
        d=json.loads(SETTINGS.read_text(encoding="utf-8"))
        if isinstance(d,dict): return d
    except Exception: pass
    return {"last_save_dir":str(Path.home()/"Music"),"last_url":"","history":[]}

def save_settings(d):
    tmp=SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(SETTINGS)

def safe_name(s):
    return (re.sub(r'[\\/:*?"<>|\x00-\x1f]',"_",s).strip(" .") or "audio")[:150]

def korean_error(message):
    s=(message or "").lower()
    if "403" in s or "forbidden" in s: return "서버가 다운로드 요청을 거부했습니다. 해당 사이트에서 허용하는 직접 다운로드 주소인지 확인해 주세요."
    if "404" in s or "not found" in s: return "요청한 미디어 파일을 찾을 수 없습니다. 주소가 정확한지 확인해 주세요."
    if "401" in s or "unauthorized" in s: return "접근 권한이 없는 주소입니다. 인증이 필요한 주소는 지원하지 않을 수 있습니다."
    if "timed out" in s or "timeout" in s: return "서버 응답 시간이 초과되었습니다. 인터넷 연결을 확인한 뒤 다시 시도해 주세요."
    if "could not resolve" in s or "no such host" in s or "name or service not known" in s: return "주소의 서버를 찾을 수 없습니다. 인터넷 연결과 주소를 확인해 주세요."
    if "invalid data found" in s or "does not contain any stream" in s or "unknown format" in s: return "지원하는 미디어 파일을 확인하지 못했습니다. 웹페이지 주소가 아닌 직접 미디어 파일 주소를 입력해 주세요."
    if "connection refused" in s or "network is unreachable" in s or "connection reset" in s: return "서버에 연결하지 못했습니다. 네트워크 상태나 서버의 접근 제한을 확인해 주세요."
    if "unsupported url" in s or "no suitable extractor" in s: return "이 사이트의 주소 형식을 지원하지 않거나 동영상 정보를 확인할 수 없습니다."
    if "private video" in s or "sign in" in s or "login required" in s: return "비공개 또는 로그인이 필요한 영상입니다. 공개적으로 접근 가능하고 다운로드가 허용된 주소인지 확인해 주세요."
    if "drm" in s or "protected" in s: return "DRM 등 보호된 콘텐츠는 추출할 수 없습니다."
    if "no space left" in s: return "저장 공간이 부족합니다. 저장 드라이브의 여유 공간을 확보해 주세요."
    return "동영상 정보를 가져오거나 음성을 MP3로 변환하지 못했습니다. 주소와 해당 사이트의 다운로드 권한을 확인해 주세요."

class App:
    def __init__(self,root):
        self.root=root
        self.root.title(f"{APP} {VERSION}")
        self.root.geometry("680x390")
        self.root.minsize(610,360)
        self.settings=load_settings(); self.events=queue.Queue(); self.busy=False; self.ffmpeg=ffmpeg_binary()
        self.url=tk.StringVar(value=self.settings.get("last_url","")); self.status=tk.StringVar(value="대기 중")
        self.build(); self.root.after(100,self.poll)

    def paste_url(self):
        try:
            value=self.root.clipboard_get().strip()
            # 기존 입력 내용을 먼저 완전히 지운 뒤 클립보드 주소로 교체
            self.entry.delete(0, tk.END)
            self.entry.insert(0, value)
            self.entry.focus_set()
            self.entry.icursor(tk.END)
        except tk.TclError:
            messagebox.showinfo("붙여넣기","클립보드에 붙여넣을 주소가 없습니다.")

    def build(self):
        self.root.configure(bg="#f5f5f5")
        f=tk.Frame(self.root,bg="#f5f5f5",padx=24,pady=20); f.pack(fill="both",expand=True)

        # 실행 파일 아이콘과 동일한 원본 PNG를 창 헤더에도 사용
        head=tk.Frame(f,bg="#f5f5f5"); head.pack(fill="x",anchor="w",pady=(0,15))
        icon_path=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))/"easy_save_audio.png"
        self.app_icon=tk.PhotoImage(file=str(icon_path))
        # 타이틀 바와 메인 화면이 같은 PNG 이미지 객체를 공유하도록 적용
        self.root.iconphoto(True,self.app_icon)
        self.header_icon=self.app_icon.subsample(6,6)
        tk.Label(head,image=self.header_icon,bg="#f5f5f5").pack(side="left",padx=(0,12))
        titlebox=tk.Frame(head,bg="#f5f5f5"); titlebox.pack(side="left",fill="y")
        tk.Label(titlebox,text=APP,font=("Segoe UI",19,"bold"),fg="#c91d2e",bg="#f5f5f5").pack(anchor="w")
        tk.Label(titlebox,text="Ryoo jaesang & 최피디",font=("Malgun Gothic",9),fg="#666",bg="#f5f5f5").pack(anchor="w")

        tk.Label(f,text="동영상 주소를 입력하면 재생 없이 음성만 MP3로 추출합니다.",bg="#f5f5f5",font=("Malgun Gothic",10)).pack(anchor="w",pady=(0,14))
        tk.Label(f,text="동영상 페이지 또는 미디어 주소",bg="#f5f5f5").pack(anchor="w")

        # 일반 Tk Entry로 입력 포커스/마우스 동작을 명확히 하고 별도 붙여넣기 버튼 제공
        urlrow=tk.Frame(f,bg="#f5f5f5"); urlrow.pack(fill="x",pady=(5,12))
        self.entry=tk.Entry(urlrow,textvariable=self.url,font=("Segoe UI",11),relief="solid",bd=1,
                            highlightthickness=1,highlightbackground="#b8b8b8",highlightcolor="#c91d2e")
        self.entry.pack(side="left",fill="x",expand=True,ipady=7)
        self.entry.bind("<Button-1>",lambda e:self.entry.focus_set())
        self.entry.bind("<Control-v>",lambda e:(self.paste_url(),"break")[1])
        self.entry.bind("<Control-V>",lambda e:(self.paste_url(),"break")[1])
        self.entry.bind("<Shift-Insert>",lambda e:(self.paste_url(),"break")[1])
        self.entry.bind("<Return>",lambda e:self.start())
        ttk.Button(urlrow,text="붙여넣기",command=self.paste_url).pack(side="left",padx=(8,0),ipady=3)

        row=tk.Frame(f,bg="#f5f5f5"); row.pack(fill="x")
        self.go=ttk.Button(row,text="확인 · MP3 만들기",command=self.start); self.go.pack(side="left")
        ttk.Button(row,text="작업 기록",command=self.history).pack(side="left",padx=8)
        tk.Label(row,text="MP3  |  192 kbps  |  48 kHz",bg="#f5f5f5").pack(side="right")
        tk.Label(f,textvariable=self.status,bg="#f5f5f5").pack(anchor="w",pady=(22,6))
        self.progress=ttk.Progressbar(f,maximum=100); self.progress.pack(fill="x")
        tk.Label(f,text="지원 사이트의 공개 영상 및 다운로드가 허용된 콘텐츠를 처리합니다. DRM·접근 제한 콘텐츠는 지원하지 않습니다.",fg="#666",bg="#f5f5f5",wraplength=620,justify="left").pack(anchor="w",pady=(12,0))

    def start(self):
        if self.busy:return
        u=self.url.get().strip(); p=urllib.parse.urlparse(u)
        if p.scheme not in ("http","https") or not p.netloc:
            messagebox.showwarning("주소 확인","http:// 또는 https://로 시작하는 동영상 주소를 입력해 주세요."); return
        self.busy=True; self.go.configure(state="disabled"); self.entry.configure(state="disabled")
        self.settings["last_url"]=u; save_settings(self.settings); self.status.set("영상 정보를 확인하고 있습니다…"); self.progress.configure(mode="indeterminate"); self.progress.start(10)
        threading.Thread(target=self.worker,args=(u,),daemon=True).start()

    def worker(self,u):
        temp_dir=None
        try:
            host=urllib.parse.urlparse(u).netloc.lower()
            is_youtube=(host=="youtu.be" or host.endswith(".youtube.com") or host=="youtube.com" or host.endswith(".youtube-nocookie.com"))
            if is_youtube:
                # 공개적으로 접근 가능하고 사용자가 다운로드 권한을 가진 영상만 처리합니다.
                temp_dir=tempfile.mkdtemp(prefix="easy_save_audio_")
                opts={"format":"bestaudio/best","outtmpl":str(Path(temp_dir)/"source.%(ext)s"),
                      "noplaylist":True,"quiet":True,"no_warnings":True,"restrictfilenames":True}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info=ydl.extract_info(u,download=True)
                    title=safe_name(info.get("title") or "audio")
                candidates=[p for p in Path(temp_dir).iterdir() if p.is_file()]
                if not candidates: raise RuntimeError("다운로드된 오디오 파일을 찾지 못했습니다.")
                self.events.put(("choose",title,str(candidates[0]),u,temp_dir))
                return
            probe=subprocess.run([self.ffmpeg,"-hide_banner","-i",u],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=45)
            info=probe.stderr or ""
            m=re.search(r"\\btitle\\s*:\\s*(.+)$",info,re.I|re.M)
            fallback=Path(urllib.parse.unquote(urllib.parse.urlparse(u).path)).stem
            title=safe_name(m.group(1).strip() if m else (fallback or "audio"))
            self.events.put(("choose",title,u,u,None))
        except Exception as e:
            if temp_dir: shutil.rmtree(temp_dir,ignore_errors=True)
            self.events.put(("error",str(e),u))

    def poll(self):
        try:
            while True:
                e=self.events.get_nowait()
                if e[0]=="choose":
                    _,title,source,u,temp_dir=e; self.progress.stop(); self.progress.configure(mode="determinate",value=0)
                    folder=Path(self.settings.get("last_save_dir",str(Path.home()/"Music")))
                    if not folder.exists():folder=Path.home()
                    out=filedialog.asksaveasfilename(parent=self.root,title="MP3 파일 저장",initialdir=str(folder),initialfile=title+".mp3",defaultextension=".mp3",filetypes=[("MP3 오디오","*.mp3")])
                    if not out:
                        if temp_dir: shutil.rmtree(temp_dir,ignore_errors=True)
                        self.finish("저장이 취소되었습니다."); self.record(u,"취소",""); continue
                    self.settings["last_save_dir"]=str(Path(out).resolve().parent); save_settings(self.settings)
                    self.status.set("음성 데이터를 가져오고 있습니다…"); self.progress.configure(mode="indeterminate"); self.progress.start(10)
                    threading.Thread(target=self.download_encode,args=(u,out),daemon=True).start()
                elif e[0]=="status":
                    self.status.set(e[1])
                elif e[0]=="done":
                    _,u,out=e; self.finish("추출 및 저장이 완료되었습니다."); self.record(u,"성공",out)
                    if messagebox.askyesno("추출 성공",f"MP3 저장 완료\\n\\n{out}\\n\\n저장 폴더를 여시겠습니까?"): os.startfile(str(Path(out).parent))
                elif e[0]=="error":
                    _,msg,u=e
                    korean=korean_error(msg)
                    self.finish("추출에 실패했습니다."); self.record(u,"실패",korean)
                    messagebox.showerror("추출 실패",korean)
        except queue.Empty: pass
        self.root.after(100,self.poll)

    def download_encode(self,u,out):
        try:
            with tempfile.TemporaryDirectory(prefix="EasySaveAudio_") as temp:
                template=str(Path(temp)/"source.%(ext)s")
                def hook(data):
                    if data.get("status")=="downloading":
                        total=data.get("total_bytes") or data.get("total_bytes_estimate")
                        done=data.get("downloaded_bytes",0)
                        if total:
                            pct=max(0,min(100,int(done*100/total)))
                            self.events.put(("status",f"음성 데이터 다운로드 중… {pct}%"))
                    elif data.get("status")=="finished":
                        self.events.put(("status","음성 데이터 수신 완료 · MP3 변환 중…"))
                opts={"format":"bestaudio/best","outtmpl":template,"quiet":True,"no_warnings":True,
                      "noplaylist":True,"progress_hooks":[hook],"retries":3,"fragment_retries":3}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info=ydl.extract_info(u,download=True)
                    candidates=[]
                    for item in info.get("requested_downloads",[]) if isinstance(info,dict) else []:
                        if item.get("filepath"): candidates.append(Path(item["filepath"]))
                    try: candidates.append(Path(ydl.prepare_filename(info)))
                    except Exception: pass
                source=next((p for p in candidates if p.exists() and p.is_file()),None)
                if source is None:
                    files=[p for p in Path(temp).iterdir() if p.is_file()]
                    source=files[0] if files else None
                if source is None: raise RuntimeError("다운로드된 미디어 파일을 찾을 수 없습니다.")
                self.events.put(("status","MP3 192kbps · 48kHz로 변환 중…"))
                cmd=[self.ffmpeg,"-y","-hide_banner","-loglevel","error","-i",str(source),"-vn","-codec:a","libmp3lame","-b:a","192k","-ar","48000",out]
                p=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=7200,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                if p.returncode or not Path(out).exists() or Path(out).stat().st_size==0:
                    raise RuntimeError(p.stderr or "오디오 인코딩 오류")
            self.events.put(("done",u,out))
        except Exception as e:
            self.events.put(("error",str(e),u))

    def finish(self,msg):
        self.busy=False; self.progress.stop(); self.progress.configure(mode="determinate",value=100 if "완료" in msg else 0); self.go.configure(state="normal"); self.entry.configure(state="normal"); self.status.set(msg)

    def record(self,u,result,detail):
        h=self.settings.get("history",[]); h.insert(0,{"time":datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),"url":u,"result":result,"detail":detail})
        self.settings["history"]=h[:200]; save_settings(self.settings)

    def history(self):
        w=tk.Toplevel(self.root); w.title("작업 기록"); w.geometry("780x380")
        t=ttk.Treeview(w,columns=("time","result","detail"),show="headings"); t.heading("time",text="작업 시각"); t.heading("result",text="결과"); t.heading("detail",text="저장 파일 / 오류")
        t.column("time",width=150); t.column("result",width=70); t.column("detail",width=520); t.pack(fill="both",expand=True,padx=10,pady=10)
        for x in self.settings.get("history",[]):t.insert("","end",values=(x.get("time",""),x.get("result",""),x.get("detail","")))
        if not self.settings.get("history"):t.insert("","end",values=("","","기록이 없습니다."))

if __name__=="__main__":
    root=tk.Tk()
    App(root); root.mainloop(    def finish(self,msg):
        self.busy=False; self.progress.stop(); self.progress.configure(mode="determinate",value=100 if "완료" in msg else 0); self.go.configure(state="normal"); self.entry.configure(state="normal"); self.status.set(msg)

    def record(self,u,result,detail):
        h=self.settings.get("history",[]); h.insert(0,{"time":datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),"url":u,"result":result,"detail":detail})
        self.settings["history"]=h[:200]; save_settings(self.settings)

    def history(self):
        w=tk.Toplevel(self.root); w.title("작업 기록"); w.geometry("780x380")
        t=ttk.Treeview(w,columns=("time","result","detail"),show="headings"); t.heading("time",text="작업 시각"); t.heading("result",text="결과"); t.heading("detail",text="저장 파일 / 오류")
        t.column("time",width=150); t.column("result",width=70); t.column("detail",width=520); t.pack(fill="both",expand=True,padx=10,pady=10)
        for x in self.settings.get("history",[]):t.insert("","end",values=(x.get("time",""),x.get("result",""),x.get("detail","")))
        if not self.settings.get("history"):t.insert("","end",values=("","","기록이 없습니다."))

if __name__=="__main__":
    root=tk.Tk()
    App(root); root.mainloop()