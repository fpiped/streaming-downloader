# streaming-downloader

`streaming-downloader` is a command-line wrapper around `yt-dlp` for downloading
a single movie or TV episode from supported HLS embed pages. It includes a
custom extractor for StreamingCommunity-style `watch` and `titles` URLs, such
as `https://example.com/it/watch/12015?e=38156`.

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

## Installation

```bash
uv sync
```

On macOS, install `ffmpeg` with Homebrew:

```bash
brew install ffmpeg
```

## Usage

```bash
uv run streaming-downloader 'https://example.com/it/watch/12015?e=38156' \
  --output-path ~/Movies/my-title.mkv
```

Arguments:

- `url` (required): HTTPS URL for a movie or a specific TV episode.
- `--output-path FILE`: exact path and filename for the final MKV. If omitted,
  the output is `~/Downloads/<title>.mkv`.
- `--concurrent-fragments N`: number of HLS fragments to download in parallel
  (default: 1). Increase it only if the provider and your connection can handle
  the additional requests.

Always wrap pasted URLs in single quotes. In particular, zsh interprets `?` as
a wildcard, so an unquoted URL containing `?e=...` is rejected by the shell
before the application receives it.

## Tests

```bash
uv run python -m unittest discover -s tests -v
```
