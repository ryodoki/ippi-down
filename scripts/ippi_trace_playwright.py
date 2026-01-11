from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4")
    ap.add_argument("--outdir", default="trace_out")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--devtools", action="store_true", help="ChromiumをDevTools付きで起動")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    har_path = outdir / "network.har"
    events_path = outdir / "events.jsonl"
    cookies_path = outdir / "cookies.json"

    print("\n[trace] HARとイベントログを採取します")
    print(f"[trace] target url : {args.url}")
    print(f"[trace] outdir     : {outdir.resolve()}")
    print("----------------------------------------------------------------")
    print("1) 開いたブラウザで、ふだん通りに検索→詳細→ダウンロード操作をしてください")
    print("2) 操作が終わったら、このコンソールで Enter を押してください")
    print("----------------------------------------------------------------\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, devtools=args.devtools)
        context = browser.new_context(
            accept_downloads=True,
            record_har_path=str(har_path),
            record_har_content="embed",
        )
        page = context.new_page()

        def log_event(obj: dict):
            with events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")

        page.on("request", lambda req: log_event({
            "t": time.time(),
            "type": "request",
            "method": req.method,
            "url": req.url,
            "resource": req.resource_type,
        }))

        page.on("response", lambda res: log_event({
            "t": time.time(),
            "type": "response",
            "url": res.url,
            "status": res.status,
            "headers": res.headers,
        }))

        page.on("requestfailed", lambda req: log_event({
            "t": time.time(),
            "type": "requestfailed",
            "url": req.url,
            "failure": (req.failure or {}),
        }))

        def on_download(d):
            log_event({
                "t": time.time(),
                "type": "download",
                "url": d.url,
                "suggested_filename": d.suggested_filename,
            })
        page.on("download", on_download)

        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1200)

        input()

        cookies = context.cookies()
        cookies_path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")

        context.close()
        browser.close()

    print("\n[done] 保存しました:")
    print(f" - HAR     : {har_path}")
    print(f" - Events  : {events_path}")
    print(f" - Cookies : {cookies_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())