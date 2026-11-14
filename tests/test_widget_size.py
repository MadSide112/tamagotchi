"""Widget template must satisfy the official Bot API 10.4 constraints:
- raw HTML up to 32768 bytes;
- at most 4096 bytes after zlib level 9 compression;
- no network access, no banned markup, widget API wired correctly.
"""
import pathlib
import unittest
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = (ROOT / 'widget' / 'template.html').read_text(encoding='utf-8')


class TestWidgetSize(unittest.TestCase):
    def test_raw_size(self):
        self.assertLessEqual(len(HTML.encode('utf-8')), 32768)

    def test_compressed_size(self):
        compressed = zlib.compress(HTML.encode('utf-8'), 9)
        self.assertLessEqual(len(compressed), 4096,
                             'widget exceeds 4KB zlib budget: %d bytes' % len(compressed))


class TestWidgetProfile(unittest.TestCase):
    def test_no_network_access(self):
        low = HTML.lower()
        for forbidden in ('fetch(', 'xmlhttprequest', 'websocket', 'http://', 'https://',
                          'src=', 'href=', '<img', '<input', '<select', '<textarea',
                          '<animate', '<link'):
            self.assertNotIn(forbidden, low)

    def test_widget_api_wired(self):
        self.assertIn('window.TelegramWidget', HTML)
        self.assertIn('.request(', HTML)
        self.assertIn('chatDataChanged', HTML)
        self.assertIn('chatData', HTML)

    def test_requests_are_tiny(self):
        # Action codes must stay well under the 64-byte query limit.
        import re
        actions = set(re.findall(r"data-a=\"(\w+)\"", HTML)) | {'sync'}
        for action in actions:
            self.assertLessEqual(len(action.encode('utf-8')), 64)


if __name__ == '__main__':
    unittest.main()
