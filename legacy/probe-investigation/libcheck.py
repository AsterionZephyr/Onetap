import importlib

for m in ["PIL", "numpy", "cv2", "win32gui", "win32api", "pyautogui", "mss"]:
    try:
        mod = importlib.import_module(m)
        print("  %-10s OK   %s" % (m, getattr(mod, "__version__", "")))
    except Exception as e:
        print("  %-10s --   %s" % (m, type(e).__name__))
