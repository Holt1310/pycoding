
# --- Clean, working fullscreen Tkinter launcher embedding two programs ---
import tkinter as tk
import os
from tkinter import filedialog, messagebox
import subprocess
import time
import ctypes
import sys
import win32gui
import win32process
import win32con
import threading
import json
import datetime
from typing import Union, Optional

# Track started child process IDs so we can terminate/restart them on reload
STARTED_PIDS = set()

# Map of launch title -> info dict {pid, hwnd, parent_hwnd}
LAUNCH_INFO = {}

# Default client settings path (can be overridden inside main)
CLIENT_SETTINGS_PATH = os.path.expanduser(r"~\\AppData\\Roaming\\Rice Lake Weighing Systems\\VIRTUi3\\settings\\ClientSettingsData.json")

# List of tuples (exe_path, custom_title, frame) to (re)launch on reload
CURRENT_LAUNCHES = []

# UI status label hook (set by main). Use set_status() to update text safely from threads.
STATUS_LABEL = None
STATUS_TEXT = ""

# Global mode tracking
calibration_mode = False  # Track if we're in calibration/settings mode
activity_timer = None
activity_start_time = time.time()
loading_in_progress = False  # Track if we're currently loading/reloading to prevent auto-restart
auto_reload_triggered = False  # Prevent multiple auto-reloads from triggering simultaneously

# Global references for overlay systems
GLOBAL_CONTAINER = None
GLOBAL_VIRTUI_OVERLAY = None
GLOBAL_BARCODE_OVERLAY = None
OVERLAY_SHOW_FUNCTION = None
BARCODE_OVERLAY_SHOW_FUNCTION = None
GUARDIAN_RUNNING = False
BARCODE_GUARDIAN_RUNNING = False
PASSWORD_DIALOG_OPEN = False  # Track if password dialog is open to exempt it from blockers

# =============================================================================
# OVERLAY HELPER FUNCTIONS - Easy to use overlay control functions
# =============================================================================

def _normalize_overlay_value(value: Union[int, str, None]) -> Union[int, None]:
    """Convert None or 'auto' to None for automatic VirtUI3 frame tracking."""
    if value is None or (isinstance(value, str) and value.lower() == 'auto'):
        return None
    # If it's a string that's not "auto", try to convert to int
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return value

def set_overlay_fullscreen() -> bool:
    """Set the transparent overlay to cover the entire screen."""
    global GLOBAL_VIRTUI_OVERLAY
    if GLOBAL_VIRTUI_OVERLAY and GLOBAL_VIRTUI_OVERLAY.get('set_custom_size'):
        success = GLOBAL_VIRTUI_OVERLAY['set_custom_size'](1920, 1080, 0, 0)
        print("✓ Overlay set to fullscreen (1920x1080)" if success else "✗ Failed to set fullscreen overlay")
        return success
    return False

def set_overlay_small(width: Union[int, str, None] = 800, height: Union[int, str, None] = 600, x: Union[int, str, None] = 100, y: Union[int, str, None] = 100) -> bool:
    """Set the transparent overlay to a small window.
    
    Args:
        width: Width in pixels (or None/'auto' for VirtUI3 frame width)
        height: Height in pixels (or None/'auto' for VirtUI3 frame height)
        x: X position in pixels (or None/'auto' for VirtUI3 frame X)
        y: Y position in pixels (or None/'auto' for VirtUI3 frame Y)
    """
    global GLOBAL_VIRTUI_OVERLAY
    if GLOBAL_VIRTUI_OVERLAY and GLOBAL_VIRTUI_OVERLAY.get('set_custom_size'):
        # Normalize values - convert None or "auto" to None
        w = _normalize_overlay_value(width)
        h = _normalize_overlay_value(height)
        x_pos = _normalize_overlay_value(x)
        y_pos = _normalize_overlay_value(y)
        
        success = GLOBAL_VIRTUI_OVERLAY['set_custom_size'](w, h, x_pos, y_pos)
        
        # Create descriptive message
        w_desc = "auto" if w is None else str(w)
        h_desc = "auto" if h is None else str(h)
        x_desc = "auto" if x_pos is None else str(x_pos)
        y_desc = "auto" if y_pos is None else str(y_pos)
        
        print(f"✓ Overlay set to small window ({w_desc}x{h_desc} at {x_desc},{y_desc})" if success else "✗ Failed to set small overlay")
        return success
    return False

def set_overlay_virtui_area() -> bool:
    """Set the transparent overlay to cover just the VirtUI3 area."""
    global GLOBAL_VIRTUI_OVERLAY
    if GLOBAL_VIRTUI_OVERLAY and GLOBAL_VIRTUI_OVERLAY.get('set_custom_size'):
        success = GLOBAL_VIRTUI_OVERLAY['set_custom_size'](1920, 120, 0, 0)
        print("✓ Overlay set to VirtUI area only (1920x120)" if success else "✗ Failed to set VirtUI area overlay")
        return success
    return False

def set_overlay_custom(width: Union[int, str, None], height: Union[int, str, None], x: Union[int, str, None] = 0, y: Union[int, str, None] = 0) -> bool:
    """Set the transparent overlay to custom dimensions.
    
    Args:
        width: Width in pixels (or None/'auto' for VirtUI3 frame width)
        height: Height in pixels (or None/'auto' for VirtUI3 frame height)
        x: X position in pixels (or None/'auto' for VirtUI3 frame X)
        y: Y position in pixels (or None/'auto' for VirtUI3 frame Y)
    """
    global GLOBAL_VIRTUI_OVERLAY
    if GLOBAL_VIRTUI_OVERLAY and GLOBAL_VIRTUI_OVERLAY.get('set_custom_size'):
        # Normalize values - convert None or "auto" to None
        w = _normalize_overlay_value(width)
        h = _normalize_overlay_value(height)
        x_pos = _normalize_overlay_value(x)
        y_pos = _normalize_overlay_value(y)
        
        success = GLOBAL_VIRTUI_OVERLAY['set_custom_size'](w, h, x_pos, y_pos)
        
        # Create descriptive message
        w_desc = "auto" if w is None else str(w)
        h_desc = "auto" if h is None else str(h)
        x_desc = "auto" if x_pos is None else str(x_pos)
        y_desc = "auto" if y_pos is None else str(y_pos)
        
        print(f"✓ Overlay set to custom size ({w_desc}x{h_desc} at {x_desc},{y_desc})" if success else f"✗ Failed to set custom overlay")
        return success
    return False

def reset_overlay_to_auto() -> bool:
    """Reset the transparent overlay to automatically track the VirtUI3 frame."""
    global GLOBAL_VIRTUI_OVERLAY
    if GLOBAL_VIRTUI_OVERLAY and GLOBAL_VIRTUI_OVERLAY.get('reset_to_auto'):
        success = GLOBAL_VIRTUI_OVERLAY['reset_to_auto']()
        print("✓ Overlay reset to auto-track VirtUI3 frame" if success else "✗ Failed to reset overlay")
        return success
    return False

# =============================================================================
# End of Overlay Helper Functions
# =============================================================================

# =============================================================================
# BARCODE OVERLAY HELPER FUNCTIONS - Easy to use barcode overlay control functions
# =============================================================================

def set_barcode_overlay_fullscreen() -> bool:
    """Set the transparent barcode overlay to cover the entire screen."""
    global GLOBAL_BARCODE_OVERLAY
    if GLOBAL_BARCODE_OVERLAY and GLOBAL_BARCODE_OVERLAY.get('set_custom_size'):
        success = GLOBAL_BARCODE_OVERLAY['set_custom_size'](1920, 1080, 0, 0)
        print("✓ Barcode overlay set to fullscreen (1920x1080)" if success else "✗ Failed to set fullscreen barcode overlay")
        return success
    return False

def set_barcode_overlay_custom(width: Union[int, str, None], height: Union[int, str, None], x: Union[int, str, None] = 0, y: Union[int, str, None] = 0) -> bool:
    """Set the transparent barcode overlay to custom dimensions.
    
    Args:
        width: Width in pixels (or None/'auto' for Bar-Code frame width)
        height: Height in pixels (or None/'auto' for Bar-Code frame height)
        x: X position in pixels (or None/'auto' for Bar-Code frame X)
        y: Y position in pixels (or None/'auto' for Bar-Code frame Y)
    """
    global GLOBAL_BARCODE_OVERLAY
    if GLOBAL_BARCODE_OVERLAY and GLOBAL_BARCODE_OVERLAY.get('set_custom_size'):
        # Normalize values - convert None or "auto" to None
        w = _normalize_overlay_value(width)
        h = _normalize_overlay_value(height)
        x_pos = _normalize_overlay_value(x)
        y_pos = _normalize_overlay_value(y)
        
        success = GLOBAL_BARCODE_OVERLAY['set_custom_size'](w, h, x_pos, y_pos)
        
        # Create descriptive message
        w_desc = "auto" if w is None else str(w)
        h_desc = "auto" if h is None else str(h)
        x_desc = "auto" if x_pos is None else str(x_pos)
        y_desc = "auto" if y_pos is None else str(y_pos)
        
        print(f"✓ Barcode overlay set to custom size ({w_desc}x{h_desc} at {x_desc},{y_desc})" if success else f"✗ Failed to set custom barcode overlay")
        return success
    return False

def set_barcode_overlay_barcode_area() -> bool:
    """Set the transparent barcode overlay to cover just the barcode area."""
    global GLOBAL_BARCODE_OVERLAY
    if GLOBAL_BARCODE_OVERLAY and GLOBAL_BARCODE_OVERLAY.get('set_custom_size'):
        success = GLOBAL_BARCODE_OVERLAY['set_custom_size'](None, None, None, None)  # Auto-track barcode frame
        print("✓ Barcode overlay set to barcode area only" if success else "✗ Failed to set barcode area overlay")
        return success
    return False

def reset_barcode_overlay_to_auto() -> bool:
    """Reset the transparent barcode overlay to automatically track the barcode frame."""
    global GLOBAL_BARCODE_OVERLAY
    if GLOBAL_BARCODE_OVERLAY and GLOBAL_BARCODE_OVERLAY.get('reset_to_auto'):
        success = GLOBAL_BARCODE_OVERLAY['reset_to_auto']()
        print("✓ Barcode overlay reset to auto-track barcode frame" if success else "✗ Failed to reset barcode overlay")
        return success
    return False

def enable_barcode_overlay() -> bool:
    """Enable the barcode overlay (show it)."""
    global GLOBAL_BARCODE_OVERLAY, BARCODE_OVERLAY_SHOW_FUNCTION
    try:
        if GLOBAL_BARCODE_OVERLAY and BARCODE_OVERLAY_SHOW_FUNCTION:
            BARCODE_OVERLAY_SHOW_FUNCTION()
            print("✓ Barcode overlay enabled")
            return True
        elif GLOBAL_BARCODE_OVERLAY:
            # Fallback to direct show for barcode blocker window
            if GLOBAL_BARCODE_OVERLAY.get('blocker') and GLOBAL_BARCODE_OVERLAY['blocker'].winfo_exists():
                GLOBAL_BARCODE_OVERLAY['blocker'].deiconify()
                GLOBAL_BARCODE_OVERLAY['blocker'].wm_attributes('-topmost', True)
            print("✓ Barcode overlay enabled (fallback method)")
            return True
    except Exception as e:
        print(f"✗ Error enabling barcode overlay: {e}")
    return False

def disable_barcode_overlay() -> bool:
    """Disable the barcode overlay (hide it)."""
    global GLOBAL_BARCODE_OVERLAY
    try:
        if GLOBAL_BARCODE_OVERLAY:
            # Hide blocker window
            if GLOBAL_BARCODE_OVERLAY.get('blocker') and GLOBAL_BARCODE_OVERLAY['blocker'].winfo_exists():
                GLOBAL_BARCODE_OVERLAY['blocker'].withdraw()
            print("✓ Barcode overlay disabled")
            return True
    except Exception as e:
        print(f"✗ Error disabling barcode overlay: {e}")
    return False

# =============================================================================
# End of Barcode Overlay Helper Functions
# =============================================================================

# USAGE EXAMPLES:
# 
# # VirtUI3 Overlay Examples:
# # Set overlay to cover entire screen
# set_overlay_fullscreen()
# 
# # Set overlay to a small 800x600 window at position 100,100
# set_overlay_small()
# 
# # Set overlay width to 1000px but use auto height and position from VirtUI3 frame
# set_overlay_custom(1000, None, None, None)
# set_overlay_custom(1000, "auto", "auto", "auto")  # Same as above
# 
# # Set overlay to custom position but use VirtUI3 frame size
# set_overlay_custom(None, None, 200, 300)
# 
# # Set overlay to custom width and fixed Y position, auto everything else
# set_overlay_custom(800, "auto", "auto", 50)
# 
# # Set overlay to just cover the VirtUI3 area
# set_overlay_virtui_area()
# 
# # Reset overlay back to automatically tracking VirtUI3 frame
# reset_overlay_to_auto()
# 
# # Barcode Overlay Examples:
# # Set barcode overlay to cover entire screen
# set_barcode_overlay_fullscreen()
# 
# # Set barcode overlay to custom dimensions
# set_barcode_overlay_custom(1500, 800, 200, 100)
# 
# # Set barcode overlay width to 1000px but use auto height and position from Bar-Code frame
# set_barcode_overlay_custom(1000, None, None, None)
# set_barcode_overlay_custom(1000, "auto", "auto", "auto")  # Same as above
# 
# # Set barcode overlay to just cover the barcode area (auto-track frame)
# set_barcode_overlay_barcode_area()
# 
# # Reset barcode overlay back to automatically tracking Bar-Code frame
# reset_barcode_overlay_to_auto()
# 
# # Enable/disable barcode overlay manually
# enable_barcode_overlay()
# disable_barcode_overlay()
#

def set_status(text):
    """Update the status text; if the status label exists, update it on the Tk mainloop thread."""
    global STATUS_LABEL, STATUS_TEXT
    try:
        STATUS_TEXT = str(text)
        # Guard against STATUS_LABEL being None and access attributes on a local reference
        if STATUS_LABEL is not None and getattr(STATUS_LABEL, 'winfo_exists', lambda: False)():
            lbl = STATUS_LABEL
            def _update():
                try:
                    # Prefer configure, fall back to config
                    if hasattr(lbl, 'configure'):
                        lbl.configure(text=STATUS_TEXT)
                    elif hasattr(lbl, 'config'):
                        lbl.config(text=STATUS_TEXT)
                except Exception:
                    pass
            try:
                lbl.after(0, _update)
            except Exception:
                _update()
        # Reset activity timer when status is manually updated (not by clock)
        if not str(text).replace(':', '').replace(' ', '').replace('AM', '').replace('PM', '').isdigit():
            try:
                # Only reset if this isn't a time display update
                globals().get('update_activity_time', lambda: None)()
            except Exception:
                pass
    except Exception:
        # best-effort only
        pass

