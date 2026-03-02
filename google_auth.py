"""
One-time OAuth2 helper — run locally to generate token.json.

Prerequisites:
  1. Go to https://console.cloud.google.com/
  2. Create a project → Enable "Google Calendar API"
  3. Create OAuth 2.0 credentials (Desktop app) → Download as credentials.json
  4. Place credentials.json in this directory
  5. Run:  python google_auth.py
  6. A browser window will open — sign in and grant calendar access
  7. token.json will be saved automatically
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"


def main():
    creds = None

    # Load existing token if available
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # If no valid credentials, run the OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Refreshing expired token…")
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                print(
                    f"❌ '{CREDENTIALS_FILE}' not found!\n"
                    "   Download it from Google Cloud Console → APIs & Services → Credentials.\n"
                    "   Save it as 'credentials.json' in this directory."
                )
                return

            print("🌐 Opening browser for Google sign-in…")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the token for future runs
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    print(f"✅ Token saved to '{TOKEN_FILE}'. You're all set!")


if __name__ == "__main__":
    main()
