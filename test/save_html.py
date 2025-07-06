import undetected_chromedriver as uc
import sys, time, re
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from bs4.element import AttributeValueList

def remove_ads(driver):
    ad_selectors = [
        "iframe",
        "[id*='ad']",
        "[class*='ad']",
        "[class*='banner']",
        "[class*='sponsor']",
    ]
    for selector in ad_selectors:
        while True:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if not elements:
                break
            for el in elements:
                try:
                    driver.execute_script("arguments[0].remove()", el)
                except Exception:
                    pass

def collapse_trivial_tags(soup, tags=("span", "div", "section")):
    # tags: sadece tek anlamlı çocuk barındırıyorsa açılacak olanlar
    def collapse(tag):
        # Sadece belirtilen tag ve sadece 1 çocuk barındırıyorsa
        while (
            tag.name in tags
            and len(tag.contents) == 1
            and getattr(tag.contents[0], 'name', None) in tags
            and not tag.attrs
        ):
            tag.unwrap()
            tag = tag.contents[0] if tag.contents else tag
        for child in list(tag.children):
            if getattr(child, 'name', None):
                collapse(child)
    collapse(soup)
    return soup

def remove_empty_tags(soup):
    # List of tags that should NOT be removed, even if empty
    void_tags = set(["br", "img", "input", "meta", "link", "hr", "source", "embed", "track", "area", "col", "base", "wbr"])
    
    def is_effectively_empty(tag):
        if tag.name in void_tags:
            return False
        # Has text content?
        text = tag.get_text(strip=True)
        if text:
            return False
        # Has non-empty child tags?
        for child in tag.find_all(recursive=False):
            if isinstance(child, str):
                if child.strip():
                    return False
            elif child.name in void_tags:
                return False
            elif not is_effectively_empty(child):
                return False
        return True

    # Traverse tags from bottom up (deepest first)
    for tag in soup.find_all(True):
        for child in tag.find_all(True, recursive=False):
            if is_effectively_empty(child):
                child.decompose()
    # Also check the root soup tag
    for tag in soup.find_all(True):
        if is_effectively_empty(tag):
            tag.decompose()
    return soup

SAFE_ATTRS = {"href", "src", "alt", "title", "name", "content"}

def clean_soup(soup, keep_head, keep_body):
    for tag in soup(["script", "style", "svg"]):
        tag.decompose()
    for tag in soup.find_all(True):
        tag.attrs.pop("style", None)
        tag.attrs.pop("class", None)
        tag.attrs.pop("id", None)
    for img in soup.find_all("img", src=True):
        if img["src"].startswith("data:image"):
            img.decompose()
    for link in soup.find_all("link", rel="stylesheet"):
        link.decompose()
    if not keep_head and soup.head:
        soup.head.decompose()
    if not keep_body and soup.body:
        soup.body.decompose()
    soup = remove_empty_tags(soup)
    soup = collapse_trivial_tags(soup)   # <-- Bunu ekle!
    return soup


def save_page_html(url, output_file="output.html", wait_time=5,
                   clean=False, keep_head=True, keep_body=True,
                   pretty_format=True, headless=True):
    opts = uc.ChromeOptions()
    if headless:
        opts.headless = True
    driver = uc.Chrome(options=opts)
    try:
        driver.get(url)
        time.sleep(wait_time)
        html = driver.page_source

        if clean:
            soup = BeautifulSoup(html, "html.parser")
            soup = clean_soup(soup, keep_head, keep_body)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(soup.prettify() if pretty_format else str(soup))
        else:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(html)
        print(f"[✔] Saved to {output_file}")
    finally:
        driver.quit()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python save_html.py <url> [output_file(.html)] [--clean] [--no-head] [--no-body] [--minify] [--no-headless]")
        sys.exit(1)

    url = sys.argv[1]
    output_file = "output.html"
    clean_flag = keep_head = keep_body = pretty_format = headless_mode = False
    keep_head = keep_body = pretty_format = headless_mode = True

    for arg in sys.argv[2:]:
        if arg.endswith(".html"):
            output_file = arg
        elif arg == "--clean":
            clean_flag = True
        elif arg == "--no-head":
            keep_head = False
        elif arg == "--no-body":
            keep_body = False
        elif arg == "--minify":
            pretty_format = False
        elif arg == "--no-headless":
            headless_mode = False

    save_page_html(
        url, output_file, wait_time=5,
        clean=clean_flag, keep_head=keep_head, keep_body=keep_body,
        pretty_format=pretty_format, headless=headless_mode
    )
