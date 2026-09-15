from dataclasses import dataclass
from typing import Optional

@dataclass
class JobPosting:
    id: str
    title: str
    company: str
    location: str
    url: str
    description: str
    source: str
