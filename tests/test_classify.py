import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine

from lg import classify, db


@pytest.mark.parametrize("url,want", [
    ("", "NONE"), ("https://www.facebook.com/x", "SOCIAL"), ("wa.me/9199", "SOCIAL"),
    ("http://foo.business.site/", "DIRECTORY"), ("https://www.justdial.com/Kochi", "DIRECTORY"),
    ("https://acme.in", None),
])
def test_host(url, want):
    assert classify.classify_url_host(url) == want


def _setup(monkeypatch, handler, ns_parked=False, dns_ok=True):
    monkeypatch.setattr(classify, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(classify, "_dns", lambda h, p: (dns_ok, ns_parked))
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=__import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()


def _status(web):
    with db.session() as s:
        return {c.place_id: c.web_status for c in s.query(db.SiteCheck)}


def test_run(monkeypatch):
    def handler(req):
        h = req.url.host
        if h == "dead.com": return httpx.Response(500)
        if h == "parked.com": return httpx.Response(200, text="This Domain May Be For Sale")
        return httpx.Response(200, text="hello")
    _setup(monkeypatch, handler)
    with db.session() as s:
        for pid, uri, drop in [("a", "", None), ("b", "https://fb.com/x", None), ("c", "live.com", None),
                               ("d", "dead.com", None), ("e", "parked.com", None), ("f", "live.com", "out")]:
            s.add(db.Place(place_id=pid, website_uri=uri, dropped_reason=drop))
        s.add(db.Lead(place_id="c", notes="keep me"))
        s.commit()
    classify.run()
    got = _status(None)
    assert got == {"a": "NONE", "b": "SOCIAL", "c": "LIVE", "d": "DEAD", "e": "DEAD"}
    with db.session() as s:
        assert s.get(db.SiteCheck, "e").parked is True
        assert s.get(db.SiteCheck, "c").https_ok is True
        assert s.get(db.Lead, "c").notes == "keep me"
    classify.run(refresh=True)
    assert _status(None) == got


def test_tls_retry_and_dns(monkeypatch):
    calls = []
    def handler(req):
        calls.append(1)
        if len(calls) == 1: raise httpx.ConnectError("bad cert")
        return httpx.Response(200, text="ok")
    _setup(monkeypatch, handler)
    import asyncio
    r = asyncio.run(classify.check_site("acme.com", classify.config.load()))
    assert (r["web_status"], r["https_ok"]) == ("LIVE", False)
    monkeypatch.setattr(classify, "_dns", lambda h, p: (False, False))
    assert asyncio.run(classify.check_site("acme.com", classify.config.load()))["web_status"] == "DEAD"
    monkeypatch.setattr(classify, "_dns", lambda h, p: (True, True))
    assert asyncio.run(classify.check_site("acme.com", classify.config.load()))["parked"] is True
