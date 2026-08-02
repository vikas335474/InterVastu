"""Unit tests for auth.py: password hashing/verification, and the
username/password validation rules used by server.py's /auth/register.
"""

import auth


def test_hash_password_then_verify_succeeds():
    hashed = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple", hashed)


def test_verify_password_fails_for_wrong_password():
    hashed = auth.hash_password("correct horse battery staple")
    assert not auth.verify_password("wrong password", hashed)


def test_hash_password_is_not_the_plaintext_and_is_salted():
    hashed1 = auth.hash_password("same password")
    hashed2 = auth.hash_password("same password")
    assert hashed1 != "same password"
    # bcrypt salts each hash independently -- two hashes of the same
    # password must not be identical.
    assert hashed1 != hashed2
    assert auth.verify_password("same password", hashed1)
    assert auth.verify_password("same password", hashed2)


def test_verify_password_returns_false_not_exception_for_corrupt_hash():
    assert auth.verify_password("anything", "not-a-real-bcrypt-hash") is False


def test_generate_session_token_is_unique_and_url_safe():
    tokens = {auth.generate_session_token() for _ in range(50)}
    assert len(tokens) == 50
    for t in tokens:
        assert all(c.isalnum() or c in "-_" for c in t)


def test_validate_username_accepts_normal_usernames():
    assert auth.validate_username("vikas_335474") is None
    assert auth.validate_username("a.b-c") is None


def test_validate_username_rejects_too_short():
    assert auth.validate_username("ab") is not None


def test_validate_username_rejects_special_characters():
    assert auth.validate_username("vikas@example.com") is not None
    assert auth.validate_username("<script>") is not None


def test_validate_password_rejects_too_short():
    assert auth.validate_password("short") is not None


def test_validate_password_accepts_long_enough():
    assert auth.validate_password("longenoughpassword") is None