def disable_windows_taskbar():
    """Hide the Windows taskbar when in calibration mode."""
    try:
        # Find the taskbar window
        taskbar_hwnd = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
        if taskbar_hwnd:
            # Hide the taskbar
            ctypes.windll.user32.ShowWindow(taskbar_hwnd, 0)  # SW_HIDE
    except Exception:
        pass

def enable_windows_taskbar():
    """Show the Windows taskbar when exiting calibration mode."""
    try:
        # Find the taskbar window
        taskbar_hwnd = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
        if taskbar_hwnd:
            # Show the taskbar
            ctypes.windll.user32.ShowWindow(taskbar_hwnd, 1)  # SW_SHOWNORMAL
    except Exception:
        pass

def set_window_title(hwnd, new_title):
    # Use ctypes to call the Win32 SetWindowTextW directly. It's a best-effort, non-critical operation.
    try:
        title = str(new_title)
        try:
            ctypes.windll.user32.SetWindowTextW(int(hwnd), ctypes.c_wchar_p(title))
        except Exception:
            # Ignore failures — some windows don't support title setting
            pass
    except Exception:
        pass

def terminate_pid(pid):
    """Try to terminate a single process by PID (best-effort)."""
    try:
        PROCESS_TERMINATE = 1
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
        if handle:
            ctypes.windll.kernel32.TerminateProcess(handle, 0)
            ctypes.windll.kernel32.CloseHandle(handle)
            try:
                STARTED_PIDS.discard(int(pid))
            except Exception:
                pass
            return True
    except Exception:
        pass
    try:
        os.kill(int(pid), 9)
        try:
            STARTED_PIDS.discard(int(pid))
        except Exception:
            pass
        return True
    except Exception:
        return False


def read_client_settings(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def write_client_settings(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def update_launch_with_mini_indicator(path, value):
    data = read_client_settings(path)
    if not data or 'UserModes' not in data:
        return False
    changed = False
    for mode in data.get('UserModes', []):
        # Update only the current mode if present; otherwise update all that match CurrentUserModeId
        try:
            mode_id = mode.get('Id', '')
            # If CurrentUserModeId matches, update that one only
            if 'CurrentUserModeId' in data and data.get('CurrentUserModeId') and data.get('CurrentUserModeId') == mode_id:
                if mode.get('LaunchWithMiniIndicator') != value:
                    mode['LaunchWithMiniIndicator'] = value
                    changed = True
                    break
        except Exception:
            continue
    if not changed:
        # fallback: update all modes so behavior is certain
        for mode in data.get('UserModes', []):
            try:
                if mode.get('LaunchWithMiniIndicator') != value:
                    mode['LaunchWithMiniIndicator'] = value
                    changed = True
            except Exception:
                continue
    if changed:
        return write_client_settings(path, data)
    return True


def get_mini_indicator_size(path):
    """Return (height, width) from the CurrentUserMode's MiniIndicatorSettings if available."""
    data = read_client_settings(path)
    if not data:
        return (None, None)
    cur = data.get('CurrentUserModeId')
    modes = data.get('UserModes', [])
    # Try to find the mode with matching Id first
    for m in modes:
        try:
            if m.get('Id') and cur and m.get('Id') == cur:
                s = m.get('MiniIndicatorSettings', {})
                return (int(s.get('WindowHeight') or 0) if s.get('WindowHeight') else None,
                        int(s.get('WindowWidth') or 0) if s.get('WindowWidth') else None)
        except Exception:
            continue
    # fallback: if any mode has MiniIndicatorSettings, return the first
    for m in modes:
        try:
            s = m.get('MiniIndicatorSettings')
            if s:
                return (int(s.get('WindowHeight') or 0) if s.get('WindowHeight') else None,
                        int(s.get('WindowWidth') or 0) if s.get('WindowWidth') else None)
        except Exception:
            continue
    return (None, None)


def compare_and_replace_with_control(control_path, target_path):
    """If control_path exists and differs from target_path, replace target with control (backup target)."""
    try:
        if not os.path.isfile(control_path):
            return False
        control = read_client_settings(control_path)
        target = read_client_settings(target_path)
        if control is None or target is None:
            return False
        if control != target:
            # backup target
            try:
                backup_path = target_path + '.bak'
                with open(backup_path, 'w', encoding='utf-8') as bf:
                    json.dump(target, bf, indent=2)
            except Exception:
                pass
            # replace
            try:
                with open(target_path, 'w', encoding='utf-8') as tf:
                    json.dump(control, tf, indent=2)
                return True
            except Exception:
                return False
        return False
    except Exception:
        return False


def ensure_launch_with_mini_true(target_path):
    """Ensure every UserMode has LaunchWithMiniIndicator set to True; return True if changed."""
    try:
        data = read_client_settings(target_path)
        if not data or 'UserModes' not in data:
            return False
        changed = False
        for mode in data.get('UserModes', []):
            try:
                if not mode.get('LaunchWithMiniIndicator'):
                    mode['LaunchWithMiniIndicator'] = True
                    changed = True
            except Exception:
                continue
        if changed:
            return write_client_settings(target_path, data)
        return False
    except Exception:
        return False

def update_launch_indicator(should_launch):
    """Updates the LaunchWithMiniIndicator setting in the ClientSettingsData.json file."""
    try:
        # Read the current settings
        data = read_client_settings(CLIENT_SETTINGS_PATH)
        if not data:
            print("Could not read client settings")
            return False
        
        # Update the LaunchWithMiniIndicator setting for all modes
        changed = False
        for mode in data.get('UserModes', []):
            try:
                if mode.get('LaunchWithMiniIndicator') != should_launch:
                    mode['LaunchWithMiniIndicator'] = should_launch
                    changed = True
            except Exception:
                continue
        
        if changed:
            result = write_client_settings(CLIENT_SETTINGS_PATH, data)
            print(f"Updated LaunchWithMiniIndicator to {should_launch}")
            return result
        return True
    except Exception as e:
        print(f"Error updating LaunchWithMiniIndicator: {e}")
        return False

def disable_virtui_overlay():
    """Disables the VirtUI3 overlay during calibration mode."""
    global GLOBAL_VIRTUI_OVERLAY
    try:
        if GLOBAL_VIRTUI_OVERLAY:
            # Hide blocker window
            if GLOBAL_VIRTUI_OVERLAY.get('blocker') and GLOBAL_VIRTUI_OVERLAY['blocker'].winfo_exists():
                GLOBAL_VIRTUI_OVERLAY['blocker'].withdraw()
            print("VirtUI3 overlay system disabled for calibration mode")
    except Exception as e:
        print(f"Error disabling VirtUI3 overlay: {e}")

def enable_virtui_overlay():
    """Re-enables the VirtUI3 overlay after calibration mode."""
    global GLOBAL_VIRTUI_OVERLAY, OVERLAY_SHOW_FUNCTION
    try:
        if GLOBAL_VIRTUI_OVERLAY and OVERLAY_SHOW_FUNCTION:
            # Use the safe show function to ensure proper positioning and visibility
            OVERLAY_SHOW_FUNCTION()
            print("VirtUI3 overlay system re-enabled after calibration mode")
        elif GLOBAL_VIRTUI_OVERLAY:
            # Fallback to direct show for blocker window
            if GLOBAL_VIRTUI_OVERLAY.get('blocker') and GLOBAL_VIRTUI_OVERLAY['blocker'].winfo_exists():
                GLOBAL_VIRTUI_OVERLAY['blocker'].deiconify()
                GLOBAL_VIRTUI_OVERLAY['blocker'].wm_attributes('-topmost', True)
            print("VirtUI3 overlay system re-enabled (fallback method)")
    except Exception as e:
        print(f"Error enabling VirtUI3 overlay: {e}")

def disable_all_overlays():
    """Disables both VirtUI3 and barcode overlays during calibration mode."""
    disable_virtui_overlay()
    disable_barcode_overlay()

def enable_all_overlays():
    """Re-enables both VirtUI3 and barcode overlays after calibration mode."""
    enable_virtui_overlay()
    enable_barcode_overlay()

def hide_overlays_for_password():
    """Temporarily hide overlays when password dialog is open."""
    global GLOBAL_VIRTUI_OVERLAY, GLOBAL_BARCODE_OVERLAY
    try:
        # Hide VirtUI3 overlay
        if GLOBAL_VIRTUI_OVERLAY and GLOBAL_VIRTUI_OVERLAY.get('blocker'):
            blocker = GLOBAL_VIRTUI_OVERLAY['blocker']
            if blocker.winfo_exists():
                blocker.withdraw()
                print("VirtUI3 overlay hidden for password dialog")
        
        # Hide barcode overlay
        if GLOBAL_BARCODE_OVERLAY and GLOBAL_BARCODE_OVERLAY.get('blocker'):
            barcode_blocker = GLOBAL_BARCODE_OVERLAY['blocker']
            if barcode_blocker.winfo_exists():
                barcode_blocker.withdraw()
                print("Barcode overlay hidden for password dialog")
    except Exception as e:
        print(f"Error hiding overlays for password: {e}")

def show_overlays_after_password():
    """Re-show overlays after password dialog closes."""
    global GLOBAL_VIRTUI_OVERLAY, GLOBAL_BARCODE_OVERLAY, OVERLAY_SHOW_FUNCTION, BARCODE_OVERLAY_SHOW_FUNCTION
    try:
        # Re-show VirtUI3 overlay
        if OVERLAY_SHOW_FUNCTION:
            OVERLAY_SHOW_FUNCTION()
            print("VirtUI3 overlay restored after password dialog")
        
        # Re-show barcode overlay
        if BARCODE_OVERLAY_SHOW_FUNCTION:
            BARCODE_OVERLAY_SHOW_FUNCTION()
            print("Barcode overlay restored after password dialog")
    except Exception as e:
        print(f"Error showing overlays after password: {e}")

def activate_virtui_overlay_when_ready():
    """Activates the VirtUI3 overlay once VirtUI3 is confirmed to be embedded."""
    global GLOBAL_VIRTUI_OVERLAY, OVERLAY_SHOW_FUNCTION
    try:
        # Wait for VirtUI3 to be properly embedded before showing overlay
        def check_and_activate():
            virtui_info = LAUNCH_INFO.get("Virtui 3 - Amazon")
            if virtui_info and virtui_info.get('hwnd') and not calibration_mode:
                if OVERLAY_SHOW_FUNCTION:
                    OVERLAY_SHOW_FUNCTION()
                    print("VirtUI3 overlay activated after successful embedding")
                    return True
            return False
        
        # Try immediately first
        if not check_and_activate():
            # If not ready, try again after a delay
            def delayed_check():
                if not check_and_activate():
                    # Try one more time after another delay
                    def final_check():
                        check_and_activate()
                    threading.Timer(2.0, final_check).start()
            threading.Timer(1.0, delayed_check).start()
            
    except Exception as e:
        print(f"Error activating VirtUI3 overlay: {e}")

def toggle_calibration_mode():
    """Toggle the calibration mode and update the VirtUI3 overlay accordingly."""
    try:
        # Read current setting
        data = read_client_settings(CLIENT_SETTINGS_PATH)
        if not data:
            print("Could not read client settings")
            return
        
        # Check current calibration mode (LaunchWithMiniIndicator = True means calibration mode)
        current_value = False
        for mode in data.get('UserModes', []):
            if mode.get('LaunchWithMiniIndicator'):
                current_value = True
                break
        
        new_value = not current_value
        
        # Update the setting
        success = update_launch_indicator(new_value)
        if success:
            mode_text = "calibration" if new_value else "normal"
            print(f"Switched to {mode_text} mode")
        else:
            print("Failed to update calibration mode")
        
    except Exception as e:
        print(f"Error toggling calibration mode: {e}")

def disable_event():
    pass  # Prevent closing the window

def start_program(path):
    exe_dir = os.path.dirname(path)
    process = subprocess.Popen([path], cwd=exe_dir)
    return process.pid

def get_hwnds_for_pid(pid):
    def callback(hwnd, hwnds):
        if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if found_pid == pid:
                hwnds.append(hwnd)
        return True
    hwnds = []
    win32gui.EnumWindows(callback, hwnds)
    return hwnds

def wait_for_window_by_pid(pid, timeout=30):
    set_status(f"Waiting for window for PID {pid}...")
    print(f"Waiting for window for PID {pid} (timeout {timeout}s)...")
    start_time = time.time()
    hwnd = None
    while time.time() - start_time < timeout:
        hwnds = get_hwnds_for_pid(pid)
        if hwnds:
            print(f"Found window handle(s) for PID {pid}: {hwnds}")
            # Prefer the largest visible window (by outer rect area) as the main UI window.
            best = None
            best_area = 0
            for h in hwnds:
                try:
                    l, t, r, b = win32gui.GetWindowRect(h)
                    area = max(0, r - l) * max(0, b - t)
                    if area > best_area:
                        best_area = area
                        best = h
                except Exception:
                    continue
            if best is not None:
                set_status(f"Found window for PID {pid}")
                print(f"Selected window {best} (area={best_area}) for PID {pid}")
                return best
            return hwnds[0]
        time.sleep(1)
    print(f"Timeout: No window found for PID {pid}")
    set_status(f"No window for PID {pid} (timeout)")
    return None

def set_window_position_and_size(hwnd, x, y, width, height):
    if hwnd:
        win32gui.SetWindowPos(hwnd, None, x, y, width, height, win32con.SWP_NOZORDER)
        print(f"Moved window to ({x}, {y}) with size ({width}, {height})")
    else:
        print("No matching window found")

def embed_window(hwnd, parent_hwnd, x, y, width, height):
    # Parent the window into our frame and make it a true child window.
    # Many apps create their own topmost window or use POPUP styles; to embed reliably
    # we remove popup/caption/thickframe styles and add WS_CHILD, then force a
    # frame-changed update and clear the topmost Z-order. Some apps re-apply
    # topmost quickly, so run a short watchdog to enforce NOTOPMOST for a moment.
    win32gui.SetParent(hwnd, parent_hwnd)
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    # Remove window decorations and popup style, add child style
    try:
        style = style & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME & ~win32con.WS_POPUP
    except Exception:
        # In case WS_POPUP isn't defined for this environment, just mask caption/thickframe
        style = style & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME
    style = style | win32con.WS_CHILD
    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)

    # Tell the window manager the frame has changed and clear TOPMOST. Use FRAMECHANGED
    # so the child respects new style. Also try bringing it to the top of the parent's Z order.
    flags = win32con.SWP_NOACTIVATE | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_FRAMECHANGED
    try:
        # Clear topmost first
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    except Exception:
        # Fallback: try using HWND_TOP
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, 0, 0, 0, 0, flags)

    # Finally set the size and show the window as a child (set to fill the parent Toplevel)
    try:
        # Clamp width/height so the child does not exceed the parent's outer rect
        try:
            pl, pt, pr, pb = win32gui.GetWindowRect(parent_hwnd)
            parent_w = max(1, pr - pl)
            parent_h = max(1, pb - pt)
        except Exception:
            parent_w = None
            parent_h = None
        # If parent size known, clamp
        if parent_w and parent_h:
            if width is None or width > parent_w:
                width = parent_w
            if height is None or height > parent_h:
                height = parent_h
            # ensure x/y keep window inside parent
            if x < 0:
                x = 0
            if y < 0:
                y = 0
    except Exception:
        pass
    set_window_position_and_size(hwnd, x, y, width, height)
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
    except Exception:
        pass

    # Short watchdog: some programs set TOPMOST repeatedly when starting; enforce NOTOPMOST briefly.
    def _clear_topmost_watch():
        # Repeatedly clear TOPMOST for a short while; some apps re-assert it several times.
        for _ in range(20):
            try:
                win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                     win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
            except Exception:
                pass
            time.sleep(0.25)

    threading.Thread(target=_clear_topmost_watch, daemon=True).start()


