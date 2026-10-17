"""Check the static Pages artifact without installing a web toolchain."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.links = []
        self.duplicates = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        identifier = data.get("id")
        if identifier:
            if identifier in self.ids:
                self.duplicates.append(identifier)
            self.ids.add(identifier)
        for key in ("src", "href"):
            if data.get(key):
                self.links.append((tag, data[key]))


def main():
    content = (ROOT / "index.html").read_text(encoding="utf-8")
    page = Page()
    page.feed(content)
    assert not page.duplicates, f"Duplicate IDs: {page.duplicates}"
    assert "Harbor-maester" in content and "96.5" in content and "93" in content
    checked = 0
    for tag, raw in page.links:
        parsed = urlsplit(raw)
        if parsed.scheme or parsed.netloc or raw.startswith("mailto:"):
            continue
        if parsed.path:
            target = (ROOT / unquote(parsed.path)).resolve()
            assert target.is_relative_to(ROOT), f"Asset leaves site directory: {raw}"
            assert target.is_file(), f"Broken local {tag} reference: {raw}"
            checked += 1
        if parsed.fragment:
            assert unquote(parsed.fragment) in page.ids, f"Missing anchor: {raw}"
    assert checked >= 4, "Expected local CSS, JavaScript, icon and images"
    print(f"Static site OK: {len(page.ids)} anchors, {checked} local assets checked")


if __name__ == "__main__":
    main()
