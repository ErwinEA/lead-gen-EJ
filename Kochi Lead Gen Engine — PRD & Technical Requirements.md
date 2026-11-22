# Kochi Lead Gen Engine — PRD & Technical Requirements

Nov 22, 2026 · @erwin

## Overview

The engine is a personal, local tool that finds Kochi businesses in three categories (reefer transport, logistics warehouses, construction contractors) on Google Maps and flags the ones with no website, only a social or directory page, a dead site, or a site that looks outdated. It outputs a ranked lead list, which Erwin then researches by hand and approaches in person or by phone to sell a website plus SEO and GEO, priced at around ₹20,000–30,000.

**Problem.** Finding these businesses by hand means searching Maps one query at a time, opening every website, and judging its age by eye. That's slow and inconsistent, and nothing records who has already been checked or contacted.

**Goals**

- Sweep all three categories across Kochi in one run, within Google's free monthly tier.
- Classify every business's web presence automatically, using signals that can be explained.
- Rank leads so the best prospects are reviewed first.
- Track research notes and outreach status for each lead in one place.

**Non-goals**

- No AI agent or automated background research. Research stays manual.
- No automated outreach: no bulk email, SMS, WhatsApp or calling.
- No other categories or cities, no multi-user access, no hosting, and nothing is sold or shared.

## Scope

The engine covers three categories inside a Kochi bounding box. It runs on Erwin's laptop for one user, at ₹0 recurring cost.

| Category | Seed search phrases (editable in config) | Exclude |
| --- | --- | --- |
| Reefer transport | reefer transport, refrigerated truck service, cold chain logistics, reefer container transport, refrigerated van rental | Cold storage that only stores (that belongs under warehouses) |
| Logistics warehouses | warehouse, warehousing services, logistics warehouse, 3PL logistics, godown for rent, container freight station, cold storage warehouse | Self-storage for households, courier franchise counters |
| Construction contractors | construction company, building contractor, civil contractor, PWD contractor, construction contractors | Interior designers, hardware shops, real estate brokers |

**Geography.** A configurable rectangle over the Kochi urban area, split into search zones so each query returns local results. Starting zones: Ernakulam city (MG Road, Kaloor), Edappally, Palarivattom, Vyttila, Kakkanad, Kalamassery, Eloor–Edayar, Aluva, Nedumbassery, Willingdon Island, Vallarpadam, Mattancherry–Fort Kochi, Thrippunithura, Maradu–Kundannoor, Cheranalloor.

**Constraints**

- Personal use only. Data stays on the local machine.
- Free: Google Places API free tier, free libraries, no paid hosting.
- Solo build, minimal UI.

**Open questions**

- Should the boundary include Angamaly and Perumbavoor, which sit outside the urban core but may have many warehouses?
- Should "builders" (real estate developers) count as construction contractors?

## Functional requirements

The engine has six capabilities. FR-1 to FR-4 are automated, and FR-5 and FR-6 are where Erwin works.

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-1 | **Discover.** Run every category phrase × zone through Google Places Text Search and store each result. | Re-running a sweep creates no duplicates (dedupe on place ID, then on normalised phone). Each lead records which query and zone found it. |
| FR-2 | **Filter.** Keep only operational businesses in scope. | Drop entries whose business status isn't OPERATIONAL, whose address doesn't contain Kochi, Ernakulam or a zone name, or that match an exclude keyword. Dropped rows are kept with a reason, so they can be reviewed. |
| FR-3 | **Classify the web presence.** Put every lead in one bucket: NONE, SOCIAL (Facebook, Instagram, Linktree, wa.me), DIRECTORY (JustDial, IndiaMART, Sulekha, TradeIndia, old business.site links), DEAD (DNS failure, timeout, 4xx or 5xx error, parked or for-sale page), or LIVE. | The classifier agrees with Erwin's manual label on at least 90% of a 50-lead sample. |
| FR-4 | **Audit staleness.** For LIVE sites, compute a 0–100 staleness score from explainable signals, take a mobile screenshot, and label the site OLD, DATED or MODERN. | Every score shows the signals behind it. OLD sites match Erwin's judgement on at least 80% of 30 labelled sites. |
| FR-5 | **Rank and review.** Compute a priority score and tier (A, B or C), list leads sorted by priority, and filter by category, web status, tier and pipeline status. | Tier A leads appear first. Each lead shows its Maps link, phone (tap-to-call), screenshot and signals. |
| FR-6 | **Track research and outreach.** Store manual fields for each lead: pipeline status, notes, years in business, GSTIN or CIN, estimated size, budget fit for ₹20–30k, next action date. Export to CSV. | Manual fields survive re-runs of FR-1 to FR-4. The CSV export opens in Sheets or Excel. |

**Pipeline statuses:** New → Researching → Qualified → Contacted → Meeting → Won / Lost / Not a fit / Do not contact.

## Flow

&#91;embedded content: lead gen pipeline · 8 stages, 1 branch\]

