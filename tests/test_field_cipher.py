from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.field_cipher import FieldCipher
from app.config import Settings
from app.models import GoRelayAccount
from app.storage.sqlite_repo import SqliteRepo


def test_encrypt_decrypt_roundtrip(tmp_path: Path) -> None:
    cipher = FieldCipher(tmp_path / "key.dat")
    plaintext = "s3cret-p@ssw0rd!"
    encrypted = cipher.encrypt(plaintext)
    assert encrypted != plaintext
    assert cipher.decrypt(encrypted) == plaintext


def test_encrypt_unicode_roundtrip(tmp_path: Path) -> None:
    cipher = FieldCipher(tmp_path / "key.dat")
    plaintext = "密码测试 emoji 🔑"
    encrypted = cipher.encrypt(plaintext)
    assert cipher.decrypt(encrypted) == plaintext


def test_empty_string_passthrough(tmp_path: Path) -> None:
    cipher = FieldCipher(tmp_path / "key.dat")
    assert cipher.encrypt("") == ""
    assert cipher.decrypt("") == ""


def test_none_passthrough(tmp_path: Path) -> None:
    cipher = FieldCipher(tmp_path / "key.dat")
    assert cipher.encrypt(None) == ""
    assert cipher.decrypt(None) == ""


def test_key_auto_generation(tmp_path: Path) -> None:
    key_path = tmp_path / "subdir" / "cipher.key"
    assert not key_path.exists()
    cipher = FieldCipher(key_path)
    assert key_path.exists()
    # Key file should be a valid Fernet key (44 bytes base64).
    raw = key_path.read_bytes().strip()
    assert len(raw) == 44
    # Verify functional.
    assert cipher.decrypt(cipher.encrypt("hello")) == "hello"


def test_key_file_permissions(tmp_path: Path) -> None:
    key_path = tmp_path / "cipher.key"
    FieldCipher(key_path)
    mode = oct(key_path.stat().st_mode & 0o777)
    assert mode == "0o600"


def test_wrong_key_fails_without_exposing_ciphertext(tmp_path: Path) -> None:
    cipher_a = FieldCipher(tmp_path / "key_a.dat")
    cipher_b = FieldCipher(tmp_path / "key_b.dat")
    encrypted = cipher_a.encrypt("secret")
    with pytest.raises(ValueError, match="stored credential cannot be decrypted") as error:
        cipher_b.decrypt(encrypted)
    assert encrypted not in str(error.value)


def test_plaintext_passthrough_on_decrypt(tmp_path: Path) -> None:
    """Old plaintext values that were never encrypted should pass through."""
    cipher = FieldCipher(tmp_path / "key.dat")
    assert cipher.decrypt("my-old-password") == "my-old-password"
    assert cipher.decrypt("旧密码 🔑") == "旧密码 🔑"


def test_corrupt_ciphertext_fails_without_exposing_value(tmp_path: Path) -> None:
    cipher = FieldCipher(tmp_path / "key.dat")
    encrypted = cipher.encrypt("secret")
    for corrupted in (encrypted[:-8], encrypted[:20] + "!" + encrypted[21:]):
        with pytest.raises(ValueError, match="stored credential cannot be decrypted") as error:
            cipher.decrypt(corrupted)
        assert corrupted not in str(error.value)


def test_concurrent_creation_publishes_one_complete_key(tmp_path: Path) -> None:
    key_path = tmp_path / "cipher.key"
    with ThreadPoolExecutor(max_workers=8) as executor:
        ciphers = list(executor.map(lambda _: FieldCipher(key_path), range(24)))
    encrypted = ciphers[0].encrypt("shared credential")
    assert all(cipher.decrypt(encrypted) == "shared credential" for cipher in ciphers)
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.glob(".field-cipher-*")) == []


def test_invalid_key_reports_recovery_without_key_material(tmp_path: Path) -> None:
    key_path = tmp_path / "cipher.key"
    key_path.write_text("invalid-sensitive-key")
    with pytest.raises(ValueError, match="invalid field encryption key") as error:
        FieldCipher(key_path)
    assert "invalid-sensitive-key" not in str(error.value)


def test_existing_key_reused(tmp_path: Path) -> None:
    key_path = tmp_path / "cipher.key"
    cipher1 = FieldCipher(key_path)
    encrypted = cipher1.encrypt("data")
    # Create a new cipher instance pointing at the same key file.
    cipher2 = FieldCipher(key_path)
    assert cipher2.decrypt(encrypted) == "data"


def test_idempotent_encrypt(tmp_path: Path) -> None:
    """Encrypting the same plaintext twice produces different ciphertexts
    (Fernet uses a timestamp nonce), but both decrypt to the same value."""
    cipher = FieldCipher(tmp_path / "key.dat")
    e1 = cipher.encrypt("hello")
    e2 = cipher.encrypt("hello")
    assert e1 != e2
    assert cipher.decrypt(e1) == "hello"
    assert cipher.decrypt(e2) == "hello"


def test_repository_restart_with_wrong_key_fails_before_credentials_are_used(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    settings = Settings.from_env()
    original_cipher = FieldCipher(tmp_path / "original.key")
    repo = SqliteRepo(settings, original_cipher)
    repo.save_gorelay_account(
        GoRelayAccount(id="account", name="Encrypted account", login_url="https://example.com", gorelay_password="secret")
    )
    repo._conn.close()
    wrong_cipher = FieldCipher(tmp_path / "wrong.key")
    with pytest.raises(ValueError, match="stored credential cannot be decrypted"):
        SqliteRepo(settings, wrong_cipher)
    restored = SqliteRepo(settings, original_cipher)
    assert restored.get_gorelay_account("account").gorelay_password == "secret"
    restored._conn.close()
