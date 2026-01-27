# Booli.se Property Listing Scraper

Scrapes all property listings from [booli.se/sok/till-salu](https://www.booli.se/sok/till-salu), visits each individual listing page to extract the **exact "for sale for X days"** count, and sends results via email.

Designed to run on [Railway](https://railway.app) as a scheduled job.

## Features

- 🎯 **Exact day counts** - Visits each listing page to get precise "Bostaden har varit till salu i X dagar"
- 🚀 **Two-phase parallel scraping** - First collects URLs, then scrapes details
- 📅 **Accurate dates** - Converts exact day counts to absolute received dates
- 📧 **Email reports** - Sends HTML report with CSV attachment
- 🔄 **Scheduled runs** - GitHub Actions triggers weekly scrapes
- 🐳 **Docker-based** - Uses Microsoft's Playwright image for reliability

## How It Works

**Phase 1:** Scrapes search result pages to collect all listing URLs (~35 listings per page × ~2,500 pages = ~85,000 URLs)

**Phase 2:** Visits each individual listing page to extract:
- Exact days on Booli (e.g., "till salu i 5 dagar")
- Price, area, rooms, floor
- Monthly fee
- Page views
- Coming soon status

## Quick Setup

### 1. Fork/Clone to GitHub

```bash
git clone https://github.com/YOUR_USERNAME/booli-scraper.git
cd booli-scraper
git remote set-url origin https://github.com/YOUR_USERNAME/booli-scraper.git
git push -u origin main
```

### 2. Deploy to Railway

1. Go to [Railway](https://railway.app) and create a new project
2. Select "Deploy from GitHub repo"
3. Choose your `booli-scraper` repository
4. Railway will auto-detect the Dockerfile

### 3. Configure Environment Variables

In Railway dashboard → Variables, add:

| Variable | Description | Example |
|----------|-------------|---------|
| `SMTP_HOST` | SMTP server | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USER` | Email username | `your-email@gmail.com` |
| `SMTP_PASSWORD` | App password* | `xxxx xxxx xxxx xxxx` |
| `EMAIL_TO` | Recipient email | `louis@berkholts.com` |
| `MAX_PAGES` | (Optional) Limit search pages | `100` |
| `MAX_LISTINGS` | (Optional) Limit listing detail scrapes | `1000` |
| `NUM_WORKERS` | (Optional) Parallel workers | `5` |

*For Gmail, use an [App Password](https://support.google.com/accounts/answer/185833), not your regular password.

### 4. Set Up Scheduled Runs (Optional)

#### Option A: Railway Cron (Recommended)

In Railway dashboard → Settings → Cron:
```
0 6 * * 0
```
This runs every Sunday at 6 AM UTC.

#### Option B: GitHub Actions

1. Get your Railway webhook URL from Settings → Deploy Webhooks
2. Add to GitHub Secrets: `RAILWAY_WEBHOOK_URL`
3. The included workflow triggers weekly runs

### 5. Manual Run

In Railway dashboard, click "Deploy" to run immediately.

Or use Railway CLI:
```bash
railway run python main.py
```

## Output

### Email Report

You'll receive an HTML email with:
- Total listing count
- New listings (last 7 days)
- Listings by date (last 14 days)
- Property type breakdown
- CSV attachment with all data

### CSV Columns

| Column | Description |
|--------|-------------|
| `listing_id` | Booli's internal ID |
| `url` | Link to listing |
| `address` | Property address |
| `property_type` | Lägenhet, Villa, etc. |
| `price_sek` | Asking price |
| `monthly_fee_sek` | Monthly fee (avgift) |
| `area_sqm` | Living area (m²) |
| `rooms` | Number of rooms |
| `floor` | Floor number |
| `days_on_booli` | Exact days listed |
| `received_date` | Calculated date (ISO) |
| `is_coming_soon` | True if "snart till salu" |
| `page_views` | Booli page views |
| `scraped_at` | Scrape timestamp |

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run with test settings (100 search pages, 500 listing details)
MAX_PAGES=100 MAX_LISTINGS=500 python main.py

# Run full scrape (no email)
python -c "
import asyncio
from scraper import AsyncBooliScraper
scraper = AsyncBooliScraper(num_workers=5)
listings = asyncio.run(scraper.scrape(max_pages=10, max_listings=100))
print(f'Scraped {len(listings)} listings')
"
```

## Architecture

```
booli-scraper/
├── main.py          # Entry point, email handling
├── scraper.py       # Two-phase async Playwright scraper
├── requirements.txt # Python dependencies
├── Dockerfile       # Railway build config
├── railway.toml     # Railway settings
└── .github/
    └── workflows/
        └── schedule.yml  # Optional GitHub Actions trigger
```

## Performance

**Note:** This scraper visits each listing page individually to get exact day counts. This takes longer but provides accurate data.

| Phase | Description | Time (5 workers) |
|-------|-------------|------------------|
| Phase 1 | Collect URLs from ~2,500 search pages | ~1 hour |
| Phase 2 | Visit ~85,000 individual listings | ~8-12 hours |

**For testing**, use `MAX_PAGES=10 MAX_LISTINGS=100` to complete in ~5 minutes.

## Troubleshooting

### "Playwright browsers not found"
The Dockerfile uses `mcr.microsoft.com/playwright/python` which includes browsers. If building locally, run `playwright install chromium`.

### "Email not sent"
Check that all SMTP variables are set. For Gmail, ensure you're using an App Password and have "Less secure app access" considerations handled.

### "Timeout errors"
Increase `NUM_WORKERS` delay or reduce workers. Booli may rate-limit aggressive scraping.

## License

MIT
