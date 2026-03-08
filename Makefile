# =============================================================================
# Pawn Recorder — top-level Makefile
# =============================================================================
#
# Usage:
#   make android-debug          build debug APK  (./gradlew assembleDebug)
#   make android-release        build release APK
#   make android-deploy         build debug APK + adb install
#   make android-run            build, install and launch on device
#   make android-logcat         stream Python/Java logs from device
#   make android-clean          remove Gradle build/ output
#   make android-attach         forward debugpy port 5678 + VS Code attach hint
#
#   make install                install Python packages (editable)
#   make install-flutter        install Flutter SDK (AUR / snap / tarball)
#   make setup-android          install Android cmdline-tools + accept licenses
#   make test                   run pytest suite
#   make lint                   run ruff + mypy
#
# Requirements:
#   pip install uv          (or: curl -LsSf https://astral.sh/uv/install.sh | sh)
#   Android SDK             (run: make setup-android)
#   JDK 17+                 (sudo pacman -S jdk-openjdk)
# =============================================================================

VENV        := $(CURDIR)/.venv
UV          := uv
PYTHON      := $(VENV)/bin/python
PYTEST      := $(VENV)/bin/pytest
RUFF        := $(VENV)/bin/ruff
MYPY        := $(VENV)/bin/mypy
GRADLEW     := ./gradlew
DROID_DIR   := pawn_recorder_droid

# Android SDK root — override with: make setup-android ANDROID_SDK_ROOT=/custom/path
ANDROID_SDK_ROOT ?= $(HOME)/Android/Sdk
CMDLINE_TOOLS_URL := https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip

# Java 17+ is required by sdkmanager. Auto-detect from /usr/lib/jvm; override if needed.
# Preference order: 21, 17 (both satisfy sdkmanager's class file version 61 requirement).
JAVA_HOME_17 := $(or \
    $(wildcard /usr/lib/jvm/java-21-openjdk), \
    $(wildcard /usr/lib/jvm/java-17-openjdk), \
    $(wildcard /usr/lib/jvm/java-21-openjdk/bin/..), \
    $(wildcard /usr/lib/jvm/temurin-21), \
    $(wildcard /usr/lib/jvm/temurin-17))

# APK output produced by `./gradlew assembleDebug`
APK_DEBUG   := $(DROID_DIR)/app/build/outputs/apk/debug/app-debug.apk

.PHONY: help install install-flutter setup-android \
        test lint \
        android-debug android-release android-deploy android-run \
        android-logcat android-clean android-attach \
        server-local \
        _require-uv _require-gradle _require-adb

# ─── default target ──────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  Pawn Recorder — available targets"
	@echo ""
	@echo "  Android:"
	@echo "    android-debug       Build debug APK  (./gradlew assembleDebug)"
	@echo "    android-release     Build release APK (./gradlew assembleRelease)"
	@echo "    android-deploy      Build debug APK + adb install"
	@echo "    android-run         Build, install and launch on device"
	@echo "    android-logcat      Stream Python/Java logs from device (Ctrl-C to stop)"
	@echo "    android-clean       Remove Gradle build/ output"
	@echo "    android-attach      Forward debugpy port 5678 then print VS Code attach hint"
	@echo ""
	@echo "  Local dev:"
	@echo "    server-local        Run Flask server on desktop (AAudio → silent stub)"
	@echo ""
	@echo "  Development:"
	@echo "    install             Install all Python deps (editable)"
	@echo "    install-flutter     Install Flutter SDK (snap / AUR / tarball)"
	@echo "    setup-android       Install Android cmdline-tools + accept SDK licenses"
	@echo "    test                pytest tests/"
	@echo "    lint                ruff + mypy"
	@echo ""

# ─── development ─────────────────────────────────────────────────────────────

install: _require-uv
	$(UV) pip install -e ".[dev,android]"
	@echo "Python deps installed."

