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

# def launch(self, *args, **kwargs):
#     if ("executablePath" not in kwargs or kwargs["executablePath"] is None) and CHROME_PATH:
#         kwargs["executablePath"] = CHROME_PATH
#     kwargs["headless"] = False
#     return orig_launch(self, *args, **kwargs)

# def launch_persistent_with_env(self, *args, **kwargs):
    
#     kwargs["userDataDir"] = USER_DATA_DIR
#     if ("executablePath" not in kwargs or kwargs["executablePath"] is None) and CHROME_PATH:
#         kwargs["executablePath"] = CHROME_PATH
#     kwargs["headless"] = False
#     return orig_launch_persistent(self, *args, **kwargs)

def launch(self, *args, **kwargs):
    kwargs["userDataDir"] = USER_DATA_DIR
    if ("executablePath" not in kwargs or kwargs["executablePath"] is None) and CHROME_PATH:
        kwargs["executablePath"] = CHROME_PATH
    kwargs["headless"] = False
    return orig_launch_persistent(self, *args, **kwargs)

sync_browser_type.launch = launch
sync_browser_type.launch_persistent_context = launch
