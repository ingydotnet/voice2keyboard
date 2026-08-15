#!/usr/bin/env python3

import os
import unittest
from unittest import mock

os.environ.setdefault("PYNPUT_BACKEND", "dummy")

import laptalk


class FakeKeyboard:
    def __init__(self):
        self.events = []
        self.typed = []

    def press(self, key):
        self.events.append(("press", key))

    def release(self, key):
        self.events.append(("release", key))

    def type(self, text):
        self.typed.append(text)


class FakeClipboard:
    name = "fake"

    def __init__(self, previous=b"previous", write_results=None):
        self.previous = previous
        self.writes = []
        self.clears = 0
        self.write_results = list(write_results or [])

    def read(self):
        return self.previous

    def write(self, data):
        self.writes.append(data)
        if self.write_results:
            return self.write_results.pop(0)
        return True

    def clear(self):
        self.clears += 1
        return True


class FakeAudioProcess:
    def __init__(self):
        self.stdout = self
        self.chunks = [b"audio", b""]

    def read(self, _size):
        return self.chunks.pop(0)

    def terminate(self):
        pass

    def wait(self):
        pass


class FakeRecognizer:
    def __init__(self, _model, _sample_rate):
        pass

    def AcceptWaveform(self, _data):
        return True

    def Result(self):
        return '{"text": "first phrase"}'

    def FinalResult(self):
        return '{"text": "second phrase"}'


class RenderTextTests(unittest.TestCase):
    def setUp(self):
        laptalk.ENGINE = "whisper"
        laptalk.GENERAL_TRANSLATIONS = {}
        laptalk.has_typed_anything = False
        laptalk.capitalize_next = True
        laptalk.last_char_typed = ""

    def test_render_complete_transcription(self):
        _, processed, text = laptalk.render_text(
            ["hello", ",", "world", "."], trailing_space=True)

        self.assertEqual(processed, ["hello", ",", "world", "."])
        self.assertEqual(text, "Hello, world. ")

    def test_render_preserves_spacing_across_chunks(self):
        self.assertEqual(laptalk.render_text(["hello"])[2], "Hello")
        self.assertEqual(laptalk.render_text(["there"])[2], " there")
        self.assertEqual(laptalk.render_text(["!"])[2], "! ")
        self.assertEqual(laptalk.render_text(["again"])[2], "Again")

    def test_render_applies_translations(self):
        laptalk.GENERAL_TRANSLATIONS = {"cloud code": "Claude Code"}

        _, processed, text = laptalk.render_text(["cloud", "code", "works"])

        self.assertEqual(processed, ["Claude Code", "works"])
        self.assertEqual(text, "Claude Code works")


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.keyboard = FakeKeyboard()
        self.old_keyboard = laptalk.kb_controller
        self.old_backend = laptalk.CLIPBOARD_BACKEND
        self.old_delay = laptalk.CLIPBOARD_RESTORE_DELAY
        self.terminal_patcher = mock.patch.object(
            laptalk, "active_window_is_terminal", return_value=False)
        self.terminal_patcher.start()
        laptalk.kb_controller = self.keyboard
        laptalk.CLIPBOARD_RESTORE_DELAY = 0

    def tearDown(self):
        self.terminal_patcher.stop()
        laptalk.kb_controller = self.old_keyboard
        laptalk.CLIPBOARD_BACKEND = self.old_backend
        laptalk.CLIPBOARD_RESTORE_DELAY = self.old_delay

    def test_paste_is_automatic_and_restores_clipboard(self):
        clipboard = FakeClipboard()
        laptalk.CLIPBOARD_BACKEND = clipboard

        self.assertTrue(laptalk.paste_text("dictated text"))

        self.assertEqual(clipboard.writes, [b"dictated text", b"previous"])
        self.assertEqual(
            self.keyboard.events,
            [
                ("press", laptalk.Key.ctrl),
                ("press", "v"),
                ("release", "v"),
                ("release", laptalk.Key.ctrl),
            ],
        )

    def test_macos_uses_command_v(self):
        clipboard = FakeClipboard()
        laptalk.CLIPBOARD_BACKEND = clipboard

        with mock.patch.object(laptalk, "IS_MACOS", True):
            self.assertTrue(laptalk.paste_text("dictated text"))

        self.assertEqual(self.keyboard.events[0], ("press", laptalk.Key.cmd))
        self.assertEqual(self.keyboard.events[-1], ("release", laptalk.Key.cmd))

    def test_linux_terminal_uses_typing_without_touching_clipboard(self):
        clipboard = FakeClipboard()
        laptalk.CLIPBOARD_BACKEND = clipboard

        with mock.patch.object(
                laptalk, "active_window_is_terminal", return_value=True):
            laptalk.emit_text("dictated text", "paste")

        self.assertEqual(self.keyboard.typed, ["dictated text"])
        self.assertEqual(self.keyboard.events, [])
        self.assertEqual(clipboard.writes, [])

    def test_empty_clipboard_is_cleared_after_paste(self):
        clipboard = FakeClipboard(previous=None)
        laptalk.CLIPBOARD_BACKEND = clipboard

        with mock.patch.object(laptalk, "clipboard_is_empty", return_value=True):
            self.assertTrue(laptalk.paste_text("dictated text"))

        self.assertEqual(clipboard.writes, [b"dictated text"])
        self.assertEqual(clipboard.clears, 1)

    def test_non_text_clipboard_falls_back_to_typing(self):
        clipboard = FakeClipboard(previous=None)
        laptalk.CLIPBOARD_BACKEND = clipboard

        with mock.patch.object(laptalk, "clipboard_is_empty", return_value=False):
            laptalk.emit_text("dictated text", "paste")

        self.assertEqual(clipboard.writes, [])
        self.assertEqual(self.keyboard.typed, ["dictated text"])

    def test_missing_backend_falls_back_to_typing(self):
        laptalk.CLIPBOARD_BACKEND = None

        laptalk.emit_text("dictated text", "paste")

        self.assertEqual(self.keyboard.typed, ["dictated text"])

    def test_failed_initial_write_falls_back_to_typing(self):
        clipboard = FakeClipboard(write_results=[False])
        laptalk.CLIPBOARD_BACKEND = clipboard

        laptalk.emit_text("dictated text", "paste")

        self.assertEqual(clipboard.writes, [b"dictated text"])
        self.assertEqual(self.keyboard.typed, ["dictated text"])

    def test_failed_restore_does_not_duplicate_output(self):
        clipboard = FakeClipboard(write_results=[True, False])
        laptalk.CLIPBOARD_BACKEND = clipboard

        laptalk.emit_text("dictated text", "paste")

        self.assertEqual(clipboard.writes, [b"dictated text", b"previous"])
        self.assertEqual(self.keyboard.typed, [])

    def test_configured_backend_order_is_respected(self):
        def installed(program):
            return f"/usr/bin/{program}" if program in {"xsel", "xclip"} else None

        with mock.patch.object(laptalk.shutil, "which", side_effect=installed):
            backend = laptalk.select_clipboard_backend(["xclip", "xsel"])

        self.assertEqual(backend.name, "xclip")