setup-android: _require-flutter
	@echo "Android SDK root: $(ANDROID_SDK_ROOT)"
	@if [ -z "$(JAVA_HOME_17)" ]; then \
		echo "ERROR: Java 17 or 21 not found in /usr/lib/jvm/."; \
		echo "Install with: sudo pacman -S jdk17-openjdk  OR  sudo pacman -S jdk-openjdk"; \
		exit 1; \
	fi
	@echo "Using Java: $(JAVA_HOME_17)"
	@mkdir -p $(ANDROID_SDK_ROOT)/cmdline-tools
	@if [ -x "$(ANDROID_SDK_ROOT)/cmdline-tools/latest/bin/sdkmanager" ]; then \
		echo "cmdline-tools already present — skipping download."; \
	else \
		echo "Downloading Android cmdline-tools..."; \
		curl -fLo /tmp/cmdline-tools.zip $(CMDLINE_TOOLS_URL); \
		unzip -qo /tmp/cmdline-tools.zip -d /tmp/cmdline-tools-extract; \
		mkdir -p $(ANDROID_SDK_ROOT)/cmdline-tools/latest; \
		cp -r /tmp/cmdline-tools-extract/cmdline-tools/* \
			$(ANDROID_SDK_ROOT)/cmdline-tools/latest/; \
		rm -rf /tmp/cmdline-tools.zip /tmp/cmdline-tools-extract; \
		echo "cmdline-tools installed."; \
	fi
	@SDKMGR=$(ANDROID_SDK_ROOT)/cmdline-tools/latest/bin/sdkmanager; \
	export JAVA_HOME=$(JAVA_HOME_17); \
	export PATH=$(JAVA_HOME_17)/bin:$$PATH; \
	export ANDROID_SDK_ROOT=$(ANDROID_SDK_ROOT); \
	export ANDROID_HOME=$(ANDROID_SDK_ROOT); \
	echo "Installing SDK components (Java: $$($$JAVA_HOME/bin/java -version 2>&1 | head -1))..."; \
	yes | $$SDKMGR --sdk_root=$(ANDROID_SDK_ROOT) \
		"cmdline-tools;latest" \
		"platform-tools" \
		"build-tools;35.0.0" \
		"platforms;android-35" \
		"platforms;android-36"; \
	echo "Accepting Android licenses..."; \
	yes | JAVA_HOME=$(JAVA_HOME_17) flutter doctor --android-licenses; \
	echo ""; \
	flutter doctor

install-flutter:
	@if command -v flutter >/dev/null 2>&1; then \
		echo "Flutter already installed: $$(flutter --version 2>&1 | head -1)"; \
	elif command -v snap >/dev/null 2>&1; then \
		echo "Installing Flutter via snap..."; \
		sudo snap install flutter --classic; \
		flutter doctor; \
	elif command -v yay >/dev/null 2>&1; then \
		echo "Installing Flutter via yay (AUR, pre-built binary)..."; \
		if pacman -Qi dart >/dev/null 2>&1; then \
			echo "Removing conflicting 'dart' package..."; \
			sudo pacman -Rdd --noconfirm dart; \
		fi; \
		yay -S --noconfirm --answerdiff None --answerclean None \
			--overwrite '/usr/lib/libgcc*' \
			--overwrite '/usr/lib/libstdc*' \
			--overwrite '/usr/share/licenses/gcc-libs/*' \
			--overwrite '/usr/share/locale/*/LC_MESSAGES/libstdc++.mo' \
			flutter-bin; \
		flutter doctor; \
	elif command -v paru >/dev/null 2>&1; then \
		echo "Installing Flutter via paru (AUR, pre-built binary)..."; \
		if pacman -Qi dart >/dev/null 2>&1; then \
			echo "Removing conflicting 'dart' package..."; \
			sudo pacman -Rdd --noconfirm dart; \
		fi; \
		paru -S --noconfirm --skipreview \
			--overwrite '/usr/lib/libgcc*' \
			--overwrite '/usr/lib/libstdc*' \
			--overwrite '/usr/share/licenses/gcc-libs/*' \
			--overwrite '/usr/share/locale/*/LC_MESSAGES/libstdc++.mo' \
			flutter-bin; \
		flutter doctor; \
	else \
		echo ""; \
		echo "  No supported package manager found (snap / yay / paru)."; \
		echo "  Install Flutter manually:"; \
		echo "    https://docs.flutter.dev/get-started/install/linux"; \
		echo ""; \
		echo "  Or install snap first:"; \
		echo "    sudo pacman -S snapd && sudo systemctl enable --now snapd.socket"; \
		echo "    sudo ln -sf /var/lib/snapd/snap /snap   # symlink for classic confinement"; \
		echo "    sudo snap install flutter --classic"; \
		echo ""; \
		exit 1; \
	fi

test:
	$(PYTEST) tests/ -v

lint:
	$(RUFF) check pawn_recorder pawn_recorder_cli pawn_recorder_droid
	$(MYPY) pawn_recorder pawn_recorder_cli

