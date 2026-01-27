#!/usr/bin/env python3
"""
Booli.se Scraper - Railway Deployment Entry Point

Scrapes all Booli listings, calculates received dates, and sends results via email.

Environment Variables (set in Railway):
    SMTP_HOST: SMTP server (default: smtp.gmail.com)
    SMTP_PORT: SMTP port (default: 587)
    SMTP_USER: Email username
    SMTP_PASSWORD: Email password or app-specific password
    EMAIL_TO: Recipient email address
    MAX_PAGES: Maximum pages to scrape (optional, default: all)
    NUM_WORKERS: Number of parallel workers (default: 5)
"""

import asyncio
import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO
from pathlib import Path

import pandas as pd

from scraper import AsyncBooliScraper


def send_email(
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]] = None,
    html_body: str = None
):
    """Send email with optional attachments."""
    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    email_to = os.environ.get('EMAIL_TO')
    
    if not all([smtp_user, smtp_password, email_to]):
        print("Warning: Email not configured. Set SMTP_USER, SMTP_PASSWORD, EMAIL_TO")
        return False
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = smtp_user
    msg['To'] = email_to
    
    # Add text body
    msg.attach(MIMEText(body, 'plain'))
    
    # Add HTML body if provided
    if html_body:
        msg.attach(MIMEText(html_body, 'html'))
    
    # Add attachments
    if attachments:
        for filename, data in attachments:
            part = MIMEApplication(data, Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            msg.attach(part)
    
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, email_to, msg.as_string())
        print(f"Email sent to {email_to}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def generate_html_report(df: pd.DataFrame, summary: dict) -> str:
    """Generate an HTML email report (English)."""
    df = df.copy()
    df['received_date'] = pd.to_datetime(df['received_date'])
    
    # Recent listings (last 7 days)
    recent = df[df['received_date'] >= (datetime.now() - pd.Timedelta(days=7))]
    
    # Count for sale vs coming soon vs new production
    for_sale_count = len(df[(df['is_coming_soon'] == False) & (df.get('is_new_production', False) == False)]) if 'is_coming_soon' in df.columns else len(df)
    coming_soon_count = df['is_coming_soon'].sum() if 'is_coming_soon' in df.columns else 0
    new_production_count = df['is_new_production'].sum() if 'is_new_production' in df.columns else 0
    
    # Date distribution with status breakdown (last 14 days)
    df_with_dates = df[df['received_date'].notna()].copy()
    df_with_dates['date'] = df_with_dates['received_date'].dt.date
    df_with_dates['status'] = df_with_dates['is_coming_soon'].apply(lambda x: 'Coming Soon' if x else 'For Sale')
    
    date_status_counts = df_with_dates.groupby(['date', 'status']).size().unstack(fill_value=0)
    date_status_counts = date_status_counts.sort_index().tail(14)
    
    # Translate property types
    property_type_translations = {
        'Lägenhet': 'Apartment',
        'Villa': 'House',
        'Radhus': 'Townhouse',
        'Kedjehus': 'Semi-detached',
        'Parhus': 'Duplex',
        'Fritidshus': 'Vacation Home',
        'Tomt/Mark': 'Land/Plot',
        'Gård': 'Farm/Estate',
    }
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
            h1 {{ color: #FF620F; }}
            h2 {{ color: #333; border-bottom: 2px solid #FF620F; padding-bottom: 5px; }}
            table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #FF620F; color: white; }}
            tr:nth-child(even) {{ background-color: #f9f9f9; }}
            .stat-box {{ display: inline-block; background: #f5f5f5; padding: 15px 25px; margin: 10px; border-radius: 8px; text-align: center; }}
            .stat-number {{ font-size: 24px; font-weight: bold; color: #FF620F; }}
            .stat-label {{ font-size: 12px; color: #666; }}
            .for-sale {{ color: #2e7d32; }}
            .coming-soon {{ color: #1565c0; }}
            .new-production {{ color: #7b1fa2; }}
        </style>
    </head>
    <body>
        <h1>🏠 Booli Listings Report</h1>
        <p>Scraped on {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</p>
        
        <div>
            <div class="stat-box">
                <div class="stat-number">{summary.get('total_listings', 0):,}</div>
                <div class="stat-label">Total Listings</div>
            </div>
            <div class="stat-box">
                <div class="stat-number for-sale">{for_sale_count:,}</div>
                <div class="stat-label">For Sale</div>
            </div>
            <div class="stat-box">
                <div class="stat-number coming-soon">{coming_soon_count:,}</div>
                <div class="stat-label">Coming Soon</div>
            </div>
            <div class="stat-box">
                <div class="stat-number new-production">{new_production_count:,}</div>
                <div class="stat-label">New Production</div>
            </div>
            <div class="stat-box">
                <div class="stat-number">{len(recent):,}</div>
                <div class="stat-label">New (Last 7 Days)</div>
            </div>
            <div class="stat-box">
                <div class="stat-number">{summary.get('avg_days_on_booli', 0):.0f}</div>
                <div class="stat-label">Avg Days Listed</div>
            </div>
        </div>
        
        <h2>📅 Listings by Date (Last 14 Days)</h2>
        <table>
            <tr><th>Date</th><th>For Sale</th><th>Coming Soon</th><th>Total</th></tr>
    """
    
    for date in date_status_counts.index:
        for_sale = date_status_counts.loc[date, 'For Sale'] if 'For Sale' in date_status_counts.columns else 0
        coming_soon = date_status_counts.loc[date, 'Coming Soon'] if 'Coming Soon' in date_status_counts.columns else 0
        total = for_sale + coming_soon
        html += f"<tr><td>{date}</td><td class='for-sale'>{for_sale:,}</td><td class='coming-soon'>{coming_soon:,}</td><td>{total:,}</td></tr>\n"
    
    html += """
        </table>
        
        <h2>🏘️ By Property Type</h2>
        <table>
            <tr><th>Type</th><th>Count</th></tr>
    """
    
    if summary.get('by_property_type'):
        for ptype, count in sorted(summary['by_property_type'].items(), key=lambda x: x[1], reverse=True):
            english_type = property_type_translations.get(ptype, ptype) if ptype else 'Unknown'
            html += f"<tr><td>{english_type}</td><td>{count:,}</td></tr>\n"
    
    html += """
        </table>
        
        <h2>📊 Statistics</h2>
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Date Range</td><td>{earliest} to {latest}</td></tr>
            <tr><td>Listings with Date</td><td>{with_date:,}</td></tr>
            <tr><td>Missing Date</td><td>{missing_date:,}</td></tr>
            <tr><td>Average Days Listed</td><td>{avg_days:.1f}</td></tr>
            <tr><td>Median Days Listed</td><td>{median_days:.1f}</td></tr>
        </table>
        
        <p style="color: #666; font-size: 12px; margin-top: 30px;">
            Full data attached as CSV. Includes both regular listings and new production (nyproduktion).
            <br>Generated by Booli Scraper on Railway.
        </p>
    </body>
    </html>
    """.format(
        earliest=summary.get('earliest_date', 'N/A'),
        latest=summary.get('latest_date', 'N/A'),
        with_date=summary.get('with_date', 0),
        missing_date=summary.get('missing_date', 0),
        avg_days=summary.get('avg_days_on_booli') or 0,
        median_days=summary.get('median_days_on_booli') or 0,
    )
    
    return html


async def main():
    """Main entry point for Railway deployment."""
    print("=" * 60)
    print("Booli.se Scraper - Railway Deployment")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)
    
    # Configuration from environment
    max_pages = os.environ.get('MAX_PAGES')
    max_pages = int(max_pages) if max_pages else None
    max_listings = os.environ.get('MAX_LISTINGS')
    max_listings = int(max_listings) if max_listings else None
    num_workers = int(os.environ.get('NUM_WORKERS', 5))
    
    print(f"Max pages: {max_pages or 'All (~2,451)'}")
    print(f"Max listings: {max_listings or 'All (~85,000)'}")
    print(f"Workers: {num_workers}")
    print()
    print("Note: This scraper visits each listing page individually to get exact 'days on Booli'")
    print()
    
    scraper = AsyncBooliScraper(
        num_workers=num_workers,
        delay=0.5
    )
    
    start_time = datetime.now()
    
    try:
        listings = await scraper.scrape(max_pages=max_pages, max_listings=max_listings)
        
        elapsed = datetime.now() - start_time
        print(f"\nScraping completed in {elapsed}")
        print(f"Total listings: {len(listings)}")
        
        if not listings:
            print("No listings scraped!")
            send_email(
                subject="⚠️ Booli Scraper - No Listings Found",
                body=f"The scraper ran but found no listings.\n\nTime: {datetime.now()}\nElapsed: {elapsed}"
            )
            return
        
        # Create DataFrame
        df = pd.DataFrame(listings)
        
        # Generate summary
        summary = scraper.get_summary()
        
        # Save locally (for debugging)
        output_path = Path('/tmp/booli_listings.csv')
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"Saved to {output_path}")
        
        # Create CSV attachment
        csv_buffer = BytesIO()
        df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
        csv_data = csv_buffer.getvalue()
        
        # Generate HTML report
        html_report = generate_html_report(df, summary)
        
        # Create text summary
        text_body = f"""Booli Scraper Report
{'=' * 40}

Scraped: {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC
Elapsed: {elapsed}
Pages: {scraper.pages_completed}

Total Listings: {summary.get('total_listings', 0):,}
With Date: {summary.get('with_date', 0):,}
Missing Date: {summary.get('missing_date', 0):,}

Date Range:
  Earliest: {summary.get('earliest_date', 'N/A')}
  Latest: {summary.get('latest_date', 'N/A')}

By Property Type:
"""
        if summary.get('by_property_type'):
            for ptype, count in sorted(summary['by_property_type'].items(), key=lambda x: x[1], reverse=True):
                text_body += f"  {ptype or 'Unknown'}: {count:,}\n"
        
        text_body += "\nFull data attached as CSV."
        
        # Send email
        today_str = datetime.now().strftime('%Y-%m-%d')
        send_email(
            subject=f"🏠 Booli Report - {summary.get('total_listings', 0):,} listings ({today_str})",
            body=text_body,
            html_body=html_report,
            attachments=[(f'booli_listings_{today_str}.csv', csv_data)]
        )
        
        print("\n✅ Scraping and email complete!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
        # Send error notification
        send_email(
            subject="❌ Booli Scraper - Error",
            body=f"The scraper encountered an error:\n\n{e}\n\nTime: {datetime.now()}"
        )
        
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
