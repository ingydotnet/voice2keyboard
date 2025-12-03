#!/usr/bin/env python3

import os
import sys
import json
import shutil
import threading
import signal
import subprocess
import time

import yaml
from vosk import Model, KaldiRecognizer
from pynput import keyboard
from pynput.keyboard import Key, Controller

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.yaml")
SAMPLE_RATE = 16000

# Key name mapping
KEY_MAP = {
    "alt_r": Key.alt_r,
    "alt_l": Key.alt_l,
    "ctl_r": Key.ctrl_r,
    "ctl_l": Key.ctrl_l,
    "shift_r": Key.shift_r,
    "shift_l": Key.shift_l,
    "scroll_lock": Key.scroll_lock,
    "pause": Key.pause,
    "insert": Key.insert,
    "delete": Key.delete,
}


def load_config():
    """Load configuration from YAML file"""
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


config = load_config()
trigger_key_name = os.environ.get("TRIGGER_KEY") or config.get("trigger_key", "alt_r")
TRIGGER_KEY = KEY_MAP.get(trigger_key_name, Key.alt_r)
DEFAULT_MODEL = config.get("default_model", "vosk-model-small-en-us-0.15")
VOICE_COMMANDS = config.get("voice_commands", {})
TYPING_MODE = config.get("typing_mode", "buffered")  # buffered or realtime
PAUSE_DELAY = config.get("pause_delay", 0.3)

# Global state
is_recording = False
has_typed_anything = False
lock = threading.Lock()
kb_controller = Controller()
model = None
recording_thread = None
stop_recording_event = threading.Event()


def check_dependencies():
    """Check if required dependencies are installed"""
    missing = []

    if shutil.which("arecord") is None:
        missing.append("arecord (install with: sudo apt install alsa-utils)")

    if missing:
        print("Missing dependencies:")
        for dep in missing:
            print(f"  - {dep}")
        return False

    return True


def process_voice_commands(words):
    """Convert voice command words to punctuation and symbols"""
    result = []
    for word in words:
        if word in VOICE_COMMANDS:
            result.append(VOICE_COMMANDS[word])
        else:
            result.append(word)
    return result


def type_text(words):
    """Type words at current cursor position"""
    global has_typed_anything

    if not words:
        return

    processed = process_voice_commands(words)

    for word in processed:
        is_punctuation = word in ".,?!:;"

        if is_punctuation:
            # Punctuation: no space before, space after
            kb_controller.type(word + " ")
            has_typed_anything = False  # Next word shouldn't have leading space
        elif has_typed_anything:
            # Regular word: space before
            kb_controller.type(" " + word)
        else:
            # First word (or after punctuation): no space before
            kb_controller.type(word)
            has_typed_anything = True


def stream_transcribe():
    """Record and transcribe audio, typing based on configured mode"""
    global model

    rec = KaldiRecognizer(model, SAMPLE_RATE)

    # Start arecord process
    process = subprocess.Popen([
        "arecord",
        "-f", "S16_LE",
        "-r", str(SAMPLE_RATE),
        "-c", "1",
        "-t", "raw",
        "-q"
    ], stdout=subprocess.PIPE)

    last_partial_words = []

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
                    if TYPING_MODE == "buffered":
                        # Buffered mode: type the complete final result with optional delay
                        if PAUSE_DELAY > 0:
                            time.sleep(PAUSE_DELAY)
                        final_words = text.split()
                        type_text(final_words)
                    else:
                        # Realtime mode: type any new words not already typed
                        final_words = text.split()
                        new_words = final_words[len(last_partial_words):]
                        if new_words:
                            type_text(new_words)
                    last_partial_words = []
            else:
                # Partial result - intermediate prediction
                if TYPING_MODE == "realtime":
                    # Realtime mode: type new words as they appear
                    partial = json.loads(rec.PartialResult())
                    partial_text = partial.get("partial", "")
                    if partial_text:
                        partial_words = partial_text.split()
                        new_words = partial_words[len(last_partial_words):]
                        if new_words:
                            type_text(new_words)
                            last_partial_words = partial_words
                # Buffered mode: ignore partials, wait for final results

        # Get any remaining audio as final result
        result = json.loads(rec.FinalResult())
        text = result.get("text", "")
        if text:
            final_words = text.split()
            if TYPING_MODE == "buffered":
                # Type the complete final result
                type_text(final_words)
            else:
                # Realtime mode: only type new words
                new_words = final_words[len(last_partial_words):]
                if new_words:
                    type_text(new_words)

    finally:
        process.terminate()
        process.wait()


def on_key_press(key):
    """Handle key press events"""
    global is_recording, recording_thread, has_typed_anything

    if key == TRIGGER_KEY:
        with lock:
            if not is_recording:
                is_recording = True
                has_typed_anything = False
                stop_recording_event.clear()
                recording_thread = threading.Thread(target=stream_transcribe, daemon=True)
                recording_thread.start()


def on_key_release(key):
    """Handle key release events"""
    global is_recording, recording_thread

    if key == TRIGGER_KEY:
        with lock:
            if is_recording:
                is_recording = False
                stop_recording_event.set()
                if recording_thread:
                    recording_thread.join(timeout=1.0)
                    recording_thread = None


def main():
    global model

    if not check_dependencies():
        return 1

    # Get model from command line or use default
    model_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    model_path = os.path.join(SCRIPT_DIR, model_name)

    if not os.path.exists(model_path):
        print(f"Model not found at {model_path}")
        return 1

    print(f"Loading Vosk model ({model_name})...")
    model = Model(model_path)

    print("voice2keyboard running")
    print(f"Hold {TRIGGER_KEY} to record")
    print(f"Mode: {TYPING_MODE}" + (f" (pause_delay: {PAUSE_DELAY}s)" if TYPING_MODE == "buffered" and PAUSE_DELAY > 0 else ""))
    print("Press Ctrl+C to exit")

    def signal_handler(sig, frame):
        print("\nExiting...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    with keyboard.Listener(on_press=on_key_press, on_release=on_key_release) as listener:
        listener.join()

    return 0


if __name__ == "__main__":
    sys.exit(main())
