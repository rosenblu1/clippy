from setuptools import setup

APP = ["clippy.py"]
OPTIONS = {
    "iconfile": "assets/AppIcon.icns",
    "resources": "assets",
    "argv_emulation": True,
    "plist": {
        "LSUIElement": True,
    },
    "packages": ["rumps", "richxerox", "PIL"],
    "excludes": "numpy",
}

setup(
    app=APP,
    name="Clippy",
    version="0.1.0",
    author="Eddie Rosenblum",
    author_email="erosenblum36@gmail.com",
    # data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
