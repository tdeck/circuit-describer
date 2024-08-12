from dataclasses import dataclass
from typing import List, Dict, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By

@dataclass
class ProjectListing:
    url: str
    title: str
    tagline: str  # Not sure what this is really called
    description_html: str
    creator: str
    #difficulty: str  # kids, amateurs, masters, fritzmasters
    license_url: str
    image_urls: List[str]
    download_urls: Dict[str, str]  # Filename -> URL


ALLOWED_LICENSES = {
    'https://creativecommons.org/licenses/by-sa/3.0/',
}

FIRST_PAGE = 1
LAST_PAGE = 5 # TODO


def scrape_single_project(url: str, driver:Optional[webdriver.Firefox]=None) -> ProjectListing:
    ephemeral_driver = driver is None

    if ephemeral_driver:
        driver = webdriver.Firefox()

    driver.get(url)

    image_urls = [a.get_attribute('href') for a in driver.find_elements(By.CSS_SELECTOR, '.thumb-gallery > li > a')]
    download_urls = {
        a.get_attribute('innerText'): a.get_attribute('href') 
        for a in driver.find_elements(By.CSS_SELECTOR, '.highlight li > a')
    }

    res = ProjectListing(
        url=url,
        title=driver.title,
        tagline=driver.find_element(By.CLASS_NAME, 'lead').get_attribute('innerText'),
        description_html=driver.find_element(By.CSS_SELECTOR, '#content div.row:nth-child(4) > div:nth-child(1)').get_attribute('innerHTML'),
        creator=driver.find_element(By.CSS_SELECTOR, '.meta > h3:nth-child(1) > a:nth-child(1)').get_attribute('innerText'),
        license_url=driver.find_element(By.CSS_SELECTOR, '.license > a').get_attribute('href'),
        image_urls=image_urls,
        download_urls=download_urls,
    )

    if ephemeral_driver:
        driver.close()

    return res


#with webdriver.Firefox() as driver:
#    print(scrape_single_project(driver, 'https://fritzing.org/projects/arduino-bipolar-stepper-motor-controller'))
    #print(scrape_single_project(driver, 'https://fritzing.org/projects/serial-voice'))
