#!/usr/bin/env python3
"""Render docs/assets/screenshots/01-mcp-thread.png from REAL tool output.

Run: python3 scripts/make_screenshots.py

What is real: the MCP tools `post_thread` and `post_tweet` from tweetkit_x/mcp_server.py run as shipped,
including the up-front file check. What is demo: the X transport. Uploads and tweets go to an in-memory
stand-in, so no cookie is read and no request reaches X; ids and URLs are made up. Stdlib only; needs
rsvg-convert (or Google Chrome) to turn the SVG into a PNG.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tweetkit_x import mcp_server  # noqa: E402
from tweetkit_x.client import TweetKit  # noqa: E402

OUT = os.path.join(ROOT, "docs", "assets", "screenshots")
W, H, SCALE = 1600, 1000, 2
MONO = "ui-monospace, 'SF Mono', Menlo, monospace"
SANS = "ui-sans-serif, -apple-system, 'Segoe UI', sans-serif"
COLORS = {"p": "#1d9bf0", "c": "#e7e9ea", "o": "#c4cfd6", "d": "#71767b", "e": "#f4212e"}


def demo_tk():
    tk = TweetKit.__new__(TweetKit)  # no cookie, no network
    n = {"m": 0, "t": 1990000000000000000}

    def upload_media(path, media_type=None, alt_text=None):
        n["m"] += 1
        return "17%016d" % n["m"]

    def create_tweet(text, media_ids=None, reply_to=None, quote_tweet_id=None):
        n["t"] += 1
        return {"ok": True, "id": str(n["t"]), "url": "https://x.com/i/status/%d" % n["t"]}

    tk.upload_media, tk.create_tweet = upload_media, create_tweet
    return tk


def run():
    tmp = tempfile.mkdtemp()
    files = []
    for name in ("banner.png", "tool-call.png", "adapter.png"):
        p = os.path.join(tmp, name)
        open(p, "wb").write(b"\x89PNG demo")
        files.append(p)
    mcp_server._get_tk = lambda: (demo_tk(), None)
    shown = {"banner": "~/launch/banner.png", "a": "~/launch/tool-call.png", "b": "~/launch/adapter.png"}
    call = [{"text": "1/ I built a thing", "images": [files[0]], "alt_texts": ["Project banner"]},
            "2/ how it works",
            {"text": "3/ before and after", "images": [files[1], files[2]]}]
    result = mcp_server.post_thread(call)
    bad = mcp_server.post_thread(["1/ ok", {"text": "2/ oops", "images": [os.path.join(tmp, "missing.png")]}])
    shutil.rmtree(tmp)
    shown_call = json.loads(json.dumps(call).replace(files[0], shown["banner"]).replace(files[1], shown["a"])
                            .replace(files[2], shown["b"]))
    bad_err = bad[0]["error"].replace(tmp, "~/launch")
    return shown_call, result, bad_err


def lines(call, result, bad_err):
    L = [[("d", "# an agent (Claude, Cursor, ...) calls the tweetkit-x MCP tool post_thread")],
         [("p", "▸ "), ("c", "post_thread(tweets=")]]
    for i, item in enumerate(call):
        L.append([("c", "    " + json.dumps(item, ensure_ascii=False) + ("," if i < len(call) - 1 else ""))])
    L += [[("c", ")")], [], [("d", "# every file is checked first; then each tweet uploads its media and replies to the previous one")]]
    for r in result:
        L.append([("o", json.dumps(r))])
    L += [[], [("d", "# a missing file anywhere in the thread: nothing is posted, no half thread")],
          [("p", "▸ "), ("c", 'post_thread(tweets=["1/ ok", {"text": "2/ oops", "images": ["~/launch/missing.png"]}])')],
          [("e", json.dumps([{"ok": False, "error": bad_err}]))]]
    return L


def svg(title, rows, size):
    lh = round(size * 1.5)
    x0, y0 = 76, 150
    assert y0 + (len(rows) - 1) * lh < H - 64, "too many lines"
    t = []
    for i, segs in enumerate(rows):
        if segs:
            t.append('<text x="%d" y="%d" xml:space="preserve">%s</text>' % (x0, y0 + i * lh, "".join(
                '<tspan fill="%s"%s>%s</tspan>' % (COLORS[k], ' font-weight="700"' if k == "p" else "", escape(s))
                for k, s in segs)))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#000"/><stop offset="1" stop-color="#0b1622"/></linearGradient></defs>
<rect width="{W}" height="{H}" fill="url(#bg)"/>
<rect x="40" y="40" width="{W - 80}" height="{H - 80}" rx="16" fill="#080a0d" stroke="#1d9bf0" stroke-opacity="0.45" stroke-width="2"/>
<path d="M40 56 a16 16 0 0 1 16 -16 h{W - 112} a16 16 0 0 1 16 16 v40 h-{W - 80} z" fill="#16181c"/>
<circle cx="76" cy="68" r="8" fill="#ff5f57"/><circle cx="102" cy="68" r="8" fill="#febc2e"/><circle cx="128" cy="68" r="8" fill="#28c840"/>
<text x="{W // 2}" y="74" text-anchor="middle" font-family="{SANS}" font-size="18" fill="#9ca3af">{escape(title)}</text>
<g font-family="{MONO}" font-size="{size}">{chr(10).join(t)}</g></svg>
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = lines(*run())
    longest = max(len("".join(s for _, s in r)) for r in rows if r)
    size = min(20, int((W - 160) / (longest * 0.602)))
    text = svg("tweetkit-x — post_thread with images (MCP)", rows, size)
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "s.svg")
        open(src, "w").write(text)
        png = os.path.join(OUT, "01-mcp-thread.png")
        if shutil.which("rsvg-convert"):
            subprocess.run(["rsvg-convert", "-w", str(W * SCALE), "-h", str(H * SCALE), src, "-o", png], check=True)
        else:
            chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            subprocess.run([chrome, "--headless", "--screenshot=" + png, "--window-size=%d,%d" % (W, H),
                            "--force-device-scale-factor=%d" % SCALE, "file://" + src], check=True, capture_output=True)
    print("docs/assets/screenshots/01-mcp-thread.png (font %dpx, %d lines)" % (size, len(rows)))


if __name__ == "__main__":
    main()
