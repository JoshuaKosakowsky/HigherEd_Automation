"""Optional MyMines sign-in credential in the user's native OS vault."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from shared.credentials import CredentialStore, CredentialStoreError, SystemCredentialStore


SERVICE = "HigherEd_Automation:MyMines"
ENTRY = "sso-login"


@dataclass(frozen=True)
class MyMinesCredential:
    username: str
    password: str = field(repr=False)


class MyMinesCredentialStore:
    def __init__(self, store: CredentialStore | None = None) -> None:
        self.store = store or SystemCredentialStore()

    def load(self) -> MyMinesCredential | None:
        secret = self.store.get_password(SERVICE, ENTRY)
        if secret is None:
            return None
        try:
            value = json.loads(secret)
            if (
                not isinstance(value, dict)
                or value.get("version") != 1
                or not isinstance(value.get("username"), str)
                or not value["username"].strip()
                or not isinstance(value.get("password"), str)
                or not value["password"]
            ):
                raise ValueError
        except (TypeError, ValueError):
            raise CredentialStoreError(
                "The saved MyMines login has an invalid format. Replace it in Connections."
            ) from None
        return MyMinesCredential(value["username"], value["password"])

    def save(self, username: str, password: str) -> None:
        username = username.strip()
        if not username or not password:
            raise ValueError("Enter both a MyMines username and password.")
        secret = json.dumps({"version": 1, "username": username, "password": password})
        self.store.set_password(SERVICE, ENTRY, secret)

    def delete(self) -> None:
        self.store.delete_password(SERVICE, ENTRY)
