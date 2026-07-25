[app]

title = ЖСК КЛЕН
package.name = klenfoto
package.domain = ru.klen

source.dir = .
source.include_exts = py,png,jpg,jpeg,ttf,json
source.include_patterns = icon.png,fon.jpg,logo.png,logo_mark.png

version = 1.0

requirements = python3,kivy==2.3.0,pillow,pyjnius,android,openssl,certifi

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png
android.presplash_color = #2EA854

android.permissions = CAMERA,INTERNET,ACCESS_NETWORK_STATE,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES

android.api = 34
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a

android.accept_sdk_license = True
android.allow_backup = True

# Разрешаем обычный http для геокодера
android.manifest.application_arguments = android:usesCleartextTraffic="true"

[buildozer]

log_level = 2
warn_on_root = 0
