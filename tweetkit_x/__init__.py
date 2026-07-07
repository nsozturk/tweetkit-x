"""tweetkit-x — post, delete & read on X (Twitter) from Python & MCP,
using your own logged-in web session. No paid API, no developer app.

    from tweetkit_x import TweetKit

    tk = TweetKit(keychain_slug="tweetkit")     # or cookie="auth_token=...; ct0=..."
    tk.post("hello world")
    tk.post_thread(["1/ intro", "2/ more", ("3/ chart", "chart.png")])
    tk.delete("1800000000000000000")
    tk.search("monero", regex=False)            # your tweets mentioning 'monero'
"""
from .client import TweetKit
from .cookie import load_cookie, save_cookie, parse_cookie, has_auth, CookieError
from . import importer

__all__ = ["TweetKit", "load_cookie", "save_cookie", "parse_cookie",
           "has_auth", "CookieError", "importer"]
__version__ = "0.3.0"
