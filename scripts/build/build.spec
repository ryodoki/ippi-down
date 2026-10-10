# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for ippi-down
# ビルド方法: .\.venv\Scripts\python.exe -m PyInstaller scripts\build\build.spec

from pathlib import Path


block_cipher = None
project_root = Path(SPECPATH).resolve().parents[1]

a = Analysis(
    [str(project_root / 'src' / 'main.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # 設定ファイルのテンプレートを含める
        (str(project_root / 'config' / 'config.example.yaml'), 'config'),
        # --self-checkで使う保存済みオフラインHTML fixture
        (
            str(
                project_root
                / 'src'
                / 'resources'
                / 'self_check_bid_sheet.html'
            ),
            'src/resources',
        ),
        # ブラウザー非依存PDF生成で使う、日本語フォントとライセンス。
        (
            str(project_root / 'src' / 'resources' / 'fonts' / 'NotoSansJP-VF.ttf'),
            'src/resources/fonts',
        ),
        (
            str(project_root / 'src' / 'resources' / 'fonts' / 'OFL-1.1.txt'),
            'src/resources/fonts',
        ),
    ],
    hiddenimports=[
        # tkinterは通常のimport解析とPyInstaller標準hookに任せる。
        # 明示するとTcl/Tkがない開発環境で誤解を招く警告になる。
        # YAML処理
        'yaml',
        'yaml.cyaml',
        '_yaml',
        'yaml.loader',
        'yaml.dumper',
        # HTTP/スクレイピング
        'requests',
        'urllib3',
        'certifi',
        'charset_normalizer',
        'idna',
        'bs4',
        'lxml',
        'lxml.etree',
        'lxml.html',
        # 内蔵PDF生成・生成物の厳格検証
        'PIL',
        'PIL._imaging',
        'reportlab',
        'reportlab.pdfbase.ttfonts',
        'reportlab.platypus',
        'pypdf',
        # EdgeフォールバックのJob Object監視
        'pywintypes',
        'win32api',
        'win32con',
        'win32event',
        'win32job',
        'win32process',
        # スケジューリング
        'schedule',
        # 定期実行通知は標準ctypes/Shell_NotifyIconWを使うためhidden import不要。
        # 旧GUI通知の任意win10toastはexeへ必須化しない。
        # その他
        'logging.handlers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # テスト関連は除外
        'pytest',
        'pytest_cov',
        'pytest_mock',
        'pytest_timeout',
        # 開発用ツールは除外
        'pyinstaller',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ippi-down',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUIアプリなのでコンソールを表示しない
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # アイコンファイルがある場合は指定
)
