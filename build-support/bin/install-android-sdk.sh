# Install the Android SDK for the Pants Android contrib module.
set -xf
# SDK_INSTALL_LOCATION and ANDROID_HOME set in travis.yaml.

# This ANDROID_HOME is a hack to work for linux and osx - will be set perm in per-os yaml.
# SDK_INSTALL_LOCATION="$HOME/opt/android-sdk-install"
# ANDROID_HOME="$SDK_INSTALL_LOCATION/android-sdk-linux"
mkdir -p "$SDK_INSTALL_LOCATION"

ANDROID_SDK_URL="http://dl.google.com/android/android-sdk_r24.4.1-linux.tgz"
SDK_FILE=$(basename $ANDROID_SDK_URL)

echo "Downloading $ANDROID_SDK_URL..."
SDK_ARCHIVE_LOCATION="$SDK_INSTALL_LOCATION"/"$SDK_FILE"

wget "$ANDROID_SDK_URL" -O "$SDK_ARCHIVE_LOCATION"
tar -C "$SDK_INSTALL_LOCATION" -xf "$SDK_ARCHIVE_LOCATION"

# Add SDKs as needed.
echo "y" | "$ANDROID_HOME"/tools/android update sdk -u --all --filter \
     platform-tools,android-19,android-20,android-21,build-tools-19.1.0,extra-android-support
