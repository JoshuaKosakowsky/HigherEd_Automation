"""Native machine-local credential vault used by browser and API sessions."""

from __future__ import annotations

import sys
from typing import Protocol


class CredentialStoreError(RuntimeError):
    """Raised when a native OS credential cannot be managed safely."""


class CredentialStore(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


class SystemCredentialStore:
    """Store secrets in Windows Credential Manager or macOS Keychain."""

    def get_password(self, service: str, username: str) -> str | None:
        keyring = _load_keyring()
        try:
            return keyring.get_password(service, username)
        except keyring.errors.KeyringError:
            raise CredentialStoreError(
                "The OS credential vault could not read the saved credential."
            ) from None

    def set_password(self, service: str, username: str, password: str) -> None:
        keyring = _load_keyring()
        try:
            keyring.set_password(service, username, password)
        except keyring.errors.KeyringError:
            raise CredentialStoreError(
                "The OS credential vault could not save the credential."
            ) from None

    def delete_password(self, service: str, username: str) -> None:
        keyring = _load_keyring()
        try:
            keyring.delete_password(service, username)
        except keyring.errors.PasswordDeleteError:
            if self.get_password(service, username) is not None:
                raise CredentialStoreError(
                    "The OS credential vault could not delete the credential."
                ) from None
        except keyring.errors.KeyringError:
            raise CredentialStoreError(
                "The OS credential vault could not delete the credential."
            ) from None


def _load_keyring() -> object:
    try:
        import keyring
    except ImportError:
        raise CredentialStoreError(
            "The keyring package is not installed in the active Python "
            "environment. Run setup.ps1 before using saved credentials."
        ) from None

    # Never use third-party or plaintext backends selected by user settings.
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring
        backend = Keyring()
    elif sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring
        backend = WinVaultKeyring()
        backend.persist = "local machine"
    else:
        raise CredentialStoreError(
            "Credential caching supports only macOS Keychain and Windows "
            "Credential Manager."
        )
    from types import SimpleNamespace
    return SimpleNamespace(
        get_password=backend.get_password,
        set_password=backend.set_password,
        delete_password=backend.delete_password,
        errors=keyring.errors,
    )
