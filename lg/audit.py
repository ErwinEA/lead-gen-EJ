"""FR-4: staleness audit of LIVE sites."""
import json
import re
import time
from datetime import date, datetime, timezone

import httpx
from sqlmodel import select

from . import config
from .config import ROOT
from .db import SiteCheck, init_db, session

CDX = "https://web.archive.org/cdx/search/cdx"
_last_req = 0.0


def _years(d: date, today: date) -> float:
    return (today - d).days / 365.25


def extract_signals(html, final_url, https_ok, load_s, weight_bytes, wayback_last_change_date, today) -> list[dict]:
    out = []

    def add(signal, points, detail):
        out.append({"signal": signal, "points": points, "detail": detail})

    low = (html or "").lower()
    if not final_url.lower().startswith("https://") or https_ok is False:
        add("no_https", 20, "no HTTPS or invalid certificate")
    if not re.search(r'<meta[^>]+name=["\']?viewport', low):
        add("no_viewport", 20, "no viewport meta")
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)[^0-9<]{0,40}((?:19|20)\d{2})", html or "", re.I)]
    if years:
        age = today.year - max(years)
        if age >= 4:
            add("old_copyright", 20, f"copyright {max(years)}")
        elif age >= 2:
            add("old_copyright", 10, f"copyright {max(years)}")
    if wayback_last_change_date:
        age = _years(wayback_last_change_date, today)
        if age >= 4:
            add("wayback_stale", 25, f"last change {wayback_last_change_date}")
        elif age >= 2:
            add("wayback_stale", 10, f"last change {wayback_last_change_date}")
    old = []
    g = re.search(r'<meta[^>]+name=["\']generator["\'][^>]*content=["\']([^"\']+)', html or "", re.I)
    if g:
        m = re.match(r"(wordpress|joomla!?)\s*([\d.]+)", g.group(1), re.I)
        if m:
            major = int(m.group(2).split(".")[0])
            if (m.group(1).lower() == "wordpress" and major < 5) or (m.group(1).lower().startswith("joomla") and major < 4):
                old.append(g.group(1))
    if ".swf" in low or "application/x-shockwave-flash" in low:
        old.append("flash")
    if "<frameset" in low:
        old.append("frameset")
    if re.search(r"jquery[-.@/]?(?:min[-.])?v?1\.\d", low):
        old.append("jquery 1.x")
    if low.count("<table") >= 5 and low.count("<table") > low.count("<div"):
        old.append("table layout")  # ponytail: crude count heuristic
    if old:
        add("old_tech", 10, ", ".join(old))
    if (load_s or 0) > 5 or (weight_bytes or 0) > 5 * 1024 * 1024:
        add("heavy_slow", 5, f"{load_s:.1f}s, {weight_bytes / 1e6:.1f}MB")
    return out


def wayback_last_change(url: str) -> date:
    """Raise on failure. Throttled to <=20 req/min, backoff on 429."""
    global _last_req
    for attempt in range(4):
        time.sleep(max(0, 3.0 - (time.time() - _last_req)))
        _last_req = time.time()
        r = httpx.get(CDX, params={"url": url, "output": "json", "fl": "timestamp,digest",
                                   "collapse": "digest"}, timeout=30)
        if r.status_code == 429:
            time.sleep(15 * 2 ** attempt)
            continue
        r.raise_for_status()
        rows = r.json()[1:]
        if not rows:
            raise LookupError("no captures")
        ts = rows[-1][0]  # CDX sorted ascending
        return date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
    raise RuntimeError("429 after retries")


def _label(score, cfg):
    t = cfg["staleness"]
    return "OLD" if score >= t["old_at"] else "DATED" if score >= t["dated_at"] else "MODERN"


def _render(page, url, shot):
    weight = [0]

    def on_resp(resp):
        try:
            weight[0] += len(resp.body())
        except Exception:
            pass

    page.on("response", on_resp)
    t = time.time()
    page.goto(url, timeout=30000, wait_until="load")
    load_s = time.time() - t
    page.screenshot(path=str(shot), full_page=False)
    return page.content(), load_s, weight[0]


def run(refresh=False) -> int:
    from playwright.sync_api import sync_playwright
    cfg = config.load()
    init_db()
    (ROOT / "screenshots").mkdir(exist_ok=True)
    today = date.today()
    n = 0
    with session() as s, sync_playwright() as pw:
        q = select(SiteCheck).where(SiteCheck.web_status == "LIVE")
        if not refresh:
            q = q.where(SiteCheck.audited_at == None)  # noqa: E711
        browser = pw.chromium.launch()
        for sc in s.exec(q).all():
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
            page = ctx.new_page()
            shot = ROOT / "screenshots" / f"{sc.place_id}.png"
            try:
                html, load_s, weight = _render(page, sc.final_url, shot)
            except Exception as e:
                ctx.close()
                print(f"audit skip {sc.place_id}: {e}")  # stays unaudited, retried next run
                continue
            ctx.close()
            notes = []
            wb = None
            try:
                wb = wayback_last_change(sc.final_url)
            except Exception as e:
                notes.append({"signal": "note", "points": 0, "detail": f"wayback unavailable: {e}"})
            sig = extract_signals(html, sc.final_url, sc.https_ok, load_s, weight, wb, today) + notes
            try:
                from htmldate import find_date
                d = find_date(html)
                if d:
                    sig.append({"signal": "htmldate", "points": 0, "detail": d})
            except Exception:
                pass
            score = min(100, sum(x["points"] for x in sig))
            sc.staleness_score, sc.staleness_label = score, _label(score, cfg)
            sc.signals_json = json.dumps(sig)
            sc.wayback_last_change = wb.isoformat() if wb else None
            sc.screenshot_path = str(shot)
            sc.audited_at = datetime.now(timezone.utc)
            s.add(sc)
            s.commit()
            n += 1
        browser.close()
    return n
