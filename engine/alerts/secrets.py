"""OS-backed credentials. Plaintext fallbacks are deliberately unavailable."""
from __future__ import annotations

import sys
from typing import Protocol, cast


class SecretVault(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str | None) -> None: ...


class KeychainVault:
    service = "com.visionapp.alerts"

    def get(self, key: str) -> str | None:
        if sys.platform != "darwin":
            raise ValueError("Alert credentials require macOS Keychain on this build")
        from keyring.backends.macOS import Keyring
        try:
            return cast(str | None, Keyring().get_password(self.service, key))  # type: ignore[no-untyped-call]
        except Exception as exc:
            raise ValueError("Could not read alert credential from macOS Keychain") from exc

    def set(self, key: str, value: str | None) -> None:
        if sys.platform != "darwin":
            raise ValueError("Alert credentials require macOS Keychain on this build")
        from keyring.backends.macOS import Keyring
        try:
            backend = Keyring()  # type: ignore[no-untyped-call]
            if value is None:
                if backend.get_password(self.service, key) is not None:
                    backend.delete_password(self.service, key)
            else:
                backend.set_password(self.service, key, value)
        except Exception as exc:
            raise ValueError("Could not update alert credential in macOS Keychain") from exc
