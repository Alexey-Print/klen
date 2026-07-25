name: Сборка APK

on:
  workflow_dispatch:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 120
    steps:
      - name: Забрать код
        uses: actions/checkout@v4

      - name: Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Java
        uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '17'

      - name: Системные пакеты
        run: |
          sudo apt-get update
          sudo apt-get install -y --no-install-recommends git zip unzip openjdk-17-jdk autoconf automake libtool pkg-config zlib1g-dev libncurses-dev cmake libffi-dev libssl-dev build-essential ccache patch

      - name: Buildozer
        run: |
          python -m pip install --upgrade pip setuptools wheel
          pip install buildozer==1.5.0 "cython==0.29.36" virtualenv

      - name: Кэш сборки
        uses: actions/cache@v4
        with:
          path: |
            ~/.buildozer
            ~/.gradle
          key: buildozer-${{ hashFiles('buildozer.spec') }}
          restore-keys: buildozer-

      - name: Собрать APK
        run: buildozer -v android debug

      - name: Выложить APK
        uses: actions/upload-artifact@v4
        with:
          name: KLEN-APK
          path: bin/*.apk
          if-no-files-found: error
