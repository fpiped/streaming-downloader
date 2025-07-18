import argparse
import io
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from manifest_mux import (
    DownloadOptions,
    TrackSelection,
    build_command,
    parse_args,
    percentage,
    positive_int,
    run_download,
    sample_duration_seconds,
    validate_url,
)
from manifest_mux_core.media import MediaValidationError, probe_media, validate_media
from manifest_mux_core.models import MediaProbe
from manifest_mux_core.yt_dlp import YtDlpClient


SAMPLE_URL = "https://example.com/it/watch/12015"


class UrlValidationTests(unittest.TestCase):
    def test_accepts_https_url(self) -> None:
        self.assertEqual(validate_url(SAMPLE_URL), SAMPLE_URL)

    def test_rejects_non_https(self) -> None:
        for value in ["http://example.com", "ftp://example.com", "not-a-url"]:
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    validate_url(value)


class CommandTests(unittest.TestCase):
    def test_download_keeps_all_audio_and_subtitle_languages_by_default(self) -> None:
        marker = Path(".last-download-path")
        command = build_command(SAMPLE_URL, Path("/tmp/download"), marker)
        self.assertIn("--no-playlist", command)
        self.assertEqual(command[command.index("--format") + 1], "bestvideo*+mergeall[vcodec=none]/best")
        self.assertEqual(command[command.index("--sub-langs") + 1], "all,-live_chat")
        self.assertIn("--audio-multistreams", command)
        self.assertIn("--embed-subs", command)
        self.assertEqual(command[command.index("--remux-video") + 1], "mkv")
        print_index = command.index("--print-to-file")
        self.assertEqual(command[print_index + 1], "after_move:%(filepath)s")
        self.assertEqual(command[-1], SAMPLE_URL)

    def test_track_selection_is_configurable_without_language_hardcoding(self) -> None:
        options = DownloadOptions(
            concurrent_fragments=4,
            fragment_retries=30,
            strict_fragments=True,
            verbose=True,
            tracks=TrackSelection(
                audio_format="bestvideo+bestaudio[language=de]",
                subtitle_languages="de,en",
                embed_subtitles=False,
            ),
        )
        command = build_command(SAMPLE_URL, Path("/tmp/download"), Path("marker"), options)
        self.assertEqual(command[command.index("--concurrent-fragments") + 1], "4")
        self.assertEqual(command[command.index("--fragment-retries") + 1], "30")
        self.assertIn("--abort-on-unavailable-fragments", command)
        self.assertIn("--verbose", command)
        self.assertEqual(command[command.index("--format") + 1], "bestvideo+bestaudio[language=de]")
        self.assertEqual(command[command.index("--sub-langs") + 1], "de,en")
        self.assertNotIn("--embed-subs", command)

    def test_parse_args_preserves_legacy_download_invocation(self) -> None:
        args = parse_args([SAMPLE_URL, "--fragment-retries", "25", "--strict-fragments"])
        self.assertEqual(args.command, "download")
        self.assertEqual(args.fragment_retries, 25)
        self.assertTrue(args.strict_fragments)

    def test_parse_args_supports_operational_subcommands(self) -> None:
        self.assertEqual(parse_args(["doctor"]).command, "doctor")
        self.assertEqual(parse_args(["inspect", SAMPLE_URL]).command, "inspect")
        self.assertEqual(parse_args(["formats", SAMPLE_URL]).command, "formats")

    def test_yt_dlp_client_builds_read_only_commands(self) -> None:
        client = YtDlpClient("yt-dlp")
        self.assertEqual(client.inspect_command(SAMPLE_URL), ["yt-dlp", "--no-playlist", "--skip-download", "--dump-single-json", SAMPLE_URL])
        self.assertEqual(client.formats_command(SAMPLE_URL), ["yt-dlp", "--no-playlist", "--list-formats", SAMPLE_URL])

    def test_sample_section_is_expressed_as_a_time_range(self) -> None:
        command = YtDlpClient("yt-dlp").download_command(
            SAMPLE_URL,
            Path("/tmp/download"),
            Path("marker"),
            DownloadOptions(sample_percent=1),
            section_end_seconds=12.5,
        )
        self.assertEqual(command[command.index("--download-sections") + 1], "*0-12.5")
        self.assertEqual(sample_duration_seconds(1_250, 1), 12.5)
        self.assertEqual(sample_duration_seconds(20, 1), 1.0)

    def test_percentage_must_be_within_zero_and_one_hundred(self) -> None:
        self.assertEqual(percentage("1"), 1.0)
        for value in ["0", "100.1", "not-a-number"]:
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    percentage(value)

    def test_positive_int_must_be_positive(self) -> None:
        self.assertEqual(positive_int("3"), 3)
        for value in ["0", "-1", "not-a-number"]:
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    positive_int(value)