Leads with no web presence skip the audit and go straight to scoring. Only LIVE sites get screenshots and the Wayback check. Manual review and outreach save their status to the same database, so the next run keeps it.

**A typical session**

1. Run `lg run` (about an hour for a full sweep, or minutes for a refresh).
2. Open the app and filter to tier A with pipeline status New.
3. For each lead, check the screenshot and signals, then research it by hand (GST portal, MCA, the firm's own pages) and fill in the research fields.
4. Mark the lead Qualified or Not a fit, then visit or call the qualified ones.
5. Update the status and next action date after each contact.

## Technical requirements

The engine is a local Python pipeline that writes to one SQLite file, with a Streamlit page on top. There's no server, no cloud database and no background jobs.

### Architecture

- **`discover`** calls Places API (New) Text Search with a `locationRestriction` rectangle per zone and `pageSize` 20, following `nextPageToken` up to 3 pages. Field mask: `places.id, displayName, formattedAddress, nationalPhoneNumber, websiteUri, googleMapsUri, rating, userRatingCount, businessStatus, types`. Requesting the website and phone fields puts every call in the Enterprise SKU, which is free for 1,000 requests a month and $35 per 1,000 after that.
- **`classify`** resolves DNS and fetches the site with httpx (10 s timeout, follow redirects, record the final URL and TLS validity). It matches the host against social and directory lists and detects parked pages by keywords and known parking nameservers.
- **`audit`** loads LIVE sites in headless Chromium (Playwright, 390 px mobile viewport), saves a screenshot, extracts the signals below, and queries the Wayback CDX API for the last content change.
- **`score`** computes the staleness score, priority score and tier.
- **`app`** is the Streamlit UI. It reads and writes the same SQLite file.

Each stage is a CLI command (`lg discover`, `lg classify`, `lg audit`, `lg score`, or `lg run` for all four). Stages are idempotent and resumable: each skips leads already processed unless `--refresh` is passed.

### Data model (SQLite)

| Table | Key columns |
| --- | --- |
| `runs` | id, started\_at, finished\_at, api\_requests\_used, notes |
| `places` | place\_id (PK), name, category, address, phone, website\_uri, maps\_uri, rating, review\_count, business\_status, types\_json, first\_seen\_run, last\_seen\_run, dropped\_reason |
| `query_hits` | run\_id, category, phrase, zone, place\_id |
| `site_checks` | place\_id, checked\_at, final\_url, http\_status, https\_ok, dns\_ok, parked, web\_status, staleness\_score, staleness\_label, signals\_json, wayback\_last\_change, screenshot\_path |
| `leads` | place\_id (PK), priority\_score, tier, pipeline\_status, notes, years\_in\_business, gstin, cin, est\_size, budget\_fit, next\_action\_date, last\_contacted, updated\_at |

Automated stages never write to the manual columns in `leads`.

### Staleness score (LIVE sites only, 0–100)

| Signal | How it's detected | Points |
| --- | --- | --- |
| No HTTPS, or an invalid or expired certificate | Final URL scheme, TLS error | 20 |
| Not mobile-friendly | No `<meta name=viewport>` | 20 |
| Old copyright year | Footer regex for © or "copyright" followed by a year. 4 or more years old scores 20; 2–3 years scores 10 | 20 / 10 |
| No content change in the archive | Wayback CDX, `collapse=digest`, last distinct capture. 4 or more years ago scores 25; 2–4 years scores 10 | 25 / 10 |
| Old technology | Generator meta (old WordPress or Joomla), Flash, framesets, table layout, jQuery 1.x | 10 |
| Heavy or slow | Load time over 5 s, or page weight over 5 MB | 5 |

A score of 50 or more is OLD, 25–49 is DATED, and under 25 is MODERN. Thresholds live in config and are calibrated on 30 hand-labelled sites. HTTP `Last-Modified` and `htmldate` results are stored for reference but don't score, because servers often report false dates.

### Priority score (0–100)

```latex
priority = need + activity + rating + reach + category
```

- **Need (0–40):** NONE, SOCIAL or DIRECTORY scores 40, DEAD 35, OLD 30, DATED 15, MODERN 0.
- **Activity (0–25):** min(review\_count, 100) ÷ 4. Review count is a rough proxy for size.
- **Rating (0–10):** 4.0 or higher scores 10, 3.0–3.9 scores 5.
- **Reach (0–15):** 15 if a phone number is listed.
- **Category (0–10):** a weight per category, set in config.

Tier A is 70 or more, B is 45–69, and C is under 45.

### Non-functional requirements

- **Cost:** a full Kochi sweep stays under 900 Enterprise requests, with a hard daily quota cap and a budget alert set in Google Cloud.
- **Rate limits:** Wayback at 20 requests a minute or fewer, with backoff on HTTP 429. Site fetches at 5 concurrent at most, with a 10 s timeout.
- **Runtime:** a full run finishes in under 60 minutes on a laptop.
- **Security:** the API key lives in `.env`, which is git-ignored. The database and screenshots stay on the local disk.
- **Reliability:** each stage commits per lead, so a crash loses at most one lead's work.

## Tech stack and cost

The whole stack is free. The only possible charge is Google Places usage beyond the free 1,000 Enterprise requests a month, and a quota cap prevents that.

| Layer | Choice | Why | Cost |
| --- | --- | --- | --- |
| Language | Python 3.12 | One language covers the pipeline and the UI | Free |
| Business data | [Google Places API (New)](https://developers.google.com/maps/documentation/places/web-service/data-fields), Text Search | Gives website, phone, rating and reviews in one call | 1,000 free Enterprise requests a month, then $35 per 1,000 ([pricing](https://developers.google.com/maps/billing-and-pricing/pricing)). A billing account with a card is required |
| HTTP | httpx (async), dnspython, tldextract | Fast concurrent fetches, DNS checks, clean domain parsing | Free |
| HTML parsing | selectolax or BeautifulSoup, htmldate | Signal extraction and a date fallback | Free |
| Browser | Playwright with Chromium | Mobile screenshots, load timing, JS-rendered pages | Free |
| Archive | Wayback Machine CDX API | Last content change date | Free, rate-limited |
| Storage | SQLite with SQLModel | One file, no server, easy to back up | Free |
| CLI | Typer | `lg run` and the per-stage commands | Free |
| UI | Streamlit (`st.data_editor`) | An editable table with filters in about 150 lines | Free |
| Config | YAML, `.env` for the key | Phrases, zones, weights and thresholds editable without code changes | Free |

**Total recurring cost: ₹0**, assuming a sweep stays inside the free tier.

## Minimal UI

The UI is one Streamlit app with three tabs. It uses default styling, so no custom design work is needed.

1. **Run.** Buttons for each stage and for a full run. Shows this month's API requests used out of 1,000, the last run's counts (found, kept, dropped, by web status), and a live log.
2. **Leads.** An editable table sorted by priority. Columns: tier, priority, name, category, web status, staleness label, reviews, rating, phone, pipeline status, next action date. Sidebar filters cover category, web status, tier, pipeline status and zone. Pipeline status, notes and the research fields can be edited inline. An "Export CSV" button exports the current filtered view.
3. **Lead detail.** Opened by picking a row. Shows the mobile screenshot, every staleness signal with its points, and links to Google Maps, the website, `tel:` for calling and `wa.me` for a manual WhatsApp message. Includes a notes box and a "Mark do-not-contact" button.

The app runs with `streamlit run app.py` and opens at `localhost:8501`.

## Risks, milestones and success

The biggest risk is Google's terms. The biggest unknown is how many in-scope Kochi businesses are on Maps at all, and the pilot answers that.

### Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| [Google Maps Platform terms](https://cloud.google.com/maps-platform/terms) bar saving business names and addresses, and bar point-in-polygon analysis on Places coordinates | API key suspended | Personal use only, nothing shared. Filter by `locationRestriction` and address text, never by coordinates. Decision needed: accept the risk, or store only place IDs and re-fetch details when a lead is viewed (which costs requests) |
| Quota overrun | Unexpected charge | Daily quota cap and a ₹100 budget alert in Google Cloud, plus a request counter in the Run tab |
| Small contractors missing from Maps | Smaller lead pool | Accept it. The pilot measures coverage |
| Category noise (an interior designer tagged as a contractor) | Wasted reviews | Exclude keywords, and Erwin marks a lead "Not a fit" so it's suppressed on future runs |
| Wayback blocks requests (HTTP 429) | Missing archive signal | Throttle, back off, and score without that signal (noted on the lead) |
| India TRAI rules on promotional calls | Penalty risk if calling at volume | Prefer in-person visits. Make only individual, manual calls, and check the rules before calling at any volume |
| DPDP Act: proprietors' phone numbers are personal data | Compliance exposure | Keep data local, honour do-not-contact, and delete leads untouched for 12 months |

### Milestones (estimated, solo)

1. **M1 — Discover (2 days).** Config, Places client, SQLite schema, dedupe. Done when one category × three zones lands in the database.
2. **M2 — Classify (1 day).** DNS and HTTP checks, social and directory lists, parked-page detection.
3. **M3 — Audit (2 days).** Playwright screenshots, signal extraction, Wayback client, staleness score.
4. **M4 — Score and UI (2 days).** Priority and tiers, plus the Streamlit Run, Leads and Detail tabs, and CSV export.
5. **M5 — Pilot and calibrate (3–5 days).** Full Kochi sweep, label 50 web statuses and 30 staleness cases by hand, tune thresholds, then visit or call 20 tier A leads.

### Success criteria

- At least 150 unique in-scope businesses found across the three categories.
- FR-3 at 90% or better and FR-4 at 80% or better against manual labels.
- A full sweep uses fewer than 1,000 Enterprise requests.
- At least 20 leads that Erwin rates Qualified after manual research.
- Business test, decided after M5: at least 2 of the 20 contacted tier A leads agree to a meeting.
