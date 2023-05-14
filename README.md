# Clippy
A simple clipboard manager for Mac in the Menubar that supports plain and rich text, html, files, and images. Clippy remembers the last 25 items you've copied, and you can pin items so they stay in the app until you clear or unpin them.

## Installing
Download and open ```Clippy-Installer.dmg```. When running the app for the first time, you'll have to right click and select 'Open' as the .app file isn't signed and I'm not shelling out ~$100 for an Apple Developer account.

## Building Locally
Install requirements with ```python3 -m pip install -r requirements.txt```. Running ```clippy.py``` at the command line will work, but if you want to build the project locally, clone the repo and run ```./build.sh```. This will create the installer (```Clippy-Installer.dmg```), as well as the bare .app file in a ```dist/``` directory (if you don't need to distribute it and are fine to manually move the .app to your Applications folder).

In the future, I'd like to set up some Github actions to setup CI and conventional versioning.