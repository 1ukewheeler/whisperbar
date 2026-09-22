# WhisperBar

A menu-bar-only macOS app for local push-to-talk dictation using MLX speech
models on Apple Silicon. Hold a key, speak, the text gets typed wherever
your cursor is. Everything runs on-device — no cloud calls, no account, no
dock icon.

<p align="center"><img src="AppIcon.icns" width="128" alt="WhisperBar icon"></p>

## Features

- **Push-to-talk dictation**, any key you like (defaults to F16), *and* a
  separate **toggle-recording key** (defaults to F17) if you'd rather press
  once to start and again to stop than hold the whole time.
- **Pick either key by clicking its name from a list, or by pressing it** —
  no need to guess which physical key maps to what, or dig into a remap
  tool first.
- **Two model backends**: OpenAI Whisper (`mlx_whisper`) and NVIDIA Parakeet
  (`parakeet_mlx`, roughly 10x faster for short clips) — switch between any
  installed model from the menu, no restart needed.
- **Text rules**: e.g. converting spoken numbers ("one two three") to digits
  ("1 2 3"), plus your own custom regex rules.
- **Learns from your corrections**: fix a bad transcription once from the
  menu and it's remembered — including fuzzy matching, so correcting one
  mishearing of an unusual word (e.g. "Quen" → "Qwen") also catches similar
  mishearings ("Quem", "Kwen", …) automatically. Corrections are kept
  per-model, since different models mishear things differently.
- **Language selection**: pin transcription to a specific language to stop
  short/ambiguous audio from occasionally getting misidentified as some
  other language, or leave it on auto-detect.
- **One-click permission setup**: a menu that shows current Microphone/
  Accessibility/Input Monitoring status and jumps straight to the right
  System Settings pane — no hunting through Privacy & Security by hand.
- A red-dot cursor indicator while recording, so it's obvious when
  push-to-talk is active.

## Requirements

- Apple Silicon Mac, macOS 13+.
- [Homebrew](https://brew.sh).

## Setup

```bash
brew install mlx ffmpeg   # mlx: Apple's array framework; ffmpeg: audio decoding
git clone <this-repo-url> whisperbar
cd whisperbar
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
./build_app.sh             # builds /Applications/WhisperBar.app
```

(`--system-site-packages` matters because Homebrew's `mlx` formula installs
working Python bindings into `python@3.14`'s site-packages — the venv
inherits those instead of trying to rebuild MLX from source.)

The built `.app` runs this project's `.venv` in place, so leave the
`whisperbar/` folder where it is after building — don't delete or move it.

### First launch

The build is unsigned (no Apple Developer account involved), so macOS will
block a plain double-click the first time. **Right-click `WhisperBar.app` in
Finder → Open**, and confirm in the dialog that appears. After that, it
opens normally (including via Login Items).

```bash
open /Applications/WhisperBar.app
```

### Permissions

Open the menu bar icon → **Permissions**. It shows current status for each
of the three permissions WhisperBar needs and has a button to jump straight
to the right System Settings pane for each:
- **Microphone** — to record while push-to-talk is held.
- **Accessibility** — to type text into other apps.
- **Input Monitoring** — to detect the push-to-talk key globally, even when
  WhisperBar isn't the focused app.

macOS doesn't let an app grant these to itself (that's a deliberate security
boundary) — you still click the checkbox yourself once each pane is open —
but nothing here requires you to find Privacy & Security manually. After
granting, use **Permissions → Recheck Permissions** rather than relaunching
the whole app.

If you rebuild the app (`./build_app.sh` again), macOS treats it as a new
binary and these permissions go stale — remove WhisperBar from each list
(the `-` button) and re-add it (`+`, pick `/Applications/WhisperBar.app`)
if push-to-talk stops responding after a rebuild.

## Installing models

The default model (`mlx-community/parakeet-tdt-0.6b-v2` — fast, accurate,
English-only) downloads automatically in the background on first launch;
you'll get a notification when it's ready.

To try others, use **Model → Download Model…** in the menu and paste any
MLX model repo id from Hugging Face. A few worth trying:

