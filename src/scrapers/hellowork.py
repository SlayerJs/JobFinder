import os
import time
import random
import logging
import requests
from bs4 import BeautifulSoup
from typing import List
from .base import BaseScraper
from src.models import JobPosting
from src.content import extract_description

logger = logging.getLogger(__name__)

class HelloWorkScraper(BaseScraper):
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
        logger.info(f"Scraping HelloWork for '{self.keyword}' in '{self.location}'...")
        if self.proxies:
            logger.info("🛡️ Routing HelloWork traffic through configured proxy.")
            
        jobs = []
        url = "https://www.hellowork.com/fr-fr/emploi/recherche.html"
        
        consecutive_seen_cards = 0

        # Deep Pagination Loop
        for page_num in range(1, self.max_pages + 1):
            if consecutive_seen_cards >= 40:
                logger.info("Hit a block of already seen jobs. Stopping HelloWork pagination early!")
                break
                
            logger.info(f"Fetching HelloWork jobs (Page: {page_num})...")
            params = {"k": self.keyword, "l": self.location, "p": page_num}

            try:
                response = requests.get(url, params=params, headers=self.headers, proxies=self.proxies, timeout=15)
                if response.status_code != 200:
                    break
                    
                soup = BeautifulSoup(response.text, "html.parser")
                job_links = soup.select("a[href*='/fr-fr/emplois/']")
                
                urls = []
                for link in job_links:
                    href = link.get("href")
                    if href and href.startswith("/"):
                        urls.append("https://www.hellowork.com" + href)
                        
                urls = list(set(urls))
                if not urls:
                    break # End of pagination, no more results
                
                for job_url in urls:
                    try:
                        job_id = job_url.split("-")[-1].split(".")[0]
                        full_id = f"hw-{job_id}"
                        
                        # SMART SKIP
                        if db and db.is_job_seen(full_id):
                            consecutive_seen_cards += 1
                            continue
                            
                        consecutive_seen_cards = 0
                            
                        res = requests.get(job_url, headers=self.headers, proxies=self.proxies, timeout=15)
                        res.raise_for_status()
                        job_soup = BeautifulSoup(res.text, "html.parser")
                        
                        title_elem = job_soup.find("h1")
                        title = title_elem.text.strip() if title_elem else "Unknown Title"
                        
                        desc_elem = job_soup.select_one("section[data-tw-component='job-description']")
                        if not desc_elem:
                            desc_elem = job_soup.find("main")
                            
                        description = extract_description(res.text)
                        
                        logger.info(f"   [HelloWork] Scraped: {title}")
                        
                        jobs.append(JobPosting(
                            id=full_id,
                            title=title,
                            company="See HelloWork Listing",
                            location=self.location,
                            url=job_url,
                            description=description,
                            source="HelloWork"
                        ))
                        
                        time.sleep(random.uniform(1.5, 3.5))
                    except Exception as e:
                        logger.error(f"Error parsing HelloWork job page: {e}")
                        
            except Exception as e:
                logger.error(f"Failed to scrape HelloWork page {page_num}: {e}")
            
        return jobs
