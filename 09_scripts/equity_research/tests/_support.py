from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def visible_html_text(document: str) -> str:
    """Read the rendered email body without markup, head or style content."""
    class BodyText(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self.omitted = 0

        def handle_starttag(self, tag, attrs):
            if tag in {'head', 'style', 'script'}:
                self.omitted += 1
            elif not self.omitted and tag in {'p', 'div', 'h1', 'h2', 'br'}:
                self.parts.append(' ')

        def handle_endtag(self, tag):
            if tag in {'head', 'style', 'script'}:
                self.omitted -= 1
            elif not self.omitted and tag in {'p', 'div', 'h1', 'h2'}:
                self.parts.append(' ')

        def handle_data(self, data):
            if not self.omitted:
                self.parts.append(data)

    parser = BodyText()
    parser.feed(document)
    return ' '.join(''.join(parser.parts).split())
