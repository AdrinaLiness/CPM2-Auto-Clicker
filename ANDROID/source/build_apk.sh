#!/bin/bash
# Сборка CPM2 AI Driver APK (без Gradle — aapt2 + d8 + apksigner)
# Тот же пайплайн, что у J.A.R.V.I.S.
set -e
SDK=/home/z/my-project/android-sdk
PROJ=/home/z/my-project/cpm2_android
BT=$SDK/android-14
PLAT=$SDK/android-34/android.jar
JAVA=$SDK/jdk-17.0.21+9/bin
OUT=$PROJ/out
export PATH="$JAVA:$PATH"

rm -rf "$OUT"
mkdir -p "$OUT/classes" "$OUT/dex" "$OUT/gen" "$PROJ/build"

echo "[1/6] aapt2 compile + link (+ R.java)..."
"$BT/aapt2" compile --dir "$PROJ/res" -o "$OUT/res.zip"
"$BT/aapt2" link \
  -o "$OUT/app-unsigned.apk" \
  -I "$PLAT" \
  --manifest "$PROJ/AndroidManifest.xml" \
  -A "$PROJ/assets" \
  --java "$OUT/gen" \
  --min-sdk-version 24 --target-sdk-version 34 \
  --version-code 1 --version-name 1.0 \
  --auto-add-overlay \
  "$OUT/res.zip"

echo "[2/6] javac..."
"$JAVA/javac" --release 8 -nowarn -classpath "$PLAT" \
  -d "$OUT/classes" \
  "$OUT/gen/com/adrina/cpm2/R.java" \
  "$PROJ"/src/com/adrina/cpm2/*.java

echo "[3/6] d8 (dex)..."
"$BT/d8" --release --lib "$PLAT" --min-api 24 \
  --output "$OUT/dex" $(find "$OUT/classes" -name "*.class")
ls -la "$OUT/dex/"

echo "[4/6] classes.dex → apk..."
cd "$OUT/dex" && zip -q -u "$OUT/app-unsigned.apk" classes.dex && cd "$SDK"

echo "[5/6] zipalign..."
"$BT/zipalign" -f 4 "$OUT/app-unsigned.apk" "$OUT/app-aligned.apk"

echo "[6/6] подпись..."
KS=$PROJ/build/cpm2.keystore
if [ ! -f "$KS" ]; then
  keytool -genkeypair -keystore "$KS" -alias cpm2 -keyalg RSA -keysize 2048 \
    -validity 10950 -storepass cpm22026 -keypass cpm22026 \
    -dname "CN=CPM2 AI Driver, OU=AdrinaLiness, O=AdrinaLiness, C=RU" >/dev/null 2>&1
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:cpm22026 \
  --out "$PROJ/CPM2-AIDriver-v1.0.apk" "$OUT/app-aligned.apk"
"$BT/apksigner" verify "$PROJ/CPM2-AIDriver-v1.0.apk" && echo "APK OK"

ls -la "$PROJ/CPM2-AIDriver-v1.0.apk"
"$BT/aapt2" dump badging "$PROJ/CPM2-AIDriver-v1.0.apk" | head -8
