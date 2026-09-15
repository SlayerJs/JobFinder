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

class LesJeudisScraper(BaseScraper):
    def __init__(self, keyword="software engineer", location="", max_pages=10):
        self.keyword = keyword
        self.location = location
        self.max_pages = max_pages
        self.proxy_url = os.getenv("PROXY_URL")

    def scrape_jobs(self, db=None) -> List[JobPosting]:
        logger.info(f"Scraping LesJeudis via Playwright...")
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
                        logger.info("Hit a block of already seen jobs. Stopping LesJeudis pagination early!")
                        break
                        
                    # Fresh context
                    
                    search_url = f"https://www.lesjeudis.com/recherche?q={quote(self.keyword, safe='')}&page={page_num}"
                    
                    logger.info(f"Fetching LesJeudis jobs (Page: {page_num})...")
                    page.goto(search_url, wait_until="domcontentloaded")
                    time.sleep(random.uniform(2.5, 4.0)) 
                    
                    # Extract URLs, Titles, and Companies directly from the search page
                    cards_data = page.evaluate("""() => {
                        let elements = Array.from(document.querySelectorAll('a')).filter(a => a.href && a.href.includes('/job/'));
                        return elements.map(a => {
                            let card = a.closest('div'); // Usually wrapped in a card div
                            let titleEl = card ? card.querySelector('h2, h3, .job-title, [class*="title"]') : null;
                            let companyEl = card ? card.querySelector('.company-name, [class*="company"]') : null;
                            return {
                                url: a.href,
                                title: titleEl ? titleEl.innerText : 'Unknown Title',
                                company: companyEl ? companyEl.innerText : 'Unknown Company'
                            };
                        });
                    }""")
                    
                    if not cards_data:
                        logger.info("No more jobs found on LesJeudis.")
                        break
                        
                    unique_cards = {c['url']: c for c in cards_data}.values()
                        
                    for job_data in unique_cards:
                        try:
                            job_url = job_data['url']
                            title = job_data['title']
                            company = job_data['company']
                            
                            # Extract ID from URL (e.g. /fr/job/administratrice-462411 -> 462411)
                            raw_id = job_url.split("-")[-1]
                            full_id = f"lesjeudis-{raw_id}"
                            
                            if db and db.is_job_seen(full_id):
                                consecutive_seen_cards += 1
                                continue
                                
                            consecutive_seen_cards = 0
                            
                            page.goto(job_url, wait_until="domcontentloaded")
                            time.sleep(random.uniform(1.5, 2.5))
                            
                            # Fallback extraction if search page failed to grab it
                            if title == 'Unknown Title':
                                title = page.title().split(" | ")[0]
                                
                            description = extract_description(page.content())
                            
                            logger.info(f"   [LesJeudis] Scraped: {title}")
                            
                            jobs.append(JobPosting(
                                id=full_id,
                                title=title,
                                company=company,
                                location=self.location,
                                url=job_url,
                                description=description,
                                source="LesJeudis"
                            ))
                        except Exception as e:
                            logger.error(f"Error parsing LesJeudis job page: {e}")
                            
                browser.close()
        except Exception as e:
            logger.error(f"LesJeudis Scraping failed: {e}")
                
        return jobs