class DownloadLifecycleTests(unittest.TestCase):
    def test_success_validates_moves_final_video_and_removes_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            destination = root / "output" / "movie.mkv"

            def complete_download(_self: YtDlpClient, command: list[str]) -> None:
                marker = Path(command[command.index("--print-to-file") + 2])
                video = marker.parent / "movie.mkv"
                video.write_text("video")
                marker.write_text(str(video), encoding="utf-8")

            with (
                patch("manifest_mux.tempfile.mkdtemp", return_value=str(workspace)),
                patch.object(YtDlpClient, "run", autospec=True, side_effect=complete_download),
                patch("manifest_mux.validate_media", return_value=MediaProbe(60.0, frozenset({"video", "audio"}))),
            ):
                result = run_download(
                    SAMPLE_URL,
                    options=DownloadOptions(),
                    yt_dlp="yt-dlp",
                    output_path=destination,
                    ffprobe="ffprobe",
                )

            self.assertEqual(result, 0)
            self.assertEqual(destination.read_text(), "video")
            self.assertFalse(workspace.exists())

    def test_failed_download_keeps_workspace_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            stderr = io.StringIO()
            with (
                patch("manifest_mux.tempfile.mkdtemp", return_value=str(workspace)),
                patch.object(YtDlpClient, "run", autospec=True, side_effect=subprocess.CalledProcessError(1, ["yt-dlp"])),
                redirect_stderr(stderr),
            ):
                result = run_download(SAMPLE_URL, options=DownloadOptions(), yt_dlp="yt-dlp", keep_temp_on_error=True)

            self.assertEqual(result, 1)
            self.assertTrue(workspace.exists())
            self.assertIn(f"Temporary files kept at: {workspace}", stderr.getvalue())
            shutil.rmtree(workspace)

    def test_validation_failure_keeps_workspace_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()

            def complete_download(_self: YtDlpClient, command: list[str]) -> None:
                marker = Path(command[command.index("--print-to-file") + 2])
                video = marker.parent / "movie.mkv"
                video.write_text("video")
                marker.write_text(str(video), encoding="utf-8")

            with (
                patch("manifest_mux.tempfile.mkdtemp", return_value=str(workspace)),
                patch.object(YtDlpClient, "run", autospec=True, side_effect=complete_download),
                patch("manifest_mux.validate_media", side_effect=MediaValidationError("missing audio")),
            ):
                result = run_download(
                    SAMPLE_URL,
                    options=DownloadOptions(),
                    yt_dlp="yt-dlp",
                    ffprobe="ffprobe",
                    keep_temp_on_error=True,
                )

            self.assertEqual(result, 1)
            self.assertTrue((workspace / "movie.mkv").exists())
            shutil.rmtree(workspace)

    def test_sample_download_resolves_duration_before_downloading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            destination = root / "sample.mkv"

            def complete_download(_self: YtDlpClient, command: list[str]) -> None:
                self.assertEqual(command[command.index("--download-sections") + 1], "*0-12.0")
                marker = Path(command[command.index("--print-to-file") + 2])
                video = marker.parent / "sample.mkv"
                video.write_text("video")
                marker.write_text(str(video), encoding="utf-8")

            with (
                patch("manifest_mux.tempfile.mkdtemp", return_value=str(workspace)),
                patch.object(YtDlpClient, "read_duration", return_value=1_200),
                patch.object(YtDlpClient, "run", autospec=True, side_effect=complete_download),
                patch("manifest_mux.validate_media", return_value=MediaProbe(12.0, frozenset({"video", "audio"}))),
            ):
                result = run_download(
                    SAMPLE_URL,
                    options=DownloadOptions(sample_percent=1),
                    yt_dlp="yt-dlp",
                    output_path=destination,
                    ffprobe="ffprobe",
                )

            self.assertEqual(result, 0)
            self.assertTrue(destination.exists())


class MediaValidationTests(unittest.TestCase):
    def test_probe_media_reads_duration_and_stream_types(self) -> None:
        completed = subprocess.CompletedProcess(
            ["ffprobe"],
            0,
            stdout='{"format": {"duration": "125.5"}, "streams": [{"codec_type": "video"}, {"codec_type": "audio"}, {"codec_type": "subtitle"}]}',
            stderr="",
        )
        with patch("manifest_mux_core.media.subprocess.run", return_value=completed):
            probe = probe_media(Path("movie.mkv"), "ffprobe")

        self.assertEqual(probe.duration_seconds, 125.5)
        self.assertEqual(probe.stream_types, frozenset({"video", "audio", "subtitle"}))

    def test_validate_media_requires_video_and_audio(self) -> None:
        with patch("manifest_mux_core.media.probe_media", return_value=MediaProbe(10.0, frozenset({"video"}))):
            with self.assertRaisesRegex(MediaValidationError, "audio"):
                validate_media(Path("movie.mkv"), "ffprobe")


if __name__ == "__main__":
    unittest.main()
