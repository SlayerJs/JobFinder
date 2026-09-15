import os
import time
import random
import logging
import requests
from bs4 import BeautifulSoup
from typing import List
from .base import BaseScraper
from src.models import JobPosting

logger = logging.getLogger(__name__)

class LinkedInScraper(BaseScraper):
    def __init__(self, keyword="software engineer", location="", max_pages=10):
        self.keyword = keyword
        self.location = location
        self.max_pages = max_pages
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        self.proxy_url = os.getenv("PROXY_URL")
        self.proxies = {"http": self.proxy_url, "https": self.proxy_url} if self.proxy_url else None

    def scrape_jobs(self, db=None) -> List[JobPosting]:
        logger.info(f"Scraping LinkedIn Guest API for '{self.keyword}'...")
        jobs = []
        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        
        consecutive_seen_cards = 0

        # Paginate through multiple pages (25 jobs per page)
        for offset in range(0, self.max_pages * 25, 25):
            if consecutive_seen_cards >= 50:
                logger.info("Hit a block of already seen jobs. Stopping LinkedIn pagination early to save requests!")
                break
                
            logger.info(f"Fetching LinkedIn jobs (Offset: {offset})...")
            params = {"keywords": self.keyword, "location": self.location, "start": offset}

            try:
                response = requests.get(url, params=params, headers=self.headers, proxies=self.proxies, timeout=15)
                if response.status_code != 200:
                    break
                    
                soup = BeautifulSoup(response.text, "html.parser")
                job_cards = soup.find_all("div", class_="base-search-card")
                
                if not job_cards:
                    break # No more results
                
                for card in job_cards:
                    try:
                        link_elem = card.find("a", class_="base-card__full-link")
                        if not link_elem:
                            continue
                            
                        job_url = link_elem["href"].split("?")[0]
                        job_id = card.get("data-entity-urn", "").split(":")[-1] or job_url.split("-")[-1]
                        full_id = f"li-{job_id}"
                        
                        # SMART SKIP: If we already evaluated this job, skip downloading the description!
                        if db and db.is_job_seen(full_id):
                            consecutive_seen_cards += 1
                            continue
                            
                        consecutive_seen_cards = 0 # Reset counter when we find a new job
                        
                        title_elem = card.find("h3", class_="base-search-card__title")
                        company_elem = card.find("h4", class_="base-search-card__subtitle")
                        title = title_elem.text.strip()
                        company = company_elem.text.strip()
                        
                        # Fetch description only for NEW jobs
                        description = self._get_job_description(job_url)
                        if not description:
                            continue

                        logger.info(f"   [LinkedIn] Scraped: {title} @ {company}")

                        jobs.append(JobPosting(
                            id=full_id, title=title, company=company, location=self.location,
                            url=job_url, description=description, source="LinkedIn"
                        ))
                        time.sleep(random.uniform(2.0, 4.0))
                    except Exception as e:
                        logger.error(f"Error parsing LinkedIn card: {e}")
            except Exception as e:
                logger.error(f"Failed to scrape LinkedIn offset {offset}: {e}")
                
        return jobs

    def _get_job_description(self, url: str) -> str:
        try:
            res = requests.get(url, headers=self.headers, proxies=self.proxies, timeout=15)
            if res.status_code != 200: return ""
            soup = BeautifulSoup(res.text, "html.parser")
            desc_div = soup.find("div", class_="show-more-less-html__markup")
            return desc_div.get_text(separator="\n").strip() if desc_div else ""
        except Exception: return ""
