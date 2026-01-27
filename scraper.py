#!/usr/bin/env python3
"""
Booli.se Async Scraper Module - v3

Two-phase scraper:
1. Collects all listing URLs from search pages (both till-salu and nyproduktion)
2. Visits each individual listing page to get exact "for sale for X days" count
"""

import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from playwright.async_api import async_playwright, Page, BrowserContext


class AsyncBooliScraper:
    """Async scraper that visits individual listing pages for accurate day counts."""
    
    SOURCES = {
        'till-salu': 'https://www.booli.se/sok/till-salu?upcomingSale=0',
        'snart-till-salu': 'https://www.booli.se/sok/till-salu?upcomingSale=1',
        'nyproduktion': 'https://www.booli.se/sok/till-salu?isNewConstruction=1',
    }
    
    def __init__(self, num_workers: int = 5, delay: float = 0.3):
        self.num_workers = num_workers
        self.delay = delay
        self.listings = []
        self.listing_urls = []  # List of tuples: (url, source_type)
        self.today = datetime.now().date()
        self.lock = asyncio.Lock()
        self.pages_completed = 0
        self.listings_completed = 0
        self.total_pages = 0
        self.total_listings = 0
        
    async def extract_listing_urls(self, page: Page, source_type: str = 'till-salu') -> list[tuple[str, str]]:
        """Extract all listing URLs from a search results page."""
        urls = []
        
        try:
            await page.wait_for_selector('a[href*="/bostad/"], a[href*="/annons/"], a[href*="/projekt/"]', timeout=15000)
        except Exception:
            return urls
        
        elements = await page.query_selector_all('a[href*="/bostad/"], a[href*="/annons/"], a[href*="/projekt/"]')
        
        for elem in elements:
            try:
                href = await elem.get_attribute('href') or ""
                if '/bostad/' in href or '/annons/' in href or '/projekt/' in href:
                    if href.startswith('/'):
                        href = f"https://www.booli.se{href}"
                    if href not in [u[0] for u in urls]:
                        urls.append((href, source_type))
            except Exception:
                continue
        
        return urls
    
    async def extract_listing_details(self, page: Page, url: str, source_type: str = 'till-salu') -> Optional[dict]:
        """Extract detailed info from an individual listing page."""
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(self.delay)
            
            listing_id = url.split('/')[-1]
            body_text = await page.inner_text('body')
            
            # Extract days on Booli - the key metric!
            days_on_booli = None
            
            # Patterns for "till salu i X dagar" or "snart till salu i X dagar"
            days_patterns = [
                r'till salu i (\d+) dag',
                r'for sale for (\d+) day',
                r'snart till salu i (\d+) dag',
                r'coming soon for (\d+) day',
            ]
            
            for pattern in days_patterns:
                match = re.search(pattern, body_text.lower())
                if match:
                    days_on_booli = int(match.group(1))
                    break
            
            # Calculate received date from days
            received_date = None
            if days_on_booli is not None:
                received_date = self.today - timedelta(days=days_on_booli)
            
            # Extract address (h1)
            address = None
            try:
                h1 = await page.query_selector('h1')
                if h1:
                    address = (await h1.inner_text()).strip()
            except Exception:
                pass
            
            # Extract price
            price = None
            price_match = re.search(r'(\d[\d\s]*)\s*kr(?:\s|$)', body_text)
            if price_match:
                try:
                    price = int(price_match.group(1).replace(' ', '').replace('\xa0', ''))
                except ValueError:
                    pass
            
            # Extract property type
            property_type = None
            for ptype in ['Lägenhet', 'Villa', 'Radhus', 'Kedjehus', 'Parhus', 'Fritidshus', 'Tomt/Mark', 'Gård']:
                if ptype.lower() in body_text.lower():
                    property_type = ptype
                    break
            
            # Extract area
            area = None
            area_match = re.search(r'(\d+(?:[,\.]\d+)?)\s*m²', body_text)
            if area_match:
                area = float(area_match.group(1).replace(',', '.'))
            
            # Extract rooms
            rooms = None
            rooms_match = re.search(r'(\d+(?:[,\.]\d+)?)\s*rum', body_text)
            if rooms_match:
                rooms = float(rooms_match.group(1).replace(',', '.'))
            
            # Extract monthly fee
            monthly_fee = None
            fee_match = re.search(r'(\d[\d\s]*)\s*(?:kr/mån|SEK/month)', body_text)
            if fee_match:
                try:
                    monthly_fee = int(fee_match.group(1).replace(' ', '').replace('\xa0', ''))
                except ValueError:
                    pass
            
            # Extract floor
            floor = None
            floor_match = re.search(r'våning (\d+)', body_text.lower())
            if floor_match:
                floor = int(floor_match.group(1))
            
            # Extract page views
            page_views = None
            views_match = re.search(r'(\d+)\s*sidvisningar', body_text.lower())
            if views_match:
                page_views = int(views_match.group(1))
            
            # Check if "snart till salu" (coming soon)
            is_coming_soon = 'snart till salu' in body_text.lower()
            
            # Extract real estate agency (Swedish name)
            agency = None
            try:
                # Method 1: Extract from the "Läs mer hos mäklaren" external link URL
                # The link goes to the agency's website, e.g., fastighetsbyran.com
                external_link = await page.query_selector('a[href*="utm_source=booli"][href*="utm_medium=referral"]')
                if external_link:
                    href = await external_link.get_attribute('href') or ""
                    # Extract domain from URL
                    domain_match = re.search(r'https?://(?:www\.)?([^/]+)', href)
                    if domain_match:
                        domain = domain_match.group(1).lower()
                        # Map common domains to agency names
                        agency_domains = {
                            'fastighetsbyran.com': 'Fastighetsbyrån',
                            'svenskfast.se': 'Svensk Fastighetsförmedling',
                            'lansfast.se': 'Länsförsäkringar Fastighetsförmedling',
                            'bjurfors.se': 'Bjurfors',
                            'erikolsson.se': 'Erik Olsson',
                            'skandiamaklarna.se': 'SkandiaMäklarna',
                            'husmanhagberg.se': 'HusmanHagberg',
                            'notar.se': 'Notar',
                            'maklarhuset.se': 'Mäklarhuset',
                            'svenskamaklarhuset.se': 'Svenska Mäklarhuset',
                            'era.se': 'ERA',
                            'hemverket.se': 'Hemverket',
                            'innerstadsspecialisten.se': 'Innerstadsspecialisten',
                            'karlssons.se': 'Karlssons Mäklarbyrå',
                            'alexanderwhite.se': 'Alexander White',
                            'perjansson.se': 'Per Jansson',
                            'historiskahem.se': 'Historiska Hem',
                            'mohv.se': 'MOHV',
                            'wrede.se': 'Wrede',
                            'magnusson.se': 'Magnusson Mäkleri',
                            'coldwellbanker.se': 'Coldwell Banker',
                            'century21.se': 'Century 21',
                            'bovision.se': 'Bovision',
                            'fantastic-frank.se': 'Fantastic Frank',
                            'ahreborger.se': 'Åhre Borger',
                            'sothebysrealty.se': "Sotheby's International Realty",
                        }
                        for agency_domain, agency_name in agency_domains.items():
                            if agency_domain in domain:
                                agency = agency_name
                                break
                        
                        # If not in our list, try to make a readable name from domain
                        if not agency:
                            # e.g., "fastighetsbyran.com" -> "Fastighetsbyran"
                            domain_name = domain.split('.')[0]
                            agency = domain_name.replace('-', ' ').title()
                
                # Method 2: Look for agency name in broker section (but not footer)
                if not agency:
                    # Find the broker section specifically
                    broker_section = await page.query_selector('h2:has-text("Ansvarig mäklare"), h2:has-text("Responsible broker")')
                    if broker_section:
                        # Get the next sibling or parent container
                        broker_container = await broker_section.evaluate_handle('el => el.parentElement || el.nextElementSibling')
                        if broker_container:
                            broker_text = await broker_container.inner_text()
                            # Look for agency name pattern - usually after rating stars
                            lines = [l.strip() for l in broker_text.split('\n') if l.strip()]
                            for line in lines:
                                # Skip common non-agency text
                                if any(skip in line.lower() for skip in ['kontakta', 'contact', 'recensioner', 'reviews', '/', 'mäklare', 'broker', 'ansvarig']):
                                    continue
                                if len(line) > 3 and len(line) < 50 and not line[0].isdigit():
                                    agency = line
                                    break
                
            except Exception:
                pass
            
            # Determine if this is new production
            is_new_production = source_type == 'nyproduktion' or '/projekt/' in url
            
            return {
                'listing_id': listing_id,
                'url': url,
                'address': address,
                'property_type': property_type,
                'price_sek': price,
                'monthly_fee_sek': monthly_fee,
                'area_sqm': area,
                'rooms': rooms,
                'floor': floor,
                'days_on_booli': days_on_booli,
                'received_date': received_date.isoformat() if received_date else None,
                'is_coming_soon': is_coming_soon,
                'is_new_production': is_new_production,
                'source': source_type,
                'agency': agency,
                'page_views': page_views,
                'scraped_at': datetime.now().isoformat(),
            }
            
        except Exception as e:
            print(f"\n  Warning: Error on {url}: {e}")
            return None
    
    async def get_total_pages(self, page: Page) -> int:
        """Extract total number of pages from pagination."""
        try:
            page_text = await page.inner_text('body')
            match = re.search(r'sida\s*\d+\s*av\s*(\d+)', page_text, re.IGNORECASE)
            if match:
                return int(match.group(1))
            
            pagination_links = await page.query_selector_all('a[href*="page="]')
            max_page = 1
            for link in pagination_links:
                href = await link.get_attribute('href') or ""
                page_match = re.search(r'page=(\d+)', href)
                if page_match:
                    max_page = max(max_page, int(page_match.group(1)))
            return max_page
            
        except Exception:
            return 1
    
    async def url_collector_worker(self, context: BrowserContext, page_queue: asyncio.Queue):
        """Worker that collects listing URLs from search pages."""
        page = await context.new_page()
        
        while True:
            try:
                item = await asyncio.wait_for(page_queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                break
            
            page_num, source_type, base_url = item
            # Handle URLs that already have query parameters
            if '?' in base_url:
                url = f"{base_url}&page={page_num}" if page_num > 1 else base_url
            else:
                url = f"{base_url}?page={page_num}" if page_num > 1 else base_url
            
            try:
                await page.goto(url, wait_until='networkidle', timeout=30000)
                await asyncio.sleep(self.delay)
                
                urls = await self.extract_listing_urls(page, source_type)
                
                async with self.lock:
                    for u in urls:
                        # Track if this URL is a duplicate
                        is_duplicate = u[0] in [x[0] for x in self.listing_urls]
                        # Add tuple: (url, source_type, is_duplicate_url)
                        self.listing_urls.append((u[0], u[1], is_duplicate))
                    self.pages_completed += 1
                    # Count unique URLs
                    unique_urls = len(set(x[0] for x in self.listing_urls))
                    progress = (self.pages_completed / self.total_pages) * 100
                    print(f"\r  Phase 1: {self.pages_completed}/{self.total_pages} pages ({progress:.1f}%) - {len(self.listing_urls)} URLs ({unique_urls} unique)", end='', flush=True)
                
            except Exception as e:
                print(f"\n  Warning: Error on search page {page_num}: {e}")
            
            page_queue.task_done()
        
        await page.close()
    
    async def detail_scraper_worker(self, context: BrowserContext, url_queue: asyncio.Queue):
        """Worker that scrapes individual listing pages."""
        page = await context.new_page()
        
        while True:
            try:
                item = await asyncio.wait_for(url_queue.get(), timeout=10.0)
            except asyncio.TimeoutError:
                break
            
            url, source_type, is_duplicate_url = item
            details = await self.extract_listing_details(page, url, source_type)
            
            async with self.lock:
                if details:
                    details['is_duplicate_url'] = is_duplicate_url
                    self.listings.append(details)
                self.listings_completed += 1
                progress = (self.listings_completed / self.total_listings) * 100
                print(f"\r  Phase 2: {self.listings_completed}/{self.total_listings} listings ({progress:.1f}%)", end='', flush=True)
            
            url_queue.task_done()
        
        await page.close()
    
    async def scrape(self, max_pages: Optional[int] = None, max_listings: Optional[int] = None) -> list[dict]:
        """
        Two-phase scrape:
        1. Collect all listing URLs from search pages (till-salu + nyproduktion)
        2. Visit each listing page for detailed info including exact days
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            
            try:
                # === PHASE 1: Collect URLs from both sources ===
                page = await context.new_page()
                
                # Handle cookie consent once
                await page.goto(self.SOURCES['till-salu'], wait_until='networkidle', timeout=30000)
                await asyncio.sleep(2)
                try:
                    cookie_button = await page.query_selector('button:has-text("Acceptera"), button:has-text("Godkänn")')
                    if cookie_button:
                        await cookie_button.click()
                        await asyncio.sleep(1)
                except Exception:
                    pass
                
                # Get page counts for both sources
                source_pages = {}
                for source_type, base_url in self.SOURCES.items():
                    await page.goto(base_url, wait_until='networkidle', timeout=30000)
                    await asyncio.sleep(1)
                    pages = await self.get_total_pages(page)
                    if max_pages:
                        pages = min(pages, max_pages)
                    source_pages[source_type] = pages
                    print(f"  {source_type}: {pages} pages")
                
                self.total_pages = sum(source_pages.values())
                print(f"\n=== Phase 1: Collecting URLs from {self.total_pages} total pages ===")
                
                # Get first page URLs from each source
                for source_type, base_url in self.SOURCES.items():
                    await page.goto(base_url, wait_until='networkidle', timeout=30000)
                    await asyncio.sleep(1)
                    first_urls = await self.extract_listing_urls(page, source_type)
                    # Convert to tuple format with is_duplicate flag
                    for u in first_urls:
                        is_duplicate = u[0] in [x[0] for x in self.listing_urls]
                        self.listing_urls.append((u[0], u[1], is_duplicate))
                    self.pages_completed += 1
                
                await page.close()
                
                # Queue remaining pages for both sources
                page_queue = asyncio.Queue()
                for source_type, base_url in self.SOURCES.items():
                    for page_num in range(2, source_pages[source_type] + 1):
                        await page_queue.put((page_num, source_type, base_url))
                
                # Start URL collector workers
                workers = []
                worker_contexts = []
                
                for i in range(self.num_workers):
                    worker_context = await browser.new_context(
                        viewport={'width': 1920, 'height': 1080},
                        user_agent=f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Worker/{i}'
                    )
                    worker_contexts.append(worker_context)
                    workers.append(asyncio.create_task(
                        self.url_collector_worker(worker_context, page_queue)
                    ))
                
                await asyncio.gather(*workers)
                
                for ctx in worker_contexts:
                    await ctx.close()
                
                print(f"\n  Collected {len(self.listing_urls)} unique listing URLs")
                
                # === PHASE 2: Scrape individual listings ===
                if max_listings:
                    self.listing_urls = self.listing_urls[:max_listings]
                
                self.total_listings = len(self.listing_urls)
                print(f"\n=== Phase 2: Scraping {self.total_listings} listing pages for exact days ===")
                
                url_queue = asyncio.Queue()
                for url_tuple in self.listing_urls:
                    await url_queue.put(url_tuple)
                
                # Start detail scraper workers
                workers = []
                worker_contexts = []
                
                for i in range(self.num_workers):
                    worker_context = await browser.new_context(
                        viewport={'width': 1920, 'height': 1080},
                        user_agent=f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Detail/{i}'
                    )
                    worker_contexts.append(worker_context)
                    workers.append(asyncio.create_task(
                        self.detail_scraper_worker(worker_context, url_queue)
                    ))
                
                await asyncio.gather(*workers)
                
                for ctx in worker_contexts:
                    await ctx.close()
                
                print()
                
            finally:
                await browser.close()
        
        # Post-process: mark duplicate listing IDs
        seen_ids = {}
        for listing in self.listings:
            lid = listing.get('listing_id')
            if lid in seen_ids:
                listing['is_duplicate_listing_id'] = True
                # Also mark the first occurrence
                seen_ids[lid]['is_duplicate_listing_id'] = True
            else:
                listing['is_duplicate_listing_id'] = False
                seen_ids[lid] = listing
        
        return self.listings
    
    def get_summary(self) -> dict:
        """Generate summary statistics."""
        if not self.listings:
            return {}
        
        df = pd.DataFrame(self.listings)
        df['received_date'] = pd.to_datetime(df['received_date'])
        
        date_counts = {}
        if df['received_date'].notna().any():
            date_counts = df.groupby(df['received_date'].dt.date).size().sort_index().to_dict()
        
        # Count duplicates
        duplicate_urls = df['is_duplicate_url'].sum() if 'is_duplicate_url' in df.columns else 0
        duplicate_ids = df['is_duplicate_listing_id'].sum() if 'is_duplicate_listing_id' in df.columns else 0
        
        return {
            'total_listings': len(df),
            'unique_ids': df['listing_id'].nunique(),
            'duplicate_urls': int(duplicate_urls),
            'duplicate_listing_ids': int(duplicate_ids),
            'with_date': df['received_date'].notna().sum(),
            'missing_date': df['received_date'].isna().sum(),
            'coming_soon': df['is_coming_soon'].sum() if 'is_coming_soon' in df.columns else 0,
            'new_production': df['is_new_production'].sum() if 'is_new_production' in df.columns else 0,
            'earliest_date': df['received_date'].min().isoformat() if df['received_date'].notna().any() else None,
            'latest_date': df['received_date'].max().isoformat() if df['received_date'].notna().any() else None,
            'by_property_type': df['property_type'].value_counts().to_dict() if 'property_type' in df.columns else {},
            'by_source': df['source'].value_counts().to_dict() if 'source' in df.columns else {},
            'date_distribution': date_counts,
            'avg_days_on_booli': float(df['days_on_booli'].mean()) if 'days_on_booli' in df.columns and df['days_on_booli'].notna().any() else None,
            'median_days_on_booli': float(df['days_on_booli'].median()) if 'days_on_booli' in df.columns and df['days_on_booli'].notna().any() else None,
        }
