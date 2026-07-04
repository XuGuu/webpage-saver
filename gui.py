#!/usr/bin/env python3
"""save-webpage 图形界面 — 粘贴链接，一键保存"""

import json
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from save_webpage import (save_article, check_cdp, launch_chrome_debug,
                          detect_site, human_size, pick_url_from_clipboard,
                          split_urls, format_share_text, build_index_html,
                          open_file)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
INDEX_FILE = "目录.html"


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
        self.root.geometry("580x680")
        self.root.resizable(False, False)

        cfg = load_config()
        self.var_dir = tk.StringVar(value=cfg.get("save_dir", self._desktop()))
        self.var_html = tk.BooleanVar(value=cfg.get("html", True))
        self.var_md = tk.BooleanVar(value=cfg.get("markdown", True))
        self.var_img = tk.BooleanVar(value=cfg.get("images", True))
        self.var_subfolder = tk.BooleanVar(value=cfg.get("subfolder", True))
        self.var_date_prefix = tk.BooleanVar(value=cfg.get("date_prefix", False))
        self.var_auto_open = tk.BooleanVar(value=cfg.get("auto_open", True))

        # 会话状态
        self.session_successes = []  # [(url, result)] 用于复制所有成功文章
        self.failed_urls = []    # 用于失败重试

        self._build_ui()

    def _desktop(self) -> str:
        d = os.path.join(os.path.expanduser("~"), "Desktop")
        return d if os.path.isdir(d) else os.path.expanduser("~")

    def _build_ui(self):
        pad = {"padx": 12, "pady": 4}

        # ---- URL ----
        frm_url = ttk.LabelFrame(self.root, text="文章链接（一行一个,支持批量）", padding=8)
        frm_url.pack(fill="x", **pad)

        self.txt_url = tk.Text(frm_url, height=3, wrap="none", font=("", 10))
        self.txt_url.pack(fill="x")
        self.txt_url.focus()

        try:
            clip = self.root.clipboard_get()
        except tk.TclError:
            clip = ""
        auto_url = pick_url_from_clipboard(clip)
        if auto_url:
            self.txt_url.insert("1.0", auto_url)

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
        frm_struct = ttk.LabelFrame(self.root, text="选项", padding=8)
        frm_struct.pack(fill="x", **pad)

        ttk.Checkbutton(frm_struct, text="用文章标题新建文件夹存放",
                        variable=self.var_subfolder).pack(anchor="w")
        ttk.Checkbutton(frm_struct, text="文件夹名前加日期(2026-06-26_标题)",
                        variable=self.var_date_prefix).pack(anchor="w")
        ttk.Checkbutton(frm_struct, text="保存完成后自动打开 HTML",
                        variable=self.var_auto_open).pack(anchor="w")

        # ---- 按钮 ----
        frm_btn = ttk.Frame(self.root, padding=8)
        frm_btn.pack(fill="x")

        self.btn_run = ttk.Button(frm_btn, text="开始保存", command=self._run)
        self.btn_run.pack(side="left")

        ttk.Button(frm_btn, text="启动 Chrome（知乎用）",
                   command=self._launch_chrome).pack(side="left", padx=(12, 0))

        # 保存后可用的操作按钮(初始禁用)
        frm_actions = ttk.Frame(self.root, padding=(12, 0))
        frm_actions.pack(fill="x")
        self.btn_copy = ttk.Button(frm_actions, text="📋 复制标题/作者/链接",
                                   command=self._copy_share, state="disabled")
        self.btn_copy.pack(side="left")
        self.btn_index = ttk.Button(frm_actions, text="📚 打开目录",
                                    command=self._open_index)
        self.btn_index.pack(side="left", padx=(8, 0))
        self.btn_retry = ttk.Button(frm_actions, text="🔁 重试失败",
                                    command=self._retry_failed, state="disabled")
        self.btn_retry.pack(side="left", padx=(8, 0))

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
        save_config({
            "save_dir": self.var_dir.get(),
            "html": self.var_html.get(),
            "markdown": self.var_md.get(),
            "images": self.var_img.get(),
            "subfolder": self.var_subfolder.get(),
            "date_prefix": self.var_date_prefix.get(),
            "auto_open": self.var_auto_open.get(),
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
        raw = self.txt_url.get("1.0", "end").strip()
        urls = split_urls(raw)
        if not urls:
            messagebox.showwarning("提示", "请输入至少一个 http(s) 开头的链接")
            return

        if not self.var_html.get() and not self.var_md.get() and not self.var_img.get():
            messagebox.showwarning("提示", "请至少选择一个保存格式")
            return

        if any(detect_site(u) == "zhihu" for u in urls) and not check_cdp():
            messagebox.showwarning("提示", "有知乎链接,需要 Chrome\n请先点「启动 Chrome」并在 Chrome 中登录知乎")
            return

        self._save_prefs()
        self.btn_run.config(state="disabled")
        self.btn_copy.config(state="disabled")
        self.btn_retry.config(state="disabled")
        self.progress.start(10)
        self._log(f"--- 开始（共 {len(urls)} 篇）---")
        self.failed_urls = []
        self.session_successes = []

        threading.Thread(target=self._do_save, args=(urls,), daemon=True).start()

    def _retry_failed(self):
        if not self.failed_urls:
            return
        urls = list(self.failed_urls)  # 拷贝一份
        self._save_prefs()
        self.btn_run.config(state="disabled")
        self.btn_retry.config(state="disabled")
        self.progress.start(10)
        self._log(f"--- 重试 {len(urls)} 篇 ---")
        self.failed_urls = []
        threading.Thread(target=self._do_save, args=(urls,), daemon=True).start()

    def _do_save(self, urls: list):
        try:
            fmts = []
            if self.var_html.get(): fmts.append("html")
            if self.var_md.get(): fmts.append("md")
            if self.var_img.get(): fmts.append("images")

            ok_count = 0
            fail_count = 0
            last_html_path = None

            for i, url in enumerate(urls, 1):
                if len(urls) > 1:
                    self._log(f"[{i}/{len(urls)}] {url}")
                try:
                    result = save_article(
                        url, self.var_dir.get(),
                        formats=fmts,
                        use_subfolder=self.var_subfolder.get(),
                        log_fn=self._log,
                        date_prefix=self.var_date_prefix.get(),
                    )
                    if result.get("error"):
                        self._log(f"  失败: {result['error']}")
                        fail_count += 1
                        self.failed_urls.append(url)
                        continue
                    for f in result.get("files", []):
                        size = os.path.getsize(f)
                        self._log(f"  {os.path.basename(f)}  ({human_size(size)})")
                    if result.get("images"):
                        self._log(f"  图片: {len(result['images'])} 张")
                    ok_count += 1
                    self.session_successes.append((url, result))
                    # 记住最后一个 HTML 路径,供自动打开
                    for f in result.get("files", []):
                        if f.endswith(".html"):
                            last_html_path = f
                except Exception as e:
                    self._log(f"  失败: {e}")
                    fail_count += 1
                    self.failed_urls.append(url)

            summary = (f"--- 完成: 成功 {ok_count} / 失败 {fail_count} ---"
                       if len(urls) > 1
                       else ("--- 完成 ---" if ok_count else "--- 失败 ---"))
            self._log(summary)

            # 自动打开最后一个成功保存的 HTML
            if last_html_path and self.var_auto_open.get():
                open_file(last_html_path)

            # 更新目录索引
            try:
                if self.var_subfolder.get() and ok_count > 0:
                    index_path = os.path.join(self.var_dir.get(), INDEX_FILE)
                    with open(index_path, "w", encoding="utf-8") as f:
                        f.write(build_index_html(self.var_dir.get()))
            except Exception as e:
                self._log(f"（生成目录索引失败:{e}）")

            self._finish(ok_count == 0)

        except Exception as e:
            self._log(f"失败: {e}")
            self._finish(True)

    def _copy_share(self):
        if not self.session_successes:
            return
        blocks = [format_share_text(
            {"title": r.get("title", ""),
             "author": r.get("author", ""),
             "date": r.get("date", "")},
            url=u) for u, r in self.session_successes]
        share = "\n\n".join(blocks)
        self.root.clipboard_clear()
        self.root.clipboard_append(share)
        self._log(f"已复制 {len(blocks)} 篇到剪贴板")

    def _open_index(self):
        index_path = os.path.join(self.var_dir.get(), INDEX_FILE)
        if not os.path.exists(index_path):
            # 现场生成一次
            try:
                with open(index_path, "w", encoding="utf-8") as f:
                    f.write(build_index_html(self.var_dir.get()))
            except Exception as e:
                messagebox.showerror("错误", f"生成目录失败:{e}")
                return
        open_file(index_path)

    def _finish(self, error: bool):
        def _do():
            self.progress.stop()
            self.btn_run.config(state="normal")
            if self.session_successes:
                self.btn_copy.config(state="normal")
            if self.failed_urls:
                self.btn_retry.config(state="normal")
        self.root.after(0, _do)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
