"""WhisperBar: a menu-bar-only push-to-talk MLX dictation app."""
from __future__ import annotations

import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import rumps
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
from PyObjCTools import AppHelper

from . import config
from .audio import AudioRecorder
from .corrections import CorrectionsStore
from .cursor_overlay import CursorOverlay
from .hotkeys import (
    NAME_TO_KEYCODE,
    HotkeyManager,
    PermissionError as HotkeyPermissionError,
    keycode_name,
)
from .inserter import insert_text
from . import permissions
from .rules import RuleEngine
from . import transcribe as transcribe_mod

MIN_RECORDING_SECONDS = 0.2
# sounddevice/PortAudio's start()/stop() have been observed to hang
# indefinitely (confirmed via py-spy: the main thread -- which also handles
# every hotkey event and UI update -- was blocked inside stream.stop()
# forever). Bounding the wait keeps the app responsive even when that
# happens, at the cost of abandoning that one recording.
AUDIO_IO_TIMEOUT_SECONDS = 5

ICON_IDLE = "🎙"
ICON_RECORDING = "🔴"
ICON_TRANSCRIBING = "⏳"
ICON_DOWNLOADING = "⬇️"


def _open_in_default_app(path) -> None:
    subprocess.run(["open", str(path)], check=False)


def _clear_menu(item: rumps.MenuItem) -> None:
    # MenuItem.clear() assumes its backing NSMenu already exists, which rumps
    # only creates lazily on the first add() -- guard against clearing a
    # submenu that's never had anything added to it yet.
    if item._menu is not None:
        item.clear()


