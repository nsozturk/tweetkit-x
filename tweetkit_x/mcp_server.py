"""tweetkit-x MCP server (FastMCP).

Exposes your X (Twitter) web session to any MCP client (Claude Desktop, Claude
Code, Cursor, …) as tools: post, thread, delete, read, search — plus friction-
free **auth setup** tools that explain exactly what the session cookie is and
how to get it.

Run:  tweetkit-mcp        (installed console script)
  or: python -m tweetkit_x.mcp_server
"""
import os

from mcp.server.fastmcp import FastMCP

from . import importer
from .client import TweetKit
from .cookie import save_cookie, CookieError

INSTRUCTIONS = """\
tweetkit posts, deletes and reads on X (Twitter) using the user's OWN logged-in
browser session — NOT the paid X API. It needs one secret: the X **session
cookie**.

The two required cookie values:
  • auth_token — the login/session token (HttpOnly, so it is hidden from
    document.cookie in the JS console; you can't just copy it from there).
  • ct0        — the CSRF token, echoed back to X as the x-csrf-token header.

If `auth_status` says not authenticated, help the user run ONE of:
  1. set_session_cookie(cookie_header) — the user opens x.com (logged in),
     DevTools (F12) → Network → clicks any request to x.com → Request Headers →
     copies the WHOLE `cookie:` value → pastes it here. Easiest, one paste.
  2. import_cookie_from_file(path) — the user saved a HAR (F12 → check
     "Preserve log" → right-click a request → Save all as HAR) or a storage-dump
     .zip (a browser extension that exports cookies.json). Point this tool at it.

Never print the cookie value back to the user. Posting/deleting affects a real,
public account — confirm the exact text/ids with the user before acting.
"""

mcp = FastMCP("tweetkit-x", instructions=INSTRUCTIONS)

# Where a freshly-set cookie is persisted. If TWEETKIT_COOKIE_KEYCHAIN is set we
# use the macOS Keychain; otherwise ~/.config/tweetkit/cookie.txt.
_KEYCHAIN = os.environ.get("TWEETKIT_COOKIE_KEYCHAIN")
_tk = None  # lazily-built TweetKit


def _get_tk():
    """Return (TweetKit, None) or (None, guidance_string) if not authenticated."""
    global _tk
    if _tk is not None:
        return _tk, None
    try:
        _tk = TweetKit(keychain_slug=_KEYCHAIN)
        return _tk, None
    except CookieError:
        return None, ("Not authenticated yet. Ask the user for their X session "
                      "cookie and call set_session_cookie(cookie_header), or "
                      "import_cookie_from_file(path) for a HAR / storage-dump zip. "
                      "See this server's instructions for how the user obtains it.")
    except ValueError as e:
        return None, f"Stored cookie is incomplete: {e}. Re-run set_session_cookie."


def _persist_and_reload(pairs):
    global _tk
    cookie_str = importer.to_cookie_string(pairs)
    where = save_cookie(cookie_str, keychain_slug=_KEYCHAIN)
    _tk = TweetKit(cookie=cookie_str)  # validate + activate immediately
    return where


# --------------------------------------------------------------------- auth
@mcp.tool()
def auth_status() -> dict:
    """Check whether tweetkit has a valid X session cookie loaded.

    Returns {authenticated, user_id, source_hint}. Call this first; if it is not
    authenticated, guide the user through set_session_cookie / import_cookie_from_file.
    """
    tk, err = _get_tk()
    if err:
        return {"authenticated": False, "help": err}
    who = tk.whoami()
    return {"authenticated": bool(who["ready"]), "user_id": who["user_id"],
            "ct0_len": who["ct0_len"]}


@mcp.tool()
def set_session_cookie(cookie_header: str) -> dict:
    """Set the X session cookie from a pasted `Cookie:` header — the easiest setup.

    HOW THE USER GETS IT (tell them this):
      1. Open x.com while logged in.
      2. Press F12 → the Network tab.
      3. Click any request to x.com (e.g. "HomeTimeline").
      4. Under "Request Headers", find the `cookie:` line and copy its ENTIRE value.
      5. Paste that whole string as `cookie_header`.

    The string must contain auth_token (the HttpOnly session token) and ct0 (the
    CSRF token). tweetkit keeps only the cookies it needs, persists them, and
    activates the session. The raw value is never echoed back.
    """
    pairs = importer.from_cookie_header(cookie_header)
    summary = importer.summarize(pairs)
    if not summary["ok"]:
        return {"ok": False, "missing_required": summary["missing_required"],
                "found": list(summary["found"].keys()),
                "hint": ("The pasted header is missing auth_token and/or ct0. Make sure "
                         "you copied the request `cookie:` header from a logged-in x.com "
                         "request (not document.cookie, which hides auth_token).")}
    where = _persist_and_reload(pairs)
    return {"ok": True, "saved_to": where, "found": summary["found"],
            "user_id": _tk.whoami()["user_id"]}


@mcp.tool()
def import_cookie_from_file(path: str) -> dict:
    """Set the X session cookie from a file on disk: HAR, storage-dump .zip, or cookie JSON.

    Accepts:
      • a .har  — F12 → check "Preserve log" → right-click a request → "Save all
        as HAR". (If Chrome scrubbed sensitive data, auth_token will be missing;
        fall back to set_session_cookie with a hand-copied header.)
      • a .zip  — a storage-dump extension export containing cookies.json.
      • a .json — a Cookie-Editor / EditThisCookie export.

    Returns which cookies were found (names + lengths, never values).
    """
    if not os.path.isfile(path):
        return {"ok": False, "error": f"file not found: {path}"}
    try:
        pairs = importer.autodetect(path)
    except Exception as e:
        return {"ok": False, "error": f"could not parse {path}: {e}"}
    summary = importer.summarize(pairs)
    if not summary["ok"]:
        return {"ok": False, "missing_required": summary["missing_required"],
                "found": list(summary["found"].keys()),
                "hint": ("auth_token/ct0 missing. A HAR exported by modern Chrome is "
                         "often scrubbed — use set_session_cookie with a hand-copied "
                         "`cookie:` header, or a storage-dump zip instead.")}
    where = _persist_and_reload(pairs)
    return {"ok": True, "saved_to": where, "found": summary["found"],
            "user_id": _tk.whoami()["user_id"]}


