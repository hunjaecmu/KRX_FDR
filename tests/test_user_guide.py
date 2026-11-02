import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapp import user_guide


def sections() -> dict[str, list[str]]:
    html = user_guide.render_html("full")
    return {
        section_id: editions.split()
        for section_id, editions in re.findall(r'<section class="card" id="(\w+)".*?data-editions="([^"]+)"', html)
    }


class UserGuideTests(unittest.TestCase):
    def test_edition_is_inserted(self):
        for edition in user_guide.EDITIONS:
            html = user_guide.render_html(edition)
            self.assertIn(f'data-edition="{edition}"', html)
            self.assertNotIn("__EDITION__", html)

    def test_unknown_edition_is_rejected(self):
        with self.assertRaises(ValueError):
            user_guide.render_html("x")

    def test_each_edition_shows_only_its_menus(self):
        found = sections()
        self.assertEqual(found["major"], ["cloud"])
        for section_id in ("menu1", "menu2", "daily", "files", "trouble"):
            self.assertNotIn("cloud", found[section_id])
        for section_id in ("menu5", "menu6", "menu7", "menu8", "deploy"):
            self.assertEqual(found[section_id], ["full"])
        for section_id in ("overview", "menu3", "menu4", "terms", "notice"):
            self.assertEqual(sorted(found[section_id]), ["cloud", "full", "lite"])

    def test_interactive_chart_help_matches_chart_editions(self):
        self.assertEqual(sections()["chart"], ["full", "cloud"])

    def test_dark_theme_applies_only_to_server_edition(self):
        html = user_guide.render_html("cloud")
        self.assertIn('body[data-edition="cloud"] {', html)
        self.assertIn("--bg: #000000", html)
        self.assertNotIn('body[data-edition="full"]', html)
        self.assertNotIn('body[data-edition="lite"]', html)

    def test_no_token_values_in_guide(self):
        html = user_guide.render_html("full")
        self.assertNotRegex(html, r"github_pat_|ghp_")


if __name__ == "__main__":
    unittest.main()
