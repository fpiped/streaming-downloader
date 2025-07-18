# streaming-downloader

`streaming-downloader` is a manifest-aware command-line wrapper around
`yt-dlp`. It downloads a single movie or TV episode from supported HLS embed
pages and can inspect any source that yt-dlp understands, including HLS and
DASH manifests.

It includes a custom source adapter for StreamingCommunity-style `watch` and
`titles` URLs, such as `https://example.com/it/watch/12015?e=38156`. Other
sources are resolved by yt-dlp's built-in extractors.

The application is intended for content you are allowed to download. Make sure
your use complies with the provider's terms and applicable law.

## What it downloads

For each requested title, the downloader:

- selects the best available video stream;
- keeps every audio stream exposed by the manifest, rather than guessing a
  preferred language;
- downloads all available subtitles except live chat, converts them to WebVTT,
  and embeds them in the final file;
- merges the selected streams into a single Matroska (`.mkv`) container;
- downloads one title at a time, never a whole playlist.

Fragments, subtitle files, and yt-dlp state are created in the system temporary
directory. When the download completes, only the final MKV is moved to the
chosen destination.

By default, yt-dlp retries each unavailable HLS fragment ten times and then
continues without it. This is useful for transient CDN failures, but it can
produce a file with a short missing section. Use `--strict-fragments` when a
complete archive matters more than completing the download.

Before delivering the final file, the application uses `ffprobe` to verify that
the container contains both a video and an audio stream. Disable this only when
needed with `--no-validate-output`.

## Installation

```bash
uv sync
```

On macOS, install `ffmpeg` with Homebrew:

```bash
brew install ffmpeg
```

## Commands

The original shorthand remains supported:

```bash
uv run streaming-downloader 'https://example.com/it/watch/12015?e=38156' \
  --output-path ~/Movies/my-title.mkv
```

It is equivalent to the explicit `download` command:

```bash
uv run streaming-downloader download 'https://example.com/it/watch/12015?e=38156' \
  --output-path ~/Movies/my-title.mkv
```

Use these read-only commands to understand a source before downloading it:

```bash
# Print yt-dlp metadata as JSON
uv run streaming-downloader inspect 'https://example.com/it/watch/12015?e=38156'

# List video, audio, and subtitle formats
uv run streaming-downloader formats 'https://example.com/it/watch/12015?e=38156'

# Check local tool availability
uv run streaming-downloader doctor
```

Always wrap pasted URLs in single quotes. In particular, zsh interprets `?` as
a wildcard, so an unquoted URL containing `?e=...` is rejected by the shell
before the application receives it.

## Download options

- `--output-path FILE`: exact path and filename for the final MKV. If omitted,
  the output is `~/Downloads/<title>.mkv`.
- `--concurrent-fragments N`: number of HLS fragments downloaded in parallel
  (default: 1). Increase it only if the provider and connection can handle the
  additional requests.
- `--fragment-retries N`: retries for an unavailable HLS fragment (default: 10).
- `--strict-fragments`: abort instead of creating an output that omits an
  unrecoverable fragment.
- `--sample-percent PERCENT`: download only the leading percentage of the
  title, while still running normal subtitle embedding, muxing, and ffprobe
  validation. Use `1` for a quick pipeline smoke test.
- `--keep-temp-on-error`: preserve the temporary workspace and print its path
  when yt-dlp, post-processing, or validation fails.
- `--format-selector SELECTOR`: advanced yt-dlp format selector. Its default
  keeps the best video and every available audio-only stream.
- `--subtitle-langs LANGS`: yt-dlp subtitle selector (default:
  `all,-live_chat`). Use standard language tags such as `it,en`, or `all`.
- `--no-embed-subs`: download subtitles without embedding them in the MKV.
- `--no-validate-output`: skip the final ffprobe video/audio validation.

For an archival download with more retries and no skipped fragments:

```bash
uv run streaming-downloader download 'https://example.com/it/watch/12015?e=38156' \
  --output-path ~/Movies/my-title.mkv \
  --fragment-retries 30 \
  --strict-fragments \
  --keep-temp-on-error
```

For a quick end-to-end test that downloads approximately the first 1% of a
title and verifies the resulting muxed file:

```bash
uv run streaming-downloader download 'https://example.com/it/watch/12015?e=38156' \
  --sample-percent 1 \
  --output-path ~/Movies/my-title-sample.mkv
```

The percentage is converted to a time range using the duration reported by the
source. HLS/DASH streams are segmented, so the actual duration can be slightly
longer than the requested percentage.

## Architecture

The command-line layer coordinates small, testable components:

```text
CLI
 ├── TrackSelection and DownloadOptions
 ├── YtDlpClient
 │    ├── provider/custom extractors
 │    └── HLS or DASH manifest download
 ├── ffprobe media validation
 └── output delivery and temporary workspace cleanup
```

Track selection is language-agnostic by default: the application preserves all
audio streams and all subtitle languages exposed by a manifest. Language
selection is an explicit user policy, not an assumption baked into an
extractor.

## Tests

```bash
uv run python -m unittest discover -s tests -v
```