# --------------------------------------------------------------------- write
@mcp.tool()
def post_tweet(text: str, image_path: str = "", reply_to: str = "") -> dict:
    """Post a tweet. Optionally attach one image (local path) and/or reply to a tweet id.

    Returns {ok, id, url}. This publishes to the user's real, public account —
    confirm the wording with the user first.
    """
    tk, err = _get_tk()
    if err:
        return {"ok": False, "error": err}
    return tk.post(text, image_path=image_path or None, reply_to=reply_to or None)


@mcp.tool()
def post_thread(tweets: list[str]) -> list[dict]:
    """Post a thread: a list of tweet texts, each auto-replying to the previous one.

    Returns one {ok,id,url} per tweet. Stops early if a tweet fails.
    """
    tk, err = _get_tk()
    if err:
        return [{"ok": False, "error": err}]
    return tk.post_thread(list(tweets))


@mcp.tool()
def delete_tweet(tweet_id: str) -> dict:
    """Delete one of the authenticated user's tweets by id. Irreversible — confirm first."""
    tk, err = _get_tk()
    if err:
        return {"ok": False, "error": err}
    return tk.delete(tweet_id)


@mcp.tool()
def delete_tweets(tweet_ids: list[str]) -> list[dict]:
    """Delete several tweets by id. Irreversible — confirm the exact list with the user first."""
    tk, err = _get_tk()
    if err:
        return [{"ok": False, "error": err}]
    return tk.delete_many(list(tweet_ids))


@mcp.tool()
def quote_tweet(text: str, quote_tweet_id: str, image_path: str = "") -> dict:
    """Quote-tweet an existing tweet (embed it with your own commentary). Optional image."""
    tk, err = _get_tk()
    if err:
        return {"ok": False, "error": err}
    return tk.quote(text, quote_tweet_id, image_path=image_path or None)


@mcp.tool()
def like_tweet(tweet_id: str) -> dict:
    """Like a tweet."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.like(tweet_id)


@mcp.tool()
def unlike_tweet(tweet_id: str) -> dict:
    """Remove a like from a tweet."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.unlike(tweet_id)


@mcp.tool()
def retweet(tweet_id: str) -> dict:
    """Repost (retweet) a tweet."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.retweet(tweet_id)


@mcp.tool()
def unretweet(tweet_id: str) -> dict:
    """Undo a repost. Pass the id of the ORIGINAL tweet that was retweeted."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.unretweet(tweet_id)


@mcp.tool()
def bookmark_tweet(tweet_id: str) -> dict:
    """Bookmark a tweet (private — invisible to others)."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.bookmark(tweet_id)


@mcp.tool()
def unbookmark_tweet(tweet_id: str) -> dict:
    """Remove a bookmark."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.unbookmark(tweet_id)


# ---------------------------------------------------------------------- read
def _fmt(tweets):
    return [{"id": t["id"], "text": t["text"], "created_at": t["created_at"],
             "likes": t["likes"], "retweets": t["retweets"], "replies": t["replies"],
             "url": t["url"]} for t in tweets]


@mcp.tool()
def get_my_tweets(limit: int = 100) -> list[dict]:
    """List the authenticated user's own recent tweets (newest first)."""
    tk, err = _get_tk()
    if err:
        return [{"error": err}]
    return _fmt(tk.get_tweets(limit=limit))


@mcp.tool()
def get_user_tweets(username: str, limit: int = 100) -> list[dict]:
    """List a given @username's recent tweets (newest first)."""
    tk, err = _get_tk()
    if err:
        return [{"error": err}]
    return _fmt(tk.get_tweets(username=username, limit=limit))


@mcp.tool()
def search_my_tweets(query: str, regex: bool = False, limit: int = 200) -> list[dict]:
    """Find the authenticated user's own tweets matching `query`.

    Local filter over your timeline (X's search API is not used). Set regex=True
    to treat `query` as a case-insensitive regular expression — handy for
    cleaning up, e.g. search_my_tweets("xmr|monero", regex=True).
    """
    tk, err = _get_tk()
    if err:
        return [{"error": err}]
    return _fmt(tk.search(query, limit=limit, regex=regex))


@mcp.tool()
def get_tweet(tweet_id: str) -> dict:
    """Fetch a single tweet by id (text, author, counts, url)."""
    tk, err = _get_tk()
    if err:
        return {"ok": False, "error": err}
    return tk.get_tweet(tweet_id)


@mcp.tool()
def search_x(query: str, latest: bool = False, limit: int = 40) -> list[dict]:
    """Search ALL of X — the real search engine, not a local filter.

    Supports X search operators: `from:user`, `to:user`, `#hashtag`, `min_faves:100`,
    `filter:media`, `since:2026-01-01`, etc. Set latest=True for newest-first
    (default is Top). Returns tweets from across X.
    """
    tk, err = _get_tk()
    if err:
        return [{"error": err}]
    return _fmt(tk.search_x(query, product="Latest" if latest else "Top", limit=limit))


def main():
    mcp.run()


if __name__ == "__main__":
    main()
