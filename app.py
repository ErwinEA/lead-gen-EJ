"""Streamlit UI: Run / Leads / Lead detail. Writes only Lead manual columns."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml
from sqlmodel import select, func

from lg.db import Lead, Place, QueryHit, Run, SiteCheck, init_db, session

ROOT = Path(__file__).resolve().parent
STATUSES = ["New", "Researching", "Qualified", "Contacted", "Meeting", "Won", "Lost",
            "Not a fit", "Do not contact"]
MANUAL = ["pipeline_status", "notes", "years_in_business", "gstin", "cin", "est_size",
          "budget_fit", "next_action_date"]
CAP = yaml.safe_load((ROOT / "config.yaml").read_text())["places"]["monthly_free_requests"]
STAGES = {"Discover": "discover", "Classify": "classify", "Audit": "audit", "Score": "score"}

st.set_page_config(page_title="Lead Gen", layout="wide")
init_db()


def run_stage(mod):
    import importlib
    return importlib.import_module(f"lg.{mod}").run()  # lazy: modules written in parallel


@st.cache_data(ttl=5)
def load():
    with session() as s:
        rows = s.exec(
            select(Place, SiteCheck, Lead)
            .outerjoin(SiteCheck, SiteCheck.place_id == Place.place_id)
            .outerjoin(Lead, Lead.place_id == Place.place_id)
            .where(Place.dropped_reason == None)  # noqa: E711
        ).all()
        zones = {}
        for pid, z in s.exec(select(QueryHit.place_id, QueryHit.zone)).all():
            zones.setdefault(pid, set()).add(z)
    out = []
    for p, c, l in rows:
        l = l or Lead(place_id=p.place_id)
        out.append(dict(
            place_id=p.place_id, tier=l.tier or "", priority=l.priority_score or 0,
            name=p.name, category=p.category, web_status=c.web_status if c else "",
            staleness=c.staleness_label if c else None, reviews=p.review_count,
            rating=p.rating, phone=p.phone, pipeline_status=l.pipeline_status or "New",
            next_action_date=l.next_action_date, notes=l.notes, years_in_business=l.years_in_business,
            gstin=l.gstin, cin=l.cin, est_size=l.est_size, budget_fit=l.budget_fit,
            zones=sorted(zones.get(p.place_id, [])), maps_uri=p.maps_uri, website=p.website_uri,
            screenshot=c.screenshot_path if c else None, signals=c.signals_json if c else "[]"))
    df = pd.DataFrame(out)
    if df.empty:
        return df
    df["_t"] = df.tier.map({"A": 0, "B": 1, "C": 2}).fillna(3)
    return df.sort_values(["_t", "priority"], ascending=[True, False]).drop(columns="_t").reset_index(drop=True)


def save_lead(pid, **vals):  # the only write path; manual columns only
    assert set(vals) <= set(MANUAL)
    with session() as s:
        lead = s.get(Lead, pid) or Lead(place_id=pid)
        for k, v in vals.items():
            v = None if pd.isna(v) else v
            if k == "years_in_business" and v is not None:
                v = int(v)  # editor returns float
            setattr(lead, k, v)
        lead.updated_at = datetime.now(timezone.utc)
        s.add(lead)
        s.commit()
    load.clear()


tab_run, tab_leads, tab_detail = st.tabs(["Run", "Leads", "Lead detail"])

with tab_run:
    cols = st.columns(len(STAGES))
    for col, (label, mod) in zip(cols, STAGES.items()):
        if col.button(f"Run {label}", key=mod):
            with st.spinner(f"{label}..."):
                try:
                    run_stage(mod)
                    load.clear()
                    col.success("done")
                except Exception as e:
                    col.error(str(e))
    now = datetime.now(timezone.utc)
    with session() as s:
        used = s.exec(select(func.sum(Run.api_requests_used)).where(
            Run.started_at >= datetime(now.year, now.month, 1, tzinfo=timezone.utc))).one() or 0
        last = s.exec(select(Run).order_by(Run.id.desc())).first()
        if last:
            seen = s.exec(select(Place).where(Place.last_seen_run == last.id)).all()
            ids = [p.place_id for p in seen]
            by_web = pd.Series([c.web_status for c in s.exec(select(SiteCheck)).all()
                                if c.place_id in ids]).value_counts()
    st.metric("API requests this month", f"{used} / {CAP}")
    st.progress(min(used / CAP, 1.0))
    if last:
        kept = sum(p.dropped_reason is None for p in seen)
        st.write(f"Last run #{last.id}: found {len(seen)}, kept {kept}, dropped {len(seen) - kept}")
        st.write(by_web.to_dict())

df = load()
with st.sidebar:
    st.header("Filters")
    f = {}
    if not df.empty:
        for key, label in [("category", "Category"), ("web_status", "Web status"),
                           ("tier", "Tier"), ("pipeline_status", "Pipeline status")]:
            f[key] = st.multiselect(label, sorted(df[key].unique()))
        zone_opts = sorted({z for zs in df.zones for z in zs})
        zsel = st.multiselect("Zone", zone_opts)
view = df
if not df.empty:
    for key, sel in f.items():
        if sel:
            view = view[view[key].isin(sel)]
    if zsel:
        view = view[view.zones.map(lambda zs: bool(set(zs) & set(zsel)))]

SHOW = ["place_id", "tier", "priority", "name", "category", "web_status", "staleness", "reviews",
        "rating", "phone", "pipeline_status", "next_action_date", "notes", "years_in_business",
        "gstin", "cin", "est_size", "budget_fit"]
with tab_leads:
    if view.empty:
        st.info("No leads yet. Run the stages first.")
    else:
        base = view[SHOW].set_index("place_id")
        edited = st.data_editor(
            base, key="editor", width="stretch",
            disabled=[c for c in base.columns if c not in MANUAL],
            column_config={
                "pipeline_status": st.column_config.SelectboxColumn(options=STATUSES, required=True),
                "next_action_date": st.column_config.TextColumn(help="YYYY-MM-DD"),
                "years_in_business": st.column_config.NumberColumn(step=1)})
        changed = [pid for pid in base.index if not base.loc[pid, MANUAL].equals(edited.loc[pid, MANUAL])
                   and not (base.loc[pid, MANUAL].fillna("") == edited.loc[pid, MANUAL].fillna("")).all()]
        if changed and st.button(f"Save {len(changed)} changed"):
            for pid in changed:
                save_lead(pid, **edited.loc[pid, MANUAL].to_dict())
            st.rerun()
        st.download_button("Export CSV", view[SHOW[1:]].to_csv(index=False).encode(),
                           "leads.csv", "text/csv")

with tab_detail:
    if df.empty:
        st.info("No leads.")
    else:
        opts = dict(zip(df.place_id, df.tier.fillna("-") + " " + df.name))
        pid = st.selectbox("Lead", list(opts), format_func=opts.get, key="lead_pick")
        r = df[df.place_id == pid].iloc[0].fillna("")  # missing values arrive as NaN
        a, b = st.columns(2)
        with a:
            shot = ROOT / r.screenshot if isinstance(r.screenshot, str) and r.screenshot else None  # ROOT / abs path = abs path
            if shot and shot.exists():
                st.image(str(shot))
            else:
                st.caption("No screenshot")
        with b:
            st.subheader(r["name"])
            st.write(f"{r.web_status} | {r.staleness or '-'} | tier {r.tier or '-'} | priority {r.priority}")
            sigs = json.loads(r.signals or "[]")
            for g in sigs:
                st.write(f"+{g.get('points')}  {g.get('signal')}: {g.get('detail', '')}")
            digits = "".join(ch for ch in r.phone if ch.isdigit())[-10:]
            links = [("Maps", r.maps_uri), ("Website", r.website),
                     ("Call", f"tel:{r.phone}" if digits else ""),
                     ("WhatsApp", f"https://wa.me/91{digits}" if digits else "")]
            st.markdown(" | ".join(f"[{n}]({u})" for n, u in links if u))
        note = st.text_area("Notes", r.notes or "", key=f"n_{pid}")
        c1, c2 = st.columns(2)
        if c1.button("Save notes"):
            save_lead(pid, notes=note)
            st.rerun()
        if c2.button("Mark do-not-contact"):
            save_lead(pid, pipeline_status="Do not contact")
            st.rerun()
