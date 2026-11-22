"""Priority score + tier. Writes only Lead.priority_score and Lead.tier."""
from sqlmodel import select

from . import config
from .db import Lead, Place, SiteCheck, init_db, session


def priority(web_status, label, review_count, rating, phone, cat_weight, cfg=None) -> int:
    cfg = cfg or config.load()
    need_map = cfg["priority"]["need"]
    key = (label or "MODERN") if web_status == "LIVE" else web_status
    need = need_map.get(key, 0)
    activity = min(review_count or 0, 100) / 4
    r = rating or 0
    rate = 10 if r >= 4.0 else 5 if r >= 3.0 else 0
    reach = 15 if phone else 0
    return round(need + activity + rate + reach + cat_weight)


def tier(score, cfg=None) -> str:
    p = (cfg or config.load())["priority"]
    return "A" if score >= p["tier_a"] else "B" if score >= p["tier_b"] else "C"


def run() -> int:
    cfg = config.load()
    init_db()
    n = 0
    with session() as s:
        rows = s.exec(select(Place, SiteCheck).where(
            Place.place_id == SiteCheck.place_id, Place.dropped_reason == None)).all()  # noqa: E711
        for p, sc in rows:
            if not sc.web_status:
                continue
            w = cfg["categories"].get(p.category, {}).get("weight", 0)
            score = priority(sc.web_status, sc.staleness_label, p.review_count, p.rating, p.phone, w, cfg)
            lead = s.get(Lead, p.place_id) or Lead(place_id=p.place_id)
            lead.priority_score, lead.tier = score, tier(score, cfg)
            s.add(lead)
            s.commit()
            n += 1
    return n
