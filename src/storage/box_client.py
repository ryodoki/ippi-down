"""Box API連携を行うクラス"""

from pathlib import Path
from typing import Optional
from ..utils.logger import Logger

# Box SDKをオプショナルインポート
try:
    from boxsdk import Client, OAuth2
    from boxsdk.exception import BoxAPIException
    BOX_SDK_AVAILABLE = True
except ImportError:
    BOX_SDK_AVAILABLE = False
    Client = None
    OAuth2 = None
    BoxAPIException = Exception


class BoxClient:
    """Box API連携を行うクラス"""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        access_token: str = "",
        refresh_token: str = "",
        logger: Optional[Logger] = None,
    ):
        """初期化"""
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.logger = logger or Logger()
        self.client: Optional[Client] = None

    def authenticate(self) -> bool:
        """Box APIに認証"""
        if not BOX_SDK_AVAILABLE:
            self.logger.error("Box SDKがインストールされていません。pip install boxsdk を実行してください。")
            return False

        try:
            if not self.client_id or not self.client_secret:
                self.logger.error("Box認証情報が設定されていません")
                return False

            # OAuth2認証（実装は簡略化、実際にはOAuthフローが必要）
            if self.access_token:
                oauth = OAuth2(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    access_token=self.access_token,
                    refresh_token=self.refresh_token,
                )
                self.client = Client(oauth)
                self.logger.info("Box認証に成功しました")
                return True
            else:
                self.logger.warning("Boxアクセストークンが設定されていません")
                return False

        except Exception as e:
            self.logger.error(f"Box認証エラー: {str(e)}")
            return False

    def upload_file(
        self, local_path: str, box_folder_id: str, box_filename: Optional[str] = None
    ) -> bool:
        """ファイルをBoxにアップロード"""
        if not BOX_SDK_AVAILABLE:
            self.logger.error("Box SDKがインストールされていません")
            return False

        try:
            if not self.client:
                if not self.authenticate():
                    return False

            file_path = Path(local_path)
            if not file_path.exists():
                self.logger.error(f"ファイルが存在しません: {local_path}")
                return False

            folder = self.client.folder(folder_id=box_folder_id)
            filename = box_filename or file_path.name

            # ファイルをアップロード
            with open(local_path, "rb") as file:
                uploaded_file = folder.upload_stream(file, filename)

            self.logger.info(f"Boxにアップロード完了: {uploaded_file.name}")
            return True

        except BoxAPIException as e:
            self.logger.error(f"Box APIエラー: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Boxアップロードエラー: {str(e)}")
            return False

    def create_folder(self, folder_name: str, parent_folder_id: Optional[str] = None) -> Optional[str]:
        """フォルダを作成"""
        if not BOX_SDK_AVAILABLE:
            self.logger.error("Box SDKがインストールされていません")
            return None

        try:
            if not self.client:
                if not self.authenticate():
                    return None

            if parent_folder_id:
                parent_folder = self.client.folder(folder_id=parent_folder_id)
                new_folder = parent_folder.create_subfolder(folder_name)
            else:
                root_folder = self.client.folder(folder_id="0")
                new_folder = root_folder.create_subfolder(folder_name)

            self.logger.info(f"Boxフォルダを作成しました: {new_folder.name}")
            return new_folder.id

        except BoxAPIException as e:
            self.logger.error(f"Box APIエラー: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"Boxフォルダ作成エラー: {str(e)}")
            return None

    def file_exists(self, box_folder_id: str, filename: str) -> bool:
        """ファイルが存在するかチェック"""
        if not BOX_SDK_AVAILABLE:
            self.logger.error("Box SDKがインストールされていません")
            return False

        try:
            if not self.client:
                if not self.authenticate():
                    return False

            folder = self.client.folder(folder_id=box_folder_id)
            items = folder.get_items()

            for item in items:
                if item.name == filename:
                    return True

            return False

        except Exception as e:
            self.logger.error(f"Boxファイル存在チェックエラー: {str(e)}")
            return False

