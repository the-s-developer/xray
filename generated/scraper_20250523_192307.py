import httpx
from bs4 import BeautifulSoup

MAX_COUNT = MAX_COUNT if 'MAX_COUNT' in globals() else 25
RESULT = []

url = 'https://www.haberler.com/teknoloji/'
response = httpx.get(url)
soup = BeautifulSoup(response.text, 'html.parser')

main_news = soup.select('div[class*=haberContent]')
if not main_news:
    main_news = soup.find_all('a', href=True)
count = 0
for a in soup.find_all('a', href=True):
    if a.get('href', '').startswith('/teknoloji/') and a.text.strip():
        title = a.text.strip()
        link = 'https://www.haberler.com' + a['href']
        RESULT.append({'title': title, 'link': link})
        count += 1
        if count >= MAX_COUNT:
            break