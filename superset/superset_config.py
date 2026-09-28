import os

SQLALCHEMY_DATABASE_URI = os.environ["META_DB_URI"]
SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache"}
DATA_CACHE_CONFIG = CACHE_CONFIG
FILTER_STATE_CACHE_CONFIG = CACHE_CONFIG
EXPLORE_FORM_DATA_CACHE_CONFIG = CACHE_CONFIG

WTF_CSRF_ENABLED = True
TALISMAN_ENABLED = False
APP_NAME = f"Superset {os.environ.get('LAB_NAME', '').upper()}"

# Browsers scope cookies by host, not port: both labs on localhost would share one
# session cookie (and, with the same SECRET_KEY, silently swap logged-in users).
SESSION_COOKIE_NAME = f"session_{os.environ.get('LAB_NAME', 'superset')}"


# Lab resets recreate the metadata DB, so a browser can keep a session cookie for a user id that no longer exists.
# Stock Flask-AppBuilder then crashes with HTTP 500 ('NoneType' has no attribute 'is_active'); treat it as logged out.
from superset.security import SupersetSecurityManager  # noqa: E402


class LabSecurityManager(SupersetSecurityManager):
    def load_user(self, pk):
        user = self.get_user_by_id(int(pk))
        return user if user is not None and user.is_active else None


CUSTOM_SECURITY_MANAGER = LabSecurityManager
