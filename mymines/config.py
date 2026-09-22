from shared.browser_profile import (
    AutomationBrowserProfile,
    get_automation_browser_profile,
)


MINES_URL = "https://my.mines.edu/"

def get_mines_profile(browser: str = "chrome") -> AutomationBrowserProfile:
    """Return the shared local automation profile for MyMines."""
    return get_automation_browser_profile(browser)
