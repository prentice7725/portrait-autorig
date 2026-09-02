from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .expression_workflow import (
    EXPRESSION_STATE_PRESETS,
    ExpressionApplyResult,
    apply_image_donors,
    apply_rig_donors,
)


class ExpressionComposerWindow:
    def __init__(self, parent: tk.Misc, initial_base: Path | None = None) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title("Portrait AutoRig — 표정 도너 조합")
        self.window.geometry("900x620")
        self.window.minsize(760, 520)

        self.base_run = tk.StringVar(value=str(initial_base) if initial_base else "")
        self.source_mode = tk.StringVar(value="image")
        self.state = tk.StringVar(value="eye_closed")
        self.donor_path = tk.StringVar()
        self.status = tk.StringVar(value="Base Rig과 도너를 선택하세요.")
        self._busy = False
        self._donors: dict[str, Path] = {}

        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.window, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="표정 도너 조합", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="메인 Rig는 그대로 두고, 눈감기·윙크·입모양 도너의 필요한 영역만 Expression Pack으로 합칩니다.",
            foreground="#666666",
        ).pack(anchor="w", pady=(2, 14))

        base_box = ttk.LabelFrame(outer, text="1. 메인 Rig", padding=10)
        base_box.pack(fill="x")
        base_box.columnconfigure(0, weight=1)
        ttk.Entry(base_box, textvariable=self.base_run).grid(row=0, column=0, sticky="ew")
        ttk.Button(base_box, text="선택…", command=self._browse_base).grid(row=0, column=1, padx=(8, 0))

        mode_box = ttk.LabelFrame(outer, text="2. 도너 방식", padding=10)
        mode_box.pack(fill="x", pady=(10, 0))
        ttk.Radiobutton(
            mode_box,
            text="생성 이미지 도너 (빠름)",
            variable=self.source_mode,
            value="image",
            command=self._mode_changed,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_box,
            text="분해된 donor Rig (정밀)",
            variable=self.source_mode,
            value="rig",
            command=self._mode_changed,
        ).pack(side="left", padx=(24, 0))

        add_box = ttk.LabelFrame(outer, text="3. 도너 추가", padding=10)
        add_box.pack(fill="x", pady=(10, 0))
        add_box.columnconfigure(2, weight=1)
        ttk.Label(add_box, text="상태").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.state_combo = ttk.Combobox(
            add_box,
            textvariable=self.state,
            values=EXPRESSION_STATE_PRESETS,
            width=18,
        )
        self.state_combo.grid(row=0, column=1, sticky="w")
        ttk.Entry(add_box, textvariable=self.donor_path).grid(row=0, column=2, sticky="ew", padx=(10, 8))
        self.browse_donor_button = ttk.Button(add_box, text="이미지 선택…", command=self._browse_donor)
        self.browse_donor_button.grid(row=0, column=3)
        ttk.Button(add_box, text="추가 / 교체", command=self._add_donor).grid(row=0, column=4, padx=(8, 0))

        list_box = ttk.LabelFrame(outer, text="4. 조합할 도너", padding=8)
        list_box.pack(fill="both", expand=True, pady=(10, 0))
        self.tree = ttk.Treeview(list_box, columns=("state", "source"), show="headings", height=10)
        self.tree.heading("state", text="상태")
        self.tree.heading("source", text="도너")
        self.tree.column("state", width=160, stretch=False)
        self.tree.column("source", width=650, stretch=True)
        scroll = ttk.Scrollbar(list_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(10, 0))
        ttk.Button(controls, text="선택 삭제", command=self._remove_selected).pack(side="left")
        ttk.Button(controls, text="전부 지우기", command=self._clear).pack(side="left", padx=(8, 0))
        self.apply_button = ttk.Button(controls, text="EXPRESSION PACK 만들기", command=self._start_apply)
        self.apply_button.pack(side="right", ipadx=12, ipady=5)

        ttk.Label(outer, textvariable=self.status).pack(anchor="w", pady=(8, 0))
        self._mode_changed()

    def _browse_base(self) -> None:
        selected = filedialog.askdirectory(title="메인 .rig 폴더 선택")
        if selected:
            self.base_run.set(selected)

    def _mode_changed(self) -> None:
        label = "이미지 선택…" if self.source_mode.get() == "image" else "donor Rig 선택…"
        self.browse_donor_button.configure(text=label)

    def _browse_donor(self) -> None:
        if self.source_mode.get() == "image":
            selected = filedialog.askopenfilename(
                title="표정 도너 이미지 선택",
                filetypes=[
                    ("Images", "*.png *.webp *.jpg *.jpeg"),
                    ("PNG", "*.png"),
                    ("All files", "*.*"),
                ],
            )
        else:
            selected = filedialog.askdirectory(title="분해된 donor .rig 폴더 선택")
        if selected:
            self.donor_path.set(selected)

    def _add_donor(self) -> None:
        state = self.state.get().strip()
        raw_path = self.donor_path.get().strip()
        if not state or not raw_path:
            messagebox.showerror("Portrait AutoRig", "상태명과 도너를 모두 지정하세요.")
            return
        path = Path(raw_path)
        if not path.exists():
            messagebox.showerror("Portrait AutoRig", f"도너가 없습니다:\n{path}")
            return
        self._donors[state] = path
        self._refresh_tree()
        self.donor_path.set("")
        self.status.set(f"{len(self._donors)}개 도너 준비됨")

    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for state, path in self._donors.items():
            self.tree.insert("", "end", iid=state, values=(state, str(path)))

    def _remove_selected(self) -> None:
        for item in self.tree.selection():
            self._donors.pop(item, None)
        self._refresh_tree()

    def _clear(self) -> None:
        self._donors.clear()
        self._refresh_tree()
        self.status.set("도너 목록을 비웠습니다.")

    def _start_apply(self) -> None:
        if self._busy:
            return
        base = Path(self.base_run.get().strip()) if self.base_run.get().strip() else None
        if base is None or not base.is_dir():
            messagebox.showerror("Portrait AutoRig", "메인 .rig 폴더를 선택하세요.")
            return
        if not self._donors:
            messagebox.showerror("Portrait AutoRig", "도너를 하나 이상 추가하세요.")
            return

        mode = self.source_mode.get()
        donors = dict(self._donors)
        self._busy = True
        self.apply_button.configure(state="disabled")
        self.status.set("표정 도너 조합 중…")
        threading.Thread(target=self._worker, args=(base, mode, donors), daemon=True).start()

    def _worker(self, base: Path, mode: str, donors: dict[str, Path]) -> None:
        try:
            if mode == "rig":
                result = apply_rig_donors(base, donors)
            else:
                result = apply_image_donors(base, donors)
            self.window.after(0, lambda: self._finish_success(result))
        except Exception as exc:
            self.window.after(0, lambda exc=exc: self._finish_error(exc))

    def _finish_success(self, result: ExpressionApplyResult) -> None:
        self._busy = False
        self.apply_button.configure(state="normal")
        states = ", ".join(result.states)
        self.status.set(f"완료 — {result.part_count}개 expression part / {len(result.states)} states")
        messagebox.showinfo(
            "Portrait AutoRig",
            f"Expression Pack을 메인 Rig에 합쳤습니다.\n\nStates: {states}\nParts: {result.part_count}",
        )

    def _finish_error(self, error: Exception) -> None:
        self._busy = False
        self.apply_button.configure(state="normal")
        self.status.set("표정 도너 조합 실패")
        messagebox.showerror("Portrait AutoRig", str(error))


def open_expression_window(parent: tk.Misc, initial_base: Path | None = None) -> ExpressionComposerWindow:
    return ExpressionComposerWindow(parent, initial_base=initial_base)
