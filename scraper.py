#!/usr/bin/env python3
"""
Booli.se Async Scraper Module - v4

Two-phase scraper with retry logic:
1. Collects all listing URLs from search pages (till-salu, snart-till-salu, nyproduktion)
2. Visits each individual listing page to get exact "for sale for X days" count
3. Retries failed pages up to 3 times
"""

import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from playwright.async_api import async_playwright, Page, BrowserContext


class AsyncBooliScraper:
    """Async scraper that visits individual listing pages for accurate day counts."""
    
    # Property types and statuses to scrape
    PROPERTY_TYPES = [
        'Lägenhet',
        'Villa', 
        'Kedjehus-Parhus-Radhus',  # Combined townhouse types
        'Fritidshus',
        'Tomt%2FMark',  # URL encoded Tomt/Mark
        'Gård',
    ]
    
    STATUSES = {
        'till-salu': 'upcomingSale=0',
        'snart-till-salu': 'upcomingSale=1',
    }
    
    # Generate all source combinations
    SOURCES = {}
    for prop_type in PROPERTY_TYPES:
        for status_name, status_param in STATUSES.items():
            # Clean property type name for dict key
            clean_type = prop_type.replace('%2F', '-').replace('-', '-').lower()
            source_key = f"{clean_type}-{status_name}"
            SOURCES[source_key] = f"https://www.booli.se/sok/till-salu?objectType={prop_type}&{status_param}"
    
    # Add nyproduktion separately (smaller, no need to split by type)
    SOURCES['nyproduktion'] = 'https://www.booli.se/sok/till-salu?isNewConstruction=1'
    
    def __init__(self, num_workers: int = 5, delay: float = 0.3, max_retries: int = 3):
        self.num_workers = num_workers
        self.delay = delay
        self.max_retries = max_retries
        self.listings = []
        self.listing_urls = []  # List of tuples: (url, source_type, is_duplicate_url)
        self.failed_urls = []   # Track failed URLs for retry
        self.today = datetime.now().date()
        self.lock = asyncio.Lock()
        self.pages_completed = 0
        self.listings_completed = 0
        self.total_pages = 0
        self.total_listings = 0
        self.success_count = 0
        self.fail_count = 0
        
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
                    # Only add booli.se URLs, skip external project URLs
                    if 'booli.se' in href:
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
                            domain_name = domain.split('.')[0]
                            agency = domain_name.replace('-', ' ').title()
                
                # Method 2: Look for agency name in broker section (but not footer)
                if not agency:
                    broker_section = await page.query_selector('h2:has-text("Ansvarig mäklare"), h2:has-text("Responsible broker")')
                    if broker_section:
                        broker_container = await broker_section.evaluate_handle('el => el.parentElement || el.nextElementSibling')
                        if broker_container:
                            broker_text = await broker_container.inner_text()
                            lines = [l.strip() for l in broker_text.split('\n') if l.strip()]
                            for line in lines:
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
                'scrape_failed': False,
                'scraped_at': datetime.now().isoformat(),
            }
            
        except Exception as e:
            # Don't print here - let the worker handle it
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
    
    async def url_collector_worker(self, context: BrowserContext, page_queue: asyncio.Queue, failed_queue: asyncio.Queue):
        """Worker that collects listing URLs from search pages with retry support."""
        page = await context.new_page()
        
        while True:
            try:
                item = await asyncio.wait_for(page_queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                break
            
            page_num, source_type, base_url, attempt = item
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
                if attempt < self.max_retries:
                    # Re-queue for retry
                    await failed_queue.put((page_num, source_type, base_url, attempt + 1))
                else:
                    print(f"\n  Failed after {self.max_retries} attempts: page {page_num} ({source_type})")
            
            page_queue.task_done()
        
        await page.close()
    
    async def detail_scraper_worker(self, context: BrowserContext, url_queue: asyncio.Queue, failed_queue: asyncio.Queue):
        """Worker that scrapes individual listing pages with retry support."""
        page = await context.new_page()
        
        while True:
            try:
                item = await asyncio.wait_for(url_queue.get(), timeout=10.0)
            except asyncio.TimeoutError:
                break
            
            url, source_type, is_duplicate_url, attempt = item
            details = await self.extract_listing_details(page, url, source_type)
            
            async with self.lock:
                if details:
                    details['is_duplicate_url'] = is_duplicate_url
                    self.listings.append(details)
                    self.success_count += 1
                else:
                    # Failed - queue for retry if attempts remain
                    if attempt < self.max_retries:
                        await failed_queue.put((url, source_type, is_duplicate_url, attempt + 1))
                    else:
                        self.fail_count += 1
                        # Add a placeholder entry for failed URLs
                        self.listings.append({
                            'listing_id': url.split('/')[-1],
                            'url': url,
                            'address': None,
                            'property_type': None,
                            'price_sek': None,
                            'monthly_fee_sek': None,
                            'area_sqm': None,
                            'rooms': None,
                            'floor': None,
                            'days_on_booli': None,
                            'received_date': None,
                            'is_coming_soon': None,
                            'is_new_production': source_type == 'nyproduktion' or '/projekt/' in url,
                            'source': source_type,
                            'agency': None,
                            'page_views': None,
                            'is_duplicate_url': is_duplicate_url,
                            'scrape_failed': True,
                            'scraped_at': datetime.now().isoformat(),
                        })
                
                self.listings_completed += 1
                progress = (self.listings_completed / self.total_listings) * 100
                if self.listings_completed % 100 == 0:  # Reduce log spam
                    print(f"\r  Phase 2: {self.listings_completed}/{self.total_listings} ({progress:.1f}%) - OK: {self.success_count}, Retrying: {failed_queue.qsize()}, Failed: {self.fail_count}", end='', flush=True)
            
            url_queue.task_done()
        
        await page.close()
    
    async def process_retry_queue(self, browser, queue: asyncio.Queue, worker_func, phase: str):
        """Process items in the retry queue."""
        if queue.empty():
            return
            
        retry_count = queue.qsize()
        print(f"\n  Retrying {retry_count} failed {phase}...")
        
        # Create new work queue from failed items
        work_queue = asyncio.Queue()
        failed_queue = asyncio.Queue()
        
        while not queue.empty():
            item = await queue.get()
            await work_queue.put(item)
        
        # Use fewer workers for retries to reduce memory pressure
        retry_workers = max(2, self.num_workers // 2)
        
        workers = []
        worker_contexts = []
        
        for i in range(retry_workers):
            worker_context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent=f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Retry/{i}'
            )
            worker_contexts.append(worker_context)
            workers.append(asyncio.create_task(
                worker_func(worker_context, work_queue, failed_queue)
            ))
        
        await asyncio.gather(*workers)
        
        for ctx in worker_contexts:
            await ctx.close()
        
        # If there are still failed items, process them again
        if not failed_queue.empty():
            await self.process_retry_queue(browser, failed_queue, worker_func, phase)
    
    async def scrape(self, max_pages: Optional[int] = None, max_listings: Optional[int] = None) -> list[dict]:
        """
        Two-phase scrape with retry logic:
        1. Collect all listing URLs from search pages (till-salu + snart-till-salu + nyproduktion)
        2. Visit each listing page for detailed info including exact days
        3. Retry failed pages up to max_retries times
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            
            try:
                # === PHASE 1: Collect URLs from all sources ===
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
                
                # Get page counts for all sources
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
                
                # Queue remaining pages for all sources
                page_queue = asyncio.Queue()
                failed_page_queue = asyncio.Queue()
                
                for source_type, base_url in self.SOURCES.items():
                    for page_num in range(2, source_pages[source_type] + 1):
                        await page_queue.put((page_num, source_type, base_url, 1))  # attempt = 1
                
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
                        self.url_collector_worker(worker_context, page_queue, failed_page_queue)
                    ))
                
                await asyncio.gather(*workers)
                
                for ctx in worker_contexts:
                    await ctx.close()
                
                # Process retries for Phase 1
                await self.process_retry_queue(browser, failed_page_queue, self.url_collector_worker, "pages")
                
                unique_urls = len(set(x[0] for x in self.listing_urls))
                print(f"\n  Collected {len(self.listing_urls)} URLs ({unique_urls} unique)")
                
                # === PHASE 2: Scrape individual listings ===
                if max_listings:
                    self.listing_urls = self.listing_urls[:max_listings]
                
                self.total_listings = len(self.listing_urls)
                print(f"\n=== Phase 2: Scraping {self.total_listings} listing pages ===")
                
                url_queue = asyncio.Queue()
                failed_url_queue = asyncio.Queue()
                
                for url_tuple in self.listing_urls:
                    # Add attempt counter: (url, source_type, is_duplicate, attempt)
                    await url_queue.put((url_tuple[0], url_tuple[1], url_tuple[2], 1))
                
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
                        self.detail_scraper_worker(worker_context, url_queue, failed_url_queue)
                    ))
                
                await asyncio.gather(*workers)
                
                for ctx in worker_contexts:
                    await ctx.close()
                
                # Process retries for Phase 2
                await self.process_retry_queue(browser, failed_url_queue, self.detail_scraper_worker, "listings")
                
                print(f"\n  Completed: {self.success_count} successful, {self.fail_count} failed after retries")
                
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
        failed_scrapes = df['scrape_failed'].sum() if 'scrape_failed' in df.columns else 0
        
        return {
            'total_listings': len(df),
            'unique_ids': df['listing_id'].nunique(),
            'duplicate_urls': int(duplicate_urls),
            'duplicate_listing_ids': int(duplicate_ids),
            'failed_scrapes': int(failed_scrapes),
            'successful_scrapes': int(self.success_count),
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
