# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for ippi-down
# ビルド方法: pyinstaller scripts/build.spec (プロジェクトルートから実行)

block_cipher = None

a = Analysis(
    ['src/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 設定ファイルのテンプレートを含める
        ('config/config.example.yaml', 'config'),
    ],
    hiddenimports=[
        # GUI関連
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'customtkinter',
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
        # スケジューリング
        'schedule',
        # Windows通知
        'win10toast',
        # 進捗表示
        'tqdm',
        # リトライ処理
        'tenacity',
        # 日時処理
        'dateutil',
        'dateutil.parser',
        # 環境変数
        'dotenv',
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
