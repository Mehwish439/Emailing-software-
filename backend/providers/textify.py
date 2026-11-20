"""
HTML -> plain text for the text/plain alternative of a campaign email.

Unlike a naive tag strip, link targets are kept ("Unsubscribe (https://...)"): a text-only reader
otherwise loses the unsubscribe link entirely. Stdlib only; never executes or fetches anything.
"""
import re
from html.parser import HTMLParser

_BLOCK = {"p", "div", "br", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6",
          "blockquote", "hr", "section", "article", "header", "footer"}
_SKIP = {"script", "style", "head", "title"}
_SKIP_HREF = ("#", "mailto:", "tel:", "javascript:")


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0
        self._href = None
        self._link_text_start = None

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip_depth += 1
            return
        if tag in _BLOCK:
            self.parts.append("\n")
        if tag == "a":
            href = (dict(attrs).get("href") or "").strip()
            self._href = href if href and not href.lower().startswith(_SKIP_HREF) else None
            self._link_text_start = len(self.parts)

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in _BLOCK:
            self.parts.append("\n")
        if tag == "a" and self._href:
            label = "".join(self.parts[self._link_text_start:]).strip()
            if self._href not in label:
                self.parts.append(f" ({self._href})")
            self._href = None

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    if not html:
        return ""
    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001  malformed markup must never block a send
        return re.sub(r"<[^>]+>", "", html).strip()
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
