import json, os, re, subprocess, threading, queue, urllib.parse, sys
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import imageio_ffmpeg

APP="이지 세이브 오디오"
VERSION="1.0.2"
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

        # 앱 아이콘과 앱 이름을 한 줄에 배치
        head=tk.Frame(f,bg="#f5f5f5"); head.pack(fill="x",anchor="w",pady=(0,15))
        tk.Label(head,text="♫",font=("Segoe UI Symbol",27,"bold"),fg="white",bg="#c91d2e",width=2,height=1).pack(side="left",padx=(0,12))
        titlebox=tk.Frame(head,bg="#f5f5f5"); titlebox.pack(side="left",fill="y")
        tk.Label(titlebox,text=APP,font=("Malgun Gothic",19,"bold"),fg="#c91d2e",bg="#f5f5f5").pack(anchor="w")
        tk.Label(titlebox,text="Ryoo jaesang & 최피디",font=("Malgun Gothic",9),fg="#666",bg="#f5f5f5").pack(anchor="w")

        tk.Label(f,text="영상 주소를 입력하면 재생 없이 MP3로 추출합니다.",bg="#f5f5f5",font=("Malgun Gothic",10)).pack(anchor="w",pady=(0,14))
        tk.Label(f,text="영상 직접 다운로드 주소",bg="#f5f5f5").pack(anchor="w")

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
        tk.Label(f,text="다운로드·변환 권한이 있는 직접 미디어 주소만 지원합니다.",fg="#666",bg="#f5f5f5").pack(anchor="w",pady=(12,0))

    def start(self):
        if self.busy:return
        u=self.url.get().strip(); p=urllib.parse.urlparse(u)
        if p.scheme not in ("http","https") or not p.netloc:
            messagebox.showwarning("주소 확인","http:// 또는 https://로 시작하는 직접 미디어 주소를 입력해 주세요."); return
        self.busy=True; self.go.configure(state="disabled"); self.entry.configure(state="disabled")
        self.settings["last_url"]=u; save_settings(self.settings); self.status.set("영상 정보를 확인하고 있습니다…"); self.progress.configure(mode="indeterminate"); self.progress.start(10)
        threading.Thread(target=self.worker,args=(u,),daemon=True).start()

    def worker(self,u):
        try:
            probe=subprocess.run([self.ffmpeg,"-hide_banner","-i",u],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=45)
            info=probe.stderr or ""
            if "Input #0" not in info and "Stream #0" not in info: raise RuntimeError("주소에 접근할 수 없거나 지원하지 않는 미디어 형식입니다. 직접 다운로드 주소인지 확인해 주세요.")
            m=re.search(r"\btitle\s*:\s*(.+)$",info,re.I|re.M)
            title=safe_name(m.group(1).strip() if m else Path(urllib.parse.unquote(urllib.parse.urlparse(u).path)).stem)
            self.events.put(("choose",title,u))
        except Exception as e:self.events.put(("error",str(e),u))

    def poll(self):
        try:
            while True:
                e=self.events.get_nowait()
                if e[0]=="choose":
                    _,title,u=e; self.progress.stop(); self.progress.configure(mode="determinate",value=0)
                    folder=Path(self.settings.get("last_save_dir",str(Path.home()/"Music")))
                    if not folder.exists():folder=Path.home()
                    out=filedialog.asksaveasfilename(parent=self.root,title="MP3 파일 저장",initialdir=str(folder),initialfile=title+".mp3",defaultextension=".mp3",filetypes=[("MP3 오디오","*.mp3")])
                    if not out:self.finish("저장이 취소되었습니다."); self.record(u,"취소",""); continue
                    self.settings["last_save_dir"]=str(Path(out).resolve().parent); save_settings(self.settings)
                    self.status.set("MP3로 변환하고 있습니다…"); self.progress.configure(mode="indeterminate"); self.progress.start(10)
                    threading.Thread(target=self.encode,args=(u,out),daemon=True).start()
                elif e[0]=="done":
                    _,u,out=e; self.finish("추출 및 저장이 완료되었습니다."); self.record(u,"성공",out)
                    if messagebox.askyesno("추출 성공",f"MP3 저장 완료\n\n{out}\n\n저장 폴더를 여시겠습니까?"): os.startfile(str(Path(out).parent))
                elif e[0]=="error":
                    _,msg,u=e; self.finish("추출에 실패했습니다."); self.record(u,"실패",msg); messagebox.showerror("추출 실패",msg)
        except queue.Empty: pass
        self.root.after(100,self.poll)

    def encode(self,u,out):
        try:
            cmd=[self.ffmpeg,"-y","-hide_banner","-loglevel","error","-i",u,"-vn","-codec:a","libmp3lame","-b:a","192k","-ar","48000",out]
            p=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=7200,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            if p.returncode or not Path(out).exists() or Path(out).stat().st_size==0:
                raise RuntimeError("MP3 변환에 실패했습니다.\n"+(p.stderr or "서버 접근 또는 오디오 인코딩 오류").strip()[-1800:])
            self.events.put(("done",u,out))
        except Exception as e:self.events.put(("error",str(e),u))

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
    try:
        if getattr(sys,"frozen",False): root.iconbitmap(str(Path(sys._MEIPASS)/"easy_save_audio.ico"))
        else: root.iconbitmap("easy_save_audio.ico")
    except Exception: pass
    App(root); root.mainloop()
