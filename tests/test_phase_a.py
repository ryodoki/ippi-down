"""Phase A リファクタリング動作確認テスト"""

import pytest
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_progress_event():
    """ProgressEventの動作確認"""
    from src.app.events import ProgressEvent, EventType
    
    # イベント作成
    event = ProgressEvent(
        type=EventType.START,
        message="テスト開始",
        total=10
    )
    
    assert event.type == EventType.START
    assert event.message == "テスト開始"
    assert event.total == 10
    assert event.current == 0


def test_logger_factory():
    """LoggerFactoryの動作確認"""
    from src.utils.logger_factory import LoggerFactory
    from src.models.config_model import LoggingConfig
    
    factory = LoggerFactory()
    
    # Logger作成
    config = LoggingConfig(
        level="INFO",
        file="logs/test.log",
        max_bytes=10485760,
        backup_count=5
    )
    
    logger1 = factory.create_logger(config, run_id="test-001")
    logger2 = factory.create_logger(config, run_id="test-001")
    
    # 同じrun_idの場合は同じLoggerインスタンスを返す
    assert logger1 is logger2
    
    # 異なるrun_idの場合は異なるLoggerインスタンス
    logger3 = factory.create_logger(config, run_id="test-002")
    assert logger1 is not logger3
    
    # 異なるconfigでも同じrun_idの場合は同じLoggerインスタンスを返す（run_idが優先）
    config2 = LoggingConfig(
        level="DEBUG",
        file="logs/test2.log",
        max_bytes=10485760,
        backup_count=5
    )
    logger4 = factory.create_logger(config2, run_id="test-001")
    assert logger1 is logger4


def test_secret_provider():
    """SecretProviderの動作確認"""
    import os
    from src.utils.secret_provider import EnvSecretProvider, ConfigSecretProvider
    
    # EnvSecretProvider
    provider = EnvSecretProvider(prefix="PPI_TEST_")
    
    # 環境変数を設定
    os.environ["PPI_TEST_CLIENT_SECRET"] = "test-secret-value"
    
    # 取得
    value = provider.get("client_secret")
    assert value == "test-secret-value"
    
    # 設定
    provider.set("access_token", "test-token")
    assert os.getenv("PPI_TEST_ACCESS_TOKEN") == "test-token"
    
    # ConfigSecretProvider
    config_provider = ConfigSecretProvider({"key1": "value1"})
    assert config_provider.get("key1") == "value1"
    
    config_provider.set("key2", "value2")
    assert config_provider.get("key2") == "value2"
    
    # クリーンアップ
    del os.environ["PPI_TEST_CLIENT_SECRET"]
    del os.environ["PPI_TEST_ACCESS_TOKEN"]


def test_event_handler_creation():
    """EventHandlerの作成確認（GUIなし）"""
    import tkinter as tk
    from src.gui.event_handler import EventHandler
    from src.gui.main_window import MainWindow
    from src.models.config_model import AppConfig
    from src.config.config_manager import ConfigManager
    
    # 最小限のGUIを作成
    root = tk.Tk()
    root.withdraw()  # 非表示
    
    try:
        config = AppConfig()
        config_manager = ConfigManager()
        main_window = MainWindow(root, config, config_manager)
        
        # EventHandlerが作成されているか確認
        assert hasattr(main_window, 'event_handler')
        assert main_window.event_handler is not None
        
        # イベントを発行
        from src.app.events import ProgressEvent, EventType
        event = ProgressEvent(
            type=EventType.MESSAGE,
            message="テストメッセージ"
        )
        main_window.event_handler.emit(event)
        
    finally:
        root.destroy()


@pytest.mark.gui
def test_gui_event_handler():
    """GUI EventHandlerの動作確認（GUIテスト）"""
    import tkinter as tk
    from src.gui.event_handler import EventHandler
    from src.gui.main_window import MainWindow
    from src.models.config_model import AppConfig
    from src.app.events import ProgressEvent, EventType
    from src.config.config_manager import ConfigManager
    
    root = tk.Tk()
    root.withdraw()
    
    try:
        config = AppConfig()
        config_manager = ConfigManager()
        main_window = MainWindow(root, config, config_manager)
        
        # イベントを発行
        event = ProgressEvent(
            type=EventType.PROGRESS,
            message="進捗テスト",
            current=5,
            total=10,
            filename="test.pdf"
        )
        main_window.event_handler.emit(event)
        
        # イベントキューに追加されているか確認
        assert not main_window.event_handler.event_queue.empty()
        
    finally:
        root.destroy()
