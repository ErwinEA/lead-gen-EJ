"""FR-3: classify each kept place's web presence into NONE/SOCIAL/DIRECTORY/DEAD/LIVE."""
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse

import dns.resolver
import httpx
import tldextract
from sqlmodel import select

from lg import config, db

_tld = tldextract.TLDExtract(suffix_list_urls=())  # offline: bundled PSL snapshot
_transport = None  # tests inject httpx.MockTransport
CONCURRENCY = 5


def _norm(url: str) -> str:
    return url if "://" in url else "https://" + url


def classify_url_host(url: str, cfg: dict | None = None) -> str | None:
    """Return 'NONE', 'SOCIAL', 'DIRECTORY' if host lists decide it, else None."""
    if not url.strip():
        return "NONE"
    cfg = cfg or config.load()
    host = _tld(urlparse(_norm(url.strip())).hostname or "").registered_domain
    if host in cfg["social_hosts"]:
        return "SOCIAL"
    if host in cfg["directory_hosts"]:
        return "DIRECTORY"
    return None


def _dns(host: str, parked_ns: list[str]) -> tuple[bool, bool]:
    """(resolves, on a parked nameserver)."""
    r = dns.resolver.Resolver()
    r.lifetime = 5
    try:
        r.resolve(host, "A")
    except Exception:
        try:
            r.resolve(host, "AAAA")
        except Exception:
            return False, False
    try:
        dom = _tld(host).registered_domain or host
        ns = [str(x).rstrip(".").lower() for x in r.resolve(dom, "NS")]
    except Exception:
        return True, False
    return True, any(n == p or n.endswith("." + p) for n in ns for p in parked_ns)


async def _get(url: str, verify: bool):
    async with httpx.AsyncClient(timeout=10, follow_redirects=True, max_redirects=5,
                                 verify=verify, transport=_transport) as c:
        return await c.get(url)


async def _fetch(url: str):
    """-> (response|None, https_ok|None). Retries with verify=False on connect errors for https."""
    urls = [url] if "://" in url else ["https://" + url, "http://" + url]
    for u in urls:
        try:
            r = await _get(u, True)
            return r, str(r.url).startswith("https")
        except httpx.ConnectError:
            if u.startswith("https"):
                try:
                    return await _get(u, False), False  # TLS invalid (or dead; DEAD if this fails)
                except httpx.HTTPError:
                    pass
        except httpx.HTTPError:
            pass
    return None, None


async def check_site(url: str, cfg: dict) -> dict:
    """Classify one URL; returns SiteCheck field values."""
    pre = classify_url_host(url, cfg)
    if pre:
        return {"web_status": pre}
    host = urlparse(_norm(url.strip())).hostname or ""
    dns_ok, ns_parked = await asyncio.to_thread(_dns, host, cfg["parked_nameservers"])
    out = {"dns_ok": dns_ok, "parked": False, "web_status": "DEAD"}
    if not dns_ok:
        return out
    r, https_ok = await _fetch(url.strip())
    if r is None:
        return out
    out.update(final_url=str(r.url), http_status=r.status_code, https_ok=https_ok)
    body = r.text.lower()
    if ns_parked or any(k in body for k in cfg["parked_keywords"]):
        out["parked"] = True
    elif r.status_code < 400:
        out["web_status"] = "LIVE"
    return out


async def _run(places: list[db.Place], cfg: dict) -> None:
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(p):
        async with sem:
            try:
                return p.place_id, await check_site(p.website_uri, cfg)
            except Exception:  # never let one site kill the sweep
                return p.place_id, {"web_status": "DEAD"}

    for fut in asyncio.as_completed([one(p) for p in places]):
        pid, vals = await fut
        with db.session() as s:
            sc = s.get(db.SiteCheck, pid) or db.SiteCheck(place_id=pid)
            # reset owned fields so refresh doesn't keep stale values; audit fields untouched
            sc.final_url, sc.http_status, sc.https_ok, sc.dns_ok, sc.parked = "", None, None, None, False
            for k, v in vals.items():
                setattr(sc, k, v)
            sc.checked_at = datetime.now(timezone.utc)
            s.add(sc)
            s.commit()


def run(refresh: bool = False) -> None:
    db.init_db()
    cfg = config.load()
    with db.session() as s:
        q = select(db.Place).where(db.Place.dropped_reason.is_(None))
        if not refresh:
            q = q.where(db.Place.place_id.not_in(select(db.SiteCheck.place_id)))
        places = s.exec(q).all()
    asyncio.run(_run(places, cfg))
