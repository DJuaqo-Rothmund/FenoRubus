# PyInstaller: PhenoRubus para Windows (carpeta con PhenoRubus.exe; el instalador la empaqueta).
#   pyinstaller tools/windows/phenorubus.spec
import logging
import os

os.environ.setdefault("KIVY_LOG_MODE", "PYTHON")    # que Kivy no suba el registro a TRACE

from kivy_deps import angle, glew, sdl2
from kivymd import hooks_path as kivymd_hooks_path
from PyInstaller.utils.hooks import collect_submodules

logging.getLogger().setLevel(logging.WARNING)
ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

datas = [(os.path.join(ROOT, d), d) for d in ("ui", "assets", "templates")]
if os.path.exists(os.path.join(ROOT, "version.txt")):
    datas.append((os.path.join(ROOT, "version.txt"), "."))

hidden = (collect_submodules("ui") + collect_submodules("plyer.platforms.win")
          + ["google_client", "sync", "sync_drive", "desktop_auth", "photo_optimizer",
             "reporter", "pdf_report", "pdfdoc", "measures_export", "trial_stats", "data_transfer",
             "importer", "ai_classifier", "ai_game", "ai_share", "catalog", "geo", "crashguard"])

a = Analysis([os.path.join(ROOT, "main.py")], pathex=[ROOT], datas=datas, hiddenimports=hidden,
             hookspath=[kivymd_hooks_path], excludes=["jnius", "android", "pytest", "tkinter"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PhenoRubus", console=False,
          icon=os.path.join(ROOT, "tools", "windows", "phenorubus.ico"))
coll = COLLECT(exe, a.binaries, a.datas,
               *[Tree(p) for p in (sdl2.dep_bins + glew.dep_bins + angle.dep_bins)],
               name="PhenoRubus")
