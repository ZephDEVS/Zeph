# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path(SPECPATH)
app_version = (project_root / "VERSION").read_text(encoding="utf-8").strip()

datas = [
    (str(project_root / "frontend" / "dist"), "frontend/dist"),
    (str(project_root / "daia" / "assets"), "daia/assets"),
    (str(project_root / "VERSION"), "."),
]

hiddenimports = [
    "bottle",
    "proxy_tools",
    "webview",
    "webview.platforms.cocoa",
]

analysis = Analysis(
    ["daia/main.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Zeph",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Zeph",
)

app = BUNDLE(
    coll,
    name="Zeph.app",
    icon=str(project_root / "Zeph.icns"),
    bundle_identifier="com.zeph.desktop",
    info_plist={
        "CFBundleName": "Zeph",
        "CFBundleDisplayName": "Zeph",
        "CFBundleShortVersionString": app_version,
        "CFBundleVersion": app_version,
        "NSMicrophoneUsageDescription": "Zeph uses the microphone for voice commands.",
        "NSSpeechRecognitionUsageDescription": "Zeph uses speech recognition for voice commands.",
    },
)
