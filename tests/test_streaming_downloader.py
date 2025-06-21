import argparse
import unittest
from pathlib import Path

from streaming_downloader import (
    build_command,
    positive_int,
    validate_url,
)


SAMPLE_URL = "https://example.com/it/watch/12015"


class UrlValidationTests(unittest.TestCase):
    def test_accepts_https_url(self) -> None:
        self.assertEqual(validate_url(SAMPLE_URL), SAMPLE_URL)
        self.assertEqual(
            validate_url("https://example.com/watch/7942"),
            "https://example.com/watch/7942",
        )

    def test_rejects_non_https(self) -> None:
        for value in ["http://example.com", "ftp://example.com", "not-a-url"]:
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    validate_url(value)


class CommandTests(unittest.TestCase):
    def test_download_is_single_title_and_mkv(self) -> None:
        marker = Path(".last-download-path")
        command = build_command(SAMPLE_URL, Path("/tmp/download"), marker)
        self.assertIn("--no-playlist", command)
        self.assertIn("--concurrent-fragments", command)
        self.assertEqual(
            command[command.index("--concurrent-fragments") + 1], "1"
        )
        self.assertIn("--merge-output-format", command)
        format_value = command[command.index("--format") + 1]
        self.assertIn("mergeall[vcodec=none]", format_value)
        self.assertTrue(format_value.endswith("/best"))
        self.assertIn("--audio-multistreams", command)
        self.assertIn("--sub-langs", command)
        self.assertIn("all,-live_chat", command)
        self.assertIn("--embed-subs", command)
        self.assertIn("--convert-subs", command)
        self.assertNotIn("--write-info-json", command)
        self.assertNotIn("--simulate", command)

        output_value = command[command.index("--output") + 1]
        self.assertEqual(output_value, "/tmp/download/%(title)s.%(ext)s")

        print_index = command.index("--print-to-file")
        self.assertEqual(command[print_index + 1], "after_dl:%(filepath)s")
        self.assertEqual(command[print_index + 2], str(marker))

        self.assertEqual(command[-1], SAMPLE_URL)

    def test_keeps_all_audio_and_subtitle_languages(self) -> None:
        command = build_command(
            SAMPLE_URL, Path("/tmp/download"), Path(".last-download-path")
        )
        format_value = command[command.index("--format") + 1]
        self.assertEqual(format_value, "bestvideo*+mergeall[vcodec=none]/best")
        self.assertIn("--audio-multistreams", command)
        self.assertEqual(command[command.index("--sub-langs") + 1], "all,-live_chat")

    def test_concurrent_fragments_is_configurable(self) -> None:
        marker = Path(".last-download-path")
        command = build_command(SAMPLE_URL, Path("/tmp/download"), marker, 32)
        self.assertEqual(
            command[command.index("--concurrent-fragments") + 1], "32"
        )

    def test_concurrent_fragments_must_be_positive(self) -> None:
        self.assertEqual(positive_int("3"), 3)
        for value in ["0", "-1", "not-a-number"]:
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    positive_int(value)


if __name__ == "__main__":
    unittest.main()