def focus_window_no_raise(hwnd):
    """Attempt to give keyboard focus to hwnd without calling SetForegroundWindow.
    Uses AttachThreadInput to attach our thread to the target thread, calls
    SetFocus/SetActiveWindow, then detaches. This usually sets keyboard focus
    without changing Z-order.
    """
    try:
        user32 = ctypes.windll.user32
        # Get thread IDs
        target_thread = user32.GetWindowThreadProcessId(hwnd, 0)
        current_thread = user32.GetCurrentThreadId()
        # Attach input threads
        attached = user32.AttachThreadInput(current_thread, target_thread, True)
        # Set active and focus
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
        # Detach
        if attached:
            user32.AttachThreadInput(current_thread, target_thread, False)
        return True
    except Exception:
        return False


def enforce_position(hwnd, parent_hwnd, x=0, y=0, interval=0.5):
    """Keep hwnd positioned at (x,y) relative to parent_hwnd by periodically
    correcting its position. Runs until the window disappears.
    """
    try:
        user32 = ctypes.windll.user32
        while True:
            time.sleep(interval)
            try:
                # If window no longer exists, stop
                if not win32gui.IsWindow(hwnd):
                    return
                # Get current rect relative to screen
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                # Get parent client origin in screen coords
                pl, pt, pr, pb = win32gui.GetWindowRect(parent_hwnd)
                # Desired screen coords
                desired_x = pl + x
                desired_y = pt + y
                if l != desired_x or t != desired_y:
                    # Move window back without changing z-order or size
                    user32.SetWindowPos(hwnd, None, desired_x, desired_y, 0, 0,
                                         win32con.SWP_NOZORDER | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
            except Exception:
                # continue monitoring
                continue
    except Exception:
        return

def setup_virtui_window_event_hook():
    """Set up Windows event hooks to catch any VirtUI3 window events and force overlay on top."""
    global GLOBAL_VIRTUI_OVERLAY
    
    def force_overlay_dominance():
        """Immediately force overlay to be on top of everything."""
        try:
            if (GLOBAL_VIRTUI_OVERLAY and not calibration_mode and not loading_in_progress):
                
                # NUCLEAR option - force blocker window to absolute top
                blocker = GLOBAL_VIRTUI_OVERLAY.get('blocker')
                
                if blocker and blocker.winfo_exists():
                    blocker.wm_attributes('-topmost', False)  # Reset topmost
                    blocker.wm_attributes('-topmost', True)   # Force topmost again
                    blocker.lift()  # Lift to front
                    
                    # Additional Windows API calls for blocker
                    try:
                        import ctypes
                        blocker_hwnd = int(blocker.winfo_id())
                        ctypes.windll.user32.SetWindowPos(
                            blocker_hwnd, -1,  # HWND_TOPMOST
                            0, 0, 0, 0,
                            0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
                        )
                    except Exception as e:
                        print(f"Error in Windows API blocker enforcement: {e}")
                    
        except Exception as e:
            print(f"Error forcing overlay dominance: {e}")
    
    def window_event_callback(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
        """Callback for Windows events - force overlay on top if VirtUI3 does anything."""
        try:
            # Check if this event is related to VirtUI3
            virtui_info = LAUNCH_INFO.get("Virtui 3 - Amazon")
            if virtui_info and virtui_info.get('hwnd') == hwnd:
                # VirtUI3 did something - IMMEDIATELY force overlay on top
                print(f"VirtUI3 window event detected (event={event}), forcing overlay dominance")
                force_overlay_dominance()
        except Exception as e:
            print(f"Error in window event callback: {e}")
    
    try:
        import ctypes
        from ctypes import wintypes
        
        # Define the event hook constants
        EVENT_SYSTEM_FOREGROUND = 0x0003
        EVENT_OBJECT_LOCATIONCHANGE = 0x800B
        EVENT_OBJECT_SHOW = 0x8002
        EVENT_OBJECT_FOCUS = 0x8005
        EVENT_SYSTEM_MOVESIZESTART = 0x000A
        EVENT_SYSTEM_MOVESIZEEND = 0x000B
        
        # Set up the hook function prototype
        WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, 
                                         wintypes.HWND, wintypes.LONG, wintypes.LONG,
                                         wintypes.DWORD, wintypes.DWORD)
        
        hook_proc = WINEVENTPROC(window_event_callback)
        
        # Hook multiple events that VirtUI3 might trigger
        events_to_hook = [
            EVENT_SYSTEM_FOREGROUND,     # When VirtUI3 gets focus
            EVENT_OBJECT_LOCATIONCHANGE, # When VirtUI3 moves
            EVENT_OBJECT_SHOW,          # When VirtUI3 becomes visible
            EVENT_OBJECT_FOCUS,         # When VirtUI3 gets focus
            EVENT_SYSTEM_MOVESIZESTART, # When VirtUI3 starts moving/resizing
            EVENT_SYSTEM_MOVESIZEEND    # When VirtUI3 ends moving/resizing
        ]
        
        hooks = []
        for event in events_to_hook:
            hook = ctypes.windll.user32.SetWinEventHook(
                event, event,  # eventMin, eventMax
                None,          # hmodWinEventProc
                hook_proc,     # lpfnWinEventProc
                0, 0,          # idProcess, idThread (0 = all processes/threads)
                0              # dwFlags (0 = WINEVENT_OUTOFCONTEXT)
            )
            if hook:
                hooks.append(hook)
        
        print(f"Set up {len(hooks)} Windows event hooks for VirtUI3 monitoring")
        return hooks
        
    except Exception as e:
        print(f"Error setting up Windows event hooks: {e}")
        return []

def start_continuous_virtui_reembedding():
    """Start a separate thread that continuously forces VirtUI3 to stay embedded."""
    def reembed_loop():
        while True:
            try:
                time.sleep(0.05)  # Check 20 times per second
                
                if loading_in_progress or calibration_mode:
                    continue
                
                virtui_info = LAUNCH_INFO.get("Virtui 3 - Amazon")
                if not virtui_info or not virtui_info.get('hwnd') or not virtui_info.get('frame'):
                    continue
                
                hwnd = virtui_info['hwnd']
                frame = virtui_info['frame']
                
                if not win32gui.IsWindow(hwnd):
                    continue
                
                try:
                    # Force embedding every cycle - no questions asked
                    target_parent = frame.winfo_id()
                    current_parent = win32gui.GetParent(hwnd)
                    
                    if current_parent != target_parent:
                        frame.update_idletasks()
                        fw = frame.winfo_width() if frame.winfo_width() > 1 else 1920
                        fh = frame.winfo_height() if frame.winfo_height() > 1 else 120
                        
                        embed_window(hwnd, target_parent, 0, 0, fw, fh)
                        print(f"CONTINUOUS re-embed: VirtUI3 parent corrected")
                        
                except Exception as e:
                    pass  # Silently continue - this runs very frequently
                    
            except Exception:
                pass  # Keep running no matter what
    
    reembed_thread = threading.Thread(target=reembed_loop, daemon=True)
    reembed_thread.start()
    print("Started continuous VirtUI3 re-embedding thread (20Hz)")

def start_virtui_state_guardian():
    """Continuously monitor and enforce VirtUI3 embedding and overlay states."""
    global GLOBAL_VIRTUI_OVERLAY, OVERLAY_SHOW_FUNCTION, GUARDIAN_RUNNING
    
    # Prevent multiple guardian instances
    if GUARDIAN_RUNNING:
        print("VirtUI3 State Guardian already running, skipping duplicate start")
        return
    
    GUARDIAN_RUNNING = True
    
    def guardian_loop():
        global GUARDIAN_RUNNING, PASSWORD_DIALOG_OPEN
        try:
            while GUARDIAN_RUNNING:
                try:
                    time.sleep(0.3)  # Reduced frequency - check 3 times per second to reduce flashing
                    
                    # Skip if loading or password dialog is open
                    if loading_in_progress or PASSWORD_DIALOG_OPEN:
                        continue
                    
                    # FORCE OVERLAY TO BE VISIBLE AND ON TOP - NO EXCEPTIONS
                    try:
                        if GLOBAL_VIRTUI_OVERLAY:
                            blocker = GLOBAL_VIRTUI_OVERLAY.get('blocker')
                            
                            # Force blocker window visible
                            if blocker and blocker.winfo_exists():
                                if not blocker.winfo_viewable():
                                    print("FORCING blocker visible")
                                    blocker.deiconify()
                                    blocker.wm_attributes('-topmost', True)
                                    blocker.wm_attributes('-alpha', 0.01)  # Maintain transparency
                            
                            # Force overlay positioning
                            try:
                                # Check if custom size is active
                                custom_size = GLOBAL_VIRTUI_OVERLAY.get('custom_size') if GLOBAL_VIRTUI_OVERLAY else None
                                
                                if custom_size and custom_size.get('active'):
                                    # Use custom positioning - don't override user settings
                                    if blocker and blocker.winfo_exists():
                                        # Get custom values, but handle None by getting frame values
                                        virtui_info = LAUNCH_INFO.get("Virtui 3 - Amazon")
                                        
                                        # Get current frame values for None substitution
                                        frame_x, frame_y, frame_w, frame_h = 0, 0, 1920, 120  # defaults
                                        if virtui_info and virtui_info.get('frame'):
                                            try:
                                                frame = virtui_info['frame']
                                                frame.update_idletasks()
                                                frame_x = frame.winfo_rootx()
                                                frame_y = frame.winfo_rooty()
                                                frame_w = frame.winfo_width() if frame.winfo_width() > 1 else 1920
                                                frame_h = frame.winfo_height() if frame.winfo_height() > 1 else 120
                                            except Exception:
                                                pass
                                        
                                        # Use custom values if not None, otherwise use frame values
                                        w = custom_size.get('width')
                                        h = custom_size.get('height') 
                                        x = custom_size.get('x')
                                        y = custom_size.get('y')
                                        
                                        # Replace None values with frame values
                                        w = int(w) if w is not None else frame_w
                                        h = int(h) if h is not None else frame_h
                                        x = int(x) if x is not None else frame_x
                                        y = int(y) if y is not None else frame_y
                                        
                                        blocker.geometry(f"{w}x{h}+{x}+{y}")
                                       # print(f"Guardian: maintaining custom overlay size {w}x{h} at ({x},{y})")
                                else:
                                    # Standard VirtUI3 frame-based positioning
                                    virtui_info = LAUNCH_INFO.get("Virtui 3 - Amazon")
                                    if virtui_info and virtui_info.get('frame'):
                                        frame = virtui_info['frame']
                                        frame.update_idletasks()
                                        x = frame.winfo_rootx()
                                        y = frame.winfo_rooty()
                                        w = frame.winfo_width()
                                        h = frame.winfo_height()
                                        
                                        if w > 1 and h > 1:
                                            # Position blocker to cover entire frame
                                            if blocker and blocker.winfo_exists():
                                                blocker.geometry(f"{w}x{h}+{x}+{y}")
                                        else:
                                            # Fallback positioning
                                            if blocker and blocker.winfo_exists():
                                                blocker.geometry("1920x120+0+0")
                                    else:
                                        # Fallback if frame not accessible
                                        if blocker and blocker.winfo_exists():
                                            blocker.geometry("1920x120+0+0")
                            except Exception as e:
                                print(f"Error positioning overlay: {e}")
                                # Emergency fallback
                                if blocker and blocker.winfo_exists():
                                    blocker.geometry("1920x120+0+0")
                            
                            # REDUCED TOPMOST ENFORCEMENT - avoid constant toggling
                            if blocker and blocker.winfo_exists():
                                blocker.wm_attributes('-topmost', True)  # Direct set instead of toggle
                            
                            # Try Windows API enforcement less frequently to reduce flashing
                            try:
                                import ctypes
                                # Only do Windows API enforcement every 3rd cycle (once per second)
                                cycle_counter = getattr(guardian_loop, 'cycle_counter', 0) + 1
                                guardian_loop.cycle_counter = cycle_counter
                                
                                if cycle_counter % 3 == 0:  # Every 3rd cycle
                                    if blocker and blocker.winfo_exists():
                                        blocker_hwnd = int(blocker.winfo_id())
                                        ctypes.windll.user32.SetWindowPos(
                                            blocker_hwnd, -1,  # HWND_TOPMOST
                                            0, 0, 0, 0,
                                            0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
                                        )
                            except Exception:
                                pass
                                
                    except Exception as e:
                        print(f"Error in overlay enforcement: {e}")
                    
                    # AGGRESSIVE VIRTUI3 EMBEDDING ENFORCEMENT
                    try:
                        virtui_info = LAUNCH_INFO.get("Virtui 3 - Amazon")
                        if virtui_info and virtui_info.get('hwnd') and virtui_info.get('frame'):
                            hwnd = virtui_info['hwnd']
                            frame = virtui_info['frame']
                            
                            # Check if window still exists
                            if not win32gui.IsWindow(hwnd):
                                continue
                            
                            # Get current state
                            try:
                                current_parent = win32gui.GetParent(hwnd)
                                current_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                                target_parent = frame.winfo_id()
                                
                                # Check for embedding violations
                                needs_reembed = False
                                violation_reason = ""
                                
                                if current_parent != target_parent:
                                    needs_reembed = True
                                    violation_reason = f"Parent mismatch: {current_parent} != {target_parent}"
                                
                                if not (current_style & win32con.WS_CHILD):
                                    needs_reembed = True
                                    violation_reason += f" Missing WS_CHILD style: {current_style}"
                                
                                # Check if VirtUI3 is trying to be visible outside its frame
                                if win32gui.IsWindowVisible(hwnd):
                                    try:
                                        vx, vy, vx2, vy2 = win32gui.GetWindowRect(hwnd)
                                        frame.update_idletasks()
                                        fx = frame.winfo_rootx()
                                        fy = frame.winfo_rooty()
                                        
                                        # Allow some tolerance for positioning
                                        if abs(vx - fx) > 20 or abs(vy - fy) > 20:
                                            needs_reembed = True
                                            violation_reason += f" Position violation: window({vx},{vy}) vs frame({fx},{fy})"
                                    except Exception:
                                        pass
                                
                                # IMMEDIATE re-embedding if any violation detected
                                if needs_reembed:
                                    print(f"GUARDIAN RE-EMBEDDING VirtUI3: {violation_reason}")
                                    
                                    # Get frame dimensions
                                    frame.update_idletasks()
                                    fw = frame.winfo_width()
                                    fh = frame.winfo_height()
                                    if fw <= 1 or fh <= 1:
                                        fw = 1920
                                        fh = 120
                                    
                                    # Force re-embed immediately
                                    embed_window(hwnd, target_parent, 0, 0, fw, fh)
                                    print(f"Guardian enforced VirtUI3 embedding: {fw}x{fh}")
                                    
                                    # Double-check after a brief delay
                                    def double_check_embed():
                                        time.sleep(0.1)
                                        try:
                                            new_parent = win32gui.GetParent(hwnd)
                                            new_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                                            if new_parent != target_parent or not (new_style & win32con.WS_CHILD):
                                                print("Guardian double-check: Re-embedding VirtUI3 again")
                                                embed_window(hwnd, target_parent, 0, 0, fw, fh)
                                        except Exception as e:
                                            print(f"Error in guardian double-check: {e}")
                                    
                                    threading.Thread(target=double_check_embed, daemon=True).start()
                                    
                            except Exception as e:
                                print(f"Error checking VirtUI3 embedding state: {e}")
                                
                    except Exception as e:
                        print(f"Error in VirtUI3 embedding enforcement: {e}")
                        
                except Exception as e:
                    print(f"Error in simplified guardian: {e}")
        finally:
            GUARDIAN_RUNNING = False
            print("Simplified VirtUI3 Guardian stopped")
                
    # Start the guardian thread
    guardian_thread = threading.Thread(target=guardian_loop, daemon=True)
    guardian_thread.start()
    print("VirtUI3 State Guardian started - continuous monitoring active")

def start_barcode_state_guardian():
    """Continuously monitor and enforce barcode embedding and overlay states."""
    global GLOBAL_BARCODE_OVERLAY, BARCODE_OVERLAY_SHOW_FUNCTION, BARCODE_GUARDIAN_RUNNING
    
    # Prevent multiple guardian instances
    if BARCODE_GUARDIAN_RUNNING:
        print("Barcode State Guardian already running, skipping duplicate start")
        return
    
    BARCODE_GUARDIAN_RUNNING = True
    
    def barcode_guardian_loop():
        global BARCODE_GUARDIAN_RUNNING, PASSWORD_DIALOG_OPEN
        try:
            while BARCODE_GUARDIAN_RUNNING:
                try:
                    time.sleep(0.3)  # Check 3 times per second to reduce flashing
                    
                    # Skip if loading or password dialog is open
                    if loading_in_progress or PASSWORD_DIALOG_OPEN:
                        continue
                    
                    # FORCE BARCODE OVERLAY TO BE VISIBLE AND ON TOP - NO EXCEPTIONS
                    try:
                        if GLOBAL_BARCODE_OVERLAY:
                            barcode_blocker = GLOBAL_BARCODE_OVERLAY.get('blocker')
                            
                            # Force barcode blocker window visible
                            if barcode_blocker and barcode_blocker.winfo_exists():
                                if not barcode_blocker.winfo_viewable():
                                    print("FORCING barcode blocker visible")
                                    barcode_blocker.deiconify()
                                    barcode_blocker.wm_attributes('-topmost', True)
                                    barcode_blocker.wm_attributes('-alpha', 0.01)  # Maintain transparency
                            
                            # Force barcode overlay positioning
                            try:
                                # Check if custom size is active
                                custom_size = GLOBAL_BARCODE_OVERLAY.get('custom_size') if GLOBAL_BARCODE_OVERLAY else None
                                
                                if custom_size and custom_size.get('active'):
                                    # Use custom positioning - don't override user settings
                                    if barcode_blocker and barcode_blocker.winfo_exists():
                                        # Get custom values, but handle None by getting frame values
                                        barcode_info = LAUNCH_INFO.get("Bar-Code")
                                        
                                        # Get current frame values for None substitution
                                        frame_x, frame_y, frame_w, frame_h = 0, 120, 1920, 960  # defaults for barcode area
                                        if barcode_info and barcode_info.get('frame'):
                                            try:
                                                frame = barcode_info['frame']
                                                frame.update_idletasks()
                                                frame_x = frame.winfo_rootx()
                                                frame_y = frame.winfo_rooty()
                                                frame_w = frame.winfo_width() if frame.winfo_width() > 1 else 1920
                                                frame_h = frame.winfo_height() if frame.winfo_height() > 1 else 960
                                            except Exception:
                                                pass
                                        
                                        # Use custom values if not None, otherwise use frame values
                                        w = custom_size.get('width')
                                        h = custom_size.get('height') 
                                        x = custom_size.get('x')
                                        y = custom_size.get('y')
                                        
                                        # Replace None values with frame values
                                        w = int(w) if w is not None else frame_w
                                        h = int(h) if h is not None else frame_h
                                        x = int(x) if x is not None else frame_x
                                        y = int(y) if y is not None else frame_y
                                        
                                        barcode_blocker.geometry(f"{w}x{h}+{x}+{y}")
                                       # print(f"Barcode Guardian: maintaining custom overlay size {w}x{h} at ({x},{y})")
                                else:
                                    # Standard Bar-Code frame-based positioning
                                    barcode_info = LAUNCH_INFO.get("Bar-Code")
                                    if barcode_info and barcode_info.get('frame'):
                                        frame = barcode_info['frame']
                                        frame.update_idletasks()
                                        x = frame.winfo_rootx()
                                        y = frame.winfo_rooty()
                                        w = frame.winfo_width()
                                        h = frame.winfo_height()
                                        
                                        if w > 1 and h > 1:
                                            # Position barcode blocker to cover entire frame
                                            if barcode_blocker and barcode_blocker.winfo_exists():
                                                barcode_blocker.geometry(f"{w}x{h}+{x}+{y}")
                                        else:
                                            # Fallback positioning for barcode area
                                            if barcode_blocker and barcode_blocker.winfo_exists():
                                                barcode_blocker.geometry("1920x960+0+120")
                                    else:
                                        # Fallback if frame not accessible
                                        if barcode_blocker and barcode_blocker.winfo_exists():
                                            barcode_blocker.geometry("1920x960+0+120")
                            except Exception as e:
                                print(f"Error positioning barcode overlay: {e}")
                                # Emergency fallback
                                if barcode_blocker and barcode_blocker.winfo_exists():
                                    barcode_blocker.geometry("1920x960+0+120")
                            
                            # REDUCED TOPMOST ENFORCEMENT - avoid constant toggling
                            if barcode_blocker and barcode_blocker.winfo_exists():
                                barcode_blocker.wm_attributes('-topmost', True)  # Direct set instead of toggle
                            
                            # Try Windows API enforcement less frequently to reduce flashing
                            try:
                                import ctypes
                                # Only do Windows API enforcement every 3rd cycle (once per second)
                                cycle_counter = getattr(barcode_guardian_loop, 'cycle_counter', 0) + 1
                                barcode_guardian_loop.cycle_counter = cycle_counter
                                
                                if cycle_counter % 3 == 0:  # Every 3rd cycle
                                    if barcode_blocker and barcode_blocker.winfo_exists():
                                        barcode_blocker_hwnd = int(barcode_blocker.winfo_id())
                                        ctypes.windll.user32.SetWindowPos(
                                            barcode_blocker_hwnd, -1,  # HWND_TOPMOST
                                            0, 0, 0, 0,
                                            0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
                                        )
                            except Exception:
                                pass
                                
                    except Exception as e:
                        print(f"Error in barcode overlay enforcement: {e}")
                    
                    # AGGRESSIVE BARCODE EMBEDDING ENFORCEMENT
                    try:
                        barcode_info = LAUNCH_INFO.get("Bar-Code")
                        if barcode_info and barcode_info.get('hwnd') and barcode_info.get('frame'):
                            hwnd = barcode_info['hwnd']
                            frame = barcode_info['frame']
                            
                            # Check if window still exists
                            if not win32gui.IsWindow(hwnd):
                                continue
                            
                            # Get current state
                            try:
                                current_parent = win32gui.GetParent(hwnd)
                                current_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                                target_parent = frame.winfo_id()
                                
                                # Check for embedding violations
                                needs_reembed = False
                                violation_reason = ""
                                
                                if current_parent != target_parent:
                                    needs_reembed = True
                                    violation_reason = f"Parent mismatch: {current_parent} != {target_parent}"
                                
                                if not (current_style & win32con.WS_CHILD):
                                    needs_reembed = True
                                    violation_reason += f" Missing WS_CHILD style: {current_style}"
                                
                                # Check if Bar-Code is trying to be visible outside its frame
                                if win32gui.IsWindowVisible(hwnd):
                                    try:
                                        bx, by, bx2, by2 = win32gui.GetWindowRect(hwnd)
                                        frame.update_idletasks()
                                        fx = frame.winfo_rootx()
                                        fy = frame.winfo_rooty()
                                        
                                        # Allow some tolerance for positioning
                                        if abs(bx - fx) > 20 or abs(by - fy) > 20:
                                            needs_reembed = True
                                            violation_reason += f" Position violation: window({bx},{by}) vs frame({fx},{fy})"
                                    except Exception:
                                        pass
                                
                                # IMMEDIATE re-embedding if any violation detected
                                if needs_reembed:
                                    print(f"BARCODE GUARDIAN RE-EMBEDDING Bar-Code: {violation_reason}")
                                    
                                    # Get frame dimensions
                                    frame.update_idletasks()
                                    fw = frame.winfo_width()
                                    fh = frame.winfo_height()
                                    if fw <= 1 or fh <= 1:
                                        fw = 1920
                                        fh = 960
                                    
                                    # Force re-embed immediately
                                    embed_window(hwnd, target_parent, 0, 0, fw, fh)
                                    print(f"Barcode Guardian enforced Bar-Code embedding: {fw}x{fh}")
                                    
                                    # Double-check after a brief delay
                                    def double_check_barcode_embed():
                                        time.sleep(0.1)
                                        try:
                                            new_parent = win32gui.GetParent(hwnd)
                                            new_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                                            if new_parent != target_parent or not (new_style & win32con.WS_CHILD):
                                                print("Barcode Guardian double-check: Re-embedding Bar-Code again")
                                                embed_window(hwnd, target_parent, 0, 0, fw, fh)
                                        except Exception as e:
                                            print(f"Error in barcode guardian double-check: {e}")
                                    
                                    threading.Thread(target=double_check_barcode_embed, daemon=True).start()
                                    
                            except Exception as e:
                                print(f"Error checking Bar-Code embedding state: {e}")
                                
                    except Exception as e:
                        print(f"Error in Bar-Code embedding enforcement: {e}")
                        
                except Exception as e:
                    print(f"Error in barcode guardian: {e}")
        finally:
            BARCODE_GUARDIAN_RUNNING = False
            print("Barcode State Guardian stopped")
                
    # Start the barcode guardian thread
    barcode_guardian_thread = threading.Thread(target=barcode_guardian_loop, daemon=True)
    barcode_guardian_thread.start()
    print("Barcode State Guardian started - continuous monitoring active")

def monitor_process_health(pid, exe_path, custom_title, frame, restart_delay=3):
    """Monitor if a process is still running and restart it if it exits unexpectedly."""
    
    def is_process_running(pid):
        """Check if a process with the given PID is still running."""
        try:
            import psutil
            return psutil.pid_exists(pid)
        except ImportError:
            # Fallback method using Windows API
            try:
                import ctypes
                PROCESS_QUERY_INFORMATION = 0x0400
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, int(pid))
                if handle:
                    # Get exit code
                    exit_code = ctypes.c_ulong()
                    result = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                    ctypes.windll.kernel32.CloseHandle(handle)
                    # STILL_ACTIVE = 259
                    return result and exit_code.value == 259
                return False
            except Exception:
                return False
    
    def monitor_loop():
        global loading_in_progress, auto_reload_triggered  # Declare globals here
        nonlocal pid
        check_interval = 2  # Check every 2 seconds
        monitor_start_time = time.time()  # Track when this monitor started
        
        while True:
            try:
                time.sleep(check_interval)
                
                # Skip monitoring if we're in a loading state or auto-reload already triggered
                if loading_in_progress or auto_reload_triggered:
                    continue
                
                # Check if this PID is still in our tracking set (if not, this is a stale monitor)
                if pid not in STARTED_PIDS:
                    print(f"Monitor for PID {pid} ('{custom_title}') is stale, exiting")
                    return
                
                # Check if process is still running
                if not is_process_running(pid):
                    # Only trigger reload if this monitor has been running for at least 10 seconds
                    # This prevents old monitors from triggering reloads for processes we just terminated
                    if time.time() - monitor_start_time < 10:
                        print(f"Process {pid} for '{custom_title}' exited too soon after monitor start, likely from reload. Exiting monitor.")
                        return
                    
                    # Process has exited unexpectedly
                    print(f"Process {pid} for '{custom_title}' has exited. Checking if reload needed...")
                    
                    # Set flag to prevent other monitors from also triggering reload
                    if auto_reload_triggered:
                        print(f"Auto-reload already triggered by another monitor, exiting monitor for '{custom_title}'")
                        return
                    
                    auto_reload_triggered = True
                    loading_in_progress = True
                    
                    set_status(f"'{custom_title}' has exited. Triggering full reload...")
                    print(f"Process {pid} for '{custom_title}' has exited. Triggering full reload...")
                    
                    try:
                        # Wait a moment before reloading
                        time.sleep(restart_delay)
                        
                        # Trigger a full reload by terminating all processes and restarting
                        # Terminate all known PIDs
                        for old_pid in list(STARTED_PIDS):
                            try:
                                # Open process and terminate cleanly if possible
                                PROCESS_TERMINATE = 1
                                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, int(old_pid))
                                if handle:
                                    ctypes.windll.kernel32.TerminateProcess(handle, 0)
                                    ctypes.windll.kernel32.CloseHandle(handle)
                            except Exception:
                                try:
                                    # Fallback to os.kill
                                    import os
                                    os.kill(int(old_pid), 9)
                                except Exception:
                                    pass
                        
                        # Clear the PID tracking
                        STARTED_PIDS.clear()
                        
                        # Small pause to allow processes to terminate
                        time.sleep(0.5)
                        
                        # Ensure LaunchWithMiniIndicator is set to True for normal embedded mode
                        try:
                            update_launch_with_mini_indicator(CLIENT_SETTINGS_PATH, True)
                            print("Set LaunchWithMiniIndicator to True for normal mode during auto-reload")
                            time.sleep(0.3)  # Allow time for settings to be written
                        except Exception as e:
                            print(f"Error setting LaunchWithMiniIndicator during auto-reload: {e}")
                        
                        # Restore frame sizes before restarting programs
                        try:
                            # Find the frame references from CURRENT_LAUNCHES
                            top_frame_ref = None
                            bottom_frame_ref = None
                            
                            for exe, title, frm in CURRENT_LAUNCHES:
                                if 'virtui' in title.lower():
                                    top_frame_ref = frm
                                elif 'bar-code' in title.lower() or 'barcode' in title.lower():
                                    bottom_frame_ref = frm
                            
                            # Restore standard frame sizes
                            if top_frame_ref:
                                try:
                                    top_frame_ref.configure(height=120)  # TOP_SLIVER_PX equivalent
                                    top_frame_ref.pack_configure(side='top', fill='x')
                                    print("Restored top frame to 120px height")
                                except Exception as e:
                                    print(f"Error restoring top frame: {e}")
                            
                            if bottom_frame_ref:
                                try:
                                    bottom_frame_ref.pack_configure(side='top', fill='both', expand=True)
                                    print("Restored bottom frame to fill remaining space")
                                except Exception as e:
                                    print(f"Error restoring bottom frame: {e}")
                            
                            # Small delay for layout to apply
                            time.sleep(0.2)
                            
                        except Exception as e:
                            print(f"Error during frame restoration in auto-reload: {e}")
                        
                        # Reset calibration mode and UI state to normal
                        try:
                            global calibration_mode
                            calibration_mode = False
                            
                            # Re-enable Windows taskbar protection for normal mode
                            enable_windows_taskbar()
                            
                            # Enable overlays for normal mode
                            enable_all_overlays()
                            
                            print("Reset calibration mode and UI state to normal during auto-reload")
                        except Exception as e:
                            print(f"Error resetting calibration mode during auto-reload: {e}")
                        
                        # Restart all configured launches
                        for exe, title, frm in list(CURRENT_LAUNCHES):
                            try:
                                threading.Thread(target=launch_and_embed, args=(exe, title, frm), daemon=True).start()
                            except Exception:
                                pass
                        
                        set_status(f"Full reload completed after '{custom_title}' exit")
                        print(f"Full reload completed after '{custom_title}' exit")
                        
                        # Reset flags after successful reload
                        def reset_flags():
                            time.sleep(30)  # Wait longer for processes to fully start and stabilize
                            global auto_reload_triggered, loading_in_progress
                            auto_reload_triggered = False
                            loading_in_progress = False
                            print("Auto-reload flags reset, monitoring can resume")
                        
                        threading.Thread(target=reset_flags, daemon=True).start()
                        
                        # Exit this monitor since new ones will be started for all processes
                        return
                        
                    except Exception as e:
                        auto_reload_triggered = False
                        loading_in_progress = False
                        set_status(f"Failed to reload after '{custom_title}' exit: {str(e)}")
                        print(f"Failed to reload after '{custom_title}' exit: {e}")
                        return
                        
            except Exception as e:
                print(f"Error in process monitor for '{custom_title}': {e}")
                time.sleep(check_interval)
    
    # Start monitoring in a separate thread
    threading.Thread(target=monitor_loop, daemon=True).start()

