"""tweetkit-x MCP server (FastMCP).

Exposes your X (Twitter) web session to any MCP client (Claude Desktop, Claude
Code, Cursor, …) as tools: post, thread, delete, read, search — plus friction-
free **auth setup** tools that explain exactly what the session cookie is and
how to get it.

Run:  tweetkit-mcp        (installed console script)
  or: python -m tweetkit_x.mcp_server
"""
import os
import sys

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
      • a .zip  — an export from the `storagedump` Chrome extension
        (https://chromewebstore.google.com/detail/storagedump/kihoghfekemdccfnpjefmggehpgnjnab),
        which can read the HttpOnly auth_token; contains cookies.json.
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


# --------------------------------------------------------- compose (more)
@mcp.tool()
def post_note(text: str, image_path: str = "", reply_to: str = "") -> dict:
    """Post a long-form (note) tweet — beyond the 280-char limit. Confirm the text first."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.post_note(text, image_path=image_path or None, reply_to=reply_to or None)


@mcp.tool()
def schedule_tweet(text: str, at_epoch: int) -> dict:
    """Schedule a tweet for a future unix timestamp (seconds since epoch)."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.schedule(text, at_epoch)


@mcp.tool()
def unschedule_tweet(scheduled_tweet_id: str) -> dict:
    """Cancel a previously scheduled tweet."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.unschedule(scheduled_tweet_id)


# ---------------------------------------------------- social graph actions
@mcp.tool()
def follow_user(username: str, notify: bool = False, dry_run: bool = False) -> dict:
    """Follow @username. notify=True also turns on the bell (notify on all their posts),
    the same two calls x.com makes. dry_run=True sends nothing and returns the exact
    requests. Acts on the user's real account — confirm first. (Undo: unfollow_user.)"""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.follow(username, notify=notify, dry_run=dry_run)


@mcp.tool()
def unfollow_user(username: str) -> dict:
    """Unfollow @username."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.unfollow(username)


@mcp.tool()
def block_user(username: str) -> dict:
    """Block @username. Confirm first."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.block(username)


@mcp.tool()
def unblock_user(username: str) -> dict:
    """Unblock @username."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.unblock(username)


@mcp.tool()
def mute_user(username: str) -> dict:
    """Mute @username (silent — they aren't notified)."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.mute(username)


@mcp.tool()
def unmute_user(username: str) -> dict:
    """Unmute @username."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.unmute(username)


@mcp.tool()
def pin_tweet(tweet_id: str) -> dict:
    """Pin one of your tweets to your profile."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.pin(tweet_id)


@mcp.tool()
def unpin_tweet(tweet_id: str) -> dict:
    """Unpin your pinned tweet."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.unpin(tweet_id)


# ------------------------------------------------------------- reads (more)
def _fmt_users(users):
    return [{"username": u["username"], "name": u.get("name"), "followers": u.get("followers"),
             "verified": u.get("verified"), "url": u["url"]} for u in users]


@mcp.tool()
def get_home_timeline(following: bool = False, limit: int = 40) -> list[dict]:
    """Your home feed. following=True → 'Following' (chronological); else 'For You'."""
    tk, err = _get_tk()
    return [{"error": err}] if err else _fmt(tk.home_timeline(following=following, limit=limit))


@mcp.tool()
def get_replies(tweet_id: str, limit: int = 50) -> list[dict]:
    """Fetch a tweet's conversation (its replies)."""
    tk, err = _get_tk()
    return [{"error": err}] if err else _fmt(tk.get_replies(tweet_id, limit=limit))


@mcp.tool()
def get_bookmarks(limit: int = 100) -> list[dict]:
    """Your bookmarked tweets."""
    tk, err = _get_tk()
    return [{"error": err}] if err else _fmt(tk.bookmarks(limit=limit))


@mcp.tool()
def get_user_likes(username: str, limit: int = 100) -> list[dict]:
    """Tweets a user has liked."""
    tk, err = _get_tk()
    return [{"error": err}] if err else _fmt(tk.user_likes(username, limit=limit))


@mcp.tool()
def get_notifications(limit: int = 40) -> list[dict]:
    """Your notifications timeline (mentions / engagement)."""
    tk, err = _get_tk()
    return [{"error": err}] if err else _fmt(tk.notifications(limit=limit))


@mcp.tool()
def get_user_profile(username: str) -> dict:
    """A user's full profile: name, bio, follower/following/tweet counts, verified, created_at."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.user_profile(username)


@mcp.tool()
def get_followers(username: str, limit: int = 100) -> list[dict]:
    """A user's followers."""
    tk, err = _get_tk()
    return [{"error": err}] if err else _fmt_users(tk.followers(username, limit=limit))


@mcp.tool()
def get_following(username: str, limit: int = 100) -> list[dict]:
    """Accounts a user follows."""
    tk, err = _get_tk()
    return [{"error": err}] if err else _fmt_users(tk.following(username, limit=limit))


@mcp.tool()
def get_likers(tweet_id: str, limit: int = 100) -> list[dict]:
    """Users who liked a tweet."""
    tk, err = _get_tk()
    return [{"error": err}] if err else _fmt_users(tk.likers(tweet_id, limit=limit))


@mcp.tool()
def get_retweeters(tweet_id: str, limit: int = 100) -> list[dict]:
    """Users who retweeted a tweet."""
    tk, err = _get_tk()
    return [{"error": err}] if err else _fmt_users(tk.retweeters(tweet_id, limit=limit))


# ------------------------------------- per-account notifications ("bell")
@mcp.tool()
def get_friendship(username: str) -> dict:
    """Your relationship with @username and its per-account notification settings:
    following, followed_by, follow_requested, notifications (bell = all posts),
    live_notifications (live video), want_retweets (their reposts shown), muting, blocking."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.friendship(username)


@mcp.tool()
def set_user_notifications(username: str, on: bool = True, kind: str = "posts",
                           dry_run: bool = False) -> dict:
    """Turn the per-account bell on/off for an account you follow.

    kind="posts" → notifications for all their posts (the profile bell).
    kind="live"  → notifications when they go live.
    X keeps these as two independent switches; "off" = posts off (and live off if wanted).
    dry_run=True returns the exact request without sending it. Confirm with the user first.
    """
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.set_notifications(username, on, kind=kind, dry_run=dry_run)


@mcp.tool()
def set_user_retweets(username: str, on: bool = True, dry_run: bool = False) -> dict:
    """Show (on) or hide (off) @username's reposts in your timeline."""
    tk, err = _get_tk()
    return {"ok": False, "error": err} if err else tk.set_retweets(username, on, dry_run=dry_run)


def _stderr_log(msg):
    print(msg, file=sys.stderr, flush=True)  # stdout is the MCP stdio channel


@mcp.tool()
def bulk_follow(usernames: list[str], notify: bool = True, max_actions: int = 5,
                journal_path: str = "", dry_run: bool = False,
                capture_suggestions: bool = True) -> dict:
    """Follow many accounts (and turn their bell on), resumably and rate-limited.

    Per account: read friendships/show → skip if already followed (+bell on) →
    follow → 2–6 s → bell on → save X's post-follow suggestions to the local DB.
    30–75 s jitter between accounts. Writes at most `max_actions` accounts per call:
    CALL AGAIN with the same journal_path to continue — finished accounts are skipped.
    Stops at once on 429 / rate-limit / follow-limit / lock (counts.stopped > 0):
    then wait hours before calling again. For long lists prefer the CLI
    (`tweetkit bulk-follow`). Only run on a list the user explicitly approved;
    try dry_run=True first (journals to <journal>.dryrun.jsonl, sends nothing).
    """
    tk, err = _get_tk()
    if err:
        return {"ok": False, "error": err}
    return tk.bulk_follow(list(usernames), notify=notify, journal_path=journal_path or None,
                          dry_run=dry_run, max_actions=max_actions,
                          capture_suggestions=capture_suggestions, log=_stderr_log)


@mcp.tool()
def bulk_set_notifications(usernames: list[str], on: bool = True, kind: str = "posts",
                           max_actions: int = 10, journal_path: str = "",
                           dry_run: bool = False) -> dict:
    """Turn the bell on/off for many accounts you already follow — resumable like bulk_follow
    (skips accounts already in the wanted state; call again with the same journal_path)."""
    tk, err = _get_tk()
    if err:
        return {"ok": False, "error": err}
    return tk.bulk_notifications(list(usernames), on=on, kind=kind,
                                 journal_path=journal_path or None, dry_run=dry_run,
                                 max_actions=max_actions, log=_stderr_log)


# ------------------------------------------------------- account suggestions
@mcp.tool()
def get_suggestions(source: str = "follow", username: str = "", limit: int = 20,
                    save: bool = True) -> dict:
    """Fetch X's account suggestions and append them (raw + parsed) to the local SQLite store.

    source="follow"  — what x.com recommends right after following @username (needs username).
    source="sidebar" — the "You might like" box on @username's profile (needs username).
    source="connect" — the general "Who to follow" / Connect tab; with username →
                       accounts similar to @username.
    Read-only on X. Returns {ok, count, users[{id, username, name, bio, followers, ...}], db}.
    """
    tk, err = _get_tk()
    if err:
        return {"ok": False, "error": err}
    return tk.suggestions(source, username or None, limit=limit, save=save)


@mcp.tool()
def list_saved_suggestions(for_username: str = "", source: str = "", distinct: bool = True,
                           limit: int = 200) -> list[dict]:
    """List suggestions saved in the local store (newest first). distinct=True keeps the
    latest row per suggested account; for_username filters by the account they were suggested for."""
    from . import store
    db = store.connect()
    try:
        return store.list_suggestions(db, for_username=for_username or None, source=source or None,
                                      distinct=distinct, limit=limit)
    finally:
        db.close()


@mcp.tool()
def export_saved_suggestions(path: str, for_username: str = "", source: str = "",
                             distinct: bool = True) -> dict:
    """Export saved suggestions to a .csv / .json / .jsonl file (format from the extension)."""
    from . import store
    db = store.connect()
    try:
        n = store.export(db, os.path.expanduser(path), for_username=for_username or None,
                         source=source or None, distinct=distinct)
    finally:
        db.close()
    return {"ok": True, "rows": n, "path": os.path.expanduser(path)}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
