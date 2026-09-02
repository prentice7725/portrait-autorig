from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .expression_gui import open_expression_window
from .gui import PortraitAutorigApp


class PortraitAutorigLauncher:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Portrait AutoRig")
        self.root.geometry("620x360")
        self.root.minsize(560, 320)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=28)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Portrait AutoRig", font=("Segoe UI", 21, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="메인 Rig를 만들고, 필요한 표정 도너를 조합하는 제작 도구",
            foreground="#666666",
        ).pack(anchor="w", pady=(4, 24))

        build = ttk.LabelFrame(outer, text="1. 메인 Rig", padding=16)
        build.pack(fill="x")
        ttk.Label(
            build,
            text="Production Portrait Bundle을 Rig Bundle로 컴파일합니다.",
        ).pack(anchor="w")
        ttk.Button(build, text="RIG 만들기", command=self._open_build).pack(anchor="e", pady=(12, 0), ipadx=18, ipady=5)

        expression = ttk.LabelFrame(outer, text="2. 표정 도너", padding=16)
        expression.pack(fill="x", pady=(14, 0))
        ttk.Label(
            expression,
            text="눈감기, 윙크, 입벌리기, A/I/U/E/O 등 여러 도너를 메인 Rig에 조합합니다.",
        ).pack(anchor="w")
        ttk.Button(
            expression,
            text="표정 도너 조합",
            command=lambda: open_expression_window(self.root),
        ).pack(anchor="e", pady=(12, 0), ipadx=18, ipady=5)

    def _open_build(self) -> None:
        window = tk.Toplevel(self.root)
        PortraitAutorigApp(window)  # Toplevel implements the Tk methods this window uses.


def main() -> None:
    root = tk.Tk()
    PortraitAutorigLauncher(root)
    # A window opened from a launched-but-not-focused process (a double
    # click on the .pyw, a shell association) otherwise draws behind
    # whatever already has focus -- indistinguishable from not having
    # started at all. Toggling topmost is the standard Tk way to force one
    # foreground swap on launch without pinning the window there permanently.
    root.lift()
    root.attributes("-topmost", True)
    root.after(200, lambda: root.attributes("-topmost", False))
    root.focus_force()
    root.mainloop()


if __name__ == "__main__":
    main()
