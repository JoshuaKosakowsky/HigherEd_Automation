from shared.browser_profile import (
    AutomationBrowserProfile,
    get_automation_browser_profile,
)

BANNER_URL = "https://appnav-prod.mines.elluciancloud.com:8101/applicationNavigator"
BANNER_ADMIN_URL = "https://banneradmin-prod.mines.elluciancloud.com:8104/BannerAdmin/?form="

def get_banner_profile(browser: str = "chrome") -> AutomationBrowserProfile:
    """Return the shared local automation profile for Banner's browser."""
    return get_automation_browser_profile(browser)
