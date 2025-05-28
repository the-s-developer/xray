from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

URL = "https://www.hurriyet.com.tr/teknoloji"
RESULT = []
if "MAX_COUNT" not in globals():
    MAX_COUNT = 10

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL, timeout=90000)
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    news = []
    # Teknoloji haberleri genellikle ana içerik alanında 'article' veya 'div' içinde başlık/link kombinasyonları ile yer alır
    # URL snapshot'ına göre başlık linkleri <h2> altında veya doğrudan <a> ile olabilir. Burada ikisine de bakıyoruz
    for h2 in soup.find_all("h2"):
        a = h2.find("a")
        if a and a.get('href'):
            title = a.get_text(strip=True)
            url = a['href']
            if not url.startswith('http'):
                url = 'https://www.hurriyet.com.tr' + url
            news.append({
                "title": title,
                "url": url
            })
        if len(news) == MAX_COUNT:
            break
    
    # Hala 10'a ulaşmadıysak diğer başlık biçimlerini de al
    if len(news) < MAX_COUNT:
        for link in soup.find_all('a', href=True):
            # /teknoloji/ ile başlayan ve başlık gibi görünen linkler
            href = link['href']
            if href.startswith('/teknoloji/') and link.get_text(strip=True):
                title = link.get_text(strip=True)
                url = 'https://www.hurriyet.com.tr' + href
                item = {"title": title, "url": url}
                if item not in news:
                    news.append(item)
            if len(news) == MAX_COUNT:
                break
    RESULT.extend(news)
    browser.close()
    print(RESULT)
