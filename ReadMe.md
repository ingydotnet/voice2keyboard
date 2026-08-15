LapTalk
=======

Talk to your Laptop — Voice to Keyboard Typing


## Status

Works on Linux and macOS!

Please report any issues or success stories.


## Synopsis

Run this in a terminal:

```bash
git clone git@github.com:laptalk/laptalk
cd laptalk
make run key=alt_r
```

Then press the Right-Alt key and speak and let go.

Your speech will be converted to text and pasted wherever your input focus is!


## Description

`laptalk` is a Linux program that provides real-time voice-to-text input. Hold a
trigger key (or key combination) to record, and the transcription appears at
your cursor when it is ready.

Supports two speech recognition engines with automatic detection:
- **Whisper** - High accuracy, great with technical terms, batch processing
- **Vosk** - Fast, offline, streaming recognition (models start with `vosk-`)

The engine is automatically inferred from the model name - no need to specify
it separately.

Can be set up as a systemd user service for always-on availability.


## Features

- **Works everywhere** - Pastes into any application that accepts text input
- **Reliable output** - Avoids dropped or transposed synthetic keystrokes in
  applications such as VS Code and Signal
- **Push-to-talk input** - Hold a trigger key or combination (e.g., Shift+Ctrl)
  to activate recording
- **Two typing modes** - Buffered (accurate, waits for pauses) or Realtime
  (immediate)
- **Offline processing** - Both engines work locally, no internet required
- **Auto-start on login** - Can run as a systemd user service
- **Configurable** - Customize model, trigger key, typing mode, and voice
  translations via YAML


## Requirements


### System

- Linux (tested on Ubuntu/Debian)
- X11 display server (Wayland support is limited)
- Working microphone


### Dependencies

**Manual install required on Linux:**
```bash
sudo apt install alsa-utils xsel   # provides arecord and clipboard access
```

`xclip` can be used instead of `xsel`. macOS provides `pbcopy` and `pbpaste`.
If no configured clipboard command is available, Laptalk falls back to
synthetic typing.

**Automatically managed by Makefile:**
- Python 3.13.1 (downloaded to `.cache/`)
- pynput (hotkey detection and keyboard simulation)
- PyYAML (configuration parsing)
- vosk (for Vosk engine)
- faster-whisper (for Whisper engine)
- Speech models (downloaded based on engine and config)


## Installation


### Quick Start

```bash
# Clone the repository
git clone git@github.com:laptalk/laptalk
cd laptalk

# Run it
make run key=alt_r
```

That's it! The service will:
1. Download Python 3.13.1 and create a virtual environment
2. Install required Python packages
3. Download the configured speech recognition model

For always-on availability, see the **Running as a Service** section below.


## Running as a Service (Linux/systemd)

To have LapTalk start automatically on login and run in the background:

### Quick Install

```bash
cd laptalk
make install
```

This will:
1. Copy the service file to `~/.config/systemd/user/laptalk.service`
2. Enable the service to start on login
3. Start the service immediately

### Customize Before Installing

The service file may need adjustment for your system's X11 configuration.

**Check your environment:**
```bash
echo "DISPLAY=$DISPLAY"
echo "XAUTHORITY=$XAUTHORITY"
```

**Edit the service file if needed:**
```bash
# Edit laptalk.service before running make install
nano laptalk.service
```

Update the `Environment` lines to match your system:
```ini
Environment="DISPLAY=:1"                              # Your DISPLAY value
Environment="XAUTHORITY=/run/user/1000/gdm/Xauthority" # Your XAUTHORITY path
```

**Customize the trigger key and log location:**

The default service uses `key=alt_r` and logs to `laptalk-log.txt`. Edit line 7:
```ini
ExecStart=/usr/bin/make -C %h/src/laptalk run key=alt_r log=%h/src/laptalk/laptalk-log.txt
```

Change `key=alt_r` to your preferred key or key combination.

### Managing the Service

```bash
# Check if it's running
make status

# View live logs
make logs

# Or view the app log file
tail -f laptalk-log.txt

# Stop and remove the service
make uninstall

# Restart after making changes
systemctl --user restart laptalk
```

### Service Configuration

