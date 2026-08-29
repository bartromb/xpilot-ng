#!/bin/sh
# Build "XPilot NG.app" from a portable install tree and wrap it in a .dmg.
#
#   make-dmg.sh <staged-install-dir> <version> <arch> <output.dmg>
#
# The staged tree is the XPILOT_PORTABLE layout: the binaries at its root with
# their data in lib/ beside them. In the bundle the binaries move to
# Contents/MacOS and the data to Contents/Resources, which is where
# Conf_anchor_datadir() looks when it finds itself in Contents/MacOS -- so the
# app works when double-clicked, with no wrapper script and no cwd assumptions.
set -eu

STAGE=$1
VERSION=$2
ARCH=$3
OUT=$4

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
APP="$WORK/XPilot NG.app"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp "$STAGE/xpilot-ng-sdl" "$STAGE/xpilot-ng-server" "$APP/Contents/MacOS/"
cp -R "$STAGE/lib" "$APP/Contents/Resources/lib"
[ -d "$STAGE/libs" ] && cp -R "$STAGE/libs" "$APP/Contents/MacOS/libs"

for doc in COPYING README.md BUILDING.md; do
    [ -f "$STAGE/$doc" ] && cp "$STAGE/$doc" "$APP/Contents/Resources/"
done

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>              <string>XPilot NG</string>
    <key>CFBundleDisplayName</key>       <string>XPilot NG</string>
    <key>CFBundleIdentifier</key>        <string>org.xpilot.xpilot-ng</string>
    <key>CFBundleVersion</key>           <string>$VERSION</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleExecutable</key>        <string>xpilot-ng-sdl</string>
    <key>CFBundlePackageType</key>       <string>APPL</string>
    <key>CFBundleSignature</key>         <string>????</string>
    <key>LSMinimumSystemVersion</key>    <string>11.0</string>
    <key>NSHighResolutionCapable</key>   <true/>
    <key>NSHumanReadableCopyright</key>
    <string>GPL-2.0-or-later. See COPYING.</string>
</dict>
</plist>
PLIST

# Drag-to-install: the window shows the app and a link to /Applications.
ln -s /Applications "$WORK/Applications"

rm -f "$OUT"
hdiutil create -volname "XPilot NG $VERSION ($ARCH)" \
    -srcfolder "$WORK" -ov -format UDZO "$OUT"
hdiutil verify "$OUT"
