#!/bin/sh
# brew install create-dmg to use this.
# make sure all pre-req files are in assets/ in working directory

# checking pre-req files
if [[ ! -f "assets/AppIcon.icns" ]]
then
    echo "assets/AppIcon.icns (used as icon for app) not in current directory. Exiting..."
    exit 1
elif [[ ! -f "assets/cup_10_pt.svg" ]]
then
    echo "assets/cup_10_pt.svg (used as menubar icon) does not exist in current directory. Exiting..."
    exit 1
elif [[ ! -f "assets/installer_background.png" ]]
then
    echo "assets/installer_background.png (used as background for dmg installer window) not in current directory. Exiting..."
    exit 1
elif [[ ! -f "clippy.py" ]]
then
    echo "clippy.py (main python script for app) not in current directory. Exiting..."
    exit 1
fi

# checking cpu chip type to name installer
CHIP_TYPE=`sysctl -n machdep.cpu.brand_string`
if [[ $CHIP_TYPE == *"Apple M"* ]]; then
    CHIP_NAME="Apple Silicon"
else
    CHIP_NAME="Universal2"
fi
INSTALLER_NAME=$CHIP_NAME" Clippy-Installer"

# clean old dmgs and cache
test -f "$INSTALLER_NAME".dmg && rm "$INSTALLER_NAME".dmg
test -e ClippyCache && rm -rf ClippyCache

# create .app file
echo "creating app file..."
python3 setup.py py2app

echo "App file created, sleeping for 1 second..."
sleep 1

# create disk image
echo "Creating  dmg..."
create-dmg \
  --volname "Clippy Installer" \
  --volicon "assets/AppIcon.icns" \
  --background "assets/installer_background.png" \
  --window-pos 200 120 \
  --window-size 636 400 \
  --icon-size 100 \
  --icon "Clippy.app" 163 210 \
  --hide-extension "Clippy.app" \
  --app-drop-link 494 203 \
  "$INSTALLER_NAME.dmg" \
  "dist/"