The service file supports:
- **Auto-restart on failure** - Automatically recovers from crashes
- **Starts on login** - Always available when you log in
- **Background operation** - Runs silently in the background
- **Logging** - All output logged via journalctl or to file

### Hot-Reload Config

The service supports hot-reloading configuration changes! Edit `config.yaml`
while the service is running and changes will be automatically detected and
applied (except model changes, which require a service restart).

Reloadable settings:
- `mode` (buffered/realtime)
- `pause` (pause delay)
- `output` (paste/type)
- `clipboard` (program order and restore delay)
- `upper` (capitalize the first character)
- `hallucinations` (ignored phrases)
- `translations` (universal phrase replacements)
- `vosk-translations` (voice-to-symbol mappings)


## Running as a Service (macOS/launchd)

To have voice2keyboard start automatically on login and run in the background on macOS:

### Quick Install

```bash
cd voice2keyboard

# Edit the plist file to set your installation path
nano voice2keyboard.plist
# Update the WorkingDirectory path to match your installation

# Copy to LaunchAgents
cp voice2keyboard.plist ~/Library/LaunchAgents/com.voice2keyboard.plist

# Load and start the service
launchctl load ~/Library/LaunchAgents/com.voice2keyboard.plist
```

### Customize Before Installing

Edit `voice2keyboard.plist` before copying:

1. **Set your installation path:** Update the `WorkingDirectory` value to your voice2keyboard directory
2. **Change the trigger key:** Replace `key=alt_r` with your preferred key in the `ProgramArguments` array
3. **Add model override:** Add `<string>model=small.en</string>` to the `ProgramArguments` array

### Managing the Service

```bash
# Check if it's running
launchctl list | grep voice2keyboard

# Stop the service
launchctl unload ~/Library/LaunchAgents/com.voice2keyboard.plist

# Start the service
launchctl load ~/Library/LaunchAgents/com.voice2keyboard.plist

# Restart the service (stop then start)
launchctl unload ~/Library/LaunchAgents/com.voice2keyboard.plist && \
launchctl load ~/Library/LaunchAgents/com.voice2keyboard.plist

# Remove the service completely
launchctl unload ~/Library/LaunchAgents/com.voice2keyboard.plist
rm ~/Library/LaunchAgents/com.voice2keyboard.plist

# View logs
tail -f v2k-log.txt
tail -f /tmp/voice2keyboard-error.txt
```

### macOS Permissions

macOS requires explicit permissions for accessibility and microphone access:

1. **Accessibility Permission** (required for keyboard simulation):
   - Go to **System Preferences** → **Security & Privacy** → **Privacy** → **Accessibility**
   - Add Terminal (or your terminal app) to the list
   - If running as a service, you may need to add `/usr/bin/make` or the Python executable

2. **Microphone Permission** (required for audio capture):
   - Go to **System Preferences** → **Security & Privacy** → **Privacy** → **Microphone**
   - Add Terminal (or your terminal app) to the list

3. **Input Monitoring** (may be required on newer macOS versions):
   - Go to **System Preferences** → **Security & Privacy** → **Privacy** → **Input Monitoring**
   - Add Terminal (or your terminal app) to the list

**Note:** You may need to restart the service after granting permissions.


## Usage

1. **Hold the trigger key** (default: Right Alt) in any application
2. **Speak** - Vosk realtime results may appear while you speak
3. **Release the key** to stop recording; Whisper then pastes the result

Laptalk performs Ctrl+V on Linux or Command+V on macOS automatically. Linux
terminal windows are detected by `WM_CLASS` and use synthetic typing instead,
avoiding terminal-specific paste shortcuts and application bindings. Laptalk
saves the existing plain-text clipboard before a paste and restores it shortly
afterward.


### Typing Modes

**Buffered mode (default, recommended):**
- Waits for natural pauses before typing
- More accurate word recognition
- Optional pause delay for better context

**Realtime mode:**
- Types words immediately as recognized
- Lower latency but may misrecognize
- Only works with Vosk engine
- Always uses synthetic typing because clipboard swaps and a held trigger
  modifier are not safe for realtime output


### Output Methods

**Paste mode (default):**
- Renders each recognition result as one string
- Copies it to the standard clipboard and performs the paste shortcut
- Restores the previous plain-text clipboard after a short delay
- Falls back to synthetic typing if the clipboard cannot be preserved or used
- Accumulates buffered Vosk results and pastes once when the trigger is released

