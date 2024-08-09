from dataclasses import dataclass
from typing import List, Dict

from lxml import etree
import requests

from config import HEADERS # This file will not be checked in; needs uagent and cookie

class ProjectListing:
    title: str
    description_html: str
    difficulty: str  # kids, amateurs, masters, fritzmasters
    image_urls: List[str]
    download_urls: Dict[str, str]  # Filename -> URL


ALLOWED_LICENSES = {
    'https://creativecommons.org/licenses/by-sa/3.0/',
}

FIRST_PAGE = 1
LAST_PAGE = 5 # TODO

def scrape_listing_page(url):
    body = requests.get(url, headers=HEADERS).content
    print(body)
    root = etree.fromstring(body, parser=etree.HTMLParser())
    print("Root", root)
    content_div = root.xpath("//*[@id='content']")
    print("CD", content_div)

scrape_listing_page('https://fritzing.org/projects/arduino-bipolar-stepper-motor-controller')
