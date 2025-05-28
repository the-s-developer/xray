from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    base_url = 'https://www.meb.gov.tr'
    page.goto(f'{base_url}/meb_haberindex.php?dil=tr', timeout=60000)
    page.wait_for_selector('table')
    rows = page.query_selector_all('table tbody tr')
    haberler = []
    for row in rows:
        cells = row.query_selector_all('td')
        if len(cells) == 2:
            tarih = cells[0].inner_text().strip()
            haber_cell = cells[1]
            link = haber_cell.query_selector('a')
            if link:
                baslik = link.inner_text().strip()
                href = link.get_attribute('href')
                if href and not href.startswith('javascript'):
                    detail_url = href if href.startswith('http') else f'{base_url}{href}'
                    # Haber detayına git
                    detail_page = browser.new_page()
                    detail_page.goto(detail_url, timeout=60000)
                    detail_page.wait_for_timeout(2000)
                    # Detay içeriği bulmaya çalış
                    try:
                        content_el = detail_page.query_selector(".newsContent")
                        icerik = content_el.inner_text().strip() if content_el else ''
                    except:
                        icerik = ''
                    haberler.append({'tarih': tarih, 'baslik': baslik, 'link': detail_url, 'icerik': icerik})
                    detail_page.close()
    # İlk 3 örnek göster
    for h in haberler[:3]:
        print(f"Tarih: {h['tarih']}\nBaşlık: {h['baslik']}\nLink: {h['link']}\nİçerik: {h['icerik'][:300]}...\n{'-'*50}")
    browser.close()
