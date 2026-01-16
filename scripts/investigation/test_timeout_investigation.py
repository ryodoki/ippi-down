"""タイムアウト問題の調査用テストスクリプト"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.logger import Logger
from src.utils.http_client import HTTPClient
from src.core.scraper import Scraper
from src.core.filter import Filter
from src.core.downloader import Downloader
from src.core.naming import Naming
from src.models.config_model import AppConfig, DownloadConditions, SearchConditions
import logging

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/timeout_test.log', encoding='utf-8')
    ]
)

logger = Logger()

def test_timeout_settings():
    """タイムアウト設定を確認"""
    logger.info("=" * 60)
    logger.info("タイムアウト設定の確認")
    logger.info("=" * 60)
    
    # デフォルト設定でHTTPClientを作成
    http_client = HTTPClient(logger)
    logger.info(f"デフォルト設定:")
    logger.info(f"  - timeout (通常リクエスト): {http_client.timeout}秒")
    logger.info(f"  - download_timeout (ダウンロード): {http_client.download_timeout}秒")
    
    # カスタム設定でHTTPClientを作成
    http_client_custom = HTTPClient(logger, timeout=10, download_timeout=60)
    logger.info(f"\nカスタム設定:")
    logger.info(f"  - timeout (通常リクエスト): {http_client_custom.timeout}秒")
    logger.info(f"  - download_timeout (ダウンロード): {http_client_custom.download_timeout}秒")
    
    return http_client, http_client_custom

def test_connection():
    """接続テスト"""
    logger.info("\n" + "=" * 60)
    logger.info("接続テスト")
    logger.info("=" * 60)
    
    http_client = HTTPClient(logger, timeout=10, download_timeout=30)
    
    # テストURL（実際のダウンロードURL）
    test_url = "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?AnkenKanriNo=021030002025412000000704&BunshoKanriId=20"
    
    logger.info(f"テストURL: {test_url}")
    logger.info(f"タイムアウト設定: 接続=10秒, 読み込み=30秒")
    
    try:
        # まず、HEADリクエストで接続をテスト
        logger.info("\n[テスト1] HEADリクエストで接続をテスト...")
        response = http_client.session.head(test_url, timeout=(10, 30))
        logger.info(f"  ✓ 接続成功: {response.status_code}")
        logger.info(f"  Content-Type: {response.headers.get('Content-Type', 'N/A')}")
        logger.info(f"  Content-Length: {response.headers.get('Content-Length', 'N/A')}")
    except Exception as e:
        logger.error(f"  ✗ 接続失敗: {type(e).__name__}: {str(e)}")
        logger.error(f"  エラー詳細: {repr(e)}")
    
    try:
        # 次に、GETリクエストで接続をテスト（stream=True）
        logger.info("\n[テスト2] GETリクエスト（stream=True）で接続をテスト...")
        response = http_client.session.get(test_url, stream=True, timeout=(10, 30))
        logger.info(f"  ✓ 接続成功: {response.status_code}")
        logger.info(f"  Content-Type: {response.headers.get('Content-Type', 'N/A')}")
        logger.info(f"  Content-Length: {response.headers.get('Content-Length', 'N/A')}")
        
        # 最初のチャンクを読み込んでみる
        chunk = next(response.iter_content(chunk_size=1024), None)
        if chunk:
            logger.info(f"  最初のチャンク: {len(chunk)}バイト")
            logger.info(f"  先頭16バイト: {chunk[:16]}")
    except Exception as e:
        logger.error(f"  ✗ 接続失敗: {type(e).__name__}: {str(e)}")
        logger.error(f"  エラー詳細: {repr(e)}")

def test_download_with_different_timeouts():
    """異なるタイムアウト設定でダウンロードをテスト"""
    logger.info("\n" + "=" * 60)
    logger.info("異なるタイムアウト設定でのダウンロードテスト")
    logger.info("=" * 60)
    
    test_url = "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?AnkenKanriNo=021030002025412000000704&BunshoKanriId=20"
    save_dir = Path("downloads/timeout_test")
    save_dir.mkdir(parents=True, exist_ok=True)
    
    # 異なるタイムアウト設定をテスト
    timeout_configs = [
        (5, 15),   # 接続5秒、読み込み15秒
        (10, 30),  # 接続10秒、読み込み30秒
        (10, 60),  # 接続10秒、読み込み60秒
    ]
    
    for connect_timeout, read_timeout in timeout_configs:
        logger.info(f"\n[テスト] 接続={connect_timeout}秒, 読み込み={read_timeout}秒")
        http_client = HTTPClient(logger, timeout=connect_timeout, download_timeout=read_timeout)
        save_path = save_dir / f"test_{connect_timeout}_{read_timeout}.pdf"
        
        try:
            success = http_client.download_file(test_url, str(save_path))
            if success:
                logger.info(f"  ✓ ダウンロード成功: {save_path}")
                logger.info(f"  ファイルサイズ: {save_path.stat().st_size}バイト")
            else:
                logger.error(f"  ✗ ダウンロード失敗")
        except Exception as e:
            logger.error(f"  ✗ エラー: {type(e).__name__}: {str(e)}")
        finally:
            http_client.close()

def test_network_diagnostics():
    """ネットワーク診断"""
    logger.info("\n" + "=" * 60)
    logger.info("ネットワーク診断")
    logger.info("=" * 60)
    
    import socket
    import time
    
    test_host = "e2ppiw01.e-bisc.go.jp"
    test_port = 443
    
    logger.info(f"ホスト: {test_host}:{test_port}")
    
    # DNS解決テスト
    try:
        logger.info("\n[診断1] DNS解決テスト...")
        start_time = time.time()
        ip_address = socket.gethostbyname(test_host)
        elapsed = time.time() - start_time
        logger.info(f"  ✓ DNS解決成功: {ip_address} (所要時間: {elapsed:.3f}秒)")
    except Exception as e:
        logger.error(f"  ✗ DNS解決失敗: {str(e)}")
        return
    
    # TCP接続テスト
    try:
        logger.info("\n[診断2] TCP接続テスト...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)  # 10秒でタイムアウト
        start_time = time.time()
        result = sock.connect_ex((ip_address, test_port))
        elapsed = time.time() - start_time
        sock.close()
        
        if result == 0:
            logger.info(f"  ✓ TCP接続成功 (所要時間: {elapsed:.3f}秒)")
        else:
            logger.error(f"  ✗ TCP接続失敗: エラーコード {result}")
    except socket.timeout:
        logger.error(f"  ✗ TCP接続タイムアウト (10秒)")
    except Exception as e:
        logger.error(f"  ✗ TCP接続エラー: {str(e)}")

def main():
    """メイン関数"""
    logger.info("タイムアウト問題の調査を開始します")
    
    # ログディレクトリを作成
    Path("logs").mkdir(exist_ok=True)
    
    # 1. タイムアウト設定の確認
    test_timeout_settings()
    
    # 2. ネットワーク診断
    test_network_diagnostics()
    
    # 3. 接続テスト
    test_connection()
    
    # 4. 異なるタイムアウト設定でのダウンロードテスト
    test_download_with_different_timeouts()
    
    logger.info("\n" + "=" * 60)
    logger.info("調査完了")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
