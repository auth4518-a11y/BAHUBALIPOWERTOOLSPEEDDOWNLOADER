"""
╔══════════════════════════════════════════════════════════════╗
║        BAHUBALIPOWERTOOLSPEED DOWNLOADER v1.0               ║
║        Parallel Chunk Downloader - Maximum Speed            ║
╚══════════════════════════════════════════════════════════════╝
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import requests
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, unquote

BG       = "#060A0F"
CARD     = "#0D1520"
ACCENT   = "#00FF88"
BLUE     = "#00CFFF"
ORANGE   = "#FF6B35"
TEXT     = "#C8E0F0"
WHITE    = "#FFFFFF"

def format_size(b):
    if b <= 0: return "0 B"
    for unit in ["B","KB","MB","GB","TB"]:
        if b < 1024: return f"{b:.2f} {unit}"
        b /= 1024
    return f"{b:.2f} PB"

def format_time(sec):
    if sec == float('inf') or sec < 0: return "--"
    sec = int(sec)
    if sec < 60: return f"{sec}s"
    m, s = divmod(sec, 60)
    if m < 60: return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


class DownloadTask:
    def __init__(self, url, save_path, chunks=8, retries=3,
                 on_progress=None, on_done=None, on_error=None):
        self.url         = url
        self.save_path   = save_path
        self.chunks      = chunks
        self.retries     = retries
        self.on_progress = on_progress
        self.on_done     = on_done
        self.on_error    = on_error
        self.total       = 0
        self.loaded      = 0
        self.speed       = 0
        self._stop       = False
        self._pause      = False
        self._lock       = threading.Lock()

    def stop(self):   self._stop  = True
    def pause(self):  self._pause = True
    def resume(self): self._pause = False

    def _wait_if_paused(self):
        while self._pause and not self._stop:
            time.sleep(0.2)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            file_size = 0
            range_ok  = False
            try:
                h = requests.head(self.url, timeout=10, allow_redirects=True)
                file_size = int(h.headers.get("content-length", 0))
                range_ok  = h.headers.get("accept-ranges","none").lower() == "bytes"
            except: pass

            if file_size > 0 and range_ok and self.chunks > 1:
                self._parallel(file_size)
            else:
                self._single()
        except Exception as e:
            if self.on_error: self.on_error(str(e))

    def _single(self):
        resp = requests.get(self.url, stream=True, timeout=30)
        resp.raise_for_status()
        self.total = int(resp.headers.get("content-length", 0))
        t0 = time.time()
        last_loaded = 0
        last_time   = t0
        with open(self.save_path, "wb") as f:
            for chunk in resp.iter_content(65536):
                if self._stop: return
                self._wait_if_paused()
                f.write(chunk)
                with self._lock:
                    self.loaded += len(chunk)
                now = time.time()
                dt  = now - last_time
                if dt >= 0.3:
                    self.speed  = (self.loaded - last_loaded) / dt
                    last_loaded = self.loaded
                    last_time   = now
                pct = (self.loaded / self.total * 100) if self.total else 0
                if self.on_progress:
                    self.on_progress(pct, self.loaded, self.total, self.speed)
        if self.on_done: self.on_done()

    def _parallel(self, file_size):
        self.total     = file_size
        chunk_size     = file_size // self.chunks
        ranges         = []
        for i in range(self.chunks):
            s = i * chunk_size
            e = s + chunk_size - 1 if i < self.chunks - 1 else file_size - 1
            ranges.append((i, s, e))

        buffers    = [None] * self.chunks
        part_load  = [0]   * self.chunks
        t0         = time.time()
        last_load  = [0]
        last_time  = [t0]

        def fetch_chunk(idx, s, e, attempt=0):
            if self._stop: return
            try:
                r = requests.get(self.url,
                    headers={"Range": f"bytes={s}-{e}"},
                    stream=True, timeout=30)
                r.raise_for_status()
                data = b""
                for piece in r.iter_content(65536):
                    if self._stop: return
                    self._wait_if_paused()
                    data += piece
                    part_load[idx] += len(piece)
                    with self._lock:
                        self.loaded = sum(part_load)
                    now = time.time()
                    dt  = now - last_time[0]
                    if dt >= 0.3:
                        self.speed   = (self.loaded - last_load[0]) / dt
                        last_load[0] = self.loaded
                        last_time[0] = now
                    pct = self.loaded / self.total * 100
                    if self.on_progress:
                        self.on_progress(pct, self.loaded, self.total, self.speed)
                buffers[idx] = data
            except Exception as ex:
                if self._stop: return
                if attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
                    fetch_chunk(idx, s, e, attempt + 1)
                else:
                    raise ex

        with ThreadPoolExecutor(max_workers=self.chunks) as ex:
            futs = [ex.submit(fetch_chunk, i, s, e) for i, s, e in ranges]
            for f in as_completed(futs):
                f.result()

        if self._stop: return
        with open(self.save_path, "wb") as f:
            for buf in buffers:
                if buf: f.write(buf)
        if self.on_done: self.on_done()


class DownloadCard(tk.Frame):
    def __init__(self, parent, filename, url):
        super().__init__(parent, bg=CARD, pady=12, padx=14)
        self.task    = None
        self.done    = False
        self._paused = False

        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x")

        body = tk.Frame(self, bg=CARD)
        body.pack(fill="x", pady=(10, 0))

        top = tk.Frame(body, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text=filename, fg=WHITE, bg=CARD,
                 font=("Consolas", 11, "bold"), anchor="w",
                 wraplength=520).pack(side="left", fill="x", expand=True)
        self.status_lbl = tk.Label(top, text="STARTING", fg=ACCENT,
                                    bg="#0d1f30", font=("Consolas", 8, "bold"),
                                    padx=8, pady=3)
        self.status_lbl.pack(side="right")

        short = url if len(url) < 72 else url[:69] + "..."
        tk.Label(body, text=short, fg="#3a6a8a", bg=CARD,
                 font=("Consolas", 8), anchor="w").pack(fill="x", pady=(2, 8))

        bar_bg = tk.Frame(body, bg="#0d1f30", height=10)
        bar_bg.pack(fill="x")
        bar_bg.pack_propagate(False)
        self.bar_fill = tk.Frame(bar_bg, bg=ACCENT)
        self.bar_fill.place(x=0, y=0, relheight=1, relwidth=0)

        stats = tk.Frame(body, bg=CARD)
        stats.pack(fill="x", pady=(6, 8))
        self.pct_lbl   = tk.Label(stats, text="0%",      fg=ACCENT, bg=CARD, font=("Consolas", 10))
        self.size_lbl  = tk.Label(stats, text="0 B",     fg=TEXT,   bg=CARD, font=("Consolas", 10))
        self.speed_lbl = tk.Label(stats, text="-- /s",   fg=BLUE,   bg=CARD, font=("Consolas", 10))
        self.eta_lbl   = tk.Label(stats, text="ETA: --", fg=TEXT,   bg=CARD, font=("Consolas", 10))
        for w in (self.pct_lbl, self.size_lbl, self.speed_lbl, self.eta_lbl):
            w.pack(side="left", padx=(0, 20))

        btns = tk.Frame(body, bg=CARD)
        btns.pack(fill="x")
        self.pause_btn = tk.Button(btns, text="⏸ Pause", command=self._toggle_pause,
                                    bg="#1a2a3a", fg=TEXT, font=("Consolas", 9),
                                    relief="flat", bd=0, padx=10, pady=4, cursor="hand2")
        self.pause_btn.pack(side="left", padx=(0, 8))
        tk.Button(btns, text="✕ Cancel", command=self._cancel,
                  bg="#1a2a3a", fg=ORANGE, font=("Consolas", 9),
                  relief="flat", bd=0, padx=10, pady=4, cursor="hand2").pack(side="left")

    def update_progress(self, pct, loaded, total, speed):
        if self.done: return
        self.status_lbl.config(text="DOWNLOADING", fg=ACCENT)
        self.pct_lbl.config(text=f"{pct:.1f}%")
        sz = f"{format_size(loaded)} / {format_size(total)}" if total else format_size(loaded)
        self.size_lbl.config(text=sz)
        self.speed_lbl.config(text=f"{format_size(speed)}/s")
        eta = (total - loaded) / speed if speed > 0 and total > 0 else float('inf')
        self.eta_lbl.config(text=f"ETA: {format_time(eta)}")
        self.bar_fill.place(relwidth=min(pct / 100, 1.0))

    def mark_done(self):
        self.done = True
        self.status_lbl.config(text="✔ COMPLETE", fg=BLUE)
        self.pct_lbl.config(text="100%")
        self.bar_fill.config(bg=BLUE)
        self.bar_fill.place(relwidth=1.0)
        self.pause_btn.config(state="disabled")

    def mark_error(self, msg):
        self.done = True
        self.status_lbl.config(text="✗ ERROR", fg=ORANGE)
        tk.Label(self, text=f"⚠ {msg}", fg=ORANGE, bg=CARD,
                 font=("Consolas", 8)).pack(pady=(0, 4))

    def _toggle_pause(self):
        if not self.task: return
        if self._paused:
            self.task.resume()
            self.pause_btn.config(text="⏸ Pause")
            self.status_lbl.config(text="DOWNLOADING", fg=ACCENT)
        else:
            self.task.pause()
            self.pause_btn.config(text="▶ Resume")
            self.status_lbl.config(text="PAUSED", fg="#ffc800")
        self._paused = not self._paused

    def _cancel(self):
        if self.task: self.task.stop()
        self.done = True
        self.status_lbl.config(text="CANCELLED", fg=ORANGE)
        self.pause_btn.config(state="disabled")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BAHUBALIPOWERTOOLSPEED DOWNLOADER v1.0")
        self.geometry("860x700")
        self.minsize(700, 500)
        self.configure(bg=BG)
        self.tasks = []
        self._build_ui()

    def _build_ui(self):
        # Title
        title_bar = tk.Frame(self, bg=CARD, pady=16)
        title_bar.pack(fill="x")
        tk.Label(title_bar, text="⚡ BAHUBALIPOWERTOOLSPEED DOWNLOADER",
                 fg=ACCENT, bg=CARD, font=("Consolas", 15, "bold")).pack()
        tk.Label(title_bar, text="PARALLEL CHUNK ENGINE  •  MAXIMUM SPEED  •  PAUSE / RESUME",
                 fg=BLUE, bg=CARD, font=("Consolas", 9)).pack(pady=(2, 0))

        # Input
        inp = tk.Frame(self, bg=CARD, padx=20, pady=16)
        inp.pack(fill="x", padx=14, pady=(12, 0))
        inp.columnconfigure(0, weight=1)

        tk.Label(inp, text="// DOWNLOAD URL", fg=BLUE, bg=CARD,
                 font=("Consolas", 9)).grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar()
        url_e = tk.Entry(inp, textvariable=self.url_var, bg="#0d1f30", fg=WHITE,
                         insertbackground=ACCENT, font=("Consolas", 10),
                         relief="flat", bd=0)
        url_e.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 10), ipady=8)
        url_e.bind("<Return>", lambda e: self._add())

        tk.Label(inp, text="// SAVE TO FOLDER", fg=BLUE, bg=CARD,
                 font=("Consolas", 9)).grid(row=2, column=0, sticky="w")
        self.folder_var = tk.StringVar(value=os.path.expanduser("~/Downloads"))
        tk.Entry(inp, textvariable=self.folder_var, bg="#0d1f30", fg=WHITE,
                 insertbackground=ACCENT, font=("Consolas", 10),
                 relief="flat", bd=0).grid(row=3, column=0, columnspan=3,
                                            sticky="ew", pady=(4, 10), ipady=8)
        tk.Button(inp, text="📁 Browse", command=self._browse,
                  bg="#1a2a3a", fg=BLUE, font=("Consolas", 9),
                  relief="flat", bd=0, padx=12, pady=6,
                  cursor="hand2").grid(row=3, column=3, padx=(8, 0))

        # Options
        opts = tk.Frame(inp, bg=CARD)
        opts.grid(row=4, column=0, columnspan=4, sticky="w", pady=(0, 12))
        tk.Label(opts, text="CHUNKS:", fg=TEXT, bg=CARD,
                 font=("Consolas", 10)).pack(side="left")
        self.chunk_var = tk.IntVar(value=8)
        tk.Spinbox(opts, from_=1, to=32, textvariable=self.chunk_var,
                   width=5, bg="#0d1f30", fg=ACCENT, font=("Consolas", 10),
                   relief="flat", bd=0, buttonbackground="#1a2a3a"
                   ).pack(side="left", padx=(4, 24))
        tk.Label(opts, text="RETRIES:", fg=TEXT, bg=CARD,
                 font=("Consolas", 10)).pack(side="left")
        self.retry_var = tk.IntVar(value=3)
        tk.Spinbox(opts, from_=1, to=10, textvariable=self.retry_var,
                   width=5, bg="#0d1f30", fg=ACCENT, font=("Consolas", 10),
                   relief="flat", bd=0, buttonbackground="#1a2a3a"
                   ).pack(side="left", padx=(4, 0))

        tk.Button(inp, text="⚡  DOWNLOAD SHURU KARO",
                  command=self._add,
                  bg=ACCENT, fg=BG, font=("Consolas", 12, "bold"),
                  relief="flat", bd=0, pady=12, cursor="hand2"
                  ).grid(row=5, column=0, columnspan=4, sticky="ew")

        # List header
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=14, pady=(14, 4))
        tk.Label(hdr, text="// ACTIVE DOWNLOADS", fg=BLUE, bg=BG,
                 font=("Consolas", 9)).pack(side="left")
        tk.Button(hdr, text="🗑 Clear Completed", command=self._clear_done,
                  bg="#0d1520", fg=ORANGE, font=("Consolas", 8),
                  relief="flat", bd=0, cursor="hand2").pack(side="right")

        # Scrollable list
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb     = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.dl_frame = tk.Frame(canvas, bg=BG)
        self.dl_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.dl_frame, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.empty_lbl = tk.Label(self.dl_frame,
            text="KOI DOWNLOAD NAHI\nURL daalo upar aur ⚡ dabao!",
            fg="#2a4a6a", bg=BG, font=("Consolas", 13, "bold"))
        self.empty_lbl.pack(pady=60)

    def _browse(self):
        d = filedialog.askdirectory()
        if d: self.folder_var.set(d)

    def _add(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Error", "URL daalo pehle bhai!"); return
        if not url.startswith(("http://", "https://")):
            messagebox.showerror("Error", "http:// ya https:// se shuru hona chahiye!"); return
        folder = self.folder_var.get().strip()
        if not os.path.isdir(folder):
            messagebox.showerror("Error", "Save folder exist nahi karta!"); return

        try:
            fname = unquote(os.path.basename(urlparse(url).path)) or "download"
        except:
            fname = "download"

        save_path = os.path.join(folder, fname)
        base, ext = os.path.splitext(save_path)
        i = 1
        while os.path.exists(save_path):
            save_path = f"{base}_{i}{ext}"; i += 1

        card = DownloadCard(self.dl_frame, fname, url)
        card.pack(fill="x", pady=4)
        self.empty_lbl.pack_forget()

        task = DownloadTask(url, save_path,
            chunks  = self.chunk_var.get(),
            retries = self.retry_var.get(),
            on_progress = lambda p, l, t, s: self.after(0, card.update_progress, p, l, t, s),
            on_done     = lambda: self.after(0, card.mark_done),
            on_error    = lambda e: self.after(0, card.mark_error, e)
        )
        card.task = task
        self.tasks.append(task)
        task.start()
        self.url_var.set("")

    def _clear_done(self):
        for w in self.dl_frame.winfo_children():
            if isinstance(w, DownloadCard) and w.done:
                w.destroy()
        if not any(isinstance(w, DownloadCard) for w in self.dl_frame.winfo_children()):
            self.empty_lbl.pack(pady=60)


if __name__ == "__main__":
    App().mainloop()
