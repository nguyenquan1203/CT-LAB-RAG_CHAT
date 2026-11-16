"""Firebase email/password REST API, adapted from the instructor's Lab 3."""

import time

import requests

from config import FIREBASE_API_KEY


class FirebaseError(Exception):
    """A display-safe error message without API keys or passwords."""


def _authenticate(action, email, password):
    if not FIREBASE_API_KEY:
        raise FirebaseError("Set FIREBASE_API_KEY in .env, then restart the app.")
    if not email.strip() or not password:
        raise FirebaseError("Enter both email and password.")
    try:
        response = requests.post(
            f"https://identitytoolkit.googleapis.com/v1/accounts:{action}",
            params={"key": FIREBASE_API_KEY},
            json={
                "email": email.strip(),
                "password": password,
                "returnSecureToken": True,
            },
            timeout=15,
        )
    except requests.RequestException:
        raise FirebaseError("Cannot reach Firebase. Check your connection and try again.") from None
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        raise FirebaseError("Firebase returned an unexpected response. Try again later.") from None
    if response.ok:
        return data

    error = data.get("error", {})
    code = str(error.get("message", "")) if isinstance(error, dict) else ""
    messages = {
        "EMAIL_EXISTS": "That email is already registered. Choose Sign in.",
        "INVALID_EMAIL": "Enter a valid email address.",
        "OPERATION_NOT_ALLOWED": "Enable Email/Password in Firebase Authentication.",
        "WEAK_PASSWORD": "Choose a password that meets this Firebase project's password policy.",
        "PASSWORD_DOES_NOT_MEET_REQUIREMENTS": "Choose a password that meets this Firebase project's password policy.",
        "INVALID_LOGIN_CREDENTIALS": "The email or password is incorrect.",
        "INVALID_PASSWORD": "The email or password is incorrect.",
        "EMAIL_NOT_FOUND": "The email or password is incorrect.",
        "USER_DISABLED": "This account has been disabled.",
        "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts. Please try again later.",
    }
    for known, message in messages.items():
        if known in code:
            raise FirebaseError(message)
    raise FirebaseError("Authentication failed. Check the Web API Key and Firebase settings.")


def create_account(email, password):
    """Create an account; the user signs in next. Never retain the password."""
    _authenticate("signUp", email, password)


def sign_in(email, password):
    data = _authenticate("signInWithPassword", email, password)
    try:
        uid, user_email = data["localId"], data["email"]
        lifetime = int(data["expiresIn"])
        if not isinstance(uid, str) or not uid or not isinstance(user_email, str) or not user_email or lifetime <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise FirebaseError("Sign-in returned incomplete data. Please try again.") from None
    # No database calls are made, so ID and refresh tokens do not need to be retained.
    return {"uid": uid, "email": user_email, "expires_at": time.time() + lifetime}

