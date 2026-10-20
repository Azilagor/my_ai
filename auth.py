"""Простая авторизация одного внутреннего пользователя."""
from __future__ import annotations
import hashlib, hmac, os, secrets
import streamlit as st

def make_password_hash(password: str, iterations: int = 310_000) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256": return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(raw_iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False

def require_login() -> None:
    if st.session_state.get("authenticated"): return
    st.title("Вход в систему аналитики")
    username = st.text_input("Логин")
    password = st.text_input("Пароль", type="password")
    if st.button("Войти", type="primary"):
        expected_user = os.getenv("APP_USERNAME", "admin")
        password_hash = os.getenv("APP_PASSWORD_HASH", "")
        if hmac.compare_digest(username, expected_user) and verify_password(password, password_hash):
            st.session_state.authenticated = True
            st.rerun()
        st.error("Неверный логин или пароль")
    st.stop()
