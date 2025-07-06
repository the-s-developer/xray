import time
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://www.bubilet.com.tr"
LISTING_URL = "https://www.bubilet.com.tr/istanbul"

# Set up undetected Chrome
options = uc.ChromeOptions()
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
driver = uc.Chrome(options=options)

def extract_event_links(soup):
    """Find all event links on the listing page"""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/etkinlik/" in href and href.startswith("/istanbul/etkinlik/"):
            full_url = urljoin(BASE_URL, href.split("?")[0])
            if full_url not in links:
                links.append(full_url)
    return links

def extract_event_data(event_url):
    """Scrape event details from an individual event page"""
    driver.get(event_url)
    time.sleep(3)

    soup = BeautifulSoup(driver.page_source, "html.parser")

    try:
        title = soup.find("h1").get_text(strip=True)
    except:
        title = "N/A"

    try:
        tickets_section = soup.find(id="biletler-section")
        ticket_card = tickets_section.select_one(".hover\\:bg-gray-50")

        date_time = ticket_card.select_one(".text-xs.text-gray-600").get_text(" ", strip=True)
        location = ticket_card.select_one(".text-xs.text-gray-500").text.strip()
        price = ticket_card.select_one(".text-lg.font-semibold").text.strip()
        buy_link = urljoin(BASE_URL, ticket_card.find("a")["href"])
    except:
        date_time = location = price = buy_link = "N/A"

    return {
        "url": event_url,
        "title": title,
        "date_time": date_time,
        "location": location,
        "price": price,
        "buy_link": buy_link
    }

# Visit listing page
driver.get(LISTING_URL)
time.sleep(4)

# Parse listing
soup = BeautifulSoup(driver.page_source, "html.parser")
event_links = extract_event_links(soup)

print(f"Found {len(event_links)} event pages.")

# Scrape each event page
all_data = []
for link in event_links:
    print(f"Scraping: {link}")
    data = extract_event_data(link)
    all_data.append(data)

# Output scraped results
for event in all_data:
    print("\n--- EVENT ---")
    for key, value in event.items():
        print(f"{key}: {value}")

driver.quit()
