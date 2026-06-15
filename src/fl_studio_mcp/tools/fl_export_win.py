"""Automate FL Studio's File > Export > Wave dialog via pywinauto.

Runs in the MCP server process (NOT inside FL Studio's Python sandbox).
Requires pywinauto 0.6+ and win32: pip install pywinauto pywin32.

Workflow automated:
  1. Bring FL Studio to foreground
  2. Press Ctrl+R (File > Export > Wave)
  3. In the Save dialog: navigate to target folder, set filename, click Save
  4. In the Render dialog: enable 'Split mixer tracks', click Start
  5. Wait for render to complete (progress bar disappears)
  6. Return list of files written
"""
from __future__ import annotations

import os
import time
from pathlib import Path


def _get_fl_window():
    from pywinauto import Desktop
    wins = Desktop(backend="win32").windows()
    for w in wins:
        txt = w.window_text()
        cls = w.class_name()
        if "FL Studio" in txt and "TWelcome" not in cls and "TFruity" in cls:
            return w
    raise RuntimeError("FL Studio main window not found. Is FL Studio open?")


def _force_foreground(hwnd):
    """Reliably bring a window to foreground using win32 tricks."""
    import win32gui, win32con, ctypes
    # Allow setting foreground from this process
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(-1)
    except Exception:
        pass
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)
    win32gui.BringWindowToTop(hwnd)
    time.sleep(0.5)


def export_split_tracks(
    folder: str = "D:\\TEST MCP\\Audio",
    stem: str = "MIX_ANALYSE",
    wait_timeout: float = 120.0,
) -> dict:
    """Trigger File > Export > Wave (split tracks) in the open FL Studio instance.

    Parameters
    ----------
    folder : destination folder (must exist)
    stem   : base filename without extension
    wait_timeout : seconds to wait for the render to finish

    Returns
    -------
    dict with 'files' (list of written WAV paths) and 'elapsed_sec'
    """
    import pywinauto
    from pywinauto.keyboard import send_keys
    import win32gui
    import win32con

    dest = Path(folder)
    dest.mkdir(parents=True, exist_ok=True)

    # --- 1. Bring FL Studio to foreground (force via win32) ---
    fl = _get_fl_window()
    hwnd = fl.handle
    _force_foreground(hwnd)
    time.sleep(0.5)

    # --- 2. Open File > Export > Wave via Ctrl+R ---
    # Use SendInput (pywinauto send_keys) — injects at system level,
    # FL Studio receives it exactly like a real keyboard press.
    send_keys("^r")   # Ctrl+R = File > Export > Wave
    time.sleep(1.5)

    # --- 3. Handle the Save-As dialog ---
    desktop = pywinauto.Desktop(backend="win32")

    # Wait for the Save dialog (class #32770 = standard Windows dialog)
    save_dlg = None
    for _ in range(20):
        time.sleep(0.5)
        wins = desktop.windows()
        for w in wins:
            cls = w.class_name()
            txt = w.window_text()
            if cls == "#32770" and ("Enregistrer" in txt or "Save" in txt or "Export" in txt):
                save_dlg = w
                break
        if save_dlg:
            break

    if save_dlg is None:
        return {"error": "Save dialog did not appear after Ctrl+R. "
                         "Check that FL Studio is in the foreground and "
                         "the project has content to export."}

    # Type the full destination path into the filename field
    filename_field = None
    for ctrl in save_dlg.children():
        if ctrl.class_name() in ("Edit", "ComboBox"):
            try:
                filename_field = ctrl
                break
            except Exception:
                pass

    full_path = str(dest / f"{stem}.wav")

    # Set filename directly on the Edit control — no global keyboard injection,
    # no focus risk, handles spaces and special chars perfectly.
    try:
        fn_edit = save_dlg.child_window(class_name="Edit")
        fn_edit.set_focus()
        fn_edit.set_edit_text(full_path)
    except Exception:
        # Fallback: select-all then type via the dialog's own keyboard
        save_dlg.set_focus()
        send_keys("^a")
        send_keys(full_path.replace(" ", "{SPACE}"))

    time.sleep(0.3)
    # Click the Save button explicitly (more reliable than Enter)
    try:
        save_btn = save_dlg.child_window(title_re="Enregistrer|Save|OK", control_type="Button")
        save_btn.click()
    except Exception:
        send_keys("{ENTER}")
    time.sleep(1.5)

    # --- 4. Handle the Render Settings dialog ---
    render_dlg = None
    for _ in range(20):
        time.sleep(0.5)
        wins = desktop.windows()
        for w in wins:
            txt = w.window_text()
            if "Rendu" in txt or "Render" in txt or "Export" in txt:
                render_dlg = w
                break
        if render_dlg:
            break

    if render_dlg is None:
        return {"error": "Render dialog did not appear after saving path."}

    # Enable "Split mixer tracks" (Sép. pistes du mix.)
    # It's a radio button / checkbox in the Divers section
    # Try to find and click it
    split_enabled = False
    for ctrl in render_dlg.descendants():
        try:
            txt = ctrl.window_text()
            if ("pistes" in txt.lower() or "split" in txt.lower() or
                    "mixer" in txt.lower()):
                ctrl.click()
                split_enabled = True
                time.sleep(0.3)
                break
        except Exception:
            pass

    # Click the Start/Début button
    start_clicked = False
    for ctrl in render_dlg.descendants():
        try:
            txt = ctrl.window_text()
            if txt in ("Début", "Start", "Begin", "Render"):
                ctrl.click()
                start_clicked = True
                break
        except Exception:
            pass

    if not start_clicked:
        return {"error": "Could not find Start/Début button in render dialog.",
                "split_enabled": split_enabled}

    # --- 5. Wait for render to complete ---
    t0 = time.time()
    while time.time() - t0 < wait_timeout:
        time.sleep(1.0)
        # Check if the render dialog is gone (render finished)
        try:
            render_dlg.wrapper_object()  # raises if window closed
        except Exception:
            break  # dialog closed = render done
    else:
        return {"error": f"Render did not complete within {wait_timeout}s."}

    elapsed = round(time.time() - t0, 1)

    # --- 6. Collect written files ---
    time.sleep(0.5)  # let OS flush
    files = sorted(str(f) for f in dest.glob(f"{stem}*.wav"))
    return {
        "folder": folder,
        "stem": stem,
        "split_enabled": split_enabled,
        "files": files,
        "elapsed_sec": elapsed,
    }
