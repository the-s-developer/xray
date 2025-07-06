import undetected_chromedriver as uc
from bs4 import BeautifulSoup
import time

# Setup undetected Chrome
options = uc.ChromeOptions()
options.add_argument("--headless")
driver = uc.Chrome(options=options)

# Go to main listing page
driver.get("https://bubilet.com.tr/istanbul")
time.sleep(5)

# Parse main page
soup = BeautifulSoup(driver.page_source, "html.parser")
event_links = soup.select('a[href^="/istanbul/etkinlik/"]')
event_urls = sorted(set("https://bubilet.com.tr" + link["href"] for link in event_links))

print(f"Found {len(event_urls)} events.\n")

# Visit each event page and extract details
for i, url in enumerate(event_urls, 1):
    try:
        driver.get(url)
        time.sleep(3)

        detail_soup = BeautifulSoup(driver.page_source, "html.parser")
        detail_section = detail_soup.select_one('#bilgiler-section')

        if detail_section:
            paragraphs = detail_section.find_all("p")
            detail_text = "\n".join(p.get_text(strip=True) for p in paragraphs)
        else:
            detail_text = "No detail section found."

        print(f"\n[{i}] {url}")
        print(detail_text)

    except Exception as e:
        print(f"\n[{i}] Error fetching {url}: {e}")

# Close browser
driver.quit()
