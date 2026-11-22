# Kochi Lead Gen

## Setup
```
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
cp .env.example .env   # set GOOGLE_PLACES_API_KEY
```

## Commands
```
lg discover [--refresh] [--limit-zones N] [--category C ...]
lg classify [--refresh]
lg audit [--refresh]
lg score
lg run    # discover, classify, audit, score; prints counts
```

## UI
```
streamlit run app.py
```

Reminder: set a daily quota cap on the Google Places API key in Google Cloud, and a ₹100 budget alert in Billing.
