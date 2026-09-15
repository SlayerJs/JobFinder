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

class WelcomeToTheJungleScraper(BaseScraper):
    def __init__(self, keyword="software engineer", location="", max_pages=10):
        self.keyword = keyword
        self.location = location
        self.max_pages = max_pages
        self.proxy_url = os.getenv("PROXY_URL")

    def scrape_jobs(self, db=None) -> List[JobPosting]:
        logger.info(f"Scraping Welcome to the Jungle via Playwright...")
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

                # Deep Pagination Loop
                for page_num in range(1, self.max_pages + 1):
                    if consecutive_seen_cards >= 40:
                        logger.info("Hit a block of already seen jobs. Stopping WTTJ pagination early!")
                        break

                    search_url = f"https://www.welcometothejungle.com/fr/jobs?query={quote(self.keyword, safe='')}&location={quote(self.location, safe='')}&page={page_num}"
                    logger.info(f"Fetching WTTJ jobs (Page: {page_num})...")
                    
                    page.goto(search_url, wait_until="domcontentloaded")
                    time.sleep(random.uniform(3.0, 5.0)) # Wait for React to render
                    
                    job_links = page.locator("a[href*='/jobs/']").all()
                    urls_to_visit = set()
                    for link in job_links:
                        href = link.get_attribute("href")
                        if href and "/jobs/" in href and "/companies/" in href:
                            urls_to_visit.add("https://www.welcometothejungle.com" + href)
                    
                    urls_to_visit = list(urls_to_visit)
                    if not urls_to_visit:
                        break # End of pagination, no more jobs found
                    
                    for job_url in urls_to_visit:
                        try:
                            job_id = job_url.split("/")[-1]
                            full_id = f"wttj-{job_id}"
                            
                            # SMART SKIP
                            if db and db.is_job_seen(full_id):
                                consecutive_seen_cards += 1
                                continue
                                
                            consecutive_seen_cards = 0 # Reset counter
                            
                            page.goto(job_url, wait_until="domcontentloaded")
                            time.sleep(random.uniform(1.5, 2.5))
                            
                            title = page.locator("h1").inner_text() if page.locator("h1").count() > 0 else "Unknown Title"
                            description = extract_description(page.content())
                            
                            logger.info(f"   [WTTJ] Scraped: {title}")
                            
                            jobs.append(JobPosting(
                                id=full_id,
                                title=title,
                                company="WTTJ Company", 
                                location=self.location,
                                url=job_url,
                                description=description,
                                source="WelcomeToTheJungle"
                            ))
                        except Exception as e:
                            logger.error(f"Error parsing WTTJ job page: {e}")
                            
                browser.close()
        except Exception as e:
            logger.error(f"WTTJ Scraping failed: {e}")
                
        return jobs
