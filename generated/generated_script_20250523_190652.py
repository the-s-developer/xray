from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

RESULT = []
MAX_COUNT = MAX_COUNT if 'MAX_COUNT' in globals() else 3

url = "https://www.haberler.com/teknoloji/"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(url)
    html = page.content()
    browser.close()

soup = BeautifulSoup(html, "html.parser")

# <main> altında, tekrar etmeyen, doğrudan haber başlığı ve linki bul
main = soup.find('main')
if main:
    habers = []
    # En fazla 3 haberi toplamak için
    # h2 ve h3 başlıklarını ve bunların parent'ındaki a'ları ara
    for htag in main.find_all(['h2', 'h3']):
        parent_link = htag.find_parent('a', href=True)
        if parent_link:
            title = htag.get_text(strip=True)
            link = parent_link['href']
            if link.startswith('/'):
                link = 'https://www.haberler.com' + link
            habers.append({'title': title, 'url': link})
        if len(habers) >= MAX_COUNT:
            break
    RESULT.extend(habers)
