from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from manifest_mux_core.media import MediaValidationError, validate_media
from manifest_mux_core.models import (
    DEFAULT_CONCURRENT_FRAGMENTS,
    DEFAULT_FRAGMENT_RETRIES,
    DownloadOptions,
    TrackSelection,
)
from manifest_mux_core.yt_dlp import YtDlpClient


COMMANDS = frozenset({"download", "inspect", "formats", "doctor"})
DEFAULT_TRACK_SELECTION = TrackSelection()


def validate_url(value: str) -> str:
    """Accept any HTTPS URL."""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise argparse.ArgumentTypeError("provide a valid HTTPS URL")
    return value


def positive_int(value: str) -> int:
    """Parse a strictly positive integer for argparse."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if number < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def percentage(value: str) -> float:
    """Parse a percentage in the open interval (0, 100]."""
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not 0 < number <= 100:
        raise argparse.ArgumentTypeError("must be greater than zero and at most 100")
    return number


def sample_duration_seconds(duration_seconds: float, sample_percent: float) -> float:
    """Return a non-empty leading sample duration from a media duration."""
    return max(1.0, duration_seconds * sample_percent / 100)


def build_command(
    url: str,
    temporary_dir: Path,
    filepath_marker: Path,
    options: DownloadOptions = DownloadOptions(),
    yt_dlp: str = "yt-dlp",
) -> list[str]:
    """Backward-compatible helper for constructing the download command."""
    return YtDlpClient(yt_dlp).download_command(url, temporary_dir, filepath_marker, options)


def resolve_yt_dlp() -> str | None:
    """Find either a globally installed or virtualenv-local yt-dlp binary."""
    yt_dlp = shutil.which("yt-dlp")
    local_yt_dlp = Path(sys.executable).with_name("yt-dlp")
    if yt_dlp is None and local_yt_dlp.is_file():
        yt_dlp = str(local_yt_dlp)
    return yt_dlp


def read_downloaded_video(filepath_marker: Path) -> Path | None:
    """Read the final media path emitted by yt-dlp after post-processing."""
    if not filepath_marker.is_file():
        return None
    marker_lines = filepath_marker.read_text(encoding="utf-8").splitlines()
    if not marker_lines:
        return None
    downloaded_video = Path(marker_lines[-1].strip())
    return downloaded_video if downloaded_video.is_file() else None


def default_destination(downloaded_video: Path) -> Path:
    return Path.home() / "Downloads" / downloaded_video.name


def run_download(
    url: str,
    *,
    options: DownloadOptions,
    yt_dlp: str,
    output_path: Path | None = None,
    keep_temp_on_error: bool = False,
    validate_output: bool = True,
    ffprobe: str | None = None,
) -> int:
    """Download, validate, and atomically deliver one title."""
    temporary_dir = Path(tempfile.mkdtemp(prefix="manifest-mux-"))
    failed = True

    try:
        filepath_marker = temporary_dir / ".last-download-path"
        client = YtDlpClient(yt_dlp)
        section_end_seconds = None
        if options.sample_percent is not None:
            try:
                duration = client.read_duration(url)
            except (subprocess.CalledProcessError, ValueError) as error:
                print(f"Error: unable to determine source duration: {error}", file=sys.stderr)
                return 1
            section_end_seconds = sample_duration_seconds(duration, options.sample_percent)
        try:
            client.run(
                client.download_command(
                    url,
                    temporary_dir,
                    filepath_marker,
                    options,
                    section_end_seconds=section_end_seconds,
                )
            )
        except subprocess.CalledProcessError as error:
            print(f"yt-dlp exited with code {error.returncode}", file=sys.stderr)
            return error.returncode or 1

        downloaded_video = read_downloaded_video(filepath_marker)
        if downloaded_video is None:
            print("Error: unable to determine the downloaded file.", file=sys.stderr)
            return 1

        if validate_output:
            if ffprobe is None:
                print("Error: ffprobe was not found. Follow the README instructions.", file=sys.stderr)
                return 2
            try:
                validate_media(downloaded_video, ffprobe)
            except MediaValidationError as error:
                print(f"Error: output validation failed: {error}", file=sys.stderr)
                return 1

        destination = (output_path or default_destination(downloaded_video)).expanduser()
        if destination.is_dir():
            print(f"Error: output path must be a file: {destination}", file=sys.stderr)
            return 1
        if destination.exists():
            print(f"Error: output path already exists: {destination}", file=sys.stderr)
            return 1
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(downloaded_video), destination)
        except OSError as error:
            print(f"Error: unable to move the downloaded file: {error}", file=sys.stderr)
            return 1

        failed = False
        print(destination)
        return 0
    finally:
        if failed and keep_temp_on_error:
            print(f"Temporary files kept at: {temporary_dir}", file=sys.stderr)
        else:
            shutil.rmtree(temporary_dir, ignore_errors=True)


def add_download_arguments(result: argparse.ArgumentParser) -> None:
    result.add_argument("url", type=validate_url)
    result.add_argument("--output-path", type=Path, metavar="FILE", help="final MKV file path")
    result.add_argument(
        "--concurrent-fragments",
        type=positive_int,
        default=DEFAULT_CONCURRENT_FRAGMENTS,
        metavar="N",
        help=f"number of fragments downloaded in parallel (default: {DEFAULT_CONCURRENT_FRAGMENTS})",
    )
    result.add_argument(
        "--fragment-retries",
        type=positive_int,
        default=DEFAULT_FRAGMENT_RETRIES,
        metavar="N",
        help=f"retries for each unavailable fragment (default: {DEFAULT_FRAGMENT_RETRIES})",
    )
    result.add_argument("--strict-fragments", action="store_true", help="fail on unavailable fragments")
    result.add_argument("--verbose", action="store_true", help="show yt-dlp and ffmpeg diagnostic output")
    result.add_argument(
        "--sample-percent",
        type=percentage,
        metavar="PERCENT",
        help="download only the leading PERCENT of the title while keeping normal muxing",
    )
    result.add_argument("--keep-temp-on-error", action="store_true", help="preserve failed download workspaces")
    result.add_argument(
        "--format-selector",
        default=DEFAULT_TRACK_SELECTION.audio_format,
        metavar="SELECTOR",
        help="yt-dlp format selector (default preserves all audio tracks)",
    )
    result.add_argument(
        "--subtitle-langs",
        default=DEFAULT_TRACK_SELECTION.subtitle_languages,
        metavar="LANGS",
        help="yt-dlp subtitle language selector (default: all except live chat)",
    )
    result.add_argument("--no-embed-subs", action="store_true", help="do not embed downloaded subtitles")
    result.add_argument("--no-validate-output", action="store_true", help="skip ffprobe output validation")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Resolve and archive HLS/DASH media with yt-dlp.")
    subparsers = result.add_subparsers(dest="command")
    download = subparsers.add_parser("download", help="download one title")
    add_download_arguments(download)
    inspect = subparsers.add_parser("inspect", help="print source metadata as JSON")
    inspect.add_argument("url", type=validate_url)
    formats = subparsers.add_parser("formats", help="list video, audio, and subtitle formats")
    formats.add_argument("url", type=validate_url)
    subparsers.add_parser("doctor", help="check required local tools")
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    values = list(sys.argv[1:] if argv is None else argv)
    # Preserve the original `manifest-mux URL` invocation.
    if values and values[0] not in COMMANDS and values[0] not in {"-h", "--help"}:
        values.insert(0, "download")
    return parser().parse_args(values)


def run_doctor() -> int:
    tools = {"yt-dlp": resolve_yt_dlp(), "ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe")}
    for name, executable in tools.items():
        print(f"{name}: {executable or 'MISSING'}")
    return 0 if all(tools.values()) else 2


def run_read_only_command(client: YtDlpClient, command: list[str]) -> int:
    try:
        client.run(command)
    except subprocess.CalledProcessError as error:
        print(f"yt-dlp exited with code {error.returncode}", file=sys.stderr)
        return error.returncode or 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "doctor":
        return run_doctor()
    if args.command is None:
        parser().print_help(sys.stderr)
        return 2

    yt_dlp = resolve_yt_dlp()
    if yt_dlp is None:
        print("Error: yt-dlp was not found. Follow the README instructions.", file=sys.stderr)
        return 2
    client = YtDlpClient(yt_dlp)
    if args.command == "inspect":
        return run_read_only_command(client, client.inspect_command(args.url))
    if args.command == "formats":
        return run_read_only_command(client, client.formats_command(args.url))

    if shutil.which("ffmpeg") is None:
        print("Error: ffmpeg was not found. Follow the README instructions.", file=sys.stderr)
        return 2
    ffprobe = shutil.which("ffprobe")
    tracks = TrackSelection(
        audio_format=args.format_selector,
        subtitle_languages=args.subtitle_langs,
        embed_subtitles=not args.no_embed_subs,
    )
    options = DownloadOptions(
        concurrent_fragments=args.concurrent_fragments,
        fragment_retries=args.fragment_retries,
        strict_fragments=args.strict_fragments,
        sample_percent=args.sample_percent,
        verbose=args.verbose,
        tracks=tracks,
    )
    return run_download(
        args.url,
        options=options,
        yt_dlp=yt_dlp,
        output_path=args.output_path,
        keep_temp_on_error=args.keep_temp_on_error,
        validate_output=not args.no_validate_output,
        ffprobe=ffprobe,
    )


if __name__ == "__main__":
    raise SystemExit(main())
