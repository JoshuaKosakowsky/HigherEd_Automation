"""Read Windows platform information without starting a console."""

import platform
import sys


def prime_windows_platform() -> None:
    """Fill Python's platform cache without invoking cmd.exe for `ver`."""
    if sys.platform != "win32":
        return
    lookup = getattr(platform, "_syscmd_ver", None)
    if lookup is None:
        return

    # The Windows fallback in CPython's platform.uname() may run "ver".
    # Supply the native OS version while that cache is populated, and
    # restore the original lookup for any explicit checks elsewhere.
    native_version = ".".join(map(str, sys.getwindowsversion().platform_version))

    def version_without_console(system="", release="", _version=""):
        return system, release, native_version

    platform._syscmd_ver = version_without_console
    try:
        platform.uname()
    finally:
        platform._syscmd_ver = lookup
