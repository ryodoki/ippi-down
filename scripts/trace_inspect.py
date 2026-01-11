from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_events(events_path: Path):
    reqfailed = []
    downloads = []
    responses = []

    if not events_path.exists():
        return reqfailed, downloads, responses

    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        t = e.get("type")
        if t == "requestfailed":
            reqfailed.append(e)
        elif t == "download":
            downloads.append(e)
        elif t == "response":
            responses.append(e)
    return reqfailed, downloads, responses


def har_entries(har_path: Path):
    har = load_json(har_path)
    return har.get("log", {}).get("entries", [])


def header_map(headers):
    out = {}
    for h in headers or []:
        name = (h.get("name") or "").lower()
        value = h.get("value")
        if name:
            out[name] = value
    return out


def is_download_like(resp_headers: dict):
    ct = (resp_headers.get("content-type") or "").lower()
    cd = (resp_headers.get("content-disposition") or "").lower()

    if "attachment" in cd:
        return True
    if "application/pdf" in ct:
        return True
    if "zip" in ct:
        return True
    if "octet-stream" in ct:
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="trace_out")
    ap.add_argument("--host-filter", default=None, help="例: e2ppiw01.e-bisc.go.jp のみ表示したい時")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    har_path = outdir / "network.har"
    events_path = outdir / "events.jsonl"
    cookies_path = outdir / "cookies.json"

    if not har_path.exists():
        print(f"[NG] HARが見つからん: {har_path}")
        return 1

    entries = har_entries(har_path)
    reqfailed, downloads, responses = parse_events(events_path)

    print("=== trace summary ===")
    print(f"har:     {har_path}  entries={len(entries)}")
    print(f"events:  {events_path}  requestfailed={len(reqfailed)}  download={len(downloads)}  response_events={len(responses)}")
    print(f"cookies: {cookies_path}  exists={cookies_path.exists()}")

    hosts = []
    for e in entries:
        url = e.get("request", {}).get("url", "")
        if not url:
            continue
        h = urlparse(url).hostname
        if h:
            hosts.append(h)

    host_counts = Counter(hosts)
    print("\n=== hosts in HAR (top 20) ===")
    for h, c in host_counts.most_common(20):
        if args.host_filter and args.host_filter not in h:
            continue
        print(f"- {h:45s} {c}")

    if reqfailed:
        print("\n=== requestfailed (top 30) ===")
        for e in reqfailed[:30]:
            url = e.get("url", "")
            if args.host_filter and args.host_filter not in url:
                continue
            failure = e.get("failure") or {}
            print(f"- {url}")
            if failure:
                print(f"    failure: {failure}")

    dl_candidates = []
    for e in entries:
        req = e.get("request", {})
        res = e.get("response", {})
        url = req.get("url", "")
        if not url:
            continue
        if args.host_filter and args.host_filter not in url:
            continue

        status = res.get("status", 0)
        resp_headers = header_map(res.get("headers", []))
        if is_download_like(resp_headers):
            dl_candidates.append({
                "status": status,
                "url": url,
                "content_type": resp_headers.get("content-type"),
                "content_disposition": resp_headers.get("content-disposition"),
                "req_method": req.get("method"),
                "req_headers": header_map(req.get("headers", [])),
            })

    print("\n=== download-like entries in HAR ===")
    if not dl_candidates:
        print("(none)  ※DL操作が記録されてない or サイトがattachmentで返してない可能性")
    else:
        for i, d in enumerate(dl_candidates[:30], 1):
            print(f"{i:02d}. {d['status']} {d['req_method']} {d['url']}")
            if d["content_type"]:
                print(f"    content-type: {d['content_type']}")
            if d["content_disposition"]:
                print(f"    content-disposition: {d['content_disposition']}")

        best = dl_candidates[0]
        print("\n=== requests reproduction hint (headers) ===")
        h = best["req_headers"]
        keep = ["user-agent", "accept", "accept-language", "referer", "origin", "cookie"]
        for k in keep:
            if k in h:
                v = h[k]
                if k == "cookie":
                    v = "(cookie omitted)"
                print(f"{k}: {v}")

        print("\n※cookieは cookies.json からSessionに入れて再現するのが安全")

    if downloads:
        print("\n=== playwright download events ===")
        for d in downloads[:20]:
            print(f"- {d.get('url')}  filename={d.get('suggested_filename')}")

    print("\n[done]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())