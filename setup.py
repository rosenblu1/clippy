from os import getenv

from setuptools import setup

from clippy import __author__ as APP_AUTHOR
from clippy import __contact__ as APP_CONTACT
from clippy import __version__ as APP_VERSION

VERS_FILE = "vers.txt"

if getenv("GITHUB_ENV"):
    print(f"GITHUB_ENV found, writing to {VERS_FILE}: v{APP_VERSION}")
    with open(VERS_FILE, "w") as f:
        f.write(f"vers=v{APP_VERSION}")

APP = ["clippy.py"]
OPTIONS = {
    "iconfile": "assets/AppIcon.icns",
    "resources": "assets",
    "argv_emulation": True,
    "plist": {
        "LSUIElement": True,
    },
    "packages": ["rumps", "richxerox", "PIL", "requests"],
    "excludes": "numpy",
}

setup(
    app=APP,
    name="Clippy",
    version=APP_VERSION,
    author=APP_AUTHOR,
    author_email=APP_CONTACT,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
