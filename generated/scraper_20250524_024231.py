from playwright.sync_api import sync_playwright
import time

def scrape_meb_haberler(max_haber=5):
    results = []
    BASE_URL = "https://www.meb.gov.tr"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.meb.gov.tr/meb_haberindex.php?dil=tr", timeout=60000)
        page.wait_for_selector('table')
        rows = page.query_selector_all("table tbody tr")
        sayac = 0
        for row in rows:
            tds = row.query_selector_all('td')
            if len(tds) != 2:
                continue
            tarih = tds[0].inner_text().strip()
            link_a = tds[1].query_selector('a')
            if not link_a:
                continue
            baslik = link_a.inner_text().strip()
            href = link_a.get_attribute('href')
            if not href or href.startswith("javascript"):
                continue
            tam_link = href if href.startswith('http') else BASE_URL + href

            # Detay sayfasına git ve haberin içeriğini çek (başlık dışı tüm metni dahil edecek şekilde)
            detail_page = browser.new_page()
            detail_page.goto(tam_link, timeout=60000)
            content = ""
            try:
                detail_page.wait_for_selector('h2', timeout=4000)
                heading = detail_page.query_selector('h2')
                texts = []
                siblings = detail_page.query_selector_all('h2 ~ *')
                for el in siblings:
                    txt = el.inner_text().strip()
                    if txt:
                        texts.append(txt)
                content = "\n".join(texts)
            except Exception as e:
                content = ""
            detail_page.close()

            results.append({
                'tarih': tarih,
                'baslik': baslik,
                'link': tam_link,
                'icerik': content
            })
            sayac += 1
            if sayac >= max_haber:
                break
            time.sleep(0.2)  # Banlanmayı önlemek için

        browser.close()
    return results

# Test: İlk 3 haber için
haberler = scrape_meb_haberler(max_haber=3)
for idx, haber in enumerate(haberler, 1):
    print(f"{idx}. Haber:")
    print(f"Tarih: {haber['tarih']}")
    print(f"Başlık: {haber['baslik']}")
    print(f"Link: {haber['link']}")
    print(f"İçerik (ilk 300 karakter):\n{haber['icerik'][:300]}...")
    print('-' * 60)
