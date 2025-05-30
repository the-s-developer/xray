import json
import sys
from playwright.sync_api import sync_playwright

RESULT = {}

print("Playwright başlatılıyor...")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    print("Chromium başlatıldı.")
    page = browser.new_page()
    print("Google ana sayfası açılıyor...")
    page.goto("https://www.google.com/")
    print("Sayfa yüklendi.")

    title = page.title()
    print(f"Sayfa başlığı bulundu: {title}")
    RESULT["title"] = title

    # Arama butonunun textini de çekelim (örnek ek veri)
    button = page.query_selector("input[name='btnK']")
    if button:
        button_text = button.get_attribute('value')
        print(f"Arama butonunun texti: {button_text}")
        RESULT["search_button_text"] = button_text
    else:
        print("Arama butonu bulunamadı.")
        RESULT["search_button_text"] = None

    print("Hatalı bir JavaScript kodu çalıştırılıyor...")
    page.evaluate("nonExistentFunction();")  # Burada exception fırlayacak

    print("Tarayıcı kapatıldı.")
    browser.close()