**Type mode:**
- Sends synthetic keyboard events, preserving the previous behavior
- Can be selected globally or for an individual trigger


### Vosk Translations

See the `config.yaml` for a table of Vosk translations.

Whisper gets almost everything right!


## Configuration

The stock configuration works great, but you can edit the `config.yaml` to
customize some behavior.
You can also set any of the config options from command line arguments.

**Note:** The trigger key is specified via a CLI argument, not in the config.
The trigger key is the only mandatory command line option.

You can specify an alternate config file using the `--config` option, which is
useful when running as a service with different configurations.

```yaml
# Model selection:
# - Whisper models: tiny, tiny.en, base, base.en, small, small.en, medium.en, etc.
# - Vosk models: vosk-model-small-en-us-0.15, vosk-model-en-us-0.22, etc.
# Can override with --model on command line
model: base.en

# Typing mode
# - buffered: Wait for natural pauses before typing (more accurate)
# - realtime: Type words immediately as recognized (faster, less accurate)
mode: buffered

# Pause delay (in seconds) after speech pause before typing
# Gives the model extra time to refine predictions
# Set to 0 to disable. Only applies in buffered mode.
pause: 0.3

# Output method: paste (default) or type
output: paste

# Clipboard backends are tried in order. Laptalk performs the paste shortcut
# and restores the previous plain-text clipboard after this delay.
clipboard:
  programs: [xsel, xclip, pbcopy]
  restore-delay: 0.25
  # Substrings matched against the active X11 window's WM_CLASS. These windows
  # use typing output; the full default list is in config.yaml.
  terminal-classes: [gnome-terminal, ptyxis, konsole, kitty, alacritty]

# A trigger key may override mode, pause, upper, or output:
# keys:
#   alt_r:
#     output: type

# Faster-whisper engine settings (ignored for Vosk models)
whisper:
  device: auto            # auto, cpu, cuda
  compute_type: auto      # auto, int8, float16, float32
  beam_size: 1            # 1 = greedy/fast, 5 = default, higher = slower/better
  vad_filter: true        # Skip silence segments for faster processing

# Voice translations - say the word, get the symbol
vosk-translations:
  full stop: "."
  tadpole: ","
  question mark: "?"
  # Add your own...
```

### Whisper Engine Settings

Fine-tune faster-whisper performance with these settings (Whisper models only):

| Setting | Values | Default | Notes |
|---------|--------|---------|-------|
| `device` | auto, cpu, cuda | auto | Auto-detects GPU availability |
| `compute_type` | auto, int8, float16, float32 | auto | int8 fastest on CPU, float16 on GPU |
| `beam_size` | 1-10 | 1 | 1 = greedy/fastest, 5 = balanced, higher = slower/better |
| `vad_filter` | true/false | true | Skip silence for faster processing |

**Performance tips:**
- On CPU: `compute_type: int8` + `beam_size: 1` gives best speed
- With these optimized settings, `small.en` may run as fast as `base.en` with defaults
- Try larger models (`small.en`, `medium.en`) with optimized settings before assuming they're too slow
- GPU users (when available) will automatically get float16 acceleration with `device: auto`

## Command Line Usage

Typically you just run:

```
$ make run key=alt_r
```

You can also also run:

```
$ python laptalk.py --key=alt_r
```

but the `make` command installs all the prerequisites (including even a local
python binary under `.cache/.local/`).

The `key=...` parameter is required for all manual runs.
Model selection uses the config value unless overridden with `model=...`.


### Running Manually

```bash
# Run with default model (from config) and Alt_R key
make run key=alt_r

# Run with Vosk model and key combination
make run key=shift_l-ctrl_r model=vosk-model-small-en-us-0.15

# With additional options
make run key=ctrl_l mode=buffered

# Override model to use Whisper
make run key=alt_r model=medium.en

# Multiple options
make run key=shift_l-alt_r model=vosk-model-small-en-us-0.15 mode=realtime pause=0.5
```


### Direct Python Invocation

