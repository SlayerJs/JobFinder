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

class ApecScraper(BaseScraper):
    def __init__(self, keyword="software engineer", location="", max_pages=10, contract_filter=None):
        self.contract_filter = contract_filter
        self.keyword = keyword
        self.location = location
        self.max_pages = max_pages
        self.proxy_url = os.getenv("PROXY_URL")

    def scrape_jobs(self, db=None) -> List[JobPosting]:
        logger.info(f"Scraping APEC via Playwright...")
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

                for page_num in range(0, self.max_pages):
                    if consecutive_seen_cards >= 40:
                        logger.info("Hit a block of already seen jobs. Stopping APEC pagination early!")
                        break
                        
                    
                    # Optional source-specific contract code from configuration.
                    search_url = f"https://www.apec.fr/candidat/recherche-emploi.html/emploi?motsCles={quote(self.keyword, safe='')}&page={page_num}"
                    
                    if self.contract_filter:
                        search_url += "&typesConvention=" + quote(str(self.contract_filter), safe="")

                    logger.info(f"Fetching APEC jobs (Page: {page_num + 1})...")
                    page.goto(search_url, wait_until="domcontentloaded")
                    time.sleep(random.uniform(2.5, 4.0)) 
                    
                    # Extract URLs, Titles, and Companies directly from the search page cards
                    # This bypasses any login/TOS modals that block the H1 on the individual job pages.
                    cards_data = page.evaluate("""() => {
                        return Array.from(document.querySelectorAll('apec-recherche-resultat')).map(card => {
                            let a = card.closest('a');
                            let titleEl = card.querySelector('.card-title');
                            let companyEl = card.querySelector('.card-offer__company');
                            return {
                                url: a ? a.href : '',
                                title: titleEl ? titleEl.innerText : 'Unknown Title',
                                company: companyEl ? companyEl.innerText : 'Unknown Company'
                            };
                        }).filter(c => c.url.includes('/detail-offre/'));
                    }""")
                    
                    if not cards_data:
                        logger.info("No more jobs found on APEC.")
                        break
                        
                    # Remove duplicates by URL
                    unique_cards = {c['url']: c for c in cards_data}.values()
                        
                    for job_data in unique_cards:
                        try:
                            job_url = job_data['url']
                            title = job_data['title']
                            company = job_data['company']
                            
                            # Extract ID from URL
                            raw_id = job_url.split("/detail-offre/")[1].split("?")[0]
                            full_id = f"apec-{raw_id}"
                            
                            if db and db.is_job_seen(full_id):
                                consecutive_seen_cards += 1
                                continue
                                
                            consecutive_seen_cards = 0
                            
                            page.goto(job_url, wait_until="domcontentloaded")
                            time.sleep(random.uniform(1.5, 2.5))
                            
                            description = extract_description(page.content())
                            
                            logger.info(f"   [APEC] Scraped: {title} @ {company}")
                            
                            jobs.append(JobPosting(
                                id=full_id,
                                title=title,
                                company=company,
                                location=self.location,
                                url=job_url,
                                description=description,
                                source="APEC"
                            ))
                        except Exception as e:
                            logger.error(f"Error parsing APEC job page: {e}")
                            
                browser.close()
        except Exception as e:
            logger.error(f"APEC Scraping failed: {e}")
                
        return jobs
