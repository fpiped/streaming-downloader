from __future__ import annotations

import subprocess
from pathlib import Path

from .models import DownloadOptions


class YtDlpClient:
    """Command builder for yt-dlp operations on provider pages and manifests."""

    def __init__(self, executable: str) -> None:
        self.executable = executable

    def download_command(
        self,
        url: str,
        temporary_dir: Path,
        filepath_marker: Path,
        options: DownloadOptions,
        section_end_seconds: float | None = None,
    ) -> list[str]:
        command = [
            self.executable,
            "--no-playlist",
            "--restrict-filenames",
            "--no-write-comments",
            "--concurrent-fragments",
            str(options.concurrent_fragments),
            "--fragment-retries",
            str(options.fragment_retries),
        ]
        if options.strict_fragments:
            command.append("--abort-on-unavailable-fragments")
        if section_end_seconds is not None:
            command.extend(["--download-sections", f"*0-{section_end_seconds}"])

        tracks = options.tracks
        command.extend(["--format", tracks.audio_format, "--audio-multistreams", "--merge-output-format", "mkv"])
        command.extend(["--sub-langs", tracks.subtitle_languages, "--write-subs", "--convert-subs", "vtt"])
        if tracks.embed_subtitles:
            command.append("--embed-subs")
        command.extend(
            [
                "--output",
                str(temporary_dir / "%(title)s.%(ext)s"),
                "--print-to-file",
                "after_dl:%(filepath)s",
                str(filepath_marker),
                url,
            ]
        )
        return command

    def inspect_command(self, url: str) -> list[str]:
        return [self.executable, "--no-playlist", "--skip-download", "--dump-single-json", url]

    def formats_command(self, url: str) -> list[str]:
        return [self.executable, "--no-playlist", "--list-formats", url]

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, check=True, text=True)

    def duration_command(self, url: str) -> list[str]:
        return [self.executable, "--no-playlist", "--skip-download", "--print", "%(duration)s", url]

    def read_duration(self, url: str) -> float:
        """Resolve duration before converting a percentage sample to seconds."""
        result = subprocess.run(
            self.duration_command(url),
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            duration = float(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError) as error:
            raise ValueError("the source did not provide a usable duration") from error
        if duration <= 0:
            raise ValueError("the source did not provide a positive duration")
        return duration