# ─── guards ──────────────────────────────────────────────────────────────────

_require-uv:
	@command -v $(UV) >/dev/null 2>&1 || \
		{ echo "uv not found — install: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }

_require-gradle:
	@test -f $(DROID_DIR)/gradlew || \
		{ echo "Gradle wrapper not found — run: cd $(DROID_DIR) && gradle wrapper"; exit 1; }

_require-flutter:
	@command -v flutter >/dev/null 2>&1 || \
		{ echo "Flutter SDK not found — run: make install-flutter"; exit 1; }

_require-adb:
	@command -v adb >/dev/null 2>&1 || \
		{ echo "adb not found — install Android platform-tools and add to PATH"; exit 1; }
	@adb devices | grep -q "device$$" || \
		{ echo "No Android device/emulator detected (run: adb devices)"; exit 1; }

# ─── android build ───────────────────────────────────────────────────────────

android-debug: _require-gradle
	cd $(DROID_DIR) && \
		JAVA_HOME=$(JAVA_HOME_17) \
		ANDROID_SDK_ROOT=$(ANDROID_SDK_ROOT) \
		ANDROID_HOME=$(ANDROID_SDK_ROOT) \
		$(GRADLEW) assembleDebug
	@echo ""
	@find $(DROID_DIR)/app/build/outputs/apk -name '*.apk' 2>/dev/null | head -5 && echo "APK ready." || \
		echo "APK not found — check build output above."

android-release: _require-gradle
	@test -n "$(KEYSTORE)"  || { echo "Set KEYSTORE=/path/to/key.jks"; exit 1; }
	@test -n "$(KEY_ALIAS)" || { echo "Set KEY_ALIAS=<alias>"; exit 1; }
	@test -n "$(KEY_PASS)"  || { echo "Set KEY_PASS=<password>"; exit 1; }
	cd $(DROID_DIR) && \
		JAVA_HOME=$(JAVA_HOME_17) \
		ANDROID_SDK_ROOT=$(ANDROID_SDK_ROOT) \
		ANDROID_HOME=$(ANDROID_SDK_ROOT) \
		$(GRADLEW) assembleRelease \
		  -Pandroid.injected.signing.store.file=$(KEYSTORE) \
		  -Pandroid.injected.signing.store.password=$(KEY_PASS) \
		  -Pandroid.injected.signing.key.alias=$(KEY_ALIAS) \
		  -Pandroid.injected.signing.key.password=$(KEY_PASS)

android-deploy: android-debug _require-adb
	adb install -r $(APK_DEBUG)
	@echo "APK installed."

android-run: android-deploy
	adb shell am start -n com.pawnrecorder.app/.MainActivity
	@echo "App launched."

android-logcat: _require-adb
	@echo "Streaming logs — press Ctrl-C to stop"
	adb logcat -s PawnRecorder:V AndroidRuntime:E python:V

# Run Flask server locally (no Android device needed — AAudio uses a silent stub)
# Mirrors the Chaquopy PYTHONPATH so imports resolve identically to the APK.
server-local:
	cd $(CURDIR)/pawn_recorder_droid/app/src/main/python && \
	PYTHONPATH=$(CURDIR)/pawn_recorder_droid/app/src/main/python:$(CURDIR) \
	$(PYTHON) $(CURDIR)/scripts/run_server_local.py

# ─── debugger ────────────────────────────────────────────────────────────────

# Forward the debugpy port from the Android device to localhost, then remind
# the user how to attach VS Code.  The app must already be running on device.
android-attach: _require-adb
	adb forward tcp:5678 tcp:5678
	@echo ""
	@echo "  Port forwarded: localhost:5678 → device:5678"
	@echo "  Attach VS Code: Run ▸ Start Debugging  (Attach to Android Python)"
	@echo "  Or press F5 with the 'Attach to Android Python (Chaquopy)' config selected."
	@echo ""
	@echo "  Tip — to pause at Python startup until VS Code connects:"
	@echo "    adb shell setprop debug.pawnrecorder.wait 1"
	@echo "    (then relaunch the app, then press F5)"
	@echo ""

# ─── clean ───────────────────────────────────────────────────────────────────

android-clean:
	cd $(DROID_DIR) && $(GRADLEW) clean 2>/dev/null || rm -rf $(DROID_DIR)/app/build
	@echo "Gradle build/ output cleared."


