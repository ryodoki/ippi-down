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
