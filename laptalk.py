#!/usr/bin/env python3

import os
import sys
import json
import shutil
import threading
import signal
import subprocess
import time
from datetime import datetime
import argparse
import re
import glob

import yaml
import platform
from pynput import keyboard
from pynput.keyboard import Key, Controller
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Try to import both engines - will be used based on runtime selection
try:
    from vosk import Model, KaldiRecognizer
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    import numpy as np
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

DEFAULT_TERMINAL_CLASSES = [
    "gnome-terminal",
    "ptyxis",
    "konsole",
    "kitty",
    "alacritty",
    "wezterm",
    "ghostty",
    "tilix",
    "terminator",
    "xfce4-terminal",
    "mate-terminal",
    "lxterminal",
    "qterminal",
    "xterm",
    "uxterm",
    "rxvt",
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.yaml")

SAMPLE_RATE = 16000
ENGINE = None  # Set via command-line argument

# Key name mapping (some keys like scroll_lock, pause, insert are not available on macOS)
KEY_MAP = {
    "alt_l": Key.alt_l,
    "alt_r": Key.alt_r,
    "ctrl_l": Key.ctrl_l,
    "ctrl_r": Key.ctrl_r,
    "ctl_l": Key.ctrl_l,  # Alias for ctrl_l
    "ctl_r": Key.ctrl_r,  # Alias for ctrl_r
    "shift_l": Key.shift_l,
    "shift_r": Key.shift_r,
    "delete": Key.delete,
}
# Add platform-specific keys only if available
for key_name in ["scroll_lock", "pause", "insert"]:
    if hasattr(Key, key_name):
        KEY_MAP[key_name] = getattr(Key, key_name)

def parse_key_spec(key_spec):
    """Parse a key spec like 'alt_r', 'shift_l+ctrl_r', or 'shift_l-ctrl_r' into a frozenset of Key objects."""
    key_spec = str(key_spec)
    if '+' in key_spec:
        parts = [k.strip() for k in key_spec.split('+')]
    elif '-' in key_spec:
        parts = [k.strip() for k in key_spec.split('-')]
    else:
        parts = [key_spec.strip()]

    keys = set()
    for k in parts:
        key_obj = KEY_MAP.get(k, KEY_MAP.get(k.lower()))
        if key_obj is None:
            valid_keys = sorted(name for name in KEY_MAP.keys() if not name.startswith('ctl_'))
            raise ValueError(f"Invalid key name '{k}'. Valid keys: {', '.join(valid_keys)}")
        keys.add(key_obj)
    return frozenset(keys)


def build_trigger_configs(config, cli_keys=None):
    """Build trigger configs from config keys: mapping, filtered by CLI --key args.

    Returns dict mapping frozenset[Key] -> dict of per-key settings.
    """
    defaults = {
        "mode": config.get("mode", "buffered"),
        "pause": config.get("pause", 0.3),
        "upper": config.get("upper", True),
        "output": config.get("output", "paste"),
    }

    keys_section = config.get("keys", {})
    result = {}

    if keys_section:
        for key_spec, overrides in keys_section.items():
            key_set = parse_key_spec(key_spec)
            merged = dict(defaults)
            if overrides and isinstance(overrides, dict):
                for field in ("mode", "pause", "upper", "output"):
                    if field in overrides:
                        merged[field] = overrides[field]
            result[key_set] = merged

    # Filter by CLI --key if provided
    if cli_keys:
        cli_key_sets = {parse_key_spec(k) for k in cli_keys}
        if keys_section:
            filtered = {ks: cfg for ks, cfg in result.items() if ks in cli_key_sets}
            # Add CLI keys not in config with defaults
            for ks in cli_key_sets:
                if ks not in filtered:
                    filtered[ks] = dict(defaults)
            result = filtered
        else:
            for ks in cli_key_sets:
                result[ks] = dict(defaults)

    return result


# Known Whisper models
WHISPER_MODELS = [
    "tiny", "tiny.en",
    "base", "base.en",
    "small", "small.en",
    "medium", "medium.en",
    "large", "large-v1", "large-v2", "large-v3",
    # Distil-Whisper models (5-6x faster, similar accuracy)
    "distil-small.en",
    "distil-medium.en",
    "distil-large-v2",
    "distil-large-v3",
]


def load_config(config_file):
    """Load configuration from YAML file"""
    with open(config_file) as f:
        return yaml.safe_load(f)


def init_config(config_path):
    """Initialize config and config-dependent globals from given path"""
    global config, GENERAL_TRANSLATIONS, VOICE_TRANSLATIONS, TYPING_MODE, PAUSE_DELAY
    global OUTPUT_METHOD, CLIPBOARD_PROGRAMS, CLIPBOARD_RESTORE_DELAY
    global CLIPBOARD_TERMINAL_CLASSES
    global CLIPBOARD_BACKEND, HALLUCINATIONS_EXACT, HALLUCINATIONS_SUBSTRING

    config = load_config(config_path)

    # Normalize general translation keys to lowercase for case-insensitive matching
    GENERAL_TRANSLATIONS = {k.lower(): v for k, v in config.get("translations", {}).items()}
    # Normalize voice translation keys to lowercase for case-insensitive matching
    VOICE_TRANSLATIONS = {k.lower(): v for k, v in config.get("vosk-translations", {}).items()}
    TYPING_MODE = config.get("mode", "buffered")  # buffered or realtime
    PAUSE_DELAY = config.get("pause", 0.3)
    OUTPUT_METHOD = config.get("output", "paste")
    clipboard_config = config.get("clipboard", {})
    CLIPBOARD_PROGRAMS = clipboard_config.get(
        "programs", ["xsel", "xclip", "pbcopy"])
    CLIPBOARD_RESTORE_DELAY = clipboard_config.get("restore-delay", 0.25)
    CLIPBOARD_TERMINAL_CLASSES = clipboard_config.get(
        "terminal-classes", DEFAULT_TERMINAL_CLASSES)
    CLIPBOARD_BACKEND = select_clipboard_backend(CLIPBOARD_PROGRAMS)

    # Parse hallucinations into exact and substring match lists
    _raw_hallucinations = config.get("hallucinations", [])
    HALLUCINATIONS_EXACT = []
    HALLUCINATIONS_SUBSTRING = []
    for h in _raw_hallucinations:
        if h.endswith('*'):
            # Substring match - remove asterisk, lowercase
            HALLUCINATIONS_SUBSTRING.append(h[:-1].lower())
        else:
            # Exact match - strip trailing space/period, lowercase
            HALLUCINATIONS_EXACT.append(h.rstrip(' .').lower())

    return config


def get_whisper_device_config(config):
    """Determine device and compute_type based on config and hardware."""
    whisper_config = config.get('whisper', {})
    device = whisper_config.get('device', 'auto')
    compute_type = whisper_config.get('compute_type', 'auto')

    # Auto-detect device
    if device == 'auto':
        try:
            import torch
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        except ImportError:
            device = 'cpu'

    # Auto-select compute_type based on device
    if compute_type == 'auto':
        compute_type = 'float16' if device == 'cuda' else 'int8'

    return device, compute_type


def reload_config():
    """Reload hot-reloadable settings from config file.

    Reloads: mode, pause, upper, output, clipboard, hallucinations,
             translations, vosk-translations
    Does NOT reload: model, keys (requires restart)
    """
    global config, GENERAL_TRANSLATIONS, VOICE_TRANSLATIONS, TYPING_MODE, PAUSE_DELAY
    global OUTPUT_METHOD, CLIPBOARD_PROGRAMS, CLIPBOARD_RESTORE_DELAY
    global CLIPBOARD_TERMINAL_CLASSES
    global CLIPBOARD_BACKEND, HALLUCINATIONS_EXACT, HALLUCINATIONS_SUBSTRING
    global TRIGGER_CONFIGS

    try:
        new_config = load_config(config_path)
    except Exception as e:
        log(f"Config reload failed: {e}")
        return False

    with lock:
        # Update config dict
        config = new_config

        # Reload general translations
        GENERAL_TRANSLATIONS = {
            k.lower(): v
            for k, v in config.get("translations", {}).items()
        }

        # Reload voice translations
        VOICE_TRANSLATIONS = {
            k.lower(): v
            for k, v in config.get("vosk-translations", {}).items()
        }

        # Reload typing mode
        TYPING_MODE = config.get("mode", "buffered")

        # Reload pause delay
        PAUSE_DELAY = config.get("pause", 0.3)

        # Reload output and clipboard settings
        OUTPUT_METHOD = config.get("output", "paste")
        clipboard_config = config.get("clipboard", {})
        CLIPBOARD_PROGRAMS = clipboard_config.get(
            "programs", ["xsel", "xclip", "pbcopy"])
        CLIPBOARD_RESTORE_DELAY = clipboard_config.get("restore-delay", 0.25)
        CLIPBOARD_TERMINAL_CLASSES = clipboard_config.get(
            "terminal-classes", DEFAULT_TERMINAL_CLASSES)
        CLIPBOARD_BACKEND = select_clipboard_backend(CLIPBOARD_PROGRAMS)

        # Reload hallucinations
        _raw_hallucinations = config.get("hallucinations", [])
        HALLUCINATIONS_EXACT = []
        HALLUCINATIONS_SUBSTRING = []
        for h in _raw_hallucinations:
            if h.endswith('*'):
                HALLUCINATIONS_SUBSTRING.append(h[:-1].lower())
            else:
                HALLUCINATIONS_EXACT.append(h.rstrip(' .').lower())

        # Update reloadable fields in TRIGGER_CONFIGS (mode, pause, upper)
        defaults = {
            "mode": config.get("mode", "buffered"),
            "pause": config.get("pause", 0.3),
            "upper": config.get("upper", True),
            "output": config.get("output", "paste"),
        }
        keys_section = config.get("keys", {})
        for keyset in TRIGGER_CONFIGS:
            merged = dict(defaults)
            # Re-apply per-key overrides from new config
            if keys_section:
                for key_spec, overrides in keys_section.items():
                    try:
                        if parse_key_spec(key_spec) == keyset and overrides and isinstance(overrides, dict):
                            for field in ("mode", "pause", "upper", "output"):
                                if field in overrides:
                                    merged[field] = overrides[field]
                    except ValueError:
                        pass
            TRIGGER_CONFIGS[keyset] = merged

    backend_name = CLIPBOARD_BACKEND.name if CLIPBOARD_BACKEND else "none"
    log(f"Config reloaded: mode={TYPING_MODE}, pause={PAUSE_DELAY}, "
        f"output={OUTPUT_METHOD}, clipboard={backend_name}, "
        f"hallucinations={len(HALLUCINATIONS_EXACT) + len(HALLUCINATIONS_SUBSTRING)}, "
        f"general_translations={len(GENERAL_TRANSLATIONS)}, "
        f"vosk_translations={len(VOICE_TRANSLATIONS)}")
    return True


class ConfigFileHandler(FileSystemEventHandler):
    """Watch for config file changes and trigger reload."""

    def __init__(self, config_filename):
        self.config_filename = config_filename
        self._last_reload = 0
        self._debounce_seconds = 0.5  # Prevent rapid reloads

    def on_modified(self, event):
        # Only react to our config file
        if event.is_directory:
            return
        if os.path.basename(event.src_path) != self.config_filename:
            return

        # Debounce - editors may trigger multiple events
        now = time.time()
        if now - self._last_reload < self._debounce_seconds:
            return
        self._last_reload = now

        log(f"Config file changed, reloading...")
        reload_config()


def start_config_watcher():
    """Start the config file watcher in a daemon thread.

    Returns the Observer instance (for potential cleanup).
    """
    if not config_path:
        log("Warning: config_path not set, skipping config watcher")
        return None

    config_dir = os.path.dirname(os.path.abspath(config_path))
    config_filename = os.path.basename(config_path)

    handler = ConfigFileHandler(config_filename)
    observer = Observer()
    observer.schedule(handler, config_dir, recursive=False)
    observer.daemon = True  # Die with main thread
    observer.start()

    log(f"Config watcher started for: {config_path}")
    return observer


# Config-dependent globals (initialized in main after --config is parsed)
config = None
GENERAL_TRANSLATIONS = {}
VOICE_TRANSLATIONS = {}
TYPING_MODE = "buffered"
PAUSE_DELAY = 0.3
OUTPUT_METHOD = "paste"
CLIPBOARD_PROGRAMS = ["xsel", "xclip", "pbcopy"]
CLIPBOARD_RESTORE_DELAY = 0.25
CLIPBOARD_TERMINAL_CLASSES = DEFAULT_TERMINAL_CLASSES
CLIPBOARD_BACKEND = None
HALLUCINATIONS_EXACT = []
HALLUCINATIONS_SUBSTRING = []

# Global state
ENGINE = None  # Current speech engine (vosk or whisper)
key_release_time = None  # Track when user released the key
is_recording = False
has_typed_anything = False
capitalize_next = True  # Capitalize first word and after sentence-ending punctuation
last_char_typed = ""  # Track last character to prevent double spaces
currently_pressed_keys = set()  # Track pressed keys for combination support
trigger_key_pressed = None  # Track which key triggered the current recording
TRIGGER_CONFIGS = {}  # frozenset[Key] -> per-trigger settings
active_trigger = None  # Which keyset is currently recording
lock = threading.Lock()
kb_controller = Controller()
model = None  # Vosk model
whisper_model = None  # Whisper model
recording_thread = None
recording_process = None  # Audio recording subprocess (arecord/rec)
stop_recording_event = threading.Event()
log_file = None  # Log file handle (None = no logging)
config_path = None  # Set in main(), used by config watcher
config_observer = None  # Config file watcher observer


def log(message):
    """Write message to log file if logging is enabled"""
    if log_file:
        print(message, file=log_file, flush=True)


def is_hallucination_text(text):
    """Check if text matches any known hallucination pattern.

    - Exact matches: text must match after stripping trailing space/period
    - Substring matches (entries with *): phrase must appear anywhere in text
    - All matching is case insensitive
    """
    normalized = text.rstrip(' .').lower()

    # Hardcoded: ignore lone periods (possibly with trailing space)
    if not normalized:
        return True

    # Ignore text starting with a period (user intent to cancel)
    if normalized.startswith('.'):
        return True

    # Ignore single letters
    if len(normalized) == 1 and normalized.isalpha():
        return True

    # Check exact matches
    if normalized in HALLUCINATIONS_EXACT:
        return True

    # Check substring matches
    text_lower = text.lower()
    for phrase in HALLUCINATIONS_SUBSTRING:
        if phrase in text_lower:
            return True

    return False


def get_audio_record_cmd():
    """Get the platform-appropriate audio recording command."""
    if IS_MACOS:
        # macOS: use sox's rec command
        return ["rec", "-q", "-t", "raw", "-b", "16", "-e", "signed", "-r", str(SAMPLE_RATE), "-c", "1", "-"]
    else:
        # Linux: use arecord
        return ["arecord", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", "-t", "raw", "-q"]


def check_dependencies():
    """Check if required dependencies are installed"""
    missing = []

    if IS_LINUX and shutil.which("arecord") is None:
        missing.append("arecord (install with: sudo apt install alsa-utils)")
    elif IS_MACOS and shutil.which("rec") is None:
        missing.append("sox (install with: brew install sox)")

    if missing:
        print("Missing dependencies:", file=sys.stderr)
        for dep in missing:
            print(f"  - {dep}", file=sys.stderr)
        return False

    return True


class ClipboardBackend:
    """Read and write plain text using a platform clipboard command."""

    def __init__(self, name, required_programs, read_command, write_command,
                 clear_command=None):
        self.name = name
        self.required_programs = required_programs
        self.read_command = read_command
        self.write_command = write_command
        self.clear_command = clear_command

    def available(self):
        return all(shutil.which(program) for program in self.required_programs)

    def _run(self, command, input_data=None):
        try:
            result = subprocess.run(
                command,
                input=input_data,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result

    def read(self):
        result = self._run(self.read_command)
        if result is None or result.returncode != 0:
            return None
        return result.stdout

    def write(self, data):
        result = self._run(self.write_command, input_data=data)
        return result is not None and result.returncode == 0

    def clear(self):
        if self.clear_command:
            result = self._run(self.clear_command)
            return result is not None and result.returncode == 0
        return self.write(b"")


def clipboard_backends():
    """Return supported clipboard command adapters by config name."""
    backends = {}
    if IS_LINUX:
        backends.update({
            "xsel": ClipboardBackend(
                "xsel",
                ["xsel"],
                ["xsel", "--clipboard", "--output"],
                ["xsel", "--clipboard", "--input"],
                ["xsel", "--clipboard", "--clear"],
            ),
            "xclip": ClipboardBackend(
                "xclip",
                ["xclip"],
                ["xclip", "-selection", "clipboard", "-out"],
                ["xclip", "-selection", "clipboard", "-in"],
            ),
        })
    if IS_MACOS:
        backends["pbcopy"] = ClipboardBackend(
            "pbcopy",
            ["pbcopy", "pbpaste"],
            ["pbpaste"],
            ["pbcopy"],
        )
    return backends


def select_clipboard_backend(programs):
    """Select the first installed clipboard backend in configured order."""
    available_backends = clipboard_backends()
    for program in programs:
        backend = available_backends.get(program)
        if backend and backend.available():
            return backend
    return None


def clipboard_is_empty():
    """Return whether the platform clipboard has no owner/content, or None."""
    if IS_LINUX:
        try:
            from Xlib import X, display
            x_display = display.Display()
            try:
                clipboard_atom = x_display.intern_atom("CLIPBOARD")
                return x_display.get_selection_owner(clipboard_atom) == X.NONE
            finally:
                x_display.close()
        except Exception:
            return None

    if IS_MACOS and shutil.which("osascript"):
        try:
            result = subprocess.run(
                ["osascript", "-e", "clipboard info"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        info = result.stdout.strip().lower()
        return not info or info == b"missing value"

    return None


def read_clipboard_snapshot(backend):
    """Return ('text', bytes), ('empty', b''), or ('unsupported', None)."""
    data = backend.read()
    if data is not None:
        return "text", data
    if clipboard_is_empty() is True:
        return "empty", b""
    return "unsupported", None


def active_window_classes():
    """Return the active X11 window's WM_CLASS values, or an empty tuple."""
    if not IS_LINUX:
        return ()
    try:
        from Xlib import X, display
        x_display = display.Display()
        try:
            root = x_display.screen().root
            active_atom = x_display.intern_atom("_NET_ACTIVE_WINDOW")
            active = root.get_full_property(active_atom, X.AnyPropertyType)
            if active is None or not active.value or active.value[0] == X.NONE:
                return ()
            window = x_display.create_resource_object("window", active.value[0])
            return tuple(window.get_wm_class() or ())
        finally:
            x_display.close()
    except Exception:
        return ()


def active_window_is_terminal():
    """Return whether the focused X11 window matches a terminal WM_CLASS."""
    window_classes = [value.lower() for value in active_window_classes()]
    markers = [value.lower() for value in CLIPBOARD_TERMINAL_CLASSES]
    return any(
        marker in window_class
        for window_class in window_classes
        for marker in markers
    )


def press_paste_shortcut():
    """Paste into the focused application using the platform shortcut."""
    modifier = Key.cmd if IS_MACOS else Key.ctrl
    kb_controller.press(modifier)
    try:
        kb_controller.press("v")
        kb_controller.release("v")
    finally:
        kb_controller.release(modifier)


def paste_text(text):
    """Paste text and restore the previous clipboard. Return True on paste."""
    backend = CLIPBOARD_BACKEND
    if backend is None:
        log("Clipboard paste unavailable: no configured backend found; using typing")
        return False

    snapshot_kind, snapshot_data = read_clipboard_snapshot(backend)
    if snapshot_kind == "unsupported":
        log("Clipboard paste unavailable: existing clipboard is not plain text; using typing")
        return False

    if not backend.write(text.encode("utf-8")):
        log(f"Clipboard paste failed using {backend.name}; using typing")
        return False

    try:
        press_paste_shortcut()
    except Exception as error:
        if snapshot_kind == "empty":
            backend.clear()
        else:
            backend.write(snapshot_data)
        log(f"Paste shortcut failed ({error}); using typing")
        return False

    time.sleep(max(0, CLIPBOARD_RESTORE_DELAY))
    if snapshot_kind == "empty":
        restored = backend.clear()
    else:
        restored = backend.write(snapshot_data)
    if not restored:
        log("Clipboard restore failed; dictated text remains on the clipboard")
    return True


def emit_text(text, output_method):
    """Emit rendered text using paste, with synthetic typing as fallback."""
    if not text:
        return
    if output_method == "paste" and active_window_is_terminal():
        log("Terminal window detected; using typing output")
        kb_controller.type(text)
        return
    if output_method == "paste" and paste_text(text):
        return
    if output_method not in ("paste", "type"):
        log(f"Unknown output method '{output_method}'; using typing")
    kb_controller.type(text)


def get_available_vosk_models():
    """Get list of downloaded Vosk models in the script directory"""
    model_dirs = glob.glob(os.path.join(SCRIPT_DIR, "vosk-model-*"))
    return [os.path.basename(d) for d in model_dirs if os.path.isdir(d)]


def infer_engine(model_name):
    """
    Infer the speech engine from the model name.
    - Models starting with 'vosk-' are Vosk models
    - All other models are assumed to be Whisper models
    """
    if model_name.startswith("vosk-"):
        return "vosk"
    else:
        return "whisper"


def resolve_model_name(pattern, engine):
    """
    Resolve a model name pattern to a full model name.
    Pattern can be:
    - Exact match: returns as-is if it matches exactly
    - Regex pattern: matches against available models

    For Vosk: matches against downloaded models in the directory
    For Whisper: matches against known Whisper model names
    """
    if engine == "vosk":
        available = get_available_vosk_models()
    elif engine == "whisper":
        available = WHISPER_MODELS
    else:
        return pattern

    # First try exact match
    if pattern in available:
        return pattern

    # Try regex match
    try:
        regex = re.compile(pattern, re.IGNORECASE)
        matches = [m for m in available if regex.search(m)]

        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            log(f"Pattern '{pattern}' matches multiple models:")
            for m in matches:
                log(f"  - {m}")
            log(f"Using first match: {matches[0]}")
            return matches[0]
        else:
            print(f"Pattern '{pattern}' does not match any available models.", file=sys.stderr)
            if engine == "vosk":
                print(f"Available Vosk models: {', '.join(available) if available else 'none (download first)'}", file=sys.stderr)
            else:
                print(f"Available Whisper models: {', '.join(available)}", file=sys.stderr)
            return pattern
    except re.error as e:
        print(f"Invalid regex pattern '{pattern}': {e}", file=sys.stderr)
        return pattern


def process_translations(words, translations_dict):
    """Convert translation words to their replacement values"""
    result = []
    i = 0
    while i < len(words):
        matched = False
        # Try matching longest phrases first (2 words, then 1 word)
        for length in [2, 1]:
            if i + length <= len(words):
                phrase = " ".join(words[i:i+length]).lower()
                if phrase in translations_dict:
                    translation_output = translations_dict[phrase]
                    next_idx = i + length

                    # If translation produces punctuation and next token is any punctuation
                    if translation_output in ".,?!:;" and next_idx < len(words) and words[next_idx] in ".,?!:;":
                        # Whisper added punctuation (might be different), skip it and use translation output
                        if not (result and result[-1] == translation_output):
                            result.append(translation_output)
                        i = next_idx + 1  # Skip both translation word and Whisper's punctuation
                    elif next_idx < len(words) and words[next_idx] == translation_output:
                        # Whisper added the exact same punctuation, skip translation word
                        # Next iteration will pick up the punctuation from Whisper
                        i += length
                    else:
                        # No following punctuation, add translation output
                        if not (translation_output in ".,?!:;" and result and result[-1] == translation_output):
                            result.append(translation_output)
                        i += length
                    matched = True
                    break
        if not matched:
            # Skip if this is duplicate consecutive punctuation
            if words[i] in ".,?!:;" and result and result[-1] == words[i]:
                i += 1
            else:
                result.append(words[i])
                i += 1
    return result


def render_text(words, trailing_space=False):
    """Render words and update cross-chunk formatting state."""
    global has_typed_anything, capitalize_next, last_char_typed

    if not words:
        return words, words, ""

    # Apply universal translations for all engines
    processed = process_translations(words, GENERAL_TRANSLATIONS)
    # Also apply vosk-specific translations for Vosk engine
    if ENGINE == "vosk":
        processed = process_translations(processed, VOICE_TRANSLATIONS)

    chunks = []
    for word in processed:
        is_punctuation = word in ".,?!:;"
        is_sentence_end = word in ".?!"

        if is_punctuation:
            # Punctuation: no space before, space after
            chunks.append(word + " ")
            last_char_typed = " "
            has_typed_anything = False  # Next word shouldn't have leading space
            if is_sentence_end:
                capitalize_next = True
        else:
            # Capitalize "I" pronoun
            if word.lower() == "i":
                word = "I"
            # Capitalize first letter if needed
            elif capitalize_next and word:
                word = word[0].upper() + word[1:]

            if capitalize_next:
                capitalize_next = False

            if has_typed_anything:
                # Regular word: space before
                chunks.append(" " + word)
                last_char_typed = word[-1] if word else ""
            else:
                # First word (or after punctuation): no space before
                chunks.append(word)
                last_char_typed = word[-1] if word else ""
                has_typed_anything = True

    if trailing_space and processed and last_char_typed != " ":
        chunks.append(" ")
        last_char_typed = " "

    return words, processed, "".join(chunks)


def output_words(words, session_config, trailing_space=False):
    """Render and emit words. Returns (original_words, processed_words)."""
    original, processed, text = render_text(words, trailing_space=trailing_space)
    emit_text(text, session_config.get("output", OUTPUT_METHOD))
    return original, processed


def stream_transcribe(session_config):
    """Record and transcribe audio, emitting results in the configured mode."""
    global model, recording_process

    typing_mode = session_config.get("mode", TYPING_MODE)
    pause_delay = session_config.get("pause", PAUSE_DELAY)
    output_method = session_config.get("output", OUTPUT_METHOD)
    effective_config = session_config
    if typing_mode == "realtime" and output_method == "paste":
        # Repeated clipboard swaps are not realtime-safe, and the trigger
        # modifier may still be held while partial results are emitted.
        effective_config = dict(session_config)
        effective_config["output"] = "type"

    rec = KaldiRecognizer(model, SAMPLE_RATE)

    # Start audio recording process
    process = subprocess.Popen(get_audio_record_cmd(), stdout=subprocess.PIPE)
    recording_process = process

    last_partial_words = []
    buffered_paste_words = []

    try:
        while not stop_recording_event.is_set():
            data = process.stdout.read(4000)
            if len(data) == 0:
                break

            if rec.AcceptWaveform(data):
                # Final result - Vosk has detected a phrase boundary (pause)
                result = json.loads(rec.Result())
                text = result.get("text", "")
                if text:
                    if typing_mode == "buffered":
                        final_words = text.split()
                        if output_method == "paste":
                            # Paste once after release so the held trigger key
                            # cannot modify the paste shortcut.
                            buffered_paste_words.extend(final_words)
                        else:
                            if pause_delay > 0:
                                time.sleep(pause_delay)
                            output_words(final_words, effective_config)
                    else:
                        # Realtime mode: type any new words not already typed
                        final_words = text.split()
                        new_words = final_words[len(last_partial_words):]
                        if new_words:
                            output_words(new_words, effective_config)
                    last_partial_words = []
            else:
                # Partial result - intermediate prediction
                if typing_mode == "realtime":
                    # Realtime mode: type new words as they appear
                    partial = json.loads(rec.PartialResult())
                    partial_text = partial.get("partial", "")
                    if partial_text:
                        partial_words = partial_text.split()
                        new_words = partial_words[len(last_partial_words):]
                        if new_words:
                            output_words(new_words, effective_config)
                            last_partial_words = partial_words
                # Buffered mode: ignore partials, wait for final results

        # Get any remaining audio as final result
        result = json.loads(rec.FinalResult())
        text = result.get("text", "")
        if text:
            final_words = text.split()
            if typing_mode == "buffered":
                if output_method == "paste":
                    buffered_paste_words.extend(final_words)
                else:
                    output_words(final_words, effective_config)
            else:
                # Realtime mode: only type new words
                new_words = final_words[len(last_partial_words):]
                if new_words:
                    output_words(new_words, effective_config)

        if buffered_paste_words:
            output_words(buffered_paste_words, effective_config)

    finally:
        process.terminate()
        process.wait()
        recording_process = None


def stream_transcribe_whisper(session_config):
    """Record and transcribe audio using faster-whisper with VAD"""
    global whisper_model, last_char_typed, recording_process

    pipeline_start = time.perf_counter()

    # Start audio recording process
    process = subprocess.Popen(get_audio_record_cmd(), stdout=subprocess.PIPE)
    recording_process = process

    audio_chunks = []

    try:
        while not stop_recording_event.is_set():
            data = process.stdout.read(4000)
            if len(data) == 0:
                break

            # Convert S16_LE to float32 numpy array
            audio_chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            audio_chunks.append(audio_chunk)

        recording_done = time.perf_counter()
        timestamp = datetime.now()

        # Always create a log entry, even if no input detected
        text = None
        is_hallucination = False
        typed_tokens = None
        original_tokens = None

        # Transcribe accumulated audio when key is released
        if audio_chunks:
            before_concat = time.perf_counter()
            audio_data = np.concatenate(audio_chunks)
            after_concat = time.perf_counter()

            # Skip if recording is too short (less than 0.5 seconds)
            if len(audio_data) >= SAMPLE_RATE * 0.5:
                # Time the transcription
                before_transcribe = time.perf_counter()
                start_time = time.perf_counter()

                # Use optimized settings for faster transcription
                whisper_config = config.get('whisper', {})
                segments, _ = whisper_model.transcribe(
                    audio_data,
                    language="en",
                    beam_size=whisper_config.get('beam_size', 1),
                    temperature=0.0,                    # Disable fallback cascade
                    condition_on_previous_text=False,   # Not needed for short recordings
                    vad_filter=whisper_config.get('vad_filter', True),
                    # compression_ratio_threshold uses default 2.4 to prevent hallucinations
                )

                # Force evaluation of segments (generator) and collect text
                # This is where the actual transcription work happens!
                text = " ".join(segment.text.strip() for segment in segments)

                after_transcribe = time.perf_counter()
                elapsed_ms = (after_transcribe - start_time) * 1000

                if text:
                    # Clean up Whisper quirks
                    before_cleanup = time.perf_counter()
                    text = text.replace(",,", ",")  # Multiple commas to single comma
                    if text.endswith("..."):
                        text = text[:-3]  # Remove trailing ellipsis
                    after_cleanup = time.perf_counter()

                    # Split words and separate punctuation for voice translation matching
                    before_tokenize = time.perf_counter()
                    tokens = []
                    for word in text.split():
                        # Separate trailing punctuation from word
                        stripped = word.rstrip(".,?!:;")
                        trailing = word[len(stripped):]
                        if stripped:
                            tokens.append(stripped)
                        if trailing:
                            # Add each punctuation character separately
                            tokens.extend(list(trailing))
                    after_tokenize = time.perf_counter()

                    # Check for hallucination - skip typing but still log
                    is_hallucination = is_hallucination_text(text)

                    if tokens:
                        typing_start = time.perf_counter()
                        if not is_hallucination:
                            original_tokens, typed_tokens = output_words(
                                tokens, session_config, trailing_space=True)
                        typing_done = time.perf_counter()
                    else:
                        typing_start = after_tokenize
                        typing_done = after_tokenize
                else:
                    # No text from transcription
                    before_cleanup = after_transcribe
                    after_cleanup = after_transcribe
                    before_tokenize = after_transcribe
                    after_tokenize = after_transcribe
                    typing_start = after_transcribe
                    typing_done = after_transcribe
            else:
                # Recording too short
                before_concat = recording_done
                after_concat = recording_done
                before_transcribe = recording_done
                after_transcribe = recording_done
                before_cleanup = recording_done
                after_cleanup = recording_done
                before_tokenize = recording_done
                after_tokenize = recording_done
                typing_start = recording_done
                typing_done = recording_done
                elapsed_ms = 0
        else:
            # No audio chunks
            before_concat = recording_done
            after_concat = recording_done
            before_transcribe = recording_done
            after_transcribe = recording_done
            before_cleanup = recording_done
            after_cleanup = recording_done
            before_tokenize = recording_done
            after_tokenize = recording_done
            typing_start = recording_done
            typing_done = recording_done
            elapsed_ms = 0

        # Always log an entry
        # Calculate timing breakdown
        user_latency_ms = (typing_done - key_release_time) * 1000 if key_release_time else 0
        wait_stop_ms = (recording_done - key_release_time) * 1000 if key_release_time else 0
        gap1_ms = (before_concat - recording_done) * 1000
        concat_ms = (after_concat - before_concat) * 1000
        gap2_ms = (before_transcribe - after_concat) * 1000
        transcribe_ms = elapsed_ms
        cleanup_ms = (after_cleanup - before_cleanup) * 1000
        tokenize_ms = (after_tokenize - before_tokenize) * 1000
        gap3_ms = (typing_start - after_tokenize) * 1000
        typing_ms = (typing_done - typing_start) * 1000

        # Pause before logging to ensure synthetic typing animation is complete.
        # Clipboard output already waited for the target and restored the clipboard.
        if typing_ms > 0 and session_config.get("output", OUTPUT_METHOD) == "type":
            time.sleep(typing_ms / 1000.0)

        # Prepare log text
        if text:
            # Truncate text for logging if needed
            if len(text) > 72:
                extra_chars = len(text) - 72
                log_text = f"{text[:72]}… +{extra_chars}"
            else:
                log_text = text
            log_text = log_text + (' [HALLUCINATION]' if is_hallucination else '')
        else:
            log_text = "<no input detected>"

        # Log: timestamp | text | breakdown
        log("")  # Blank line before entry
        log(f"time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        log(f"key:  {trigger_key_pressed}")
        log(f"text: {log_text}")
        if typed_tokens and original_tokens and original_tokens != typed_tokens:
            log(f"Text: {' '.join(typed_tokens)}")
        log(f"info:")
        log(f"  wait_stop: {wait_stop_ms:.0f}ms")
        log(f"  concat: {concat_ms:.0f}ms")
        log(f"  transcribe: {transcribe_ms:.0f}ms")
        log(f"  cleanup: {cleanup_ms:.0f}ms")
        log(f"  tokenize: {tokenize_ms:.0f}ms")
        log(f"  output: {typing_ms:.0f}ms")
        log(f"  TOTAL: {user_latency_ms:.0f}ms")

    finally:
        process.terminate()
        process.wait()
        recording_process = None


def on_key_press(key):
    """Handle key press events"""
    global is_recording, recording_thread, has_typed_anything, capitalize_next
    global last_char_typed, currently_pressed_keys, trigger_key_pressed, active_trigger

    # Track pressed keys for combination detection
    currently_pressed_keys.add(key)

    # Check each trigger (longest match first) to see if all its keys are pressed
    for trigger_keyset, trigger_config in sorted(TRIGGER_CONFIGS.items(), key=lambda x: len(x[0]), reverse=True):
        if trigger_keyset.issubset(currently_pressed_keys):
            with lock:
                if not is_recording:
                    is_recording = True
                    has_typed_anything = False
                    capitalize_next = trigger_config.get("upper", True)
                    last_char_typed = ""  # Reset for new recording
                    trigger_key_pressed = key  # Remember which key triggered this recording
                    active_trigger = trigger_keyset
                    session_config = dict(trigger_config)  # Snapshot for this session
                    stop_recording_event.clear()

                    # Select transcription function based on engine
                    transcribe_fn = stream_transcribe_whisper if ENGINE == "whisper" else stream_transcribe
                    recording_thread = threading.Thread(target=transcribe_fn, args=(session_config,), daemon=True)
                    recording_thread.start()
            break  # Only activate the first matching trigger


def on_key_release(key):
    """Handle key release events"""
    global is_recording, recording_thread, currently_pressed_keys, key_release_time, active_trigger

    # Remove from pressed keys
    currently_pressed_keys.discard(key)

    # If we were recording and any key from the active trigger was released, stop recording
    if is_recording and active_trigger and key in active_trigger:
        with lock:
            if is_recording:
                key_release_time = time.perf_counter()  # Track when user released key
                is_recording = False
                stop_recording_event.set()
                if recording_thread:
                    recording_thread.join(timeout=1.0)
                    recording_thread = None
                active_trigger = None


def main():
    global model, whisper_model, TRIGGER_CONFIGS, TYPING_MODE, PAUSE_DELAY, ENGINE
    global config_path, config_observer

    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        prog="laptalk.py",
        usage="%(prog)s [--key KEY ...] [--log LOG] [--config FILE] [--model MODEL]",
        description="LapTalk: Hold a key to record, text appears as you speak",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --key alt_r
  %(prog)s --key shift_r --key alt_r
  %(prog)s --key shift_l+ctrl_r --model vosk-model-small-en-us-0.15
  %(prog)s --key ctrl_l --mode buffered
  %(prog)s --key alt_r --model medium.en

Available keys: """ + ", ".join(sorted(k for k in KEY_MAP.keys() if not k.startswith('ctl_'))) + """

Key combinations: Use '+' to combine keys (e.g., shift_l+ctrl_l, shift_l+alt_r)

Select a model and other options in config.yaml or use --model=... etc.
"""
    )

    parser.add_argument("--key", action="append", dest="keys", default=None,
                        help="Trigger key or combination (repeatable, e.g., --key alt_r --key shift_r)")
    parser.add_argument("--log",
                        help="Log file path (default: no logging). Use /dev/stdout for console output")
    parser.add_argument("--config", metavar="FILE",
                        help="Config file path (default: config.yaml in script directory)")

    parser.add_argument("--model",
                        help="Model name (default: from config, engine auto-inferred)")
    parser.add_argument("--mode", dest="typing_mode", choices=["buffered", "realtime"],
                        help="Typing mode (default: from config)")
    parser.add_argument("--pause", type=float, metavar="SECONDS",
                        help="Pause delay in seconds for buffered mode (default: from config)")

    args = parser.parse_args()

    # Load config (before anything that needs it)
    config_path = args.config if args.config else DEFAULT_CONFIG_FILE
    init_config(config_path)

    # Set up logging
    global log_file
    log_path = args.log if args.log else config.get("log")
    if log_path:
        log_file = open(log_path, 'a', buffering=1)  # Line buffered, append mode
    else:
        log_file = None

    # Get model name from command line or config
    if args.model:
        model_name = args.model
    else:
        # Get model from config
        model_name = config.get("model")
        if not model_name:
            print("Error: No model specified", file=sys.stderr)
            print("Either set 'model' in config.yaml or use --model on command line", file=sys.stderr)
            return 1

    # Infer engine from model name
    engine = infer_engine(model_name)
    ENGINE = engine  # Update global so on_key_press uses the right engine

    # Resolve model name (support regex matching)
    model_name = resolve_model_name(model_name, engine)

    # Build trigger key configurations
    try:
        TRIGGER_CONFIGS = build_trigger_configs(config, cli_keys=args.keys)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not TRIGGER_CONFIGS:
        print("Error: No trigger keys defined.", file=sys.stderr)
        print("Either add a 'keys:' section to config.yaml or use --key on command line.", file=sys.stderr)
        return 1
    if args.typing_mode:
        TYPING_MODE = args.typing_mode
    if args.pause is not None:
        PAUSE_DELAY = args.pause

    if not check_dependencies():
        return 1

    # Check if requested engine is available
    if engine == "vosk" and not VOSK_AVAILABLE:
        print(f"Error: Vosk engine selected but not installed", file=sys.stderr)
        print(f"Run: pip install vosk", file=sys.stderr)
        return 1
    elif engine == "whisper" and not WHISPER_AVAILABLE:
        print(f"Error: Whisper engine selected but not installed", file=sys.stderr)
        print(f"Run: pip install faster-whisper numpy", file=sys.stderr)
        return 1

    if engine == "vosk":
        model_path = os.path.join(SCRIPT_DIR, model_name)

        if not os.path.exists(model_path):
            print(f"Vosk model not found at {model_path}", file=sys.stderr)
            return 1

        log(f"Loading Vosk model ({model_name})...")
        model = Model(model_path)

    elif engine == "whisper":
        log(f"Loading Whisper model ({model_name})...")
        device, compute_type = get_whisper_device_config(config)
        whisper_config = config.get('whisper', {})

        whisper_model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            cpu_threads=4,  # Prevents thread contention
        )
        log(f"Whisper model loaded")
        log(f"Whisper config: device={device}, compute_type={compute_type}, "
            f"beam_size={whisper_config.get('beam_size', 1)}, "
            f"vad_filter={whisper_config.get('vad_filter', True)}")

        # Warn if realtime mode is set with Whisper
        if TYPING_MODE == "realtime":
            log("Warning: realtime mode not supported with Whisper engine, using buffered mode")

    else:
        print(f"Unknown engine: {engine}", file=sys.stderr)
        return 1

    # Format trigger keys display
    def format_keyset(keyset):
        if len(keyset) > 1:
            return "+".join(str(k) for k in keyset)
        return str(list(keyset)[0])

    log("laptalk running")
    log(f"Engine: {engine}")
    backend_name = CLIPBOARD_BACKEND.name if CLIPBOARD_BACKEND else "none"
    log(f"Output: {OUTPUT_METHOD}" +
        (f" (clipboard: {backend_name})" if OUTPUT_METHOD == "paste" else ""))
    for keyset, kcfg in TRIGGER_CONFIGS.items():
        extras = []
        if kcfg.get("mode") != TYPING_MODE:
            extras.append(f"mode={kcfg['mode']}")
        if kcfg.get("pause") != PAUSE_DELAY:
            extras.append(f"pause={kcfg['pause']}")
        if not kcfg.get("upper", True):
            extras.append("upper=false")
        if kcfg.get("output") != OUTPUT_METHOD:
            extras.append(f"output={kcfg['output']}")
        suffix = f" ({', '.join(extras)})" if extras else ""
        log(f"Hold {format_keyset(keyset)} to record{suffix}")
        if (engine == "vosk" and kcfg.get("mode") == "realtime" and
                kcfg.get("output") == "paste"):
            log("  Realtime Vosk uses type output while the trigger is held")
    log(f"Mode: {TYPING_MODE}" + (f" (pause_delay: {PAUSE_DELAY}s)" if TYPING_MODE == "buffered" and PAUSE_DELAY > 0 else ""))
    log("Press Ctrl+C to exit")

    def signal_handler(sig, frame):
        log("\nExiting...")
        # Stop recording and clean up subprocess
        stop_recording_event.set()
        if recording_process:
            recording_process.terminate()
            recording_process.wait()
        if recording_thread:
            recording_thread.join(timeout=2.0)
        if config_observer:
            config_observer.stop()
        if log_file:
            log_file.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Start config file watcher
    config_observer = start_config_watcher()

    with keyboard.Listener(on_press=on_key_press, on_release=on_key_release) as listener:
        listener.join()

    return 0


if __name__ == "__main__":
    sys.exit(main())
