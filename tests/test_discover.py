import pytest
from sqlmodel import create_engine, select

from lg import db, discover


def P(i, **kw):
    d = {"id": i, "displayName": {"text": f"Co {i}"}, "formattedAddress": "Kakkanad, Kochi",
         "nationalPhoneNumber": "0484 123 4567", "businessStatus": "OPERATIONAL", "types": ["storage"]}
    d.update(kw)
    return d


@pytest.fixture(autouse=True)
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))


def sweep(places, **kw):
    calls = []
    def post(body, headers):
        calls.append(body)
        return {"places": places}
    discover.run(limit_zones=1, categories=["reefer_transport"], post=post, **kw)
    return calls


def test_dedupe_filter_resume_and_lead_preserved():
    places = [P("a"), P("b", nationalPhoneNumber="+91 484-1234567"),  # same phone as a
              P("c", businessStatus="CLOSED_PERMANENTLY", nationalPhoneNumber="1"),
              P("d", formattedAddress="Mumbai", nationalPhoneNumber="2"),
              P("e", displayName={"text": "Cold storage only Ltd"}, nationalPhoneNumber="3")]
    calls = sweep(places)
    assert len(calls) == 5  # 5 phrases x 1 zone, one page each
    with db.session() as s:
        got = {p.place_id: p.dropped_reason for p in s.exec(select(db.Place))}
        assert set(got) == {"a", "c", "d", "e"}  # b merged into a
        assert got["a"] is None
        assert got["c"].startswith("status") and got["d"].startswith("address")
        assert got["e"].startswith("exclude")
        s.get(db.Lead, "a").notes = "manual"; s.commit()
        assert s.get(db.Run, 1).api_requests_used == 5
    assert sweep(places) == []  # resumed: nothing re-queried
    assert len(sweep(places, refresh=True)) == 5
    with db.session() as s:
        assert s.get(db.Lead, "a").notes == "manual"
        assert len(s.exec(select(db.Lead)).all()) == 4


def test_request_cap(monkeypatch):
    monkeypatch.setattr(discover.config, "load", _capped)
    calls = sweep([P("a")])
    assert len(calls) == 2


def _capped():
    import yaml
    from lg.config import ROOT
    c = yaml.safe_load((ROOT / "config.yaml").read_text())
    c["places"]["sweep_request_cap"] = 2
    return c
