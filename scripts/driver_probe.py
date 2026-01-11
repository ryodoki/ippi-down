"""driver_probe.py

ippi-down の現行実装（requests + BeautifulSoup + ViewState）を前提に、
対象ページに対して "requests でいけるか / ブラウザ自動化が要るか" を
ざっくり実測・判定する診断スクリプト。

注意:
  - 完全自動で100%当てるのは無理（クリック手順や認証方式に依存する）。
    ただし「requestsで落とせるか」はテストできるので、切り分けはかなり進む。
  - Playwright/Selenium は任意。入ってなければスキップして理由を出す。

使い方（Windows / PowerShell）:

  # 1) まずは設定ファイル前提で診断（おすすめ）
  python .\scripts\driver_probe.py --config .\config\config.yaml

  # 2) URLを直指定（設定より優先）
  python .\scripts\driver_probe.py --url "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"

  # 3) Playwrightも走らせる（Playwright導入済みの場合）
  python .\scripts\driver_probe.py --config .\config\config.yaml --run-playwright

  # 4) Seleniumも走らせる（Chrome + driver 準備済みの場合）
  python .\scripts\driver_probe.py --config .\config\config.yaml --run-selenium

出力:
  - コンソールにレポート表示
  - --json を付けると JSON も出力
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---- プロジェクト import 用のパス調整（scripts/ から実行しても動くように） ----
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _safe_import(module_name: str):
    try:
        __import__(module_name)
        return sys.modules[module_name]
    except Exception:
        return None


def _guess_is_spa(html: str) -> Tuple[bool, Dict[str, Any]]:
    """HTMLから "SPAっぽさ" を雑に推定"""
    script_count = len(re.findall(r"<script\b", html, flags=re.IGNORECASE))
    noscript = bool(re.search(r"<noscript\b", html, flags=re.IGNORECASE))
    has_root = bool(re.search(r"id=\"(app|root)\"", html, flags=re.IGNORECASE))
    text_len = len(re.sub(r"<[^>]+>", " ", html))
    html_len = len(html)

    ratio_text = 0.0 if html_len == 0 else (text_len / html_len)

    indicators = {
        "script_count": script_count,
        "noscript": noscript,
        "has_app_or_root": has_root,
        "text_ratio": round(ratio_text, 4),
        "html_len": html_len,
    }

    spa_like = (has_root and script_count >= 5 and ratio_text < 0.25) or (script_count >= 12 and ratio_text < 0.2)
    return spa_like, indicators


def _file_magic_ok(path: Path, ext: str) -> bool:
    """保存されたファイルが "それっぽい" かを先頭バイトで判定"""
    ext = ext.lower()
    try:
        with path.open("rb") as f:
            head = f.read(16)
    except Exception:
        return False

    if ext == ".pdf":
        return head.startswith(b"%PDF")
    if ext in {".xlsx", ".docx", ".pptx", ".zip"}:
        return head.startswith(b"PK")
    if ext in {".csv", ".txt"}:
        return b"\x00" not in head
    return len(head) > 0


@dataclass
class ProbeResult:
    name: str
    ok: bool
    score: int
    details: Dict[str, Any]


def _requests_probe(search_url: str, config_path: str) -> ProbeResult:
    """現行実装ベース（Scraper/HTTPClient）で、
    (1) ページ取得
    (2) 検索送信
    (3) ファイルリンク抽出
    (4) サンプル1件ダウンロードして中身チェック
    を試す。
    """

    details: Dict[str, Any] = {"search_url": search_url, "config": config_path}
    try:
        from src.utils.logger import Logger
        from src.utils.http_client import HTTPClient
        from src.core.scraper import Scraper
        from src.config.config_manager import ConfigManager

        logger = Logger()
        cfg = ConfigManager(config_path=config_path, logger=logger).load_config()
        file_types = cfg.download_conditions.file_types
        details["file_types"] = file_types

        http = HTTPClient(logger=logger)
        scraper = Scraper(http_client=http, logger=logger)

        # 1) 初期ページ取得
        soup0 = scraper.fetch_page(search_url)
        if soup0 is None:
            return ProbeResult(
                name="requests",
                ok=False,
                score=0,
                details={**details, "error": "初期ページ取得に失敗（HTTP/認証/ネットワーク）"},
            )

        html0 = str(soup0)
        spa_like, spa_ind = _guess_is_spa(html0)
        details["spa_like"] = spa_like
        details["spa_indicators"] = spa_ind

        # 2) 検索送信
        soup = scraper.submit_search_form(search_url, cfg.search_conditions)
        if soup is None:
            return ProbeResult(
                name="requests",
                ok=False,
                score=10 if not spa_like else 5,
                details={**details, "error": "検索フォーム送信/結果取得に失敗（ViewState変化 or 認証）"},
            )

        # 3) リンク抽出
        files = scraper.extract_file_links_from_search_results(soup, search_url, file_types)
        details["extracted_count"] = len(files)
        if not files:
            score = 20 if not spa_like else 10
            return ProbeResult(
                name="requests",
                ok=False,
                score=score,
                details={**details, "error": "ファイルリンクが抽出できない（HTML構造変更/条件0件/リンクが拡張子無し）"},
            )

        # 4) サンプル1件ダウンロード
        sample = files[0]
        tmp_dir = Path(tempfile.mkdtemp(prefix="ippi_probe_"))
        ext = sample.file_type or Path(sample.filename).suffix or ".bin"
        save_path = tmp_dir / ("sample" + ext)

        ok = http.download_file(sample.url, str(save_path), referer=sample.page_url)
        details["sample_url"] = sample.url
        details["sample_saved"] = str(save_path)
        details["download_success_flag"] = ok
        if not ok or not save_path.exists():
            return ProbeResult(
                name="requests",
                ok=False,
                score=35,
                details={**details, "error": "サンプルDLが失敗（HTTP 429/403/リダイレクト/タイムアウト等）"},
            )

        # 中身チェック
        magic_ok = _file_magic_ok(save_path, ext)
        details["magic_ok"] = magic_ok
        details["file_size"] = save_path.stat().st_size

        if not magic_ok:
            return ProbeResult(
                name="requests",
                ok=False,
                score=45,
                details={**details, "error": "DLはできたが中身がファイルっぽくない（HTML保存の可能性）"},
            )

        return ProbeResult(
            name="requests",
            ok=True,
            score=90,
            details=details,
        )

    except Exception as e:
        return ProbeResult(
            name="requests",
            ok=False,
            score=0,
            details={**details, "error": f"例外: {type(e).__name__}: {e}"},
        )


def _playwright_probe(search_url: str, sample_href_substr: Optional[str] = None) -> ProbeResult:
    """Playwrightが入ってる環境なら、
    - ページを開けるか
    - 画面上の a[href*=\"...\"] をクリックして download イベントが取れるか
    を試す。
    """

    details: Dict[str, Any] = {"search_url": search_url, "sample_href_substr": sample_href_substr}
    pw = _safe_import("playwright.sync_api")
    if pw is None:
        return ProbeResult(
            name="playwright",
            ok=False,
            score=0,
            details={
                **details,
                "error": "Playwrightが未インストール（pip install playwright / python -m playwright install chromium が必要）",
            },
        )

    try:
        from playwright.sync_api import sync_playwright

        tmp_dir = Path(tempfile.mkdtemp(prefix="ippi_pw_probe_"))
        details["download_dir"] = str(tmp_dir)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)

            html = page.content()
            spa_like, spa_ind = _guess_is_spa(html)
            details["spa_like_after_js"] = spa_like
            details["spa_indicators_after_js"] = spa_ind

            if not sample_href_substr:
                browser.close()
                return ProbeResult(
                    name="playwright",
                    ok=True,
                    score=55,
                    details={**details, "note": "ページ表示は成功。ただしクリック対象未指定のためDL実測は省略"},
                )

            locator = page.locator(f"a[href*='{sample_href_substr}']")
            if locator.count() == 0:
                browser.close()
                return ProbeResult(
                    name="playwright",
                    ok=False,
                    score=40,
                    details={**details, "error": "指定条件のリンクがDOM上に見つからない"},
                )

            with page.expect_download(timeout=60000) as dl_info:
                locator.first.click()

            dl = dl_info.value
            suggested = dl.suggested_filename
            save_path = tmp_dir / suggested
            dl.save_as(str(save_path))
            details["saved"] = str(save_path)
            details["suggested_filename"] = suggested
            ext = Path(suggested).suffix or ".bin"
            details["magic_ok"] = _file_magic_ok(save_path, ext)
            details["file_size"] = save_path.stat().st_size if save_path.exists() else 0

            browser.close()

            if not save_path.exists() or details["file_size"] == 0:
                return ProbeResult(
                    name="playwright",
                    ok=False,
                    score=45,
                    details={**details, "error": "downloadイベントは取れたがファイル保存ができてない"},
                )
            if not details["magic_ok"]:
                return ProbeResult(
                    name="playwright",
                    ok=False,
                    score=50,
                    details={**details, "error": "保存できたが中身がファイルっぽくない（HTML等）"},
                )

            return ProbeResult(name="playwright", ok=True, score=80, details=details)

    except Exception as e:
        return ProbeResult(
            name="playwright",
            ok=False,
            score=0,
            details={**details, "error": f"例外: {type(e).__name__}: {e}"},
        )


def _selenium_probe(search_url: str) -> ProbeResult:
    """Seleniumのテスト（最低限、起動してページ開けるかだけ見る）"""

    details: Dict[str, Any] = {"search_url": search_url}
    sel = _safe_import("selenium")
    if sel is None:
        return ProbeResult(
            name="selenium",
            ok=False,
            score=0,
            details={
                **details,
                "error": "Seleniumが未インストール（pip install selenium webdriver-manager が必要）",
            },
        )

    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        wdm = _safe_import("webdriver_manager.chrome")
        driver_path = None
        if wdm is not None:
            from webdriver_manager.chrome import ChromeDriverManager
            driver_path = ChromeDriverManager().install()
            details["chromedriver"] = driver_path

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")

        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(60)
        driver.get(search_url)

        title = driver.title
        html = driver.page_source
        spa_like, spa_ind = _guess_is_spa(html)
        details["title"] = title
        details["spa_like_after_js"] = spa_like
        details["spa_indicators_after_js"] = spa_ind
        driver.quit()

        return ProbeResult(name="selenium", ok=True, score=50, details=details)

    except Exception as e:
        return ProbeResult(
            name="selenium",
            ok=False,
            score=0,
            details={**details, "error": f"例外: {type(e).__name__}: {e}"},
        )


def _recommend(results: List[ProbeResult]) -> Tuple[str, str]:
    best = max(results, key=lambda r: r.score)
    if best.name == "requests":
        reason = "requestsでサンプルDLまで通ってるなら、ブラウザ自動化は過剰"
    elif best.name == "playwright":
        reason = "requests側で詰まりやすい（JS/認証/リンク生成）雰囲気が濃いのでブラウザ自動化が無難"
    else:
        reason = "Selenium縛りがあるなら仕方ない（基本はPlaywright優先）"
    return best.name, reason


def main() -> int:
    ap = argparse.ArgumentParser(description="ippi-down: driver probe (requests / playwright / selenium)")
    ap.add_argument("--config", default="config/config.yaml", help="設定ファイルパス")
    ap.add_argument("--url", default=None, help="対象URL（指定すると設定より優先）")
    ap.add_argument("--run-playwright", action="store_true", help="Playwrightでも簡易診断する")
    ap.add_argument("--run-selenium", action="store_true", help="Seleniumでも簡易診断する")
    ap.add_argument(
        "--sample-href-substr",
        default=None,
        help="Playwrightでクリック対象リンクを絞るための href 部分文字列（例: 'DownloadServices'）",
    )
    ap.add_argument("--json", action="store_true", help="結果をJSONでも出力")
    args = ap.parse_args()

    search_url = args.url
    if not search_url:
        try:
            from src.config.config_manager import ConfigManager
            from src.utils.logger import Logger
            cfg = ConfigManager(config_path=args.config, logger=Logger()).load_config()
            search_url = cfg.target_urls[0] if cfg.target_urls else None
        except Exception:
            search_url = None

    if not search_url:
        search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"

    results: List[ProbeResult] = []
    results.append(_requests_probe(search_url=search_url, config_path=args.config))

    if args.run_playwright:
        results.append(_playwright_probe(search_url=search_url, sample_href_substr=args.sample_href_substr))
    else:
        results.append(ProbeResult(name="playwright", ok=False, score=0, details={"skipped": True}))

    if args.run_selenium:
        results.append(_selenium_probe(search_url=search_url))
    else:
        results.append(ProbeResult(name="selenium", ok=False, score=0, details={"skipped": True}))

    best, reason = _recommend(results)

    print("\n=== driver probe report ===")
    print(f"target: {search_url}")
    for r in results:
        status = "OK" if r.ok else "NG"
        print(f"- {r.name:10s} : {status}  score={r.score}")
        if "error" in r.details:
            print(f"    -> {r.details['error']}")
        if r.details.get("spa_like") is True:
            print("    -> (requests) SPAっぽいHTML。JS無しで中身が取れない可能性")
        if r.details.get("spa_like_after_js") is True:
            print("    -> (browser) JS実行後はSPAっぽいDOM")

    print("\n=== recommendation ===")
    print(f"best: {best}")
    print(f"reason: {reason}")

    if args.json:
        payload = {
            "target": search_url,
            "recommendation": {"best": best, "reason": reason},
            "results": [asdict(r) for r in results],
        }
        print("\n=== json ===")
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
