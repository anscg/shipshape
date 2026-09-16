#!/usr/bin/env python3
"""Hack Club Make — 4x2" shipping labels for the H30C-Lite.

GUI:  ./run.sh
CLI:  ./run.sh --line1 "Manan Sharma" --qr "https://..." --print
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading

import label_render as lr

# Preview resolution. 203 dpi is the usual thermal head, and previewing there
# shows one screen pixel per printer dot with no resampling. It is an
# assumption about the H30C-Lite, not a measured fact: if the head turns out to
# be 300 dpi the real print will be cleaner than this preview suggests.
PREVIEW_DPI = 203
PREVIEW_W = int(round(PREVIEW_DPI * 4.0))
DPI_CHOICES = ("203", "300", "600")

FIELD_LABELS = ("Line 1", "Line 2", "Line 3", "Line 4", "Line 5")
FIELD_HINT = "Lines 1–2 sit beside the QR, so they wrap earlier. Blank lines are skipped."

SAMPLE = lr.DEFAULT_LINES


# --------------------------------------------------------------------------- GUI

def run_gui(initial: lr.Label, dpi: int, media: str):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    from PIL import ImageTk

    root = tk.Tk()
    root.title("Make Labels")

    style = ttk.Style()
    if "aqua" in style.theme_names():
        style.theme_use("aqua")

    style.configure("Heading.TLabel", font=("-apple-system", 11, "bold"))
    style.configure("Muted.TLabel", foreground="#8a8a8e")

    state = {"photo": None, "job": None, "printing": False}
    mono_var = tk.BooleanVar(value=True)

    outer = ttk.Frame(root, padding=(20, 18, 20, 16))
    outer.pack(fill="both", expand=True)

    # ---- preview -----------------------------------------------------------
    preview_h = int(round(PREVIEW_W * lr.LABEL_H_IN / lr.LABEL_W_IN))
    shell = ttk.Frame(outer, relief="solid", borderwidth=1)
    shell.pack()
    canvas = tk.Canvas(
        shell, width=PREVIEW_W, height=preview_h,
        highlightthickness=0, borderwidth=0, background="#ffffff",
    )
    canvas.pack()
    caption = ttk.Frame(outer)
    caption.pack(fill="x", pady=(6, 0))
    ttk.Label(
        caption,
        text=f"4 × 2 in  ·  actual size, modelled on a {PREVIEW_DPI} dpi head",
        style="Muted.TLabel",
    ).pack(side="left")
    ttk.Checkbutton(
        caption, text="1-bit (as printed)", variable=mono_var,
    ).pack(side="right")

    # ---- address -----------------------------------------------------------
    form = ttk.Frame(outer)
    form.pack(fill="x", pady=(18, 0))
    form.columnconfigure(1, weight=1)

    ttk.Label(form, text="Address", style="Heading.TLabel").grid(
        row=0, column=0, columnspan=2, sticky="w"
    )
    ttk.Label(form, text=FIELD_HINT, style="Muted.TLabel").grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(2, 8)
    )

    entries = []
    lines = initial.normalised()
    first_entry = None
    for i, field_name in enumerate(FIELD_LABELS):
        ttk.Label(form, text=field_name).grid(
            row=i + 2, column=0, sticky="e", pady=4, padx=(0, 12)
        )
        var = tk.StringVar(value=lines[i])
        ent = ttk.Entry(form, textvariable=var, font=("-apple-system", 13))
        ent.grid(row=i + 2, column=1, sticky="ew", pady=4)
        entries.append(var)
        if first_entry is None:
            first_entry = ent

    row = len(FIELD_LABELS) + 2
    ttk.Separator(form, orient="horizontal").grid(
        row=row, column=0, columnspan=2, sticky="ew", pady=14
    )
    ttk.Label(form, text="QR code", style="Heading.TLabel").grid(
        row=row + 1, column=0, columnspan=2, sticky="w", pady=(0, 8)
    )
    ttk.Label(form, text="Content").grid(
        row=row + 2, column=0, sticky="e", pady=4, padx=(0, 12)
    )
    qr_var = tk.StringVar(value=initial.qr_data)
    ttk.Entry(form, textvariable=qr_var, font=("-apple-system", 13)).grid(
        row=row + 2, column=1, sticky="ew", pady=4
    )

    # ---- printer -----------------------------------------------------------
    ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=16)

    printer_row = ttk.Frame(outer)
    printer_row.pack(fill="x")
    printer_row.columnconfigure(1, weight=1)

    printers = lr.list_printers()
    printer_var = tk.StringVar(
        value=lr.default_printer() or (printers[0] if printers else "")
    )
    ttk.Label(printer_row, text="Printer").grid(row=0, column=0, sticky="e", padx=(0, 12))
    ttk.Combobox(
        printer_row, textvariable=printer_var, values=printers, state="readonly"
    ).grid(row=0, column=1, sticky="ew")

    native_lbl = ttk.Label(printer_row, text="", style="Muted.TLabel")
    native_lbl.grid(row=2, column=1, sticky="w", pady=(6, 0))

    def on_printer(*_):
        native = lr.printer_resolution(printer_var.get().strip())
        if native:
            dpi_var.set(str(native))
            native_lbl.configure(
                text=f"driver reports {native} dpi — 1-bit output is exact at this dpi"
            )
        else:
            native_lbl.configure(
                text="driver does not report a resolution; set Output DPI to the head's own dpi"
            )

    printer_var.trace_add("write", on_printer)

    ttk.Label(printer_row, text="Copies").grid(row=0, column=2, sticky="e", padx=(16, 8))
    copies_var = tk.StringVar(value="1")
    ttk.Spinbox(printer_row, from_=1, to=99, width=4, textvariable=copies_var).grid(
        row=0, column=3
    )

    ttk.Label(printer_row, text="Output DPI").grid(row=1, column=0, sticky="e", padx=(0, 12), pady=(8, 0))
    dpi_var = tk.StringVar(value=str(dpi))
    ttk.Combobox(
        printer_row, textvariable=dpi_var, values=DPI_CHOICES, state="readonly", width=6
    ).grid(row=1, column=1, sticky="w", pady=(8, 0))

    ttk.Label(printer_row, text="Media").grid(row=1, column=2, sticky="e", padx=(16, 8), pady=(8, 0))
    media_var = tk.StringVar(value=media)
    ttk.Entry(printer_row, textvariable=media_var, width=16).grid(
        row=1, column=3, sticky="w", pady=(8, 0)
    )

    # ---- actions -----------------------------------------------------------
    actions = ttk.Frame(outer)
    actions.pack(fill="x", pady=(18, 0))

    status = ttk.Label(actions, text="Ready", style="Muted.TLabel")
    status.pack(side="left")

    def current_label() -> lr.Label:
        return lr.Label(lines=[v.get() for v in entries], qr_data=qr_var.get())

    def set_status(msg, error=False):
        status.configure(text=msg, foreground="#d1344b" if error else "#8a8a8e")

    # ---- live preview ------------------------------------------------------
    def draw_preview():
        state["job"] = None
        try:
            img = lr.render(current_label(), dpi=PREVIEW_DPI, mono=mono_var.get())
        except Exception as exc:  # noqa: BLE001 - reported in the status line
            set_status(f"Preview failed: {exc}", error=True)
            return
        # No resize: the render is already exactly PREVIEW_W x preview_h.
        state["photo"] = ImageTk.PhotoImage(img)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=state["photo"])

    def schedule_preview(*_):
        if state["job"] is not None:
            root.after_cancel(state["job"])
        state["job"] = root.after(160, draw_preview)

    for var in list(entries) + [qr_var, mono_var]:
        var.trace_add("write", schedule_preview)

    # ---- save / print ------------------------------------------------------
    def save_file():
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG image", "*.png"), ("PDF document", "*.pdf")],
            initialfile="label.png",
        )
        if not path:
            return
        out_dpi = int(dpi_var.get())
        img = lr.render(current_label(), dpi=out_dpi, mono=mono_var.get())
        if path.lower().endswith(".pdf"):
            lr.save_pdf(img, path, out_dpi)
        else:
            img.save(path, dpi=(out_dpi, out_dpi))
        set_status(f"Saved {os.path.basename(path)}")

    def do_print():
        target = printer_var.get().strip()
        if not target:
            messagebox.showerror("No printer", "No CUPS printer is available.")
            return
        if state["printing"]:
            return
        state["printing"] = True
        set_status("Sending…")

        label = current_label()
        out_dpi = int(dpi_var.get())
        try:
            copies = max(1, int(copies_var.get()))
        except ValueError:
            copies = 1
        media_name = media_var.get().strip() or "Custom.4x2in"
        mono = mono_var.get()

        def worker():
            try:
                msg = lr.print_label(
                    label, target, dpi=out_dpi, copies=copies,
                    media=media_name, mono=mono,
                )
                root.after(0, lambda: set_status(msg))
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or "").strip() or str(exc)
                root.after(0, lambda: set_status(f"Print failed: {detail}", error=True))
            except Exception as exc:  # noqa: BLE001
                root.after(0, lambda: set_status(f"Print failed: {exc}", error=True))
            finally:
                root.after(0, lambda: state.__setitem__("printing", False))

        threading.Thread(target=worker, daemon=True).start()

    def clear_all():
        for var in entries:
            var.set("")
        qr_var.set("")
        set_status("Cleared")

    print_btn = ttk.Button(actions, text="Print", command=do_print)
    try:
        print_btn.configure(default="active")
    except tk.TclError:
        pass
    print_btn.pack(side="right")
    ttk.Button(actions, text="Save…", command=save_file).pack(side="right", padx=(0, 8))
    ttk.Button(actions, text="Clear", command=clear_all).pack(side="right", padx=(0, 8))

    root.bind("<Command-p>", lambda e: do_print())
    root.bind("<Control-p>", lambda e: do_print())
    root.bind("<Command-s>", lambda e: save_file())
    root.bind("<Control-s>", lambda e: save_file())
    root.bind("<Command-Return>", lambda e: do_print())

    on_printer()
    draw_preview()
    root.update_idletasks()
    root.minsize(root.winfo_reqwidth(), root.winfo_reqheight())
    root.resizable(False, False)
    if first_entry is not None:
        first_entry.focus_set()
    root.mainloop()


# --------------------------------------------------------------------------- CLI

def main(argv=None):
    p = argparse.ArgumentParser(description='Hack Club Make 4x2in shipping labels')
    for i in range(1, lr.N_LINES + 1):
        p.add_argument(f"--line{i}", default=None, help=f"address line {i}")
    p.add_argument("--qr", default=None, help="QR payload")
    p.add_argument("--dpi", type=int, default=203, help="render DPI (default: 203)")
    p.add_argument("--media", default="Custom.4x2in", help="CUPS media name")
    p.add_argument("--out", default=None, help="write a PNG/PDF instead of opening the GUI")
    p.add_argument("--print", dest="do_print", action="store_true", help="send to the printer")
    p.add_argument("--printer", default=None, help="CUPS printer name")
    p.add_argument("--copies", type=int, default=1)
    p.add_argument("--grayscale", action="store_true",
                   help="keep anti-aliased edges instead of 1-bit thermal output")
    p.add_argument("--list-printers", action="store_true")
    args = p.parse_args(argv)

    if args.list_printers:
        for name in lr.list_printers():
            print(name)
        return 0

    given = [getattr(args, f"line{i}") for i in range(1, lr.N_LINES + 1)]
    has_lines = any(g is not None for g in given)
    label = lr.Label(
        lines=[g or "" for g in given] if has_lines else list(SAMPLE),
        qr_data=args.qr if args.qr is not None else lr.DEFAULT_QR,
    )

    if args.out:
        img = lr.render(label, dpi=args.dpi, mono=not args.grayscale)
        if args.out.lower().endswith(".pdf"):
            lr.save_pdf(img, args.out, args.dpi)
        else:
            img.save(args.out, dpi=(args.dpi, args.dpi))
        print(f"Wrote {args.out}")

    if args.do_print:
        target = args.printer or lr.default_printer()
        if not target:
            names = lr.list_printers()
            target = names[0] if names else None
        if not target:
            print("No CUPS printer found.", file=sys.stderr)
            return 1
        print(lr.print_label(label, target, dpi=args.dpi, copies=args.copies,
                             media=args.media, mono=not args.grayscale))
        return 0

    if not args.out:
        run_gui(label, args.dpi, args.media)
    return 0


if __name__ == "__main__":
    sys.exit(main())
