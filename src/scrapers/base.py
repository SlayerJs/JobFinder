from abc import ABC, abstractmethod
from typing import List
from src.models import JobPosting

class BaseScraper(ABC):
    @abstractmethod
    def scrape_jobs(self, db=None) -> List[JobPosting]:
        """
        Scrapes the target job board.
        If db is provided, checks db.is_job_seen() to skip fetching descriptions for known jobs.
        """
        pass
