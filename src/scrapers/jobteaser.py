from urllib.parse import quote
import os
import time
import random
import logging
from typing import List
from playwright.sync_api import sync_playwright
from .base import BaseScraper
from src.models import JobPosting
from src.content import extract_description

logger = logging.getLogger(__name__)

class JobTeaserScraper(BaseScraper):
    def __init__(self, keyword="software engineer", location="", max_pages=10):
        self.keyword = keyword
        self.location = location
        self.max_pages = max_pages
        self.proxy_url = os.getenv("PROXY_URL")

    def scrape_jobs(self, db=None) -> List[JobPosting]:
        logger.info(f"Scraping JobTeaser via Playwright...")
        jobs = []
        
        try:
            with sync_playwright() as p:
                launch_args = {"headless": True}
                
                if self.proxy_url:
                    logger.info("🛡️ Routing Playwright traffic through configured proxy.")
                    launch_args["proxy"] = {"server": self.proxy_url}
                
                browser = p.chromium.launch(**launch_args)
                page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

                consecutive_seen_cards = 0

                for page_num in range(1, self.max_pages + 1):
                    if consecutive_seen_cards >= 40:
                        logger.info("Hit a block of already seen jobs. Stopping JobTeaser pagination early!")
                        break
                        
                    # Launch a completely fresh browser for EVERY page.
                    # This gives Datadome "amnesia" so it thinks we are a brand new user hitting the page from Google.
                    
                    search_url = f"https://www.jobteaser.com/fr/job-offers?keyword={quote(self.keyword, safe='')}&location={quote(self.location, safe='')}&page={page_num}"
                    
                    logger.info(f"Fetching JobTeaser jobs (Page: {page_num})...")
                    page.goto(search_url, wait_until="domcontentloaded")
                    time.sleep(random.uniform(2.5, 4.0))
                    
                    # JobTeaser job links all contain '/job-offers/' followed by the ID
                    job_links = page.locator("a[href*='/job-offers/']").all()
                    urls_to_visit = set()
                    
                    for link in job_links:
                        href = link.get_attribute("href")
                        if href and "/job-offers/" in href and not href.endswith("/job-offers") and not href.endswith("/job-offers/"):
                            if href.startswith("http"):
                                urls_to_visit.add(href)
                            else:
                                urls_to_visit.add("https://www.jobteaser.com" + href)
                    
                    urls_to_visit = list(urls_to_visit)
                    if not urls_to_visit:
                        break # No more results on this page
                        
                    for job_url in urls_to_visit:
                        try:
                            # JobTeaser IDs are usually in the URL like: .../job-offers/1234567-title
                            job_id = job_url.split("/")[-1].split("-")[0]
                            full_id = f"jt-{job_id}"
                            
                            # SMART SKIP
                            if db and db.is_job_seen(full_id):
                                consecutive_seen_cards += 1
                                continue
                                
                            consecutive_seen_cards = 0
                            
                            page.goto(job_url, wait_until="domcontentloaded")
                            time.sleep(random.uniform(1.5, 3.0))
                            
                            title = page.locator("h1").inner_text() if page.locator("h1").count() > 0 else "Unknown Title"
                            
                            # Scrape the entire main body to ensure we don't miss any criteria text
                            description = extract_description(page.content())
                            
                            logger.info(f"   [JobTeaser] Scraped: {title}")
                            
                            jobs.append(JobPosting(
                                id=full_id,
                                title=title,
                                company="JobTeaser Company", # AI will parse the exact company from the body
                                location=self.location,
                                url=job_url,
                                description=description,
                                source="JobTeaser"
                            ))
                        except Exception as e:
                            logger.error(f"Error parsing JobTeaser job page: {e}")
                            
                browser.close()
        except Exception as e:
            logger.error(f"JobTeaser Scraping failed: {e}")
                
        return jobs
