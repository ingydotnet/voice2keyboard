# voice2keyboard

A Linux daemon that provides real-time voice-to-text input. Hold a trigger key to record, and words appear at your cursor as you speak. Runs as a systemd user service for always-on availability.

## Features

- **Push-to-talk input** - Hold a trigger key (default: Right Alt) to activate voice recording
- **Real-time transcription** - Words appear at your cursor as you speak, not after you stop
- **Works everywhere** - Types into any application that accepts keyboard input
- **Voice commands** - Say "period", "question", "return" etc. to insert punctuation
- **Offline processing** - Uses Vosk for local speech recognition, no internet required
- **Auto-start on login** - Runs as a systemd user service, persists across reboots
- **Configurable** - Customize trigger key, model, and voice commands via YAML config

## Requirements

### System

- Linux (tested on Ubuntu/Debian)
- X11 display server (Wayland support is limited)
- Working microphone

### Dependencies

**Manual install required:**
```bash
sudo apt install alsa-utils   # provides arecord
```

**Automatically managed by Makefile:**
- Python 3.14 (downloaded to `.cache/`)
- pynput (hotkey detection and keyboard simulation)
- vosk (streaming speech recognition)
- Vosk model (downloaded based on `config.yaml`)

## Installation

### Quick Start

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/voice2keyboard.git
cd voice2keyboard

# Install and start the service
make install
```

That's it! The service will:
1. Download Python 3.14 and create a virtual environment
2. Install required Python packages (pynput, vosk, pyyaml)
3. Download the configured Vosk speech recognition model
4. Install and enable the systemd user service
5. Start the service immediately

### Verify Installation

```bash
make status   # Check if service is running
make logs     # View live logs
```

## Usage

1. **Hold the trigger key** (default: Right Alt) in any application
2. **Speak** - words appear in real-time at your cursor position
3. **Release the key** to stop recording

### Voice Commands

Say these words to insert punctuation and special characters:

| Say | Types |
|-----|-------|
| "period" | `.` |
| "kebab" | `,` |
| "question" | `?` |
| "exclamation" | `!` |
| "colon" | `:` |
| "semicolon" | `;` |
| "hyphen" / "dash" | `-` |
| "quote" | `"` |
| "parenthesis" | `(` |
| "parentheses" | `)` |
| "return" | newline |
| "paragraph" | double newline |
| "zero" - "ten" | `0` - `10` |

## Configuration

Edit `config.yaml` to customize behavior:

```yaml
# Trigger key to hold for recording
# Options: alt_r, alt_l, ctrl_r, ctrl_l, shift_r, shift_l,
#          scroll_lock, pause, insert, delete
trigger_key: alt_r

# Vosk model for speech recognition
default_model: vosk-model-small-en-us-0.15
# default_model: vosk-model-en-us-0.22-lgraph  # larger, more accurate

# Voice commands - say the word, get the symbol
voice_commands:
  period: "."
  comma: ","
  # Add your own...
```

### Trigger Key Override

You can temporarily override the trigger key when running manually:

```bash
make run key=ctrl_l
```

### Available Vosk Models

Models are downloaded from [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models). Some options:

| Model | Size | Notes |
|-------|------|-------|
| `vosk-model-small-en-us-0.15` | ~40MB | Default, fast, good for most uses |
| `vosk-model-en-us-0.22-lgraph` | ~128MB | Better accuracy, slower startup |
| `vosk-model-en-us-0.22` | ~1.8GB | Best accuracy, requires more RAM |

To change models, update `default_model` in `config.yaml` and run `make run` or reinstall the service.

## Make Commands

| Command | Description |
|---------|-------------|
| `make install` | Install as systemd service (auto-starts on login) |
| `make uninstall` | Stop and remove the service |
| `make status` | Check service status |
| `make logs` | View live logs (journalctl) |
| `make run` | Run manually in foreground (for testing) |
| `make run key=ctrl_l` | Run with a different trigger key |
| `make clean` | Remove generated files |
| `make realclean` | Remove everything including models |

## Architecture

```
voice2keyboard/
├── voice2keyboard.py      # Main daemon script
├── config.yaml            # Configuration file
├── voice2keyboard.service # systemd service template
├── Makefile               # Build system (uses 'makes' framework)
├── CLAUDE.md              # AI assistant instructions
└── .cache/                # Auto-generated: Python, venv, build tools
```

### How It Works

1. **Hotkey detection** - pynput monitors keyboard events for the trigger key
2. **Audio capture** - arecord captures microphone input at 16kHz mono
3. **Speech recognition** - Vosk processes audio in real-time using a local model
4. **Keyboard simulation** - pynput types recognized words at the cursor position
5. **Voice commands** - Special words are converted to punctuation before typing

### Real-time Processing

Unlike batch transcription, voice2keyboard types words as they are recognized:

- **Partial results** - Words appear immediately as Vosk detects them
- **Final results** - Corrections are applied when phrases complete
- **Smart spacing** - Automatically handles spaces around words and punctuation

## Troubleshooting

### Service won't start

```bash
make logs                           # Check for errors
systemctl --user status voice2keyboard
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

pynput works best with X11. If using Wayland, you may need to run under XWayland or switch to X11 session.

Check your session type:
```bash
echo $XDG_SESSION_TYPE
```

### Model not found

If the model fails to download, manually download from [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models) and extract to the project root.

## Development

### Running from source

```bash
make run   # Uses managed Python environment
```

### Project dependencies

The Makefile uses the [makes](https://github.com/makeplus/makes) framework which:
- Downloads and manages a standalone Python installation
- Creates an isolated virtual environment
- Handles model downloading and extraction
- Generates the systemd service file with correct paths

## License

See repository for license information.

## Contributing

Contributions welcome! Please open an issue or pull request.
