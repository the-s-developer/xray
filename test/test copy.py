import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

# Launch undetected Chrome
options = uc.ChromeOptions()
# options.add_argument('--headless')  # Uncomment for headless mode
driver = uc.Chrome(options=options)

# Your target URL
url = 'https://www.bubilet.com.tr/istanbul'

try:
    driver.get(url)
    time.sleep(3)  # Wait for the page and Swiper to load

    # Get all links from swiper slides
    slides = driver.find_elements(By.CSS_SELECTOR, '.swiper-slide a')
    links = list({slide.get_attribute('href') for slide in slides if slide.get_attribute('href')})

    print(f"Found {len(links)} detail pages.")

    for idx, link in enumerate(links, 1):
        print(f"Visiting {idx}/{len(links)}: {link}")
        driver.get(link)
        time.sleep(2)  # Adjust delay as needed for page load
        # --- Place scraping logic here if desired ---

    print("Done.")

finally:
    driver.quit()
