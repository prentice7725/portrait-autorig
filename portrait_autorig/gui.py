from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import urllib.parse
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .workflow import (
    BuildResult,
    bundle_kind,
    compile_batch,
    compile_bundle_input,
    default_batch_output_path,
    default_output_path,
    discover_portrait_bundles,
)


class _PreviewRequestHandler(SimpleHTTPRequestHandler):
    """Serve the checked-in preview and one generated Rig Bundle locally."""

    def __init__(self, *args, preview_root: Path, run_root: Path, **kwargs):
        self.preview_root = preview_root.resolve()
        self.run_root = run_root.resolve()
        super().__init__(*args, directory=str(self.preview_root), **kwargs)

    def translate_path(self, path: str) -> str:
        route = urllib.parse.urlsplit(path).path.lstrip("/")
        if route.startswith("preview/"):
            root, relative = self.preview_root, route[len("preview/"):]
        elif route.startswith("run/"):
            root, relative = self.run_root, route[len("run/"):]
        else:
            return str(self.preview_root / "__missing__")
        candidate = (root / Path(*urllib.parse.unquote(relative).split("/"))).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return str(root / "__missing__")
        return str(candidate)

    def log_message(self, _format: str, *_args) -> None:
        return

    def end_headers(self) -> None:
        # The viewer must always execute the checked-out preview/runtime pair,
        # never a stale browser-cached module from an earlier build.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()


