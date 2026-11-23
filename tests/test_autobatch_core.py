import unittest

from autobatch_core import organize_seasons, parse_episode, parse_media


class ParserTests(unittest.TestCase):
    def test_season_episode_filename(self):
        row = parse_episode("Breaking.Bad.S01E02.1080p.WEB-DL.mkv")
        self.assertEqual((row["series_title"], row["season"], row["episode"]), ("Breaking Bad", 1, 2))

    def test_other_patterns(self):
        self.assertEqual(parse_episode("Prison Break Season 2 Episode 12.mp4")["episode"], 12)
        self.assertEqual(parse_episode("The.Penguin.1x03.mkv")["season"], 1)

    def test_caption_and_video(self):
        self.assertEqual(parse_media("unknown.mp4", "The Last of Us S02E03", True)["season"], 2)
        self.assertIsNone(parse_media("series.S01E01.srt", "", False))

    def test_reject_ambiguous_and_unlabeled(self):
        self.assertIsNone(parse_episode("Breaking.Bad.S01E01-E02.mkv"))
        self.assertIsNone(parse_episode("Breaking.Bad.S01E01E02.mkv"))
        self.assertIsNone(parse_episode("S01E01.mkv"))
        self.assertIsNone(parse_episode("Just a video.mkv"))

    def test_underscore_and_interleaved_marketing_tags(self):
        a = parse_episode("Breaking_Bad_S01E03_1080p.mkv")
        b = parse_episode("[MEDIA] Breaking.Bad - Season 1 Episode 03.mp4")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertEqual(a["series_id"], b["series_id"])

    def test_season_with_underscore_and_space(self):
        parsed = parse_episode("Silo_Season_02_Episode_04_WEBRip.mp4")
        self.assertIsNotNone(parsed)
        self.assertEqual((parsed["season"], parsed["episode"]), (2, 4))

    def test_same_show_normalization(self):
        a = parse_episode("Breaking.Bad.S01E02.mkv")
        b = parse_episode("Breaking_Bad_S02E02.mkv")
        self.assertEqual(a["series_id"], b["series_id"])

    def test_skip_intruder_and_detect_duplicate(self):
        records = [
            {"season": 1, "episode": 1, "message_id": 101},
            {"season": 1, "episode": 2, "message_id": 102},
            {"season": 1, "episode": 3, "message_id": 104},
            {"season": 1, "episode": 4, "message_id": 105},
            {"season": 1, "episode": 4, "message_id": 109},
            {"season": 2, "episode": 2, "message_id": 110},
        ]
        out = organize_seasons(records)
        self.assertEqual(out[0]["message_ids"], [101, 102, 104, 105])
        self.assertEqual(out[0]["duplicates"], 1)
        self.assertEqual(out[1]["missing"], [1])


if __name__ == "__main__":
    unittest.main()