```bash
# Basic usage (key required, uses model from config)
python laptalk.py --key alt_r

# With custom config file
python laptalk.py --key alt_r --config /path/to/custom-config.yaml

# With Vosk model
python laptalk.py --key shift_l-alt_r --model vosk-model-small-en-us-0.15

# With Whisper model
python laptalk.py --key shift_l-ctrl_r --model medium.en

# With additional options
python laptalk.py --key alt_r --mode buffered --pause 0.5

# See all options
python laptalk.py --help
```


### Performance Logging

Track transcription performance and identify bottlenecks using the `log=...`
argument:

```bash
# Log to file (silent operation, no console output)
make run key=alt_r log=laptalk-log.txt

# Log to console (stdout)
make run key=alt_r log=/dev/stdout

# Direct Python invocation
python laptalk.py --key alt_r --log laptalk-log.txt

# View the log in another terminal
tail -f laptalk-log.txt
```

**Log output format:**
```
time: 2025-12-26 00:09:28
text: Hopefully this is still fast.
info:
  wait_stop: 104ms
  concat=0ms
  transcribe: 926ms
  cleanup: 0ms
  tokenize: 0ms
  output: 49ms
  TOTAL: 1080ms
```

**Timing breakdown:**
- **wait_stop**: Time for recording loop to stop after key release
- **concat**: Audio concatenation time
- **transcribe**: Whisper transcription time (includes text collection)
- **cleanup**: Text cleanup time (removing Whisper artifacts)
- **tokenize**: Token processing time
- **output**: Time spent pasting and restoring the clipboard, or typing
- **TOTAL**: Total user-perceived delay (key release → text appears)

Use this to:
- Identify performance bottlenecks
- Compare different models
- Test optimization settings
- Debug latency issues


## Running Multiple Instances

You can run multiple instances simultaneously with different models and
trigger keys:

**Example:**

```bash
# Terminal 1 - Whisper for accuracy (uses default model from config)
make run key=alt_r

# Terminal 2 - Vosk for speed
make run key=ctrl_l model=vosk-model-small-en-us-0.15
```

Now you can use `Alt_R` for accurate Whisper transcription and `Ctrl_L` for
fast Vosk transcription!

**Important considerations:**

1. **Use non-overlapping trigger keys**
   - ✅ Good: `alt_r` and `ctrl_l`
   - ✅ Good: `alt_r` and `shift_l-ctrl_r`
   - ❌ Bad: `alt_r` and `shift_l-alt_r` (both include `alt_r`)

2. **Microphone access**
   - Most Linux systems handle multiple processes accessing the mic
     simultaneously
   - Avoid holding both trigger keys at the same time
   - Best practice: use one instance at a time

3. **Use cases**
   - Quick switching: Whisper for technical writing, Vosk for casual notes
   - Different contexts: One key per hand, or different keys for different
     postures
   - A/B testing: Compare engine accuracy side-by-side

4. **Systemd service**
   - The default service runs a single instance
   - For multiple persistent instances, create separate service files
   - Or run additional instances manually in terminals


## Speech Engines


### Whisper

**Pros:**
- Higher accuracy
- Better with technical vocabulary (CLI, GitHub, API, etc.)
- Handles punctuation naturally

**Cons:**
- Batch processing only (no realtime mode)
- Higher latency
- Larger models

**Models:**
- Downloaded automatically via faster-whisper
- Cached in `~/.cache/huggingface/`

| Model | Size | Notes |
|-------|------|-------|
| `tiny.en` | ~75MB | Fastest, lowest accuracy |
| `base.en` | ~140MB | Good balance |
| `small.en` | ~466MB | **Recommended** - good speed/accuracy |
| `medium.en` | ~1.5GB | Best accuracy, slower |


### Vosk

**Pros:**
- Streaming recognition (types as you speak in realtime mode)
- Lower latency
- Smaller models

**Cons:**
- Lower accuracy
- Less familiar with technical terms

