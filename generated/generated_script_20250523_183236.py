# Scraper for haberler.com/teknoloji - extracts first 3 technology news (title + url)
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

RESULT = []
MAX_COUNT = MAX_COUNT if 'MAX_COUNT' in globals() else 3

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://www.haberler.com/teknoloji/")
    html = page.content()
    browser.close()

soup = BeautifulSoup(html, 'html.parser')
news_items = []

# Try to find news in the main news-teaser structure (safe fallback for haberler.com/teknoloji)
for link in soup.find_all('a', href=True):
    heading = link.find('h3')
    if heading and link['href'].startswith("/teknoloji/"):
        news_items.append({
            'title': heading.get_text(strip=True),
            'url': 'https://www.haberler.com' + link['href']
        })
    if len(news_items) >= MAX_COUNT:
        break

if len(news_items) < MAX_COUNT:
    for heading in soup.find_all('h3'):
        alink = heading.find_parent('a')
        if alink and alink['href'].startswith("/teknoloji/"):
            news_items.append({
                'title': heading.get_text(strip=True),
                'url': 'https://www.haberler.com' + alink['href']
            })
        if len(news_items) >= MAX_COUNT:
            break

RESULT.extend(news_items[:MAX_COUNT])
# Sample output: print(RESULT)
