# Clippy
A simple clipboard manager for Mac in the Menubar that supports plain and rich text, html, files, and images. Clippy remembers the last 25 items you've copied, and you can pin items so they stay in the app until you clear or unpin them.

## Installing
Download and open ```Clippy-Installer.dmg```. When running the app for the first time, you'll have to right click and select 'Open' as the .app file isn't signed and I'm not shelling out ~$100 for an Apple Developer account.

## CI/Pushing to main branch
There are github actions set up to automatically rebuild the Installer on push to main unless \[NOBUILD\] is in the commit message.

To create a new release, add \[RELEASE\] to your commit message. The version tag used will be the value of ```__version__``` in ```clippy.py```. The pipeline is: 
    - ```./build.sh``` is run, which runs ```python3 setup.py py2app``` and creates the .app file. 
    - ```setup.py``` imports ```clippy.__version__```
    - ```setup.py``` sets a ```GITHUB_ENV``` variable to the imported version
    - The ```CI-build-release.yml``` github workflow creates a tag for the version and makes a release with it!

## Building Locally
Install python requirements with ```python3 -m pip install -r requirements.txt```. Running ```clippy.py``` at the command line will work, but if you want to build the project locally, clone the repo, install ```create-dmg``` (e.g. with ```brew install create-dmg```), and run ```./build.sh```. This will create the installer (```Clippy-Installer.dmg```), as well as the bare .app file in a ```dist/``` directory (if you don't need to distribute it and are fine to manually move the .app to your Applications folder).