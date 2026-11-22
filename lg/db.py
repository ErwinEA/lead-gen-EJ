"""Shared SQLite schema. All stages import from here."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from sqlmodel import Field, SQLModel, Session, create_engine

DB_PATH = Path(__file__).resolve().parent.parent / "leads.db"
engine = create_engine(f"sqlite:///{DB_PATH}")


class Run(SQLModel, table=True):
    __tablename__ = "runs"
    id: Optional[int] = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    api_requests_used: int = 0
    notes: str = ""


class Place(SQLModel, table=True):
    __tablename__ = "places"
    place_id: str = Field(primary_key=True)
    name: str = ""
    category: str = ""
    address: str = ""
    phone: str = ""
    phone_norm: str = ""  # digits only, last 10; dedupe key
    website_uri: str = ""
    maps_uri: str = ""
    rating: Optional[float] = None
    review_count: int = 0
    business_status: str = ""
    types_json: str = "[]"
    first_seen_run: Optional[int] = None
    last_seen_run: Optional[int] = None
    dropped_reason: Optional[str] = None  # None = kept


class QueryHit(SQLModel, table=True):
    __tablename__ = "query_hits"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    category: str
    phrase: str
    zone: str
    place_id: str


class SiteCheck(SQLModel, table=True):
    __tablename__ = "site_checks"
    place_id: str = Field(primary_key=True)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    final_url: str = ""
    http_status: Optional[int] = None
    https_ok: Optional[bool] = None
    dns_ok: Optional[bool] = None
    parked: bool = False
    web_status: str = ""  # NONE SOCIAL DIRECTORY DEAD LIVE
    staleness_score: Optional[int] = None
    staleness_label: Optional[str] = None  # OLD DATED MODERN
    signals_json: str = "[]"  # [{"signal","points","detail"}]
    wayback_last_change: Optional[str] = None
    screenshot_path: Optional[str] = None
    audited_at: Optional[datetime] = None  # set by audit stage


class Lead(SQLModel, table=True):
    """priority_score/tier written by score; the rest are MANUAL, automated stages never touch them."""
    __tablename__ = "leads"
    place_id: str = Field(primary_key=True)
    priority_score: Optional[int] = None
    tier: Optional[str] = None
    pipeline_status: str = "New"
    notes: str = ""
    years_in_business: Optional[int] = None
    gstin: str = ""
    cin: str = ""
    est_size: str = ""
    budget_fit: str = ""
    next_action_date: Optional[str] = None
    last_contacted: Optional[str] = None
    updated_at: Optional[datetime] = None


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def session() -> Session:
    return Session(engine)
