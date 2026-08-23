# -*- coding: utf-8 -*-

"""カスタム例外定義"""


class PpiDownloaderError(Exception):
    """ベース例外クラス"""
    pass


class NetworkError(PpiDownloaderError):
    """ネットワークエラー（接続エラー、タイムアウト等）"""
    pass


class RateLimitError(PpiDownloaderError):
    """レート制限エラー（429 Too Many Requests等）"""
    def __init__(self, message: str = "", retry_after: int = None):
        super().__init__(message)
        self.retry_after = retry_after


class BlockedRequestError(PpiDownloaderError):
    """通信ポリシー違反（許可外URL、robots.txt の Disallow 等）で送信を止めた"""
    def __init__(self, message: str = "", reason: str = ""):
        super().__init__(message)
        self.reason = reason


class RequestBudgetExceededError(PpiDownloaderError):
    """1回の実行で送れるリクエスト上限に達した"""
    pass


class OutsideAllowedHoursError(PpiDownloaderError):
    """稼働を許可された時間帯の外側で送信しようとした"""
    pass


class FilesystemError(PpiDownloaderError):
    """ファイルシステムエラー（ディレクトリ作成失敗、ファイル書き込み失敗等）"""
    pass


class ConfigError(PpiDownloaderError):
    """設定エラー（設定ファイルの読み込み失敗、検証エラー等）"""
    pass


class ScrapingError(PpiDownloaderError):
    """スクレイピングエラー（HTML解析失敗、要素が見つからない等）"""
    pass


class ValidationError(PpiDownloaderError):
    """検証エラー（設定値の検証失敗等）"""
    pass