**Models:**
- Download from [alphacephei.com/vosk/models](
  https://alphacephei.com/vosk/models)
- Extracted to project root directory

| Model | Size | Notes |
|-------|------|-------|
| `vosk-model-small-en-us-0.15` | ~40MB | Default, fast |
| `vosk-model-en-us-0.22-lgraph` | ~128MB | Better accuracy |
| `vosk-model-en-us-0.22` | ~1.8GB | Best accuracy |


## Key Combinations

You can use modifier key combinations as triggers:

**Examples:**
- `shift_l-ctrl_l` - Left Shift + Left Ctrl
- `shift_l-ctrl_r` - Left Shift + Right Ctrl
- `shift_l-alt_r` - Left Shift + Right Alt
- `ctrl_l-alt_l-shift_l` - All three left modifiers

**Available keys:**
- Modifiers: `alt_l`, `alt_r`, `ctrl_l`, `ctrl_r`, `shift_l`, `shift_r`
- Special: `scroll_lock`, `pause`, `insert`, `delete`

**Note:** Order doesn't matter - `ctrl_r-shift_l` and `shift_l-ctrl_r` are
equivalent.


## Make Commands

| Command | Description |
|---------|-------------|
| `make run key=<trigger-key>` | Run the program |
| `make install` | Install as systemd service (auto-starts on login) |
| `make uninstall` | Stop and remove the service |
| `make status` | Check service status |
| `make logs` | View live logs (journalctl) |
| `make help` | Show LapTalk help |
| `make clean` | Remove generated files |
| `make realclean` | Remove everything including models |
| `make distclean` | Remove even .cache/ |


## Architecture

```
laptalk/
├── laptalk.py      # Main daemon script (~500 lines)
├── config.yaml     # Configuration file
├── laptalk.service # systemd service template
├── Makefile        # Build system (uses 'makes' framework)
└── .cache/         # Auto installed: Python, venv, build tools
```


### How It Works

1. **Hotkey detection** - pynput monitors keyboard events for the trigger
   key/combination
2. **Audio capture** - arecord captures microphone input at 16kHz mono
3. **Speech recognition**:
   - **Vosk**: Streams audio for real-time processing
   - **Whisper**: Accumulates audio, transcribes on key release
4. **Voice translation processing** - Converts special words to punctuation
5. **Keyboard simulation** - pynput types recognized text at cursor position


### Processing Pipeline

**Vosk (Buffered Mode):**
```
Hold key → 
Stream audio → 
Detect pause → 
Type complete phrase → 
Release key
```

**Vosk (Realtime Mode):**
```
Hold key → 
Stream audio → 
Type words immediately → 
Release key
```

**Whisper (Buffered Mode):**
```
Hold key → 
Accumulate audio → 
Release key → 
Transcribe → 
Process voice translations → 
Type text
```


## Troubleshooting


### Service won't start

```bash
make logs                     # Check for errors
systemctl --user status laptalk
```


### No audio input

```bash
arecord -d 3 test.wav && aplay test.wav   # Test microphone
```


### Permission errors with keyboard

On some systems, you may need to add your user to the `input` group:
```bash
sudo usermod -a -G input $USER
# Log out and back in
```


### X11 vs Wayland

pynput works best with X11.
If using Wayland, you may need to run under XWayland or switch to X11 session.

Check your session type:
```bash
echo $XDG_SESSION_TYPE
```


### Double spaces or punctuation issues

Make sure you're using the latest version - voice translation processing has
been improved to handle Whisper's automatic punctuation.


### Engine not installed

```bash
# If you get "Vosk engine selected but not installed"
pip install vosk

# If you get "Whisper engine selected but not installed"
pip install faster-whisper numpy
```


## Tips


### Choosing an Engine

**Use Whisper if:**
- You need high accuracy
- You frequently use technical terms
- You can tolerate slight delay

**Use Vosk if:**
- You want low latency
- You prefer realtime typing
- You have limited disk space


### Choosing a Model

**Whisper:**
- Use `small.en` for best speed/accuracy balance
- Try `base.en` on slower machines
- Use `medium.en` for maximum accuracy (slower)

**Vosk:**
- Start with `vosk-model-small-en-us-0.15`
- Upgrade to `vosk-model-en-us-0.22-lgraph` for better accuracy


### Optimizing Accuracy

1. Speak clearly and at normal pace
2. Use buffered mode with pause delay (default 0.3s)
3. Add common misrecognitions to voice translations
4. Use Whisper for technical content


## License

MIT License - see [License](License) for details.


## Contributing

Contributions welcome! Please open an issue or pull request.
