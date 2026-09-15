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

class FranceTravailScraper(BaseScraper):
    def __init__(self, keyword="software engineer", location="", max_pages=10):
        self.keyword = keyword
        self.location = location
        self.max_pages = max_pages
        self.proxy_url = os.getenv("PROXY_URL")

    def scrape_jobs(self, db=None) -> List[JobPosting]:
        logger.info(f"Scraping France Travail via Playwright...")
        jobs = []
        
        try:
            with sync_playwright() as p:
                launch_args = {"headless": True}
                if self.proxy_url:
                    launch_args["proxy"] = {"server": self.proxy_url}
                
                browser = p.chromium.launch(**launch_args)
                page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36")

                consecutive_seen_cards = 0

                for page_num in range(0, self.max_pages):
                    if consecutive_seen_cards >= 40:
                        break
                        
                    
                    # natureContrat=E1,E2,FA,FJ,FP (Filters for different types of stages/contracts usually, but we will let the AI filter it)
                    if page_num == 0:
                        search_url = f"https://candidat.francetravail.fr/offres/recherche?motsCles={quote(self.keyword, safe='')}"
                    else:
                        start_idx = page_num * 20
                        end_idx = start_idx + 19
                        search_url = f"https://candidat.francetravail.fr/offres/recherche.rechercheoffre:afficherplusderesultats/{start_idx}-{end_idx}/0?motsCles={quote(self.keyword, safe='')}"
                        
                    logger.info(f"Fetching France Travail jobs (Page: {page_num + 1})...")
                    page.goto(search_url, wait_until="domcontentloaded")
                    time.sleep(random.uniform(2.5, 4.0)) 
                    
                    cards_data = page.evaluate("""() => {
                        let elements = Array.from(document.querySelectorAll('a')).filter(a => a.href && a.href.includes('/offres/recherche/detail/'));
                        return elements.map(a => {
                            let card = a.closest('li'); 
                            let titleEl = card ? card.querySelector('.titre, h2') : null;
                            let companyEl = card ? card.querySelector('.nom-entreprise, .entreprise') : null;
                            return {
                                url: a.href,
                                title: titleEl ? titleEl.innerText : 'Unknown Title',
                                company: companyEl ? companyEl.innerText : 'See Listing'
                            };
                        });
                    }""")
                    
                    if not cards_data:
                        break
                        
                    unique_cards = {c['url']: c for c in cards_data}.values()
                        
                    for job_data in unique_cards:
                        try:
                            job_url = job_data['url']
                            title = job_data['title']
                            company = job_data['company']
                            
                            raw_id = job_url.split("/")[-1]
                            full_id = f"francetravail-{raw_id}"
                            
                            if db and db.is_job_seen(full_id):
                                consecutive_seen_cards += 1
                                continue
                                
                            consecutive_seen_cards = 0
                            
                            page.goto(job_url, wait_until="domcontentloaded")
                            time.sleep(random.uniform(1.5, 2.5))
                            
                            if title == 'Unknown Title':
                                title = page.title().split(" | ")[0]
                                
                            description = extract_description(page.content())
                            
                            logger.info(f"   [FranceTravail] Scraped: {title}")
                            
                            jobs.append(JobPosting(
                                id=full_id,
                                title=title,
                                company=company,
                                location=self.location,
                                url=job_url,
                                description=description,
                                source="FranceTravail"
                            ))
                        except Exception as e:
                            logger.error(f"Error parsing FranceTravail job page: {e}")
                            
                browser.close()
        except Exception as e:
            logger.error(f"France Travail Scraping failed: {e}")
                
        return jobs
