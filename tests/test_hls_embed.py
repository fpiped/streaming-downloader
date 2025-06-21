import unittest
from unittest.mock import patch

from yt_dlp import YoutubeDL
from yt_dlp_plugins.extractor.hls_embed import HlsEmbedIE


class HlsEmbedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = HlsEmbedIE(YoutubeDL({"quiet": True}))

    def test_iso8601_timestamp_is_timezone_independent(self) -> None:
        self.assertEqual(
            self.extractor._iso8601_to_unix("2024-01-01T00:00:00Z"),
            1704067200,
        )
        self.assertEqual(
            self.extractor._iso8601_to_unix("2024-01-01T01:00:00+01:00"),
            1704067200,
        )
        self.assertIsNone(self.extractor._iso8601_to_unix(None))

    def test_playlist_url_preserves_query_and_encodes_tokens(self) -> None:
        url = self.extractor._build_playlist_url(
            "https://cdn.example/stream.m3u8?quality=best",
            {"expires": "123", "token": "a+b/c="},
        )
        self.assertEqual(
            url,
            "https://cdn.example/stream.m3u8?quality=best&expires=123&token=a%2Bb%2Fc%3D&h=1",
        )

    def test_missing_loaded_season_does_not_crash(self) -> None:
        info = {
            "props": {
                "title": {"id": 12, "name": "Example"},
                "ziggy": {"location": "https://example.com/it/titles/12"},
                "loadedSeason": None,
            }
        }
        self.assertIsNone(self.extractor._get_season(info))

    def test_real_extract_decodes_html_attribute(self) -> None:
        webpage = '<main data-page="{&quot;props&quot;: {&quot;title&quot;: {&quot;type&quot;: &quot;movie&quot;}}}"></main>'
        with (
            patch.object(self.extractor, "_download_webpage", return_value=webpage),
            patch.object(self.extractor, "_get_movie", return_value={"id": "12"}) as get_movie,
        ):
            result = self.extractor._real_extract("https://example.com/titles/12")

        self.assertEqual(result, {"id": "12"})
        self.assertEqual(get_movie.call_args.args[0]["props"]["title"]["type"], "movie")


if __name__ == "__main__":
    unittest.main()