class WhisperBarApp(rumps.App):
    def __init__(self):
        super().__init__(name="WhisperBar", title=ICON_IDLE, quit_button=None)
        _hide_dock_icon()

        self.settings = config.load_settings()
        self.recorder = AudioRecorder(sample_rate=self.settings["sample_rate"])
        # All PortAudio start()/stop() calls go through here, never through
        # the CGEventTap callback (main thread) directly -- see
        # AUDIO_IO_TIMEOUT_SECONDS above for why.
        self._audio_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio-io")
        self.rules = RuleEngine()
        self.corrections = CorrectionsStore()
        self.hotkeys = HotkeyManager()
        self.cursor_overlay = CursorOverlay()

        self.last_transcription: str | None = None
        self.last_transcription_model: str | None = None
        self._downloading = False
        self._recording = False
        self._hotkey_permission_ok = False

        self.permissions_menu = rumps.MenuItem("Permissions")
        self.model_menu = rumps.MenuItem("Model")
        self.language_menu = rumps.MenuItem("Language")
        self.ptt_menu_item = rumps.MenuItem("Push-to-Talk Key")
        self.toggle_menu_item = rumps.MenuItem("Toggle Recording Key")
        self.rules_menu = rumps.MenuItem("Rules")
        self.numbers_toggle = rumps.MenuItem(
            "Convert spoken numbers to digits", callback=self._toggle_numbers_rule
        )
        self.corrections_menu = rumps.MenuItem("Corrections")
        self.correct_last_item = rumps.MenuItem(
            "Correct Last Transcription…", callback=self._correct_last
        )
        self.launch_at_login_item = rumps.MenuItem(
            "Launch at Login", callback=self._toggle_launch_at_login
        )

        self.menu = [
            self.permissions_menu,
            None,
            self.model_menu,
            self.language_menu,
            self.ptt_menu_item,
            self.toggle_menu_item,
            self.rules_menu,
            self.corrections_menu,
            None,
            self.launch_at_login_item,
            None,
            rumps.MenuItem("Quit WhisperBar", callback=self._quit),
        ]

        self._rebuild_model_menu()
        self._rebuild_language_menu()
        self._rebuild_ptt_menu()
        self._rebuild_toggle_menu()
        self._rebuild_rules_menu()
        self._rebuild_corrections_menu()
        self.launch_at_login_item.state = self.settings.get("launch_at_login", False)

        self._start_hotkeys()
        self._rebuild_permissions_menu()
        self._ensure_default_model()

    # ---- setup -----------------------------------------------------

    def _start_hotkeys(self) -> None:
        try:
            self.hotkeys.start()
            self.hotkeys.bind(
                "ptt", self.settings["ptt_keycode"], on_down=self._on_ptt_press, on_up=self._on_ptt_release
            )
            self.hotkeys.bind("toggle", self.settings.get("toggle_keycode"), on_down=self._on_toggle_press)
            self._hotkey_permission_ok = True
        except HotkeyPermissionError as exc:
            self._hotkey_permission_ok = False
            rumps.notification("WhisperBar", "Permission needed", str(exc))

    # ---- permissions menu -------------------------------------------------
    #
    # macOS deliberately doesn't let an app flip these on itself -- these
    # are one-click jumps to the right System Settings pane plus a status
    # readout, not an actual grant. "Recheck" re-attempts creating the
    # event tap (harmless if it already succeeded, see HotkeyManager.start)
    # so you don't have to relaunch the whole app after granting.

    _MIC_STATUS_LABELS = {
        "granted": "✅ Granted",
        "denied": "❌ Denied",
        "restricted": "🚫 Restricted",
        "not_determined": "⚪ Not requested yet",
        "unknown": "❓ Unknown",
    }

    def _rebuild_permissions_menu(self) -> None:
        _clear_menu(self.permissions_menu)
        mic_label = self._MIC_STATUS_LABELS.get(permissions.microphone_status(), "❓ Unknown")
        hotkey_label = "✅ Working" if self._hotkey_permission_ok else "❌ Needs permission"
        self.permissions_menu.add(rumps.MenuItem(f"Microphone: {mic_label}", callback=None))
        self.permissions_menu.add(rumps.MenuItem(f"Accessibility & Input Monitoring: {hotkey_label}", callback=None))
        self.permissions_menu.add(None)
        self.permissions_menu.add(
            rumps.MenuItem("Open Microphone Settings…", callback=lambda _s: permissions.open_pane("microphone"))
        )
        self.permissions_menu.add(
            rumps.MenuItem(
                "Open Accessibility Settings…", callback=lambda _s: permissions.open_pane("accessibility")
            )
        )
        self.permissions_menu.add(
            rumps.MenuItem(
                "Open Input Monitoring Settings…",
                callback=lambda _s: permissions.open_pane("input_monitoring"),
            )
        )
        self.permissions_menu.add(None)
        self.permissions_menu.add(rumps.MenuItem("Recheck Permissions", callback=self._recheck_permissions))

    def _recheck_permissions(self, _sender) -> None:
        self._start_hotkeys()
        self._rebuild_permissions_menu()
        rumps.notification(
            "WhisperBar",
            "Permissions rechecked",
            "Accessibility & Input Monitoring: " + ("working" if self._hotkey_permission_ok else "still needs permission"),
        )

    def _ensure_default_model(self) -> None:
        installed = transcribe_mod.list_installed_models()
        if installed:
            # Warm the model into memory now so the first push-to-talk press
            # doesn't stall on loading multi-GB weights off disk.
            transcribe_mod.preload_model(self.settings["model"])
            return
        model = self.settings["model"]
        self._downloading = True
        self.title = ICON_DOWNLOADING

        def on_done(error: str | None):
            def _finish():
                self._downloading = False
                self.title = ICON_IDLE
                self._rebuild_model_menu()
                if error:
                    rumps.notification("WhisperBar", "Model download failed", error)
                else:
                    rumps.notification("WhisperBar", "Model ready", model)
                    transcribe_mod.preload_model(model)

            AppHelper.callAfter(_finish)

        rumps.notification("WhisperBar", "Downloading model", f"{model} (first run only)")
        transcribe_mod.download_model_async(model, on_done)

    # ---- push-to-talk / toggle recording ---------------------------------

    def _on_ptt_press(self) -> None:
        self._request_start_recording()

    def _on_ptt_release(self) -> None:
        self._request_stop_recording()

    def _on_toggle_press(self) -> None:
        # Single key, press to start, press again to stop -- as opposed to
        # push-to-talk's hold semantics. Both funnel into the same
        # start/stop machinery and share self._recording, so whichever key
        # started a recording, either can be used interchangeably to check
        # state (though only the one that started it makes sense to use).
        if self._recording:
            self._request_stop_recording()
        else:
            self._request_start_recording()

    def _request_start_recording(self) -> None:
        # This runs on the CGEventTap callback, i.e. the main thread -- it
        # must return immediately no matter what PortAudio does, so the
        # actual start() call is dispatched to the audio-io executor rather
        # than called here directly.
        if self._downloading or self._recording:
            return
        self._recording = True
        AppHelper.callAfter(setattr, self, "title", ICON_RECORDING)
        AppHelper.callAfter(self.cursor_overlay.show)
        self._audio_executor.submit(self._start_recording_safe)

    def _start_recording_safe(self) -> None:
        try:
            self.recorder.start()
        except Exception as exc:  # noqa: BLE001
            self._recording = False
            AppHelper.callAfter(setattr, self, "title", ICON_IDLE)
            AppHelper.callAfter(self.cursor_overlay.hide)
            AppHelper.callAfter(lambda: rumps.notification("WhisperBar", "Recording failed", str(exc)))

    def _request_stop_recording(self) -> None:
        # Same constraint as _request_start_recording: never block the main
        # thread, so even the *wait* for stop() to finish happens on its
        # own thread.
        if not self._recording:
            return
        self._recording = False
        AppHelper.callAfter(self.cursor_overlay.hide)
        threading.Thread(target=self._stop_recording_and_process, daemon=True).start()

    def _stop_recording_and_process(self) -> None:
        future = self._audio_executor.submit(self.recorder.stop)
        try:
            audio = future.result(timeout=AUDIO_IO_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            AppHelper.callAfter(setattr, self, "title", ICON_IDLE)
            AppHelper.callAfter(
                lambda: rumps.notification(
                    "WhisperBar", "Recording got stuck", "Recovered automatically -- try again."
                )
            )
            self._recover_stuck_audio()
            return
        except Exception as exc:  # noqa: BLE001
            AppHelper.callAfter(setattr, self, "title", ICON_IDLE)
            AppHelper.callAfter(lambda: rumps.notification("WhisperBar", "Recording failed", str(exc)))
            return

        if self.recorder.duration_seconds(audio) < MIN_RECORDING_SECONDS:
            AppHelper.callAfter(setattr, self, "title", ICON_IDLE)
            return
        AppHelper.callAfter(setattr, self, "title", ICON_TRANSCRIBING)
        self._process_audio(audio)

    def _recover_stuck_audio(self) -> None:
        # The old executor's single worker thread is permanently blocked
        # inside whatever PortAudio call hung; abandon it (it leaks as a
        # zombie thread) rather than letting every future press/release
        # queue up behind a call that will never return.
        self._audio_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio-io")
        self.recorder = AudioRecorder(sample_rate=self.settings["sample_rate"])

    def _process_audio(self, audio) -> None:
        try:
            raw_text = transcribe_mod.transcribe(
                audio,
                self.settings["model"],
                sample_rate=self.settings["sample_rate"],
                language=self.settings.get("language"),
            )
            text = self.corrections.apply(self.settings["model"], raw_text)
            text = self.rules.apply(text)
            text = text.strip()
            if text:
                insert_text(text, method=self.settings.get("insert_method", "type"))
                self.last_transcription = text
                self.last_transcription_model = self.settings["model"]

                def _enable():
                    self.correct_last_item.set_callback(self._correct_last)

                AppHelper.callAfter(_enable)
        except Exception as exc:  # noqa: BLE001
            def _notify():
                rumps.notification("WhisperBar", "Transcription failed", str(exc))

            AppHelper.callAfter(_notify)
        finally:
            AppHelper.callAfter(setattr, self, "title", ICON_IDLE)

    # ---- model menu ----------------------------------------------------

    def _rebuild_model_menu(self) -> None:
        _clear_menu(self.model_menu)
        installed = transcribe_mod.list_installed_models()
        if not installed:
            self.model_menu.add(rumps.MenuItem("(no models installed)", callback=None))
        for repo_id in installed:
            item = rumps.MenuItem(repo_id, callback=self._select_model)
            item.state = repo_id == self.settings["model"]
            self.model_menu.add(item)
        self.model_menu.add(None)
        self.model_menu.add(rumps.MenuItem("Download Model…", callback=self._download_model))

    def _select_model(self, sender: rumps.MenuItem) -> None:
        self.settings["model"] = sender.title
        config.save_settings(self.settings)
        self._rebuild_model_menu()
        self._rebuild_language_menu()
        self._rebuild_corrections_menu()

    # ---- language menu --------------------------------------------------

    def _rebuild_language_menu(self) -> None:
        _clear_menu(self.language_menu)
        if not transcribe_mod.supports_language(self.settings["model"]):
            self.language_menu.add(
                rumps.MenuItem(
                    "Not supported by this model (always multilingual)", callback=None
                )
            )
            return
        current = self.settings.get("language")
        for label, code in transcribe_mod.LANGUAGES:
            item = rumps.MenuItem(label, callback=self._select_language)
            item.state = code == current
            self.language_menu.add(item)

    def _select_language(self, sender: rumps.MenuItem) -> None:
        code = dict(transcribe_mod.LANGUAGES).get(sender.title)
        self.settings["language"] = code
        config.save_settings(self.settings)
        self._rebuild_language_menu()

    def _download_model(self, _sender) -> None:
        response = rumps.Window(
            message="Enter a Hugging Face repo id for an MLX whisper model\n"
            "(e.g. mlx-community/whisper-large-v3-turbo):",
            title="Download Model",
            default_text="mlx-community/",
            ok="Download",
            cancel="Cancel",
        ).run()
        if not response.clicked:
            return
        repo_id = response.text.strip()
        if not repo_id:
            return

        self._downloading = True
        self.title = ICON_DOWNLOADING

        def on_done(error: str | None):
            def _finish():
                self._downloading = False
                self.title = ICON_IDLE
                self._rebuild_model_menu()
                if error:
                    rumps.notification("WhisperBar", "Model download failed", error)
                else:
                    rumps.notification("WhisperBar", "Model ready", repo_id)

            AppHelper.callAfter(_finish)

        rumps.notification("WhisperBar", "Downloading model", repo_id)
        transcribe_mod.download_model_async(repo_id, on_done)

    # ---- push-to-talk / toggle key pickers -------------------------------
    #
    # Each key can be set two ways: click its name directly from the
    # submenu's list of F13-F20 (no need to know/press the physical key
    # blind -- useful since not every keyboard has all of them without a
    # remap), or "Press a key to set…" to capture whatever's actually
    # pressed, including non-F-row keys. Both write through the same
    # settings + HotkeyManager update path.

    def _rebuild_ptt_menu(self) -> None:
        _clear_menu(self.ptt_menu_item)
        self.ptt_menu_item.title = f"Push-to-Talk Key: {keycode_name(self.settings['ptt_keycode'])}"
        self.ptt_menu_item.add(rumps.MenuItem("Press a key to set…", callback=self._change_ptt_key))
        self.ptt_menu_item.add(None)
        current = self.settings["ptt_keycode"]
        for name, code in NAME_TO_KEYCODE.items():
            item = rumps.MenuItem(name, callback=self._select_ptt_key)
            item.state = code == current
            self.ptt_menu_item.add(item)

    def _select_ptt_key(self, sender: rumps.MenuItem) -> None:
        code = NAME_TO_KEYCODE.get(sender.title)
        if code is None:
            return
        if code == self.settings.get("toggle_keycode"):
            rumps.notification("WhisperBar", "Key already in use", f"{sender.title} is set as the Toggle Recording key.")
            return
        self.settings["ptt_keycode"] = code
        config.save_settings(self.settings)
        self.hotkeys.set_keycode("ptt", code)
        self._rebuild_ptt_menu()

    def _change_ptt_key(self, _sender) -> None:
        rumps.notification(
            "WhisperBar", "Press a key", "Press the key you want to use for push-to-talk…"
        )

        def _captured(keycode: int):
            if keycode == self.settings.get("toggle_keycode"):
                AppHelper.callAfter(
                    lambda: rumps.notification(
                        "WhisperBar", "Key already in use", "That key is set as the Toggle Recording key."
                    )
                )
                return
            self.settings["ptt_keycode"] = keycode
            config.save_settings(self.settings)
            self.hotkeys.set_keycode("ptt", keycode)

            def _update_ui():
                self._rebuild_ptt_menu()
                rumps.notification("WhisperBar", "Push-to-talk key set", keycode_name(keycode))

            AppHelper.callAfter(_update_ui)

        self.hotkeys.capture_next_key(_captured)

    def _rebuild_toggle_menu(self) -> None:
        _clear_menu(self.toggle_menu_item)
        code = self.settings.get("toggle_keycode")
        self.toggle_menu_item.title = f"Toggle Recording Key: {keycode_name(code) if code is not None else 'Disabled'}"
        self.toggle_menu_item.add(rumps.MenuItem("Press a key to set…", callback=self._change_toggle_key))
        disable_item = rumps.MenuItem("Disable", callback=self._disable_toggle_key)
        disable_item.state = code is None
        self.toggle_menu_item.add(disable_item)
        self.toggle_menu_item.add(None)
        for name, kcode in NAME_TO_KEYCODE.items():
            item = rumps.MenuItem(name, callback=self._select_toggle_key)
            item.state = kcode == code
            self.toggle_menu_item.add(item)

    def _select_toggle_key(self, sender: rumps.MenuItem) -> None:
        code = NAME_TO_KEYCODE.get(sender.title)
        if code is None:
            return
        if code == self.settings.get("ptt_keycode"):
            rumps.notification("WhisperBar", "Key already in use", f"{sender.title} is set as the Push-to-Talk key.")
            return
        self.settings["toggle_keycode"] = code
        config.save_settings(self.settings)
        self.hotkeys.set_keycode("toggle", code)
        self._rebuild_toggle_menu()

    def _disable_toggle_key(self, _sender) -> None:
        self.settings["toggle_keycode"] = None
        config.save_settings(self.settings)
        self.hotkeys.set_keycode("toggle", None)
        self._rebuild_toggle_menu()

    def _change_toggle_key(self, _sender) -> None:
        rumps.notification(
            "WhisperBar", "Press a key", "Press the key you want to use to toggle recording…"
        )

        def _captured(keycode: int):
            if keycode == self.settings.get("ptt_keycode"):
                AppHelper.callAfter(
                    lambda: rumps.notification(
                        "WhisperBar", "Key already in use", "That key is set as the Push-to-Talk key."
                    )
                )
                return
            self.settings["toggle_keycode"] = keycode
            config.save_settings(self.settings)
            self.hotkeys.set_keycode("toggle", keycode)

            def _update_ui():
                self._rebuild_toggle_menu()
                rumps.notification("WhisperBar", "Toggle key set", keycode_name(keycode))

            AppHelper.callAfter(_update_ui)

        self.hotkeys.capture_next_key(_captured)

    # ---- rules menu ----------------------------------------------------

    def _rebuild_rules_menu(self) -> None:
        _clear_menu(self.rules_menu)
        self.numbers_toggle.state = self.rules.is_builtin_enabled("spoken-numbers")
        self.rules_menu.add(self.numbers_toggle)
        self.rules_menu.add(None)
        self.rules_menu.add(
            rumps.MenuItem("Edit Rules File…", callback=lambda _s: _open_in_default_app(config.RULES_PATH))
        )

    def _toggle_numbers_rule(self, sender: rumps.MenuItem) -> None:
        enabled = not sender.state
        self.rules.set_builtin_enabled("spoken-numbers", enabled)
        sender.state = enabled

    # ---- corrections menu ------------------------------------------------

    def _rebuild_corrections_menu(self) -> None:
        _clear_menu(self.corrections_menu)
        self.corrections_menu.add(self.correct_last_item)
        # Rebuilt on every model switch (the "Open Corrections File" target
        # changes), not just at startup -- don't clobber an already-enabled
        # correction flow if we already have a transcription to correct.
        self.correct_last_item.set_callback(self._correct_last if self.last_transcription else None)
        self.corrections_menu.add(None)
        model = self.settings["model"]
        self.corrections_menu.add(
            rumps.MenuItem(
                f"Open Corrections File ({model})…",
                callback=lambda _s: _open_in_default_app(config.corrections_path(self.settings["model"])),
            )
        )

    def _correct_last(self, _sender) -> None:
        if not self.last_transcription:
            return
        response = rumps.Window(
            message="What should WhisperBar have typed instead?\n"
            "This fix is remembered and applied automatically next time.",
            title="Correct Last Transcription",
            default_text=self.last_transcription,
            ok="Save",
            cancel="Cancel",
        ).run()
        if not response.clicked:
            return
        corrected = response.text.strip()
        if corrected and corrected != self.last_transcription:
            self.corrections.add(self.last_transcription_model, self.last_transcription, corrected)
            rumps.notification("WhisperBar", "Correction saved", f"{self.last_transcription!r} → {corrected!r}")

    # ---- launch at login ------------------------------------------------

    def _toggle_launch_at_login(self, sender: rumps.MenuItem) -> None:
        from . import launch_agent

        enabled = not sender.state
        try:
            if enabled:
                launch_agent.install()
            else:
                launch_agent.uninstall()
        except launch_agent.NotPackagedError:
            rumps.notification(
                "WhisperBar",
                "Not available",
                "Launch at Login requires the built WhisperBar.app in /Applications.",
            )
            return
        sender.state = enabled
        self.settings["launch_at_login"] = enabled
        config.save_settings(self.settings)

    # ---- quit --------------------------------------------------------

    def _quit(self, _sender) -> None:
        # A stuck PortAudio call leaves its worker thread permanently
        # blocked; Python's normal interpreter shutdown waits to join every
        # non-daemon thread (including abandoned ThreadPoolExecutor
        # workers) before exiting, which would make Quit itself hang in
        # that state. os._exit() skips all of that -- fine here since
        # nothing in this app buffers state that isn't already written to
        # disk immediately (config.save_settings() etc.).
        import os

        self.hotkeys.stop()
        os._exit(0)


def _hide_dock_icon() -> None:
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)


def run() -> None:
    WhisperBarApp().run()