def _start_preview_server(run_root: Path) -> tuple[ThreadingHTTPServer, str]:
    preview_root = Path(__file__).resolve().parent.parent / "preview"
    handler = lambda *args, **kwargs: _PreviewRequestHandler(
        *args, preview_root=preview_root, run_root=run_root, **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/preview/index.html"


class PortraitAutorigApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Portrait AutoRig")
        self.root.geometry("880x650")
        self.root.minsize(760, 560)

        self.mode = tk.StringVar(value="single")
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.auto_output = tk.BooleanVar(value=True)
        self.legacy = tk.BooleanVar(value=False)
        self.soften_back_hair = tk.BooleanVar(value=False)
        self.recursive = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Portrait Bundle을 선택하세요.")
        self.progress_text = tk.StringVar(value="")
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._busy = False
        self._last_output: Path | None = None
        self._preview_server: ThreadingHTTPServer | None = None

        self._build_ui()
        self.root.after(100, self._drain_events)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="Portrait AutoRig", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Label(
            header,
            text="Semantic Bundle → Rig Bundle",
            foreground="#666666",
        ).pack(side="left", padx=(14, 0), pady=(6, 0))

        mode_box = ttk.LabelFrame(outer, text="빌드 모드", padding=12)
        mode_box.pack(fill="x", pady=(16, 10))
        ttk.Radiobutton(
            mode_box,
            text="한 명 빌드",
            variable=self.mode,
            value="single",
            command=self._mode_changed,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_box,
            text="폴더 일괄 빌드",
            variable=self.mode,
            value="batch",
            command=self._mode_changed,
        ).pack(side="left", padx=(24, 0))

        paths = ttk.LabelFrame(outer, text="경로", padding=12)
        paths.pack(fill="x", pady=(0, 10))
        paths.columnconfigure(1, weight=1)

        ttk.Label(paths, text="입력").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
        input_entry = ttk.Entry(paths, textvariable=self.input_path)
        input_entry.grid(row=0, column=1, sticky="ew", pady=5)
        input_entry.bind("<FocusOut>", lambda _event: self._refresh_auto_output())
        ttk.Button(paths, text="선택…", command=self._browse_input).grid(row=0, column=2, padx=(10, 0), pady=5)

        ttk.Label(paths, text="출력").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Entry(paths, textvariable=self.output_path).grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Button(paths, text="선택…", command=self._browse_output).grid(row=1, column=2, padx=(10, 0), pady=5)

        ttk.Checkbutton(
            paths,
            text="입력 경로에 맞춰 출력 경로 자동 설정",
            variable=self.auto_output,
            command=self._refresh_auto_output,
        ).grid(row=2, column=1, sticky="w", pady=(5, 0))

        options = ttk.LabelFrame(outer, text="옵션", padding=12)
        options.pack(fill="x", pady=(0, 10))
        ttk.Checkbutton(options, text="Legacy 입력", variable=self.legacy).pack(side="left")
        ttk.Checkbutton(options, text="Back hair 움직임 완화", variable=self.soften_back_hair).pack(side="left", padx=(22, 0))
        self.recursive_check = ttk.Checkbutton(options, text="하위 폴더까지 찾기", variable=self.recursive)
        self.recursive_check.pack(side="left", padx=(22, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(2, 12))
        self.build_button = ttk.Button(actions, text="BUILD", command=self._start_build)
        self.build_button.pack(side="left", ipadx=18, ipady=6)
        self.viewer_button = ttk.Button(actions, text="뷰어 열기", command=self._open_viewer, state="disabled")
        self.viewer_button.pack(side="left", padx=(10, 0), ipady=6)
        self.open_button = ttk.Button(actions, text="결과 폴더 열기", command=self._open_output, state="disabled")
        self.open_button.pack(side="left", padx=(8, 0), ipady=6)
        ttk.Button(actions, text="로그 지우기", command=self._clear_log).pack(side="right")

        progress_frame = ttk.Frame(outer)
        progress_frame.pack(fill="x")
        self.progress = ttk.Progressbar(progress_frame, mode="determinate", maximum=1, value=0)
        self.progress.pack(fill="x")
        ttk.Label(progress_frame, textvariable=self.progress_text, foreground="#666666").pack(anchor="w", pady=(4, 0))

        status_box = ttk.LabelFrame(outer, text="상태", padding=10)
        status_box.pack(fill="x", pady=(10, 10))
        ttk.Label(status_box, textvariable=self.status).pack(anchor="w")

        log_box = ttk.LabelFrame(outer, text="빌드 로그", padding=8)
        log_box.pack(fill="both", expand=True)
        self.log = tk.Text(log_box, height=12, wrap="word", state="disabled", font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(log_box, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._mode_changed()

    def _mode_changed(self) -> None:
        is_batch = self.mode.get() == "batch"
        self.recursive_check.configure(state="normal" if is_batch else "disabled")
        self.build_button.configure(text="BUILD ALL" if is_batch else "BUILD")
        self._refresh_auto_output()

    def _browse_input(self) -> None:
        title = "Portrait Bundle 선택" if self.mode.get() == "single" else "Portrait Bundle들이 있는 폴더 선택"
        selected = filedialog.askdirectory(title=title)
        if selected:
            self.input_path.set(selected)
            self._refresh_auto_output()

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(title="출력 위치 선택")
        if selected:
            if self.mode.get() == "single":
                input_path = Path(self.input_path.get()) if self.input_path.get() else None
                if input_path is not None:
                    self.output_path.set(str(Path(selected) / default_output_path(input_path).name))
                else:
                    self.output_path.set(selected)
            else:
                self.output_path.set(selected)
            self.auto_output.set(False)

    def _refresh_auto_output(self) -> None:
        if not self.auto_output.get() or not self.input_path.get().strip():
            return
        input_path = Path(self.input_path.get().strip())
        if self.mode.get() == "single":
            self.output_path.set(str(default_output_path(input_path)))
        else:
            self.output_path.set(str(default_batch_output_path(input_path)))

    def _validate_paths(self) -> tuple[Path, Path]:
        raw_input = self.input_path.get().strip()
        raw_output = self.output_path.get().strip()
        if not raw_input:
            raise ValueError("입력 경로를 선택하세요.")
        if not raw_output:
            raise ValueError("출력 경로를 선택하세요.")
        input_path = Path(raw_input)
        output_path = Path(raw_output)
        if not input_path.exists():
            raise ValueError(f"입력 경로가 없습니다: {input_path}")
        if not input_path.is_dir():
            raise ValueError(f"입력은 폴더여야 합니다: {input_path}")
        if self.mode.get() == "single" and not self.legacy.get():
            # `.portrait` is the conventional directory name used by batch
            # discovery, not part of the Bundle file contract. Validate the
            # selected directory by its manifest/layers so future bundle
            # types (for example full-body characters) can use any name.
            try:
                bundle_kind(input_path)
            except Exception as exc:
                raise ValueError(f"Bundle 검증 실패: {exc}") from exc
        return input_path, output_path

    def _start_build(self) -> None:
        if self._busy:
            return
        try:
            input_path, output_path = self._validate_paths()
        except Exception as exc:
            messagebox.showerror("Portrait AutoRig", str(exc))
            return

        # Tk variables belong to the UI thread. Snapshot every option before the
        # worker starts so the background compiler never touches tkinter state.
        mode = self.mode.get()
        legacy = self.legacy.get()
        soften_back_hair = self.soften_back_hair.get()
        recursive = self.recursive.get()

        self._busy = True
        self.build_button.configure(state="disabled")
        self.viewer_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.progress.configure(value=0, maximum=1)
        self.progress_text.set("")
        self.status.set("빌드 중…")
        self._append_log(f"\n=== {input_path} ===")

        thread = threading.Thread(
            target=self._build_worker,
            args=(input_path, output_path, mode, legacy, soften_back_hair, recursive),
            daemon=True,
        )
        thread.start()

    def _build_worker(
        self,
        input_path: Path,
        output_path: Path,
        mode: str,
        legacy: bool,
        soften_back_hair: bool,
        recursive: bool,
    ) -> None:
        try:
            if mode == "single":
                self._events.put(("progress_init", 1))
                result = compile_bundle_input(
                    input_path,
                    output_path,
                    legacy=legacy,
                    soften_back_hair=soften_back_hair,
                )
                self._events.put(("result", result))
                self._events.put(("progress", (1, 1, input_path.name)))
                self._events.put(("done", [result]))
            else:
                count = len(discover_portrait_bundles(input_path, recursive=recursive))
                if count == 0:
                    raise ValueError("선택한 폴더에서 .portrait 번들을 찾지 못했습니다.")
                self._events.put(("progress_init", count))

                def on_progress(index: int, total: int, source: Path,
                                result: BuildResult | None, error: Exception | None) -> None:
                    if result is not None:
                        self._events.put(("result", result))
                    if error is not None:
                        self._events.put(("build_error", (source, error)))
                    self._events.put(("progress", (index, total, source.name)))

                results = compile_batch(
                    input_path,
                    output_path,
                    recursive=recursive,
                    legacy=legacy,
                    soften_back_hair=soften_back_hair,
                    on_progress=on_progress,
                )
                self._events.put(("done", results))
        except Exception as exc:
            self._events.put(("fatal", exc))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "progress_init":
                    total = max(1, int(payload))
                    self.progress.configure(maximum=total, value=0)
                elif kind == "progress":
                    index, total, name = payload  # type: ignore[misc]
                    self.progress.configure(maximum=total, value=index)
                    self.progress_text.set(f"{index}/{total}  {name}")
                elif kind == "result":
                    result = payload  # type: ignore[assignment]
                    self._last_output = result.output_path
                    self._append_log(
                        f"OK  {result.input_path.name}\n"
                        f"    rig: {result.output_path}\n"
                        f"    preflight: {result.preflight_status} / rest: {result.rest_fidelity_status}"
                    )
                elif kind == "build_error":
                    source, error = payload  # type: ignore[misc]
                    self._append_log(f"FAIL  {source.name}: {error}")
                elif kind == "done":
                    results = payload  # type: ignore[assignment]
                    self._finish_success(results)
                elif kind == "fatal":
                    self._finish_error(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _finish_success(self, results: list[BuildResult]) -> None:
        self._busy = False
        self.build_button.configure(state="normal")
        if results:
            self._last_output = results[-1].output_path
            self.viewer_button.configure(state="normal")
            self.open_button.configure(state="normal")
            self._open_viewer()
        self.status.set(f"완료 — {len(results)}개 Rig Bundle 생성")
        self._append_log("=== DONE ===")

    def _finish_error(self, error: Exception) -> None:
        self._busy = False
        self.build_button.configure(state="normal")
        if self._last_output is not None:
            self.viewer_button.configure(state="normal")
            self.open_button.configure(state="normal")
        self.status.set("빌드 실패")
        self._append_log(f"ERROR  {error}")
        messagebox.showerror("Portrait AutoRig", str(error))

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _open_output(self) -> None:
        target = self._last_output or (Path(self.output_path.get()) if self.output_path.get() else None)
        if target is None:
            return
        folder = target if target.is_dir() else target.parent
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            messagebox.showerror("Portrait AutoRig", f"폴더를 열 수 없습니다:\n{exc}")

    def _open_viewer(self) -> None:
        target = self._last_output or (Path(self.output_path.get()) if self.output_path.get() else None)
        if target is None:
            return
        run_root = target if target.is_dir() else target.parent
        manifests = sorted(run_root.glob("*_rig_manifest.json"))
        if not manifests:
            messagebox.showerror("Portrait AutoRig", f"Rig manifest를 찾을 수 없습니다:\n{run_root}")
            return
        # A run directory can contain manifests from repeated builds.  Never
        # let lexical ordering silently open an older artifact: the canonical
        # compiler output wins, otherwise use the newest generated manifest.
        canonical = run_root / "portrait_rig_manifest.json"
        manifest = canonical if canonical.exists() else max(
            manifests, key=lambda path: path.stat().st_mtime
        )
        try:
            if self._preview_server is not None:
                self._preview_server.shutdown()
                self._preview_server.server_close()
            self._preview_server, base_url = _start_preview_server(run_root)
            manifest_url = base_url + "?manifest=" + urllib.parse.quote(
                "/run/" + manifest.name, safe="/"
            )
            if not webbrowser.open(manifest_url):
                raise RuntimeError("기본 브라우저를 열지 못했습니다.")
        except Exception as exc:
            messagebox.showerror("Portrait AutoRig", f"뷰어를 열 수 없습니다:\n{exc}")


def main() -> None:
    root = tk.Tk()
    PortraitAutorigApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
