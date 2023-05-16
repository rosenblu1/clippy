import os

from setuptools import setup

from clippy import __author__ as APP_AUTHOR
from clippy import __contact__ as APP_CONTACT
from clippy import __version__ as APP_VERSION

if env_file := os.getenv("GITHUB_ENV"):
    print(f"Github environment detected! Setting env.VERSION_TAG to v{APP_VERSION}")
    with open(env_file, "a") as f:
        f.write(f"VERSION_TAG=v{APP_VERSION}\n")

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
