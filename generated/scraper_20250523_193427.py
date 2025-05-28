import httpx
from bs4 import BeautifulSoup

MAX_COUNT = MAX_COUNT if 'MAX_COUNT' in globals() else 3
RESULT = []

url = 'https://meb.gov.tr'
resp = httpx.get(url)
soup = BeautifulSoup(resp.text, 'html.parser')

count = 0
for link in soup.select('a[href]'):
    ann = link.find('div') or link
    text = ann.text if ann and ann.text else ''
    if 'duyuru' in link.get('href', '').lower() or 'duyuru' in text.lower():
        parent = link.parent
        tarih = None
        baslik = link.text.strip()
        detay_url = link['href'] if link['href'].startswith('http') else url.rstrip('/') + '/' + link['href'].lstrip('/')
        for sibling in link.find_all_previous(['p', 'span', 'div']):
            if any(str(k).lower() in sibling.text.lower() for k in ['202', '20', 'may', 'nisan', 'mart', 'ocak', 'subat', 'temmuz', 'agustos', 'eylul', 'ekim', 'aralik']):
                tarih = sibling.text.strip()
                break
        detay = ''
        try:
            detay_resp = httpx.get(detay_url)
            detay_soup = BeautifulSoup(detay_resp.text, 'html.parser')
            detay_para = detay_soup.find_all('p')
            if detay_para:
                detay = ' '.join([d.get_text(strip=True) for d in detay_para if len(d.get_text(strip=True)) > 40][:2])
            else:
                detay = detay_soup.get_text(strip=True)[:300]
        except Exception:
            detay = ''
        item = {'Tarih': tarih, 'Başlık': baslik, 'Detay': detay, 'Link': detay_url}
        RESULT.append(item)
        count += 1
        if count == MAX_COUNT:
            break