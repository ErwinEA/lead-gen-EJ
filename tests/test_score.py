from datetime import date

from lg.audit import extract_signals
from lg.score import priority, tier

T = date(2026, 11, 22)
CFG = {"priority": {"need": {"NONE": 40, "SOCIAL": 40, "DIRECTORY": 40, "DEAD": 35, "OLD": 30, "DATED": 15, "MODERN": 0},
                    "tier_a": 70, "tier_b": 45}}


def sig(html, url="https://a.com", ok=True, load=1.0, w=1000, wb=None):
    return {s["signal"]: s["points"] for s in extract_signals(html, url, ok, load, w, wb, T)}


def test_modern_clean():
    h = '<meta name="viewport" content="x">© 2026'
    assert sig(h) == {}


def test_all_bad():
    h = "<html>© 2015 <frameset></frameset></html>"
    s = sig(h, url="http://a.com", load=6, wb=date(2020, 1, 1))
    assert s == {"no_https": 20, "no_viewport": 20, "old_copyright": 20, "wayback_stale": 25,
                 "old_tech": 10, "heavy_slow": 5}


def test_mid_tiers():
    h = '<meta name="viewport" content="x">Copyright 2024'
    assert sig(h, wb=date(2023, 6, 1)) == {"old_copyright": 10, "wayback_stale": 10}
    assert sig(h, wb=date(2025, 6, 1)) == {"old_copyright": 10}


def test_https_invalid_and_weight():
    h = '<meta name="viewport" content="x">'
    assert sig(h, ok=False, w=6 * 1024 * 1024) == {"no_https": 20, "heavy_slow": 5}


def test_priority_tier():
    assert priority("NONE", None, 100, 4.5, "999", 10, CFG) == 100
    assert priority("LIVE", "OLD", 40, 3.5, "", 8, CFG) == 53
    assert priority("LIVE", "MODERN", 0, None, "", 8, CFG) == 8
    assert [tier(x, CFG) for x in (70, 69, 45, 44)] == ["A", "B", "B", "C"]
