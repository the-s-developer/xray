import os
import sys

sys.stdout = sys.stderr

try:
    from playwright.sync_api import _api
    sync_browser_type = _api.SyncBrowserType
except (ImportError, AttributeError):
    from playwright._impl._browser_type import BrowserType as sync_browser_type

orig_launch = sync_browser_type.launch
orig_launch_persistent = sync_browser_type.launch_persistent_context

def launch_with_env(self, *args, **kwargs):
    chrome_path = os.environ.get("CHROME_PATH")
    if ("executablePath" not in kwargs or kwargs["executablePath"] is None) and chrome_path:
        kwargs["executablePath"] = chrome_path
    return orig_launch(self, *args, **kwargs)

def launch_persistent_with_env(self, *args, **kwargs):
    chrome_path = os.environ.get("CHROME_PATH")
    patch_user_data_dir = os.environ.get("USER_DATA_DIR")

    kwargs["userDataDir"] = patch_user_data_dir

    if ("executablePath" not in kwargs or kwargs["executablePath"] is None) and chrome_path:
        kwargs["executablePath"] = chrome_path
    return orig_launch_persistent(self, *args, **kwargs)

# Patch fonksiyonlarını ata
sync_browser_type.launch = launch_with_env
sync_browser_type.launch_persistent_context = launch_persistent_with_env

from playwright.sync_api import sync_playwright
