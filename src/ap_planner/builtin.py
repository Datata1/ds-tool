"""Values built into a release (the desktop app's build fills them in; empty in the source).

GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET: OAuth client "Desktop app" of the maintainer's Google
Cloud project (scope drive.file only). Google treats the secret of desktop clients as public.
``AP_GOOGLE_CLIENT_ID`` / ``AP_GOOGLE_CLIENT_SECRET`` override them (e.g. in ``.env``).
"""

GOOGLE_CLIENT_ID = ""
GOOGLE_CLIENT_SECRET = ""
