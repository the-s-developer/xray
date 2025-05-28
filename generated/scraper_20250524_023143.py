from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('https://www.meb.gov.tr/meb_haberindex.php?dil=tr', timeout=60000)
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
                haberler.append({'tarih': tarih, 'baslik': baslik, 'link': href})
    print(haberler[:5])
    browser.close()