def launch_and_embed(exe_path, custom_title, frame):
    global loading_in_progress
    loading_in_progress = True  # Set loading flag
    
    set_status(f"Starting '{custom_title}'")
    print(f"Launching: {exe_path}")
    pid = start_program(exe_path)
    try:
        # remember the started pid for reload/terminate operations
        if pid:
            STARTED_PIDS.add(pid)
    except Exception:
        pass
    print(f"Started process PID: {pid}")
    hwnd = wait_for_window_by_pid(pid, timeout=60)
    if hwnd:
        set_status(f"Embedding '{custom_title}'")
        print(f"Embedding window {hwnd} for '{custom_title}'")
        set_window_title(hwnd, custom_title)
        # Ensure the Toplevel/frame is realized and measured. Wait until frame has non-zero size.
        frame.update_idletasks()
        # Wait up to a few seconds for layout to happen
        wait_start = time.time()
        w = frame.winfo_width()
        h = frame.winfo_height()
        while (w == 1 or h == 1 or w == 0 or h == 0) and time.time() - wait_start < 5:
            time.sleep(0.05)
            frame.update_idletasks()
            w = frame.winfo_width()
            h = frame.winfo_height()

        parent_hwnd = frame.winfo_id()

        # Query the child app's current outer size. If the frame is smaller than
        # the app (e.g. the top sliver), prefer to keep the app's native size and
        # let the frame clip it instead of stretching — this preserves aspect and
        # avoids visual distortion. If the frame is large (barcode area), fill it.
        try:
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            child_w = max(1, r - l)
            child_h = max(1, b - t)
        except Exception:
            child_w = None
            child_h = None

        frame_w = w
        frame_h = h
        # Fallbacks
        if frame_w == 0 or frame_h == 0:
            frame_w = frame.winfo_screenwidth()
            frame_h = frame.winfo_screenheight()

        # Barcode app should always fill the frame (avoid clipping/stretched visuals)
        if 'barcode' in custom_title.lower() or custom_title.lower().startswith('bar-code'):
            width = frame_w
            height = frame_h
            x = 0
            y = 0
        else:
            # If the app is taller than the frame (top sliver), don't force it to shrink;
            # embed at native size so it is clipped instead of distorted. Otherwise fill.
            if child_w and child_h and child_h > frame_h:
                width = child_w
                height = child_h
                x = 0
                y = 0
            else:
                width = frame_w
                height = frame_h
                x = 0
                y = 0

        embed_window(hwnd, parent_hwnd, x, y, width, height)
        set_status(f"Embedded '{custom_title}'")
        print(f"Embedded '{custom_title}' in launcher.")
        # Start a monitor thread that ensures the app stays embedded.
        def monitor_and_reembed(pid, parent_hwnd, frame, custom_title, interval=1):
            missed = 0
            while True:
                time.sleep(interval)
                hwnds = get_hwnds_for_pid(pid)
                if not hwnds:
                    missed += 1
                    # If no window for a while, assume process exited and stop monitoring
                    if missed > 6:
                        return
                    continue
                missed = 0
                # pick the main candidate window(s) and ensure embedding
                for candidate in hwnds:
                    try:
                        parent = win32gui.GetParent(candidate)
                        style = win32gui.GetWindowLong(candidate, win32con.GWL_STYLE)
                        needs_reparent = (parent != parent_hwnd) or not (style & win32con.WS_CHILD)
                    except Exception:
                        needs_reparent = True
                    if needs_reparent:
                        set_status(f"Re-embedding '{custom_title}'")
                        print(f"Re-embedding window {candidate} for '{custom_title}' (monitor)")
                        # Update size and re-embed
                        try:
                            frame.update_idletasks()
                            # Determine target size like initial embed: prefer native child size
                            # if the child is taller than the frame (so we don't shrink it).
                            fw = frame.winfo_width()
                            fh = frame.winfo_height()
                            if fw == 0 or fh == 0:
                                fw = frame.winfo_screenwidth()
                                fh = frame.winfo_screenheight()
                            try:
                                l, t, r, b = win32gui.GetWindowRect(candidate)
                                child_w = max(1, r - l)
                                child_h = max(1, b - t)
                            except Exception:
                                child_w = None
                                child_h = None

                            if child_w and child_h and child_h > fh:
                                tw = child_w
                                th = child_h
                            else:
                                tw = fw
                                th = fh

                            set_window_title(candidate, custom_title)
                            embed_window(candidate, parent_hwnd, 0, 0, tw, th)
                            
                            # If this is VirtUI3, trigger overlay repositioning
                            if 'virtui' in custom_title.lower():
                                print(f"VirtUI3 re-embedded, scheduling overlay refresh")
                                # Small delay to let embedding settle, then refresh overlay
                                set_overlay_custom("auto", 25, "auto", "auto")
                                
                                def refresh_overlay():
                                    time.sleep(0.2)
                                    if OVERLAY_SHOW_FUNCTION and not calibration_mode:
                                        try:
                                            OVERLAY_SHOW_FUNCTION()
                                        except Exception as e:
                                            print(f"Error refreshing overlay after re-embed: {e}")
                                threading.Thread(target=refresh_overlay, daemon=True).start()
                                
                        except Exception as e:
                            set_status(f"Monitor failed to re-embed '{custom_title}'")
                            print(f"Monitor failed to re-embed: {e}")
                        break

        threading.Thread(target=monitor_and_reembed, args=(pid, parent_hwnd, frame, custom_title), daemon=True).start()
        # If this is the barcode app, start a periodic focus attempt that doesn't raise.
        if custom_title.lower().startswith('bar-code') or 'barcode' in custom_title.lower():
            def periodic_focus(pid, interval=5):
                while True:
                    time.sleep(interval)
                    hwnds = get_hwnds_for_pid(pid)
                    for h in hwnds:
                        try:
                            focus_window_no_raise(h)
                        except Exception:
                            pass

            threading.Thread(target=periodic_focus, args=(pid, 5), daemon=True).start()
        # If this is VirtUi3, enforce its position inside the top sliver so users can't move it.
        if 'virtui' in custom_title.lower() or 'virtui3' in custom_title.lower():
            def start_enforcer(pid, parent_hwnd, interval=0.25):
                """Continuously find the main window for pid and snap it to the parent's origin.
                This handles cases where the app recreates its window (new hwnd) or resets position.
                """
                user32 = ctypes.windll.user32
                while True:
                    try:
                        time.sleep(interval)
                        hwnds = get_hwnds_for_pid(pid)
                        if not hwnds:
                            continue
                        # pick largest window as the main window
                        best = None
                        best_area = 0
                        for h in hwnds:
                            try:
                                l, t, r, b = win32gui.GetWindowRect(h)
                                area = max(0, r - l) * max(0, b - t)
                                if area > best_area:
                                    best_area = area
                                    best = h
                            except Exception:
                                continue
                        if not best:
                            continue
                        # compute desired screen coords from parent
                        try:
                            pl, pt, pr, pb = win32gui.GetWindowRect(parent_hwnd)
                            desired_x = pl
                            desired_y = pt
                            # get current rect of the child
                            l, t, r, b = win32gui.GetWindowRect(best)
                            if l != desired_x or t != desired_y:
                                # Move window back without changing z-order or size
                                user32.SetWindowPos(best, 0, desired_x, desired_y, 0, 0,
                                                     win32con.SWP_NOZORDER | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                        except Exception:
                            # ignore transient errors and keep monitoring
                            continue
                    except Exception:
                        # outer loop protection
                        time.sleep(interval)

            threading.Thread(target=start_enforcer, args=(pid, parent_hwnd), daemon=True).start()
    else:
        print(f"Could not find window for PID {pid}")
        messagebox.showerror("Error", f"Could not find window for '{custom_title}'. Please check the program.")
    
    # record last-known info for this custom_title (best-effort)
    try:
        LAUNCH_INFO[custom_title] = {'pid': pid, 'hwnd': hwnd if 'hwnd' in locals() else None, 'parent_hwnd': frame.winfo_id(), 'frame': frame}
    except Exception:
        pass
    
    # Start process health monitoring for this application
    if pid:
        monitor_process_health(pid, exe_path, custom_title, frame)
    
    # Final reparenting check for VirtUI3 after monitoring starts
    if 'virtui' in custom_title.lower() or 'virtui3' in custom_title.lower():
        def final_virtui_reparent():
            time.sleep(3)  # Wait for monitoring to fully establish
            try:
                hwnds = get_hwnds_for_pid(pid)
                if hwnds:
                    # Find the best window (largest area)
                    best = None
                    best_area = 0
                    for h in hwnds:
                        try:
                            l, t, r, b = win32gui.GetWindowRect(h)
                            area = max(0, r - l) * max(0, b - t)
                            if area > best_area:
                                best_area = area
                                best = h
                        except Exception:
                            continue
                    
                    if best:
                        parent_hwnd = frame.winfo_id()
                        print(f"Final reparenting check for VirtUI3 window {best}")
                        
                        # Check if it's properly parented
                        try:
                            current_parent = win32gui.GetParent(best)
                            style = win32gui.GetWindowLong(best, win32con.GWL_STYLE)
                            needs_reparent = (current_parent != parent_hwnd) or not (style & win32con.WS_CHILD)
                            
                            if needs_reparent:
                                print(f"Re-embedding VirtUI3 window {best} in final check")
                                # Get frame dimensions
                                frame.update_idletasks()
                                fw = frame.winfo_width()
                                fh = frame.winfo_height()
                                if fw == 0 or fh == 0:
                                    fw = frame.winfo_screenwidth() 
                                    fh = 120  # Default top frame height
                                
                                # Re-embed the window
                                embed_window(best, parent_hwnd, 0, 0, fw, fh)
                                set_status(f"Final reparenting completed for '{custom_title}'")
                                # Activate overlay now that VirtUI3 is properly embedded
                                threading.Timer(1.0, activate_virtui_overlay_when_ready).start()
                                # Start continuous re-embedding first (most aggressive)
                                threading.Timer(1.5, start_continuous_virtui_reembedding).start()
                                # Start continuous state guardian for VirtUI3
                                threading.Timer(2.0, start_virtui_state_guardian).start()
                                # Set up Windows event hooks for ultimate overlay enforcement
                                threading.Timer(3.0, setup_virtui_window_event_hook).start()
                            else:
                                print(f"VirtUI3 window {best} already properly parented")
                                # Activate overlay since VirtUI3 is confirmed embedded
                                threading.Timer(0.5, activate_virtui_overlay_when_ready).start()
                                # Start continuous re-embedding first (most aggressive)
                                threading.Timer(0.8, start_continuous_virtui_reembedding).start()
                                # Start continuous state guardian for VirtUI3
                                threading.Timer(1.0, start_virtui_state_guardian).start()
                                # Set up Windows event hooks for ultimate overlay enforcement
                                threading.Timer(2.0, setup_virtui_window_event_hook).start()
                        except Exception as e:
                            print(f"Error in final VirtUI3 reparenting check: {e}")
            except Exception as e:
                print(f"Error in final VirtUI3 reparenting: {e}")
        
        threading.Thread(target=final_virtui_reparent, daemon=True).start()
    
    # If this is a barcode program, start barcode guardian and overlay
    if 'barcode' in custom_title.lower() or custom_title.lower().startswith('bar-code'):
        def activate_barcode_overlay_and_guardian():
            try:
                # Activate barcode overlay after brief delay
                if BARCODE_OVERLAY_SHOW_FUNCTION:
                    BARCODE_OVERLAY_SHOW_FUNCTION()
                    print("Barcode overlay activated after successful embedding")
                
                # Start barcode state guardian
                start_barcode_state_guardian()
                print("Barcode guardian started for Bar-Code program")
            except Exception as e:
                print(f"Error activating barcode overlay and guardian: {e}")
        
        threading.Timer(1.0, activate_barcode_overlay_and_guardian).start()
    
    # Clear loading flag
    loading_in_progress = False

def main():

    exe_path1 = r"C:\\Program Files (x86)\\Rice Lake Weighing Systems\\VIRTUi3\\Client.exe"
    exe_path2 = r"C:\\Program Files (x86)\\Rice Lake Weighing Systems\\SZ3690438\\Client.exe"
    custom_title1 = "Virtui 3 - Amazon"
    custom_title2 = "Bar-Code"

    # Check if the executables exist, otherwise prompt user to locate them
    if not os.path.isfile(exe_path1):
        messagebox.showinfo("Locate Program", f"Could not find {exe_path1}. Please locate the Virtui 3 - Amazon executable.")
        exe_path1 = filedialog.askopenfilename(title="Select Virtui 3 - Amazon executable", filetypes=[("Executable files", "*.exe")])
        if not exe_path1:
            messagebox.showerror("Error", "Virtui 3 - Amazon executable not selected. Exiting.")
            return
    if not os.path.isfile(exe_path2):
        messagebox.showinfo("Locate Program", f"Could not find {exe_path2}. Please locate the Bar-Code executable.")
        exe_path2 = filedialog.askopenfilename(title="Select Bar-Code executable", filetypes=[("Executable files", "*.exe")])
        if not exe_path2:
            messagebox.showerror("Error", "Bar-Code executable not selected. Exiting.")
            return

    # Control file (optional). If present, use it to replace the user's settings when they differ.
    control_settings_path = os.path.expanduser(r"~\\AppData\\Roaming\\Rice Lake Weighing Systems\\VIRTUi3\\settings\\ClientSettingsData.control.json")
    try:
        replaced = compare_and_replace_with_control(control_settings_path, CLIENT_SETTINGS_PATH)
        if replaced:
            set_status('Replaced client settings from control file')
    except Exception:
        pass

    # Ensure LaunchWithMiniIndicator is true for any blank/false entries; if we changed settings, we will reload children later.
    try:
        changed = ensure_launch_with_mini_true(CLIENT_SETTINGS_PATH)
        if changed:
            set_status('Updated LaunchWithMiniIndicator to true in settings')
    except Exception:
        changed = False

    root = tk.Tk()
    root.title("Lift Operator Launcher")
    # Keep the root as the Tk master but don't show it — we'll use two Toplevels
    # to host each program so they appear as isolated windows in their normal sizes.
    root.attributes('-topmost', True)
    root.protocol("WM_DELETE_WINDOW", disable_event)

    # Block all keypresses except Ctrl+C. This prevents user input in the
    # launcher UI; note that embedded child windows (external programs)
    # may still receive keyboard events unless those windows are also
    # explicitly handled at the OS level.
    def _key_blocker(event):
        try:
            # Control mask is usually bit 2 (0x4) in Tk event.state
            ctrl_pressed = (event.state & 0x4) != 0
        except Exception:
            ctrl_pressed = False
        keysym = getattr(event, 'keysym', '')
        # Allow Ctrl+C explicitly
        if ctrl_pressed and keysym.lower() == 'c':
            return None
        # Block everything else
        return "break"

    # Bind globally so keys don't reach widgets. Add the binding to catch all Key events.
    root.bind_all('<Key>', _key_blocker, add=True)
    # Also ensure Alt+F4 is blocked
    root.bind_all('<Alt-F4>', lambda e: 'break', add=True)

    # Optional: Hide the taskbar (Windows only)
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    except Exception:
        pass

    # Create a single fullscreen, topmost Toplevel and stack two frames vertically.
    # The top frame will be a small sliver for VirtUi3 and the bottom frame will
    # hold the barcode app filling the rest of the screen.
    TOP_SLIVER_PX = 120  # small sliver height for VirtUi3; change if needed

    container = tk.Toplevel(root)
    container.title("Launcher Container")
    container.attributes('-fullscreen', True)
    container.attributes('-topmost', True)
    container.protocol("WM_DELETE_WINDOW", disable_event)

    # Top small frame (virtui3)
    top_frame = tk.Frame(container, bg='black', height=TOP_SLIVER_PX)
    top_frame.pack(side='top', fill='x')

    # Bottom frame (barcode) fills the rest
    bottom_frame = tk.Frame(container, bg='gray')
    bottom_frame.pack(side='top', fill='both', expand=True)
    # Taskbar: a small visible bar under the barcode frame with controls
    TASKBAR_HEIGHT = 40
    taskbar = tk.Frame(container, bg='#222222', height=TASKBAR_HEIGHT)
    taskbar.pack(side='bottom', fill='x')

    # Password for exiting the launcher. Change to a secure value as needed.
    EXIT_PASSWORD = "9171"

    # Hide the root window so only the container is visible.
    root.withdraw()

    # Create VirtUI3 protection overlay - transparent blocker only
    def create_virtui_overlay():
        try:
            # Pure transparent blocker window (no visible elements)
            blocker = tk.Toplevel()
            blocker.overrideredirect(True)  # No title bar or decorations
            blocker.configure(bg='gray')  # Any color - will be transparent with alpha
            blocker.withdraw()  # Start hidden until VirtUI3 is properly embedded
            
            # Make it transparent using alpha but still capture clicks
            blocker.wm_attributes('-topmost', True)
            blocker.wm_attributes('-alpha', 0.01)  # Almost fully transparent but still captures events
            
            # Make the entire blocker capture all clicks
            def block_click(event):
                global PASSWORD_DIALOG_OPEN
                # Allow clicks through if password dialog is open
                if PASSWORD_DIALOG_OPEN:
                    print("Click allowed through - password dialog is open")
                    return  # Don't return "break" to allow event to pass through
                print("Click blocked by transparent blocker")
                return "break"
            
            # Bind all mouse events to the blocker window itself
            blocker.bind("<Button-1>", block_click)
            blocker.bind("<Button-2>", block_click) 
            blocker.bind("<Button-3>", block_click)
            blocker.bind("<Double-Button-1>", block_click)
            # NOTE: Motion events removed to prevent hover interference
            blocker.focus_set()
            
            def update_overlay_position(custom_width=None, custom_height=None, custom_x=None, custom_y=None):
                try:
                    # Get VirtUI3 frame position and size from launch info
                    virtui_info = LAUNCH_INFO.get("Virtui 3 - Amazon")
                    if virtui_info and virtui_info.get('frame'):
                        frame = virtui_info['frame']
                        frame.update_idletasks()
                        frame_x = frame.winfo_rootx()
                        frame_y = frame.winfo_rooty()
                        frame_width = frame.winfo_width()
                        frame_height = frame.winfo_height()
                        
                        if frame_width > 1 and frame_height > 1:  # Valid dimensions
                            # Use custom dimensions if provided, otherwise use frame dimensions
                            x = custom_x if custom_x is not None else frame_x
                            y = custom_y if custom_y is not None else frame_y
                            width = custom_width if custom_width is not None else frame_width
                            height = custom_height if custom_height is not None else frame_height
                            
                            # Ensure all values are valid integers
                            width = int(width) if width is not None else frame_width
                            height = int(height) if height is not None else frame_height
                            x = int(x) if x is not None else frame_x
                            y = int(y) if y is not None else frame_y
                            
                            # Position blocker with specified dimensions
                            blocker.geometry(f"{width}x{height}+{x}+{y}")
                            print(f"Positioned transparent overlay: {width}x{height} at ({x},{y})")
                            return True
                        else:
                            # Fallback positioning with custom dimensions if provided
                            x = custom_x if custom_x is not None else 0
                            y = custom_y if custom_y is not None else 0
                            width = custom_width if custom_width is not None else 1920
                            height = custom_height if custom_height is not None else 120
                            
                            # Ensure all values are valid integers
                            width = int(width) if width is not None else 1920
                            height = int(height) if height is not None else 120
                            x = int(x) if x is not None else 0
                            y = int(y) if y is not None else 0
                            
                            blocker.geometry(f"{width}x{height}+{x}+{y}")
                            print(f"Fallback positioned transparent overlay: {width}x{height} at ({x},{y})")
                            return True
                    else:
                        # Fallback positioning with custom dimensions if provided
                        x = custom_x if custom_x is not None else 0
                        y = custom_y if custom_y is not None else 0
                        width = custom_width if custom_width is not None else 1920
                        height = custom_height if custom_height is not None else 120
                        
                        # Ensure all values are valid integers
                        width = int(width) if width is not None else 1920
                        height = int(height) if height is not None else 120
                        x = int(x) if x is not None else 0
                        y = int(y) if y is not None else 0
                        
                        blocker.geometry(f"{width}x{height}+{x}+{y}")
                        print(f"No VirtUI3 frame - positioned transparent overlay: {width}x{height} at ({x},{y})")
                        return True
                except Exception as e:
                    print(f"Error updating overlay position: {e}")
                    return False
                    return False
            
            def show_overlay_safely():
                try:
                    global PASSWORD_DIALOG_OPEN
                    # Don't show overlay if password dialog is open
                    if PASSWORD_DIALOG_OPEN:
                        print("VirtUI3 overlay hidden - password dialog is open")
                        if blocker.winfo_exists():
                            blocker.withdraw()
                        return
                    
                    # Show blocker window
                    if blocker.winfo_exists():
                        update_overlay_position()
                        blocker.deiconify()
                        blocker.wm_attributes('-topmost', True)
                        blocker.wm_attributes('-alpha', 0.01)  # Ensure transparency
                        print("Transparent blocker window shown")
                except Exception as e:
                    print(f"Error showing overlay safely: {e}")
            
            # Store windows for management
            overlay_system = {
                'blocker': blocker,
                'show_function': show_overlay_safely,
                'update_position': update_overlay_position  # Add reference to position function
            }
            
            # Add convenience function to set custom overlay size
            def set_custom_overlay_size(width=None, height=None, x=None, y=None):
                """Set custom dimensions for the transparent overlay independent of VirtUI3 frame.
                
                Args:
                    width: Custom width in pixels (None = use VirtUI3 frame width)
                    height: Custom height in pixels (None = use VirtUI3 frame height)  
                    x: Custom X position in pixels (None = use VirtUI3 frame X)
                    y: Custom Y position in pixels (None = use VirtUI3 frame Y)
                """
                try:
                    if blocker.winfo_exists():
                        # Store custom size in overlay system so Guardian respects it
                        overlay_system['custom_size'] = {
                            'width': width,
                            'height': height,
                            'x': x,
                            'y': y,
                            'active': True
                        }
                        
                        # Apply the custom size immediately
                        update_overlay_position(width, height, x, y)
                        
                        # Make sure overlay is visible and on top
                        blocker.deiconify()
                        blocker.wm_attributes('-topmost', True)
                        blocker.wm_attributes('-alpha', 0.01)
                        
                        print(f"Set custom overlay size: {width}x{height} at ({x},{y})")
                        return True
                    else:
                        print("Transparent overlay window does not exist")
                        return False
                except Exception as e:
                    print(f"Error setting custom overlay size: {e}")
                    return False
            
            # Function to reset to automatic VirtUI3 frame tracking
            def reset_to_auto_size():
                """Reset overlay to automatically track VirtUI3 frame size."""
                try:
                    # Clear custom size settings
                    overlay_system['custom_size'] = {'active': False}
                    
                    # Return to standard frame-based positioning
                    update_overlay_position()
                    
                    print("Reset overlay to automatic VirtUI3 frame tracking")
                    return True
                except Exception as e:
                    print(f"Error resetting to auto size: {e}")
                    return False
            
            # Add the convenience functions to the overlay system
            overlay_system['set_custom_size'] = set_custom_overlay_size
            overlay_system['reset_to_auto'] = reset_to_auto_size
            
            # Store reference to show function in a global variable for external access
            global OVERLAY_SHOW_FUNCTION
            OVERLAY_SHOW_FUNCTION = show_overlay_safely
            
            print("Created transparent blocker overlay (no buttons)")
            return overlay_system
            
        except Exception as e:
            print(f"Error creating VirtUI3 overlay system: {e}")
            return None
    
    # Create VirtUI3 overlay but don't show it yet - wait for embedding to complete
    virtui_overlay = create_virtui_overlay()
    
    # Make globally accessible
    global GLOBAL_VIRTUI_OVERLAY
    GLOBAL_VIRTUI_OVERLAY = virtui_overlay

    # Create Barcode protection overlay - transparent blocker for barcode area
    def create_barcode_overlay():
        try:
            # Pure transparent blocker window for barcode area (no visible elements)
            barcode_blocker = tk.Toplevel()
            barcode_blocker.overrideredirect(True)  # No title bar or decorations
            barcode_blocker.configure(bg='blue')  # Different color to distinguish from VirtUI3 overlay
            barcode_blocker.withdraw()  # Start hidden until Bar-Code is properly embedded
            
            # Make it transparent using alpha but still capture clicks
            barcode_blocker.wm_attributes('-topmost', True)
            barcode_blocker.wm_attributes('-alpha', 0.01)  # Almost fully transparent but still captures events
            
            # Make the entire blocker capture all clicks
            def block_barcode_click(event):
                global PASSWORD_DIALOG_OPEN
                # Allow clicks through if password dialog is open
                if PASSWORD_DIALOG_OPEN:
                    print("Click allowed through barcode blocker - password dialog is open")
                    return  # Don't return "break" to allow event to pass through
                print("Click blocked by transparent barcode blocker")
                return "break"
            
            # Bind all mouse events to the barcode blocker window itself
            barcode_blocker.bind("<Button-1>", block_barcode_click)
            barcode_blocker.bind("<Button-2>", block_barcode_click) 
            barcode_blocker.bind("<Button-3>", block_barcode_click)
            barcode_blocker.bind("<Double-Button-1>", block_barcode_click)
            # NOTE: Motion events removed to prevent hover interference
            barcode_blocker.focus_set()
            
            def update_barcode_overlay_position(custom_width=None, custom_height=None, custom_x=None, custom_y=None):
                try:
                    # Get Bar-Code frame position and size from launch info
                    barcode_info = LAUNCH_INFO.get("Bar-Code")
                    if barcode_info and barcode_info.get('frame'):
                        frame = barcode_info['frame']
                        frame.update_idletasks()
                        frame_x = frame.winfo_rootx()
                        frame_y = frame.winfo_rooty()
                        frame_width = frame.winfo_width()
                        frame_height = frame.winfo_height()
                        
                        if frame_width > 1 and frame_height > 1:  # Valid dimensions
                            # Use custom dimensions if provided, otherwise use frame dimensions
                            x = custom_x if custom_x is not None else frame_x
                            y = custom_y if custom_y is not None else frame_y
                            width = custom_width if custom_width is not None else frame_width
                            height = custom_height if custom_height is not None else frame_height
                            
                            # Ensure all values are valid integers
                            width = int(width) if width is not None else frame_width
                            height = int(height) if height is not None else frame_height
                            x = int(x) if x is not None else frame_x
                            y = int(y) if y is not None else frame_y
                            
                            # Position barcode blocker with specified dimensions
                            barcode_blocker.geometry(f"{width}x{height}+{x}+{y}")
                            print(f"Positioned transparent barcode overlay: {width}x{height} at ({x},{y})")
                            return True
                        else:
                            # Fallback positioning with custom dimensions if provided
                            x = custom_x if custom_x is not None else 0
                            y = custom_y if custom_y is not None else 120
                            width = custom_width if custom_width is not None else 1920
                            height = custom_height if custom_height is not None else 960
                            
                            # Ensure all values are valid integers
                            width = int(width) if width is not None else 1920
                            height = int(height) if height is not None else 960
                            x = int(x) if x is not None else 0
                            y = int(y) if y is not None else 120
                            
                            barcode_blocker.geometry(f"{width}x{height}+{x}+{y}")
                            print(f"Fallback positioned transparent barcode overlay: {width}x{height} at ({x},{y})")
                            return True
                    else:
                        # Fallback positioning with custom dimensions if provided (barcode area defaults)
                        x = custom_x if custom_x is not None else 0
                        y = custom_y if custom_y is not None else 120
                        width = custom_width if custom_width is not None else 1920
                        height = custom_height if custom_height is not None else 960
                        
                        # Ensure all values are valid integers
                        width = int(width) if width is not None else 1920
                        height = int(height) if height is not None else 960
                        x = int(x) if x is not None else 0
                        y = int(y) if y is not None else 120
                        
                        barcode_blocker.geometry(f"{width}x{height}+{x}+{y}")
                        print(f"No Bar-Code frame - positioned transparent barcode overlay: {width}x{height} at ({x},{y})")
                        return True
                except Exception as e:
                    print(f"Error updating barcode overlay position: {e}")
                    return False
            
            def show_barcode_overlay_safely():
                try:
                    global PASSWORD_DIALOG_OPEN
                    # Don't show barcode overlay if password dialog is open
                    if PASSWORD_DIALOG_OPEN:
                        print("Barcode overlay hidden - password dialog is open")
                        if barcode_blocker.winfo_exists():
                            barcode_blocker.withdraw()
                        return
                    
                    # Show barcode blocker window
                    if barcode_blocker.winfo_exists():
                        update_barcode_overlay_position()
                        barcode_blocker.deiconify()
                        barcode_blocker.wm_attributes('-topmost', True)
                        barcode_blocker.wm_attributes('-alpha', 0.01)  # Ensure transparency
                        print("Transparent barcode blocker window shown")
                except Exception as e:
                    print(f"Error showing barcode overlay safely: {e}")
            
            # Store windows for management
            barcode_overlay_system = {
                'blocker': barcode_blocker,
                'show_function': show_barcode_overlay_safely,
                'update_position': update_barcode_overlay_position
            }
            
            # Add convenience function to set custom barcode overlay size
            def set_custom_barcode_overlay_size(width=None, height=None, x=None, y=None):
                """Set custom dimensions for the transparent barcode overlay independent of Bar-Code frame.
                
                Args:
                    width: Custom width in pixels (None = use Bar-Code frame width)
                    height: Custom height in pixels (None = use Bar-Code frame height)  
                    x: Custom X position in pixels (None = use Bar-Code frame X)
                    y: Custom Y position in pixels (None = use Bar-Code frame Y)
                """
                try:
                    if barcode_blocker.winfo_exists():
                        # Store custom size in barcode overlay system so Guardian respects it
                        barcode_overlay_system['custom_size'] = {
                            'width': width,
                            'height': height,
                            'x': x,
                            'y': y,
                            'active': True
                        }
                        
                        # Apply the custom size immediately
                        update_barcode_overlay_position(width, height, x, y)
                        
                        # Make sure barcode overlay is visible and on top
                        barcode_blocker.deiconify()
                        barcode_blocker.wm_attributes('-topmost', True)
                        barcode_blocker.wm_attributes('-alpha', 0.01)
                        
                        print(f"Set custom barcode overlay size: {width}x{height} at ({x},{y})")
                        return True
                    else:
                        print("Transparent barcode overlay window does not exist")
                        return False
                except Exception as e:
                    print(f"Error setting custom barcode overlay size: {e}")
                    return False
            
            # Function to reset to automatic Bar-Code frame tracking
            def reset_barcode_to_auto_size():
                """Reset barcode overlay to automatically track Bar-Code frame size."""
                try:
                    # Clear custom size settings
                    barcode_overlay_system['custom_size'] = {'active': False}
                    
                    # Return to standard frame-based positioning
                    update_barcode_overlay_position()
                    
                    print("Reset barcode overlay to automatic Bar-Code frame tracking")
                    return True
                except Exception as e:
                    print(f"Error resetting barcode overlay to auto size: {e}")
                    return False
            
            # Add the convenience functions to the barcode overlay system
            barcode_overlay_system['set_custom_size'] = set_custom_barcode_overlay_size
            barcode_overlay_system['reset_to_auto'] = reset_barcode_to_auto_size
            
            # Store reference to show function in a global variable for external access
            global BARCODE_OVERLAY_SHOW_FUNCTION
            BARCODE_OVERLAY_SHOW_FUNCTION = show_barcode_overlay_safely
            
            print("Created transparent barcode blocker overlay")
            return barcode_overlay_system
            
        except Exception as e:
            print(f"Error creating barcode overlay system: {e}")
            return None
    
    # Create Barcode overlay but don't show it yet - wait for embedding to complete
    barcode_overlay = create_barcode_overlay()
    
    # Make globally accessible
    global GLOBAL_BARCODE_OVERLAY
    GLOBAL_BARCODE_OVERLAY = barcode_overlay

    # Password prompt helper (defined in main so it can close root)
    def open_password_prompt(on_success=None):
        global PASSWORD_DIALOG_OPEN
        PASSWORD_DIALOG_OPEN = True  # Set flag to exempt password dialog from blockers
        hide_overlays_for_password()  # Hide overlays immediately when dialog opens
        
        dlg = tk.Toplevel()  # Don't parent to container
        dlg.title('Enter Password')
        dlg.grab_set()
        dlg.geometry('400x700')
        dlg.configure(bg='#333333')
        dlg.resizable(False, False)
        dlg.overrideredirect(True)  # Remove window border and X button
        
        # Ensure it appears on top with maximum priority
        dlg.wm_attributes('-topmost', True)
        dlg.lift()
        dlg.focus_force()
        
        # Cleanup function to ensure flag is reset if dialog is destroyed unexpectedly
        def cleanup_password_dialog():
            global PASSWORD_DIALOG_OPEN
            PASSWORD_DIALOG_OPEN = False
            print("Password dialog cleanup - flag reset and overlays restored")
        
        # Bind cleanup to dialog destruction
        dlg.bind("<Destroy>", lambda e: cleanup_password_dialog())
        
        # Center the dialog
        dlg.update_idletasks()
        x = (dlg.winfo_screenwidth() // 2) - (400 // 2)
        y = (dlg.winfo_screenheight() // 2) - (600 // 2)
        dlg.geometry(f'400x600+{x}+{y}')
        
        # Force visibility and focus multiple times
        dlg.update()
        dlg.lift()
        dlg.focus_force()
        dlg.wm_attributes('-topmost', True)
        
        # Password entry tracking
        entered_password = ['']
        
        # Status bar showing masked password
        status_frame = tk.Frame(dlg, bg='#222222', height=60)
        status_frame.pack(fill='x', padx=10, pady=10)
        status_frame.pack_propagate(False)
        
        status_lbl = tk.Label(status_frame, text='Enter Password:', fg='white', bg='#222222', 
                             font=('Arial', 16))
        status_lbl.pack(side='left', padx=10, pady=10)
        
        password_display = tk.Label(status_frame, text='', fg='yellow', bg='#222222', 
                                   font=('Arial', 20, 'bold'))
        password_display.pack(side='right', padx=10, pady=10)
        
        def update_display():
            # Show asterisks for entered digits
            masked = '*' * len(entered_password[0])
            password_display.configure(text=masked)
        
        def add_digit(digit):
            if len(entered_password[0]) < 10:  # Limit password length
                entered_password[0] += str(digit)
                update_display()
        
        def clear_entry():
            entered_password[0] = ''
            update_display()
        
        def check_password():
            global PASSWORD_DIALOG_OPEN
            if entered_password[0] == EXIT_PASSWORD:
                PASSWORD_DIALOG_OPEN = False  # Clear flag before closing dialog
                dlg.grab_release()
                dlg.destroy()
                show_overlays_after_password()  # Restore overlays after successful password
                if on_success:
                    on_success()
            else:
                # Flash red and clear
                password_display.configure(fg='red', text='INCORRECT')
                dlg.after(1000, lambda: (clear_entry(), password_display.configure(fg='yellow')))
        
        # Keypad frame
        keypad_frame = tk.Frame(dlg, bg='#333333')
        keypad_frame.pack(fill='both', padx=20, pady=10)
        
        # Button style
        btn_config = {
            'font': ('Arial', 24, 'bold'),
            'width': 3,
            'height': 2,
            'bg': '#555555',
            'fg': 'white',
            'activebackground': '#777777',
            'activeforeground': 'white',
            'relief': 'raised',
            'bd': 3
        }
        
        # Create number buttons in a 3x3 grid (1-9)
        for i in range(3):
            for j in range(3):
                num = i * 3 + j + 1
                btn = tk.Button(keypad_frame, text=str(num), 
                               command=lambda n=num: add_digit(n), **btn_config)
                btn.grid(row=i, column=j, padx=5, pady=5, sticky='nsew')
        
        # Bottom row: Clear, 0, Enter
        clear_btn = tk.Button(keypad_frame, text='Clear', command=clear_entry,
                             font=('Arial', 16, 'bold'), width=6, height=2,
                             bg='#cc4444', fg='white', activebackground='#ee6666',
                             relief='raised', bd=3)
        clear_btn.grid(row=3, column=0, padx=5, pady=5, sticky='nsew')
        
        zero_btn = tk.Button(keypad_frame, text='0', command=lambda: add_digit(0), **btn_config)
        zero_btn.grid(row=3, column=1, padx=5, pady=5, sticky='nsew')
        
        enter_btn = tk.Button(keypad_frame, text='Enter', command=check_password,
                             font=('Arial', 16, 'bold'), width=6, height=2,
                             bg='#44cc44', fg='white', activebackground='#66ee66',
                             relief='raised', bd=3)
        enter_btn.grid(row=3, column=2, padx=5, pady=5, sticky='nsew')
        
        # Configure grid weights for responsive layout
        for i in range(4):
            keypad_frame.grid_rowconfigure(i, weight=1)
        for j in range(3):
            keypad_frame.grid_columnconfigure(j, weight=1)
        
        def on_cancel():
            global PASSWORD_DIALOG_OPEN
            PASSWORD_DIALOG_OPEN = False  # Clear flag before closing dialog
            show_overlays_after_password()  # Restore overlays when canceling
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()
        
        # Large cancel button spanning full width below keypad
        cancel_btn = tk.Button(dlg, text='Cancel', command=on_cancel,
                              font=('Arial', 18, 'bold'), bg='#666666', fg='white',
                              activebackground='#888888', height=3)
        cancel_btn.pack(fill='x', padx=20, pady=20)

    # Success handler: exit launcher cleanly
    def exit_launcher():
        try:
            root.quit()
        except Exception:
            pass
        try:
            os._exit(0)
        except Exception:
            pass

    # Terminate child processes started by this launcher
    def terminate_children():
        # Try to terminate using Windows APIs for each PID we started
        set_status('Terminating child processes...')
        for pid in list(STARTED_PIDS):
            try:
                # Open process and terminate cleanly if possible
                PROCESS_TERMINATE = 1
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
                if handle:
                    ctypes.windll.kernel32.TerminateProcess(handle, 0)
                    ctypes.windll.kernel32.CloseHandle(handle)
            except Exception:
                try:
                    # Fallback to os.kill
                    os.kill(int(pid), 9)
                except Exception:
                    pass
        STARTED_PIDS.clear()

    # Reload launcher: terminate children, then exec the same Python process again
    def reload_launcher():
        global loading_in_progress
        
        # Show loading overlay during reload
        show_overlay(20)
        
        # Set loading flag to prevent auto-restart during reload
        loading_in_progress = True
        
        # Reload only the child programs (no container restart)
        try:
            set_status('Reloading child programs...')
            terminate_children()
            # small pause to allow processes to terminate
            time.sleep(0.5)
            
            # Ensure LaunchWithMiniIndicator is set to True before restarting
            try:
                update_launch_with_mini_indicator(CLIENT_SETTINGS_PATH, True)
                set_status('Updated LaunchWithMiniIndicator to true during reload...')
            except Exception as e:
                print(f"Error updating LaunchWithMiniIndicator during reload: {e}")
            
            # Restore frame sizes to initial state before restarting programs
            try:
                # Reset top frame to standard sliver height
                top_frame.configure(height=TOP_SLIVER_PX)
                top_frame.pack_configure(side='top', fill='x')
                
                # Reset bottom frame to fill remaining space
                bottom_frame.pack_configure(side='top', fill='both', expand=True)
                
                # Force update to apply the size changes
                container.update_idletasks()
                
                print(f"Restored frame sizes: top={TOP_SLIVER_PX}px, bottom=fill")
                set_status('Restored frame layout for reload...')
                time.sleep(0.2)  # Brief pause for layout to apply
            except Exception as e:
                print(f"Error restoring frame sizes during reload: {e}")
            
            # restart all configured launches
            for exe, title, frame in list(CURRENT_LAUNCHES):
                try:
                    threading.Thread(target=launch_and_embed, args=(exe, title, frame), daemon=True).start()
                except Exception:
                    pass
        except Exception:
            # best-effort only
            pass
        finally:
            # Clear loading flag after a delay (launch_and_embed will also clear it)
            def clear_loading_flag():
                time.sleep(10)  # Wait longer than individual launches
                global loading_in_progress
                loading_in_progress = False
            threading.Thread(target=clear_loading_flag, daemon=True).start()

    # Add visual elements to the taskbar: label + Exit (password) + Power
    status_lbl = tk.Label(taskbar, text='Launcher locked', fg='white', bg='#222222')
    status_lbl.pack(side='left', padx=8)
    # expose to set_status
    global STATUS_LABEL
    STATUS_LABEL = status_lbl

    # Track last activity time for idle timeout
    last_activity_time = [time.time()]  # use list for mutable reference
    
    def update_activity_time():
        """Reset the activity timer"""
        last_activity_time[0] = time.time()
    
    def check_idle_and_update_clock():
        """Check if idle for 20+ seconds and update status to current time"""
        try:
            current_time = time.time()
            idle_duration = current_time - last_activity_time[0]
            
            if idle_duration >= 20:
                # Show current time in status
                import datetime
                current_datetime = datetime.datetime.now()
                time_str = current_datetime.strftime("%I:%M:%S %p")
                set_status(time_str)
            
            # Check again in 1 second
            root.after(1000, check_idle_and_update_clock)
        except Exception:
            # Continue checking even if there's an error
            root.after(1000, check_idle_and_update_clock)
    
    # Start the idle checker
    check_idle_and_update_clock()
    
    # Bind activity events to reset timer
    def on_activity(event=None):
        update_activity_time()
    
    # Monitor mouse and keyboard activity on the container
    container.bind('<Motion>', on_activity)
    container.bind('<Button>', on_activity)
    container.bind('<Key>', on_activity)
    root.bind_all('<Motion>', on_activity)
    root.bind_all('<Button>', on_activity)

    # Keep original layout params to restore later
    saved_layout = {'top_sliver_px': TOP_SLIVER_PX, 'bottom_pack_info': None}

    def show_overlay(duration=20):
        """Show a fullscreen, topmost overlay for `duration` seconds then remove it."""
        try:
            # Create overlay as Toplevel so it's managed by Tk mainloop (safe)
            overlay = tk.Toplevel(root)  # Parent to root instead of container to cover everything
            overlay.overrideredirect(True)
            overlay.attributes('-topmost', True)
            # completely opaque black (no transparency)
            overlay.configure(bg='black')
            # ensure geometry covers the ENTIRE screen including protection bars
            overlay.update_idletasks()
            sw = overlay.winfo_screenwidth()
            sh = overlay.winfo_screenheight()
            overlay.geometry(f"{sw}x{sh}+0+0")
            
            # Add "Loading..." text with animated dots centered on screen
            loading_label = tk.Label(overlay, text="Loading", fg='white', bg='black', 
                                   font=('Arial', 24, 'bold'))
            loading_label.place(relx=0.5, rely=0.5, anchor='center')
            
            # Animate dots
            dot_states = ["", ".", "..", "..."]
            dot_index = [0]  # use list for mutable reference
            
            def animate_dots():
                if overlay.winfo_exists():
                    loading_label.configure(text=f"Loading{dot_states[dot_index[0]]}")
                    dot_index[0] = (dot_index[0] + 1) % len(dot_states)
                    overlay.after(500, animate_dots)  # update every 500ms
            
            # Periodically refocus container while keeping overlay on top
            def refocus_container():
                if overlay.winfo_exists():
                    try:
                        # Get container bottom-right coordinates (as close to corner as possible)
                        container.update_idletasks()
                        # Use rightmost and bottommost pixels of the container
                        cx = container.winfo_x() + container.winfo_width() - 1
                        cy = container.winfo_y() + container.winfo_height() - 1
                        
                        # Simulate mouse click on container bottom-right using Win32 API
                        user32 = ctypes.windll.user32
                        # Set cursor position to container bottom-right corner
                        user32.SetCursorPos(cx, cy)
                        # Send left mouse button down and up (click)
                        user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
                        user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
                        
                        # Ensure overlay stays on top after the click
                        overlay.lift()
                        overlay.focus_force()
                    except Exception:
                        pass
                    # Schedule next refocus in 1 second
                    overlay.after(1000, refocus_container)
            
            # start animation and refocus
            animate_dots()
            refocus_container()
            
            # prevent interactions
            overlay.focus_force()
            # schedule destroy
            overlay.after(int(duration * 1000), lambda: overlay.destroy() if overlay.winfo_exists() else None)
        except Exception:
            pass
    def _apply_barcode_resize(smaller_height=400, top_h_override=None):
        # make barcode section smaller and placed at bottom of the screen
        try:
            # Determine top sliver height: prefer override, otherwise read mini indicator settings
            if top_h_override is not None:
                top_h = int(top_h_override)
            else:
                mini_h, mini_w = get_mini_indicator_size(CLIENT_SETTINGS_PATH)
                top_h = mini_h if mini_h else 0
            # set top_frame height so VirtUi3 will embed into that region
            top_frame.configure(height=top_h)
            top_frame.pack_propagate(False)
            # bottom_frame becomes smaller and anchored to bottom by packing a spacer above it
            # detach existing packing and re-pack: create spacer
            for w in container.pack_slaves():
                pass
            # Repack: spacer (expand) then bottom_frame (fixed height) then taskbar
            try:
                bottom_frame.pack_forget()
            except Exception:
                pass
            spacer = tk.Frame(container, bg=container['bg'])
            spacer.pack(side='top', fill='both', expand=True)
            bottom_frame.pack(side='top', fill='x')
            bottom_frame.configure(height=smaller_height)
            bottom_frame.pack_propagate(False)
            # store spacer so Finish can remove it
            saved_layout['spacer'] = spacer
            container.update_idletasks()
        except Exception:
            pass

    def _restore_layout():
        try:
            # restore top_frame height
            top_frame.configure(height=saved_layout.get('top_sliver_px', TOP_SLIVER_PX))
            top_frame.pack_propagate(False)
            # remove spacer if exists and repack bottom_frame to fill
            spacer = saved_layout.get('spacer')
            if spacer:
                try:
                    spacer.destroy()
                except Exception:
                    pass
                saved_layout['spacer'] = None
            try:
                bottom_frame.pack_forget()
            except Exception:
                pass
            bottom_frame.pack(side='top', fill='both', expand=True)
            bottom_frame.configure(height=0)
            bottom_frame.pack_propagate(True)
            
            # Ensure taskbar is still at the bottom
            try:
                taskbar.pack_forget()
                taskbar.pack(side='bottom', fill='x')
            except Exception:
                pass
                
            container.update_idletasks()
        except Exception:
            pass

    def minify_virtui():
        set_status('Minifying VirtUi3...')
        # 1) Close embedded VirtUi3 (best-effort)
        try:
            info = LAUNCH_INFO.get(custom_title1)
            if info and info.get('pid'):
                terminate_pid(info.get('pid'))
        except Exception:
            pass
        # 2) update settings file to set LaunchWithMiniIndicator: false
        try:
            update_launch_with_mini_indicator(CLIENT_SETTINGS_PATH, False)
        except Exception:
            pass
        # 3) shrink/move barcode and set top_frame to mini indicator height
        # save current top sliver so it can be restored exactly
        try:
            saved_layout['top_sliver_px'] = top_frame.winfo_height() or TOP_SLIVER_PX
        except Exception:
            saved_layout['top_sliver_px'] = TOP_SLIVER_PX
        # enlarge top sliver to give VirtUi3 more room (900 px override)
        _apply_barcode_resize(smaller_height=300, top_h_override=900)

        
        # 4) restart VirtUi3 so it picks up the changed setting
        try:
            threading.Thread(target=launch_and_embed, args=(exe_path1, custom_title1, top_frame), daemon=True).start()
        except Exception:
            pass


    def finish_restore():
        set_status('Restoring layout and VirtUi3...')
        # 1) Close existing VirtUi3 (if any)
        show_overlays_after_password()  # Restore overlays when dialog closes
        
        try:
            info = LAUNCH_INFO.get(custom_title1)
            if info and info.get('pid'):
                terminate_pid(info.get('pid'))
        except Exception:
            pass
        # 2) update settings to true
        try:
            update_launch_with_mini_indicator(CLIENT_SETTINGS_PATH, True)
            set_overlay_custom("auto", 45, "auto", "auto")
            set_barcode_overlay_custom("auto", "auto", "auto", "auto")
            time.sleep(0.5)  # Allow time for settings to be written
        except Exception:
            pass
        # 3) restore barcode layout
        _restore_layout()
        # 4) restart virtui
        try:
            threading.Thread(target=launch_and_embed, args=(exe_path1, custom_title1, top_frame), daemon=True).start()
        except Exception:
            pass


    # Power confirmation dialog
    def show_power_confirmation():
        dlg = tk.Toplevel(container)
        dlg.title('Confirm Shutdown')
        dlg.transient(container)
        dlg.grab_set()
        dlg.geometry('400x300')
        dlg.configure(bg='#333333')
        dlg.resizable(False, False)
        dlg.overrideredirect(True)  # Remove window border and X button
        
        # Center the dialog
        dlg.update_idletasks()
        x = (dlg.winfo_screenwidth() // 2) - (400 // 2)
        y = (dlg.winfo_screenheight() // 2) - (300 // 2)
        dlg.geometry(f'400x300+{x}+{y}')
        
        # Warning message
        warning_frame = tk.Frame(dlg, bg='#333333')
        warning_frame.pack(expand=True, fill='both', padx=20, pady=20)
        
        # Warning icon and text
        warning_lbl = tk.Label(warning_frame, text='⚠️', fg='#ffaa00', bg='#333333', 
                              font=('Arial', 48))
        warning_lbl.pack(pady=10)
        
        message_lbl = tk.Label(warning_frame, text='Shutdown Computer?', fg='white', bg='#333333', 
                              font=('Arial', 20, 'bold'))
        message_lbl.pack(pady=10)
        
        info_lbl = tk.Label(warning_frame, text='This will power down the PC immediately', 
                           fg='#cccccc', bg='#333333', font=('Arial', 14))
        info_lbl.pack(pady=5)
        
        # Button frame
        btn_frame = tk.Frame(warning_frame, bg='#333333')
        btn_frame.pack(expand=True, fill='x', pady=20)
        
        def confirm_shutdown():
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()
            
            # Actually shutdown the PC
            try:
                # Terminate child processes first
                terminate_children()
                # Power down the PC immediately
                os.system('shutdown /s /t 0')
            except Exception:
                # Fallback: just exit if shutdown fails
                exit_launcher()
        
        def cancel_shutdown():
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()
        
        # Shutdown button (red)
        shutdown_btn = tk.Button(btn_frame, text='Shutdown', command=confirm_shutdown,
                                font=('Arial', 16, 'bold'), width=12, height=2,
                                bg='#cc4444', fg='white', activebackground='#ee6666',
                                relief='raised', bd=3)
        shutdown_btn.pack(side='left', padx=10, pady=10)
        
        # Cancel button (gray)
        cancel_btn = tk.Button(btn_frame, text='Cancel', command=cancel_shutdown,
                              font=('Arial', 16, 'bold'), width=12, height=2,
                              bg='#666666', fg='white', activebackground='#888888',
                              relief='raised', bd=3)
        cancel_btn.pack(side='right', padx=10, pady=10)

    # Power button (shows confirmation dialog)
    def on_power():
        show_power_confirmation()

    power_btn = tk.Button(taskbar, text='⏻ Power', command=on_power, bg='#cc4444', fg='white')
    power_btn.pack(side='right', padx=8, pady=4)

    # Exit button (explicit password exit)
    def on_exit():
        open_password_prompt(on_success=exit_launcher)

    exit_btn = tk.Button(taskbar, text='Exit', command=on_exit, bg='#444', fg='white')
    exit_btn.pack(side='right', padx=8, pady=4)

    # Reload button: stops children and restarts launcher
    reload_btn = tk.Button(taskbar, text='Reload', command=reload_launcher, bg='#666', fg='white')
    reload_btn.pack(side='right', padx=8, pady=4)

    # Toggle button: starts as 'Modify' which will minify; when active shows 'Finish' to restore
    toggle_state = {'modified': False}

    def _toggle_action():
        global calibration_mode
        if not toggle_state['modified']:
            # Require password before entering calibration/settings mode
            def on_password_success():
                set_overlay_custom(0, 0, "auto", "auto")
                set_barcode_overlay_custom(0, 0, "auto", "auto")
                try:
                    # show overlay while we transition
                    show_overlay(20)
                except Exception:
                    pass
                minify_virtui()
                toggle_state['modified'] = True
                calibration_mode = True
                
                # Disable Windows taskbar protection when in calibration mode
                disable_windows_taskbar()
                # Update VirtUI3 settings for calibration mode (LaunchWithMiniIndicator = False)
                update_launch_with_mini_indicator(CLIENT_SETTINGS_PATH, False)
                toggle_btn.configure(text='Finish')
                set_status('Calibration / Settings Mode Active')
            
            # Open password prompt
            open_password_prompt(on_password_success)
        else:
            # show overlay while we restore
            try:
                show_overlay(20)
            except Exception:
                pass
            finish_restore()
            set_overlay_custom("auto", 25, "auto", "auto")
            set_barcode_overlay_custom("auto", "auto", "auto", "auto")
                
            toggle_state['modified'] = False
            calibration_mode = False
            set_overlay_custom("auto", 25, "auto", "auto")
            
            # Re-enable Windows taskbar protection when exiting calibration mode
            enable_windows_taskbar()
            # Update VirtUI3 settings for normal mode (LaunchWithMiniIndicator = True)
            update_launch_with_mini_indicator(CLIENT_SETTINGS_PATH, True)
            toggle_btn.configure(text='Calibrate / Settings')
            set_status('Launcher restored')

    toggle_btn = tk.Button(taskbar, text='Calibrate / Settings', command=_toggle_action, bg='#2b6', fg='black')
    toggle_btn.pack(side='right', padx=8, pady=4)

    # Register the programs to CURRENT_LAUNCHES so reload can restart them
    CURRENT_LAUNCHES.clear()
    CURRENT_LAUNCHES.append((exe_path1, custom_title1, top_frame))
    CURRENT_LAUNCHES.append((exe_path2, custom_title2, bottom_frame))

    # Launch and embed each configured program
    # show overlay for 20s at startup to cover other windows
    try:
        show_overlay(20)
    except Exception:
        pass
    for exe, title, frame in list(CURRENT_LAUNCHES):
        threading.Thread(target=launch_and_embed, args=(exe, title, frame), daemon=True).start()

    root.mainloop()

if __name__ == "__main__":
    main()