class TriggerConfigTests(unittest.TestCase):
    def test_output_can_be_overridden_per_trigger(self):
        config = {
            "output": "paste",
            "keys": {
                "alt_r": {"output": "type"},
            },
        }

        trigger_configs = laptalk.build_trigger_configs(config)

        self.assertEqual(list(trigger_configs.values())[0]["output"], "type")


class TerminalDetectionTests(unittest.TestCase):
    def test_gnome_terminal_wm_class_is_detected(self):
        old_classes = laptalk.CLIPBOARD_TERMINAL_CLASSES
        laptalk.CLIPBOARD_TERMINAL_CLASSES = ["gnome-terminal"]
        try:
            with mock.patch.object(
                    laptalk,
                    "active_window_classes",
                    return_value=("gnome-terminal-server", "Gnome-terminal")):
                self.assertTrue(laptalk.active_window_is_terminal())
        finally:
            laptalk.CLIPBOARD_TERMINAL_CLASSES = old_classes

    def test_non_terminal_wm_class_is_not_detected(self):
        with mock.patch.object(
                laptalk, "active_window_classes", return_value=("code", "Code")):
            self.assertFalse(laptalk.active_window_is_terminal())


class VoskOutputTests(unittest.TestCase):
    def setUp(self):
        laptalk.stop_recording_event.clear()

    @mock.patch.object(laptalk.subprocess, "Popen", return_value=FakeAudioProcess())
    @mock.patch.object(laptalk, "KaldiRecognizer", FakeRecognizer)
    @mock.patch.object(laptalk, "output_words")
    def test_buffered_paste_is_emitted_once_after_recording(
            self, output_words, _popen):
        config = {"mode": "buffered", "pause": 0, "output": "paste"}

        laptalk.stream_transcribe(config)

        output_words.assert_called_once_with(
            ["first", "phrase", "second", "phrase"], config)

    @mock.patch.object(laptalk.subprocess, "Popen", return_value=FakeAudioProcess())
    @mock.patch.object(laptalk, "KaldiRecognizer", FakeRecognizer)
    @mock.patch.object(laptalk, "output_words")
    def test_realtime_paste_uses_typing_while_trigger_is_held(
            self, output_words, _popen):
        config = {"mode": "realtime", "pause": 0, "output": "paste"}

        laptalk.stream_transcribe(config)

        for call in output_words.call_args_list:
            self.assertEqual(call.args[1]["output"], "type")


if __name__ == "__main__":
    unittest.main()
