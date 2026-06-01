#!/usr/bin/env python3
"""save-webpage 图形界面 — 粘贴链接，一键保存"""

import json
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from save_webpage import save_article, check_cdp, launch_chrome_debug, detect_site, human_size

# 配置文件路径
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("文章保存工具")
        self.root.geometry("560x520")
        self.root.resizable(False, False)

        # 加载配置
        cfg = load_config()
        self.var_dir = tk.StringVar(value=cfg.get("save_dir", self._desktop()))
        self.var_html = tk.BooleanVar(value=cfg.get("html", True))
        self.var_md = tk.BooleanVar(value=cfg.get("markdown", True))
        self.var_img = tk.BooleanVar(value=cfg.get("images", True))
        self.var_subfolder = tk.BooleanVar(value=cfg.get("subfolder", True))

        self._build_ui()

    def _desktop(self) -> str:
        d = os.path.join(os.path.expanduser("~"), "Desktop")
        return d if os.path.isdir(d) else os.path.expanduser("~")

    def _build_ui(self):
        pad = {"padx": 12, "pady": 4}

        # ---- URL ----
        frm_url = ttk.LabelFrame(self.root, text="文章链接", padding=8)
        frm_url.pack(fill="x", **pad)

        self.var_url = tk.StringVar()
        ent = ttk.Entry(frm_url, textvariable=self.var_url)
        ent.pack(fill="x")
        ent.focus()

        # ---- 保存位置 ----
        frm_dir = ttk.LabelFrame(self.root, text="保存到", padding=8)
        frm_dir.pack(fill="x", **pad)

        row_dir = ttk.Frame(frm_dir)
        row_dir.pack(fill="x")
        ttk.Entry(row_dir, textvariable=self.var_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(row_dir, text="选择...", command=self._pick_dir).pack(side="left", padx=(6, 0))

        # ---- 保存格式 ----
        frm_fmt = ttk.LabelFrame(self.root, text="保存格式（可多选）", padding=8)
        frm_fmt.pack(fill="x", **pad)

        row_fmt = ttk.Frame(frm_fmt)
        row_fmt.pack(fill="x")
        ttk.Checkbutton(row_fmt, text="HTML（给看）", variable=self.var_html).pack(side="left")
        ttk.Checkbutton(row_fmt, text="Markdown（给 LLM）", variable=self.var_md).pack(side="left", padx=(16, 0))
        ttk.Checkbutton(row_fmt, text="图片", variable=self.var_img).pack(side="left", padx=(16, 0))

        # ---- 目录结构 ----
        frm_struct = ttk.LabelFrame(self.root, text="目录结构", padding=8)
        frm_struct.pack(fill="x", **pad)

        ttk.Checkbutton(frm_struct, text="用文章标题新建文件夹存放（多选时建议开启）",
                        variable=self.var_subfolder).pack(anchor="w")
        ttk.Label(frm_struct, text="开启: 文章标题/文章.html  |  关闭: 直接存到上面选的文件夹",
                  foreground="gray", font=("", 9)).pack(anchor="w", pady=(2, 0))

        # ---- 按钮 ----
        frm_btn = ttk.Frame(self.root, padding=8)
        frm_btn.pack(fill="x")

        self.btn_run = ttk.Button(frm_btn, text="开始保存", command=self._run)
        self.btn_run.pack(side="left")

        ttk.Button(frm_btn, text="启动 Chrome（知乎用）", command=self._launch_chrome).pack(side="left", padx=(12, 0))

        # ---- 日志 ----
        frm_log = ttk.LabelFrame(self.root, text="日志", padding=4)
        frm_log.pack(fill="both", expand=True, padx=12, pady=(4, 8))

        self.log = tk.Text(frm_log, height=8, wrap="word", state="disabled",
                           font=("Consolas", 9), bg="#1e1e1e", fg="#cccccc",
                           relief="flat", padx=8, pady=6)
        scrollbar = ttk.Scrollbar(frm_log, command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)

        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill="x", padx=12, pady=(0, 8))

    def _log(self, msg: str):
        def _do():
            self.log.configure(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, _do)

    def _pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.var_dir.get())
        if d:
            self.var_dir.set(d)

    def _save_prefs(self):
        """保存用户偏好到配置文件。"""
        save_config({
            "save_dir": self.var_dir.get(),
            "html": self.var_html.get(),
            "markdown": self.var_md.get(),
            "images": self.var_img.get(),
            "subfolder": self.var_subfolder.get(),
        })

    def _launch_chrome(self):
        self._log("正在启动 Chrome...")
        try:
            launch_chrome_debug()
            self._log("Chrome 已启动，登录态已保留")
            messagebox.showinfo("完成", "Chrome 已启动\n\n如需抓知乎，请在 Chrome 中登录知乎\n然后回来点「开始保存」")
        except Exception as e:
            self._log(f"失败: {e}")
            messagebox.showerror("错误", str(e))

    def _run(self):
        url = self.var_url.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入文章链接")
            return

        # 至少选一个格式
        if not self.var_html.get() and not self.var_md.get() and not self.var_img.get():
            messagebox.showwarning("提示", "请至少选择一个保存格式")
            return

        # 知乎检查
        if detect_site(url) == "zhihu" and not check_cdp():
            messagebox.showwarning("提示", "知乎需要 Chrome\n请先点「启动 Chrome」并在 Chrome 中登录知乎")
            return

        self._save_prefs()
        self.btn_run.config(state="disabled")
        self.progress.start(10)
        self._log("--- 开始 ---")

        threading.Thread(target=self._do_save, args=(url,), daemon=True).start()

    def _do_save(self, url: str):
        try:
            fmts = []
            if self.var_html.get(): fmts.append("html")
            if self.var_md.get(): fmts.append("md")
            if self.var_img.get(): fmts.append("images")

            result = save_article(
                url, self.var_dir.get(),
                formats=fmts,
                use_subfolder=self.var_subfolder.get(),
                log_fn=self._log,
            )

            if result.get("error"):
                self._log(f"")
                self._log(f"失败: {result['error']}")
                self._finish(True)
                return

            self._log(f"")
            for f in result.get("files", []):
                size = os.path.getsize(f)
                self._log(f"  {os.path.basename(f)}  ({human_size(size)})")
            if result.get("images"):
                self._log(f"  图片: {len(result['images'])} 张")
            self._log("--- 完成 ---")

            self._finish(False)

        except Exception as e:
            self._log(f"失败: {e}")
            self._finish(True)

    def _finish(self, error: bool):
        def _do():
            self.progress.stop()
            self.btn_run.config(state="normal")
        self.root.after(0, _do)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