| Model | Backend | Notes |
|---|---|---|
| `mlx-community/parakeet-tdt-0.6b-v2` | Parakeet | **Default.** English-only, ~10x faster than Whisper turbo, best English accuracy of the Parakeet models. |
| `mlx-community/parakeet-tdt-0.6b-v3` | Parakeet | Same speed, multilingual (25 languages) — use this if you dictate in more than English. |
| `mlx-community/whisper-large-v3-turbo` | Whisper | Slower (~0.8s vs ~0.1s per short clip) but a different model family if Parakeet's output style doesn't suit you. |
| `mlx-community/distil-whisper-large-v3` | Whisper | Smaller/faster Whisper variant; still slower than either Parakeet model. |

Anything already in your local Hugging Face cache
(`~/.cache/huggingface`) that one of the two backends can load shows up
automatically under **Model** — no need to re-download across projects.

Only two model families are supported: Whisper (`mlx_whisper`) and Parakeet
(`parakeet_mlx`), auto-detected from the repo name. Other MLX architectures
would need a new backend in `whisperbar/backends.py` (see that file's
docstring for why it's split out that way).

## Using it

- **Push-to-talk**: hold the key (default **F16**), speak, release. The menu
  bar icon shows 🎙 idle, 🔴 recording, ⏳ transcribing, and a small red dot
  follows your cursor while recording.
- **Toggle recording**: press the toggle key (default **F17**) once to
  start, once more to stop — an alternative to holding.
- **Change either key**: menu → **Push-to-Talk Key** or **Toggle Recording
  Key** → either click a key name directly from the list (F13–F20), or
  **"Press a key to set…"** to capture any other key by pressing it. The
  toggle key can also be turned off entirely from its own submenu.
- **Switch models**: menu → **Model** → pick one.
- **Language**: menu → **Language** (Whisper models only — Parakeet has no
  per-call language control; use the English-only `v2` checkpoint if you
  want guaranteed English from Parakeet).
- **Rules**: menu → **Rules**. "Convert spoken numbers to digits" is on by
  default. **Edit Rules File…** opens `rules.json` in your default editor
  for custom find/replace rules:
  ```json
  {"id": "my-rule", "type": "regex", "pattern": "\\bteh\\b", "replacement": "the", "enabled": true}
  ```
- **Corrections**: menu → **Corrections → Correct Last Transcription…**
  pre-fills what was typed — edit it to what you actually wanted and save.
  **Open Corrections File…** opens the current model's corrections file so
  you can review/delete entries by hand.
- **Launch at Login**: toggle in the menu.

## Data locations

All config lives in `~/Library/Application Support/WhisperBar/`:
- `settings.json` — active model, language, push-to-talk/toggle keys, insert method.
- `rules.json` — your text-transform rules.
- `corrections/<model-name>.json` — learned mistake → fix phrases, one file
  per model.

## Testing changes

`tests/test_transcribe.py` runs synthetic speech (generated locally via
macOS's `say`, see `tests/audio/generate.sh` — no microphone needed) through
every installed model, replicating the app's actual threading pattern
(model load on one thread, transcription on a fresh thread per call —
that's what catches backend-specific threading bugs that single-threaded
testing misses):

```bash
tests/audio/generate.sh          # regenerate test audio, if needed
.venv/bin/python3 tests/test_transcribe.py
```

## Troubleshooting

- **Nothing happens when I hold the key**: check Accessibility + Input
  Monitoring permissions (see above — these go stale after a rebuild), then
  relaunch the app.
- **Text doesn't get typed into a particular app**: try switching
  `"insert_method"` in `settings.json` between `"paste"` (clipboard +
  Cmd-V, restores your previous clipboard after) and `"type"` (synthetic
  keystrokes) and relaunch — different apps handle one or the other more
  reliably.
- **First transcription after launch is slow**: that's the model loading
  into memory; WhisperBar preloads it in the background at startup, but a
  press right at launch can still catch it mid-load. It stays loaded after
  that, so it's fast from then on.
- **The app freezes / cursor indicator gets stuck**: audio start/stop calls
  are timeout-guarded and self-recover after ~5 seconds if the OS audio
  layer hangs; if the whole app seems unresponsive, Quit still works (it
  force-exits rather than waiting on anything stuck).
