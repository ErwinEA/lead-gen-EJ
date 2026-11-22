"""FR-1 discover + FR-2 filter: Places Text Search sweep of phrase x zone."""
import json
import os
from datetime import datetime, timezone

import httpx
from sqlmodel import func, select

from lg import config, db

URL = "https://places.googleapis.com/v1/places:searchText"
MASK = ("places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
        "places.websiteUri,places.googleMapsUri,places.rating,places.userRatingCount,"
        "places.businessStatus,places.types,nextPageToken")


def _http_post(body: dict, headers: dict) -> dict:
    r = httpx.post(URL, json=body, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def _drop_reason(p: dict, cfg: dict, cat: str) -> str | None:
    if p["business_status"] != "OPERATIONAL":
        return f"status:{p['business_status'] or 'unknown'}"
    addr = p["address"].lower()
    if not any(k.lower() in addr for k in cfg["address_keywords"] + list(cfg["zones"])):
        return "address:out_of_area"
    hay = (p["name"] + " " + p["types_json"]).lower()
    for k in cfg["categories"][cat].get("exclude", []):
        if k.lower() in hay:
            return f"exclude:{k}"
    return None


def run(refresh: bool = False, limit_zones: int | None = None,
        categories: list[str] | None = None, post=None) -> int:
    """Returns run id. `post(body, headers) -> dict` is injectable for tests."""
    post = post or _http_post
    cfg = config.load()
    pl = cfg["places"]
    headers = {"X-Goog-Api-Key": os.environ.get("GOOGLE_PLACES_API_KEY", ""),
               "X-Goog-FieldMask": MASK}
    zones = list(cfg["zones"].items())[:limit_zones]
    cats = {c: v for c, v in cfg["categories"].items() if not categories or c in categories}
    db.init_db()
    with db.session() as s:
        r = db.Run(started_at=datetime.now(timezone.utc))
        s.add(r); s.commit(); s.refresh(r)
        rid = r.id
        now = datetime.now(timezone.utc)
        month_used = s.exec(select(func.coalesce(func.sum(db.Run.api_requests_used), 0)).where(
            db.Run.started_at >= datetime(now.year, now.month, 1, tzinfo=timezone.utc),
            db.Run.id != rid)).one()  # earlier runs this month
        done = set() if refresh else {
            (h.phrase, h.zone) for h in s.exec(select(db.QueryHit))}
        try:
            for cat, cv in cats.items():
                for phrase in cv["phrases"]:
                    for zone, box in zones:
                        if (phrase, zone) in done:
                            continue
                        token = None
                        for _ in range(pl["max_pages"]):
                            if month_used + r.api_requests_used >= min(pl["sweep_request_cap"], pl["monthly_free_requests"]):
                                r.notes = "aborted: request cap"
                                return rid
                            body = {"textQuery": phrase, "pageSize": pl["page_size"],
                                    "locationRestriction": {"rectangle": {
                                        "low": {"latitude": box["low"][0], "longitude": box["low"][1]},
                                        "high": {"latitude": box["high"][0], "longitude": box["high"][1]}}}}
                            if token:
                                body["pageToken"] = token
                            r.api_requests_used += 1
                            data = post(body, headers)
                            for raw in data.get("places", []):
                                _save(s, cfg, r, cat, phrase, zone, raw)
                            token = data.get("nextPageToken")
                            if not token:
                                break
        finally:
            r.finished_at = datetime.now(timezone.utc)
            s.add(r); s.commit()
    return rid


def _save(s, cfg, r, cat, phrase, zone, raw) -> None:
    phone = raw.get("nationalPhoneNumber", "")
    norm = "".join(c for c in phone if c.isdigit())[-10:]
    p = dict(
        place_id=raw["id"], name=raw.get("displayName", {}).get("text", ""), category=cat,
        address=raw.get("formattedAddress", ""), phone=phone, phone_norm=norm,
        website_uri=raw.get("websiteUri", ""), maps_uri=raw.get("googleMapsUri", ""),
        rating=raw.get("rating"), review_count=raw.get("userRatingCount", 0),
        business_status=raw.get("businessStatus", ""), types_json=json.dumps(raw.get("types", [])))
    row = s.get(db.Place, p["place_id"])
    if not row and norm:  # same business under a new place_id
        row = s.exec(select(db.Place).where(db.Place.phone_norm == norm)).first()
    if row:
        pid, cat = row.place_id, row.category
        for k, v in p.items():
            if k not in ("place_id", "category"):
                setattr(row, k, v)
        row.last_seen_run = r.id
    else:
        pid = p["place_id"]
        row = db.Place(**p, first_seen_run=r.id, last_seen_run=r.id)
    row.dropped_reason = _drop_reason(p, cfg, cat)
    s.add(row)
    s.add(db.QueryHit(run_id=r.id, category=cat, phrase=phrase, zone=zone, place_id=pid))
    if not s.get(db.Lead, pid):
        s.add(db.Lead(place_id=pid))
    s.commit()
