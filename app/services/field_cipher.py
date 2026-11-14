from __future__ import annotations

import os
import base64
import binascii
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class FieldCipher:
    """Fernet symmetric encryption for sensitive database fields.

    Automatically generates a key file if one does not exist.
    Key file permissions are set to 0o600 (owner read/write only).
    """

    def __init__(self, key_path: Path) -> None:
        self._key_path = key_path
        self._key_path.parent.mkdir(parents=True, exist_ok=True)

        if not self._key_path.exists():
            descriptor, temporary_path = tempfile.mkstemp(prefix=".field-cipher-", dir=self._key_path.parent)
            try:
                with os.fdopen(descriptor, "wb") as temporary_file:
                    temporary_file.write(Fernet.generate_key())
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())
                try:
                    # Publish a complete key once, without replacing a key
                    # another process has already created.
                    os.link(temporary_path, self._key_path)
                except FileExistsError:
                    pass
            finally:
                os.unlink(temporary_path)

        raw = self._key_path.read_bytes().strip()
        try:
            self._fernet = Fernet(raw)
        except (ValueError, binascii.Error):
            raise ValueError("invalid field encryption key; restore the original key file") from None

    def encrypt(self, plaintext: str | None) -> str:
        """Encrypt a plaintext string. Returns empty string for None/empty input."""
        if not plaintext:
            return ""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str | None) -> str:
        """Decrypt a ciphertext string. Returns empty string for None/empty input."""
        if not ciphertext:
            return ""
        if not self._looks_encrypted(ciphertext):
            # Only legacy plaintext can pass through for the repository's
            # one-time encryption migration.
            return ciphertext
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError):
            raise ValueError(
                "stored credential cannot be decrypted; restore the original field encryption key or a valid backup"
            ) from None

    @staticmethod
    def _looks_encrypted(value: str) -> bool:
        if value.startswith("gAAAA"):
            return True
        try:
            raw = base64.urlsafe_b64decode(value.encode("ascii"))
        except (UnicodeError, ValueError, binascii.Error):
            return False
        return len(raw) >= 73 and raw[0] == 0x80
