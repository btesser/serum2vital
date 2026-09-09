"""Type a fixture filename into the already focused Serum save dialog."""
import ctypes
import sys
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
ULONG_PTR = ctypes.c_size_t

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", INPUTUNION)]

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT

title = ctypes.create_unicode_buffer(512)
user32.GetWindowTextW(user32.GetForegroundWindow(), title, len(title))
numeric_value = len(sys.argv) > 2 and sys.argv[2] == "--value"
valid_target = (title.value == "Serum 2/2-Serum 2" if numeric_value
                else title.value.lower().startswith("save preset as"))
if not valid_target:
    raise SystemExit(f"No input sent: foreground window is {title.value!r}")

def key(vk=0, scan=0, flags=0):
    return INPUT(1, INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))

events = [key(0x11), key(0x41), key(0x41, flags=2), key(0x11, flags=2)]
filename = sys.argv[1]
for char in filename:
    events.extend((key(scan=ord(char), flags=4), key(scan=ord(char), flags=6)))
if numeric_value:
    events.extend((key(0x0D), key(0x0D, flags=2)))
batch = (INPUT * len(events))(*events)
sent = user32.SendInput(len(batch), batch, ctypes.sizeof(INPUT))
if sent != len(batch):
    raise RuntimeError(f"Sent {sent}/{len(batch)} input events; error {ctypes.get_last_error()}")
print("Value entered." if numeric_value else "Filename typed; Save was not pressed.")
