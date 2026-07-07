"""tweetkit-x command-line interface.

    tweetkit import --paste                 # paste a Cookie: header, then Ctrl-D
    tweetkit import --file x.com.har         # HAR / storagedump.zip / cookie json
    tweetkit import --file dump.zip --keychain tweetkit
    tweetkit whoami
    tweetkit post "hello world"
    tweetkit post "with a pic" --image pic.png
    tweetkit post "a reply" --reply-to 1800000000000000000
    tweetkit thread thread.txt               # tweets separated by blank lines
    tweetkit delete 1800000000000000000 [more_ids...]
    tweetkit tweets [@user] --limit 100      # list tweets (default: you)
    tweetkit search monero [@user] --regex   # filter your tweets

Cookie source for all commands: --keychain <slug> / --cookie-file <path>, else
the env / default-file resolution described in `tweetkit.cookie`.
"""
import argparse
import json
import sys

from . import importer
from .client import TweetKit
from .cookie import save_cookie, CookieError


def _kw(a):
    return {"cookie_file": getattr(a, "cookie_file", None),
            "keychain_slug": getattr(a, "keychain", None)}


def _cmd_import(a):
    if a.paste:
        sys.stderr.write("Paste your `Cookie:` header, then press Ctrl-D:\n")
        pairs = importer.from_cookie_header(sys.stdin.read())
    elif a.file:
        pairs = importer.autodetect(a.file)
    else:
        print("give --paste or --file <har|zip|json|txt>", file=sys.stderr)
        return 1

    summary = importer.summarize(pairs)
    print(json.dumps(summary, indent=2))
    if not summary["ok"]:
        print(f"\n✗ missing required cookie(s): {', '.join(summary['missing_required'])}.\n"
              "  If this came from a HAR, it was probably scrubbed of sensitive data — "
              "copy the `Cookie:` header by hand (README Method A) or use a storage-dump zip.",
              file=sys.stderr)
        return 1
    where = save_cookie(importer.to_cookie_string(pairs),
                        out_file=a.out, keychain_slug=a.keychain)
    print(f"\n✓ cookie saved → {where}")
    return 0


def _cmd_whoami(a):
    print(json.dumps(TweetKit(**_kw(a)).whoami()))
    return 0


def _cmd_post(a):
    r = TweetKit(**_kw(a)).post(a.text, image_path=a.image, reply_to=a.reply_to)
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


def _cmd_thread(a):
    blocks = [b.strip() for b in open(a.file).read().split("\n\n") if b.strip()]
    if not blocks:
        print("thread file is empty", file=sys.stderr)
        return 1
    results = TweetKit(**_kw(a)).post_thread(blocks)
    for i, r in enumerate(results, 1):
        print(f"[{i}/{len(blocks)}] " + json.dumps(r, ensure_ascii=False))
    return 0 if all(r.get("ok") for r in results) else 1


def _cmd_delete(a):
    results = TweetKit(**_kw(a)).delete_many(a.ids)
    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    return 0 if all(r.get("ok") for r in results) else 1


def _cmd_tweets(a):
    tk = TweetKit(**_kw(a))
    tweets = tk.get_tweets(username=a.user, limit=a.limit)
    for t in tweets:
        print(f"[{t['created_at']}] {t['url']}")
        print(f"  ❤{t['likes']} 🔁{t['retweets']} 💬{t['replies']}")
        print("  " + t["text"].replace("\n", "\n  "))
        print()
    print(f"# {len(tweets)} tweet", file=sys.stderr)
    return 0


def _cmd_search(a):
    tk = TweetKit(**_kw(a))
    tweets = tk.search(a.query, username=a.user, limit=a.limit, regex=a.regex)
    for t in tweets:
        print(f"[{t['created_at']}] {t['url']}")
        print("  " + t["text"].replace("\n", "\n  "))
        print()
    print(f"# {len(tweets)} match", file=sys.stderr)
    return 0


def _cmd_searchx(a):
    tk = TweetKit(**_kw(a))
    product = "Latest" if a.latest else "Top"
    tweets = tk.search_x(a.query, product=product, limit=a.limit)
    for t in tweets:
        print(f"[{t['created_at']}] @{t['author']} {t['url']}")
        print(f"  ❤{t['likes']} 🔁{t['retweets']}  " + t["text"][:180].replace("\n", " "))
        print()
    print(f"# {len(tweets)} results (all of X, product={product})", file=sys.stderr)
    return 0


def _cmd_get(a):
    r = TweetKit(**_kw(a)).get_tweet(a.id)
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


def _cmd_quote(a):
    r = TweetKit(**_kw(a)).quote(a.text, a.quote_id, image_path=a.image)
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


def _engage(a, method):
    tk = TweetKit(**_kw(a))
    fn = getattr(tk, method)
    ok = True
    for tid in a.ids:
        r = fn(tid)
        print(json.dumps({**r, "tweet_id": tid}, ensure_ascii=False))
        ok = ok and r.get("ok")
    return 0 if ok else 1


def _print_tweets(tweets):
    for t in tweets:
        print(f"[{t['created_at']}] @{t['author']} {t['url']}")
        print("  " + t["text"][:160].replace("\n", " "))
    print(f"# {len(tweets)} tweets", file=sys.stderr)
    return 0


def _print_users(users):
    for u in users:
        print(f"@{u['username']}  {u.get('name') or ''}  ({u.get('followers','?')} followers)  {u['url']}")
    print(f"# {len(users)} users", file=sys.stderr)
    return 0


def _cmd_note(a):
    r = TweetKit(**_kw(a)).post_note(a.text, image_path=a.image, reply_to=a.reply_to)
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


def _cmd_schedule(a):
    r = TweetKit(**_kw(a)).schedule(a.text, a.at, image_path=a.image)
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


def _cmd_unschedule(a):
    r = TweetKit(**_kw(a)).unschedule(a.id)
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


def _cmd_profile(a):
    print(json.dumps(TweetKit(**_kw(a)).user_profile(a.user), ensure_ascii=False))
    return 0


def _cmd_home(a):
    return _print_tweets(TweetKit(**_kw(a)).home_timeline(following=a.following, limit=a.limit))


def _cmd_replies(a):
    return _print_tweets(TweetKit(**_kw(a)).get_replies(a.id, limit=a.limit))


def _cmd_bookmarks(a):
    return _print_tweets(TweetKit(**_kw(a)).bookmarks(limit=a.limit))


def _cmd_likes(a):
    return _print_tweets(TweetKit(**_kw(a)).user_likes(a.user, limit=a.limit))


def _cmd_notifications(a):
    return _print_tweets(TweetKit(**_kw(a)).notifications(limit=a.limit))


def _cmd_followers(a):
    return _print_users(TweetKit(**_kw(a)).followers(a.user, limit=a.limit))


def _cmd_following(a):
    return _print_users(TweetKit(**_kw(a)).following(a.user, limit=a.limit))


def _cmd_likers(a):
    return _print_users(TweetKit(**_kw(a)).likers(a.id, limit=a.limit))


def _cmd_retweeters(a):
    return _print_users(TweetKit(**_kw(a)).retweeters(a.id, limit=a.limit))


def _user_action(a, method):
    r = getattr(TweetKit(**_kw(a)), method)(a.user)
    print(json.dumps({**r, "user": a.user}, ensure_ascii=False))
    return 0 if r.get("ok") else 1


def _tweet_action(a, method):
    r = getattr(TweetKit(**_kw(a)), method)(a.id)
    print(json.dumps({**r, "id": a.id}, ensure_ascii=False))
    return 0 if r.get("ok") else 1


def build_parser():
    ap = argparse.ArgumentParser(prog="tweetkit",
                                 description="Post/delete/read on X via your web session (no paid API).")
    ap.add_argument("--cookie-file", help="path to a file holding the cookie string")
    ap.add_argument("--keychain", help="macOS Keychain slug holding the cookie")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", help="import your session cookie")
    p.add_argument("--paste", action="store_true", help="read a Cookie header from stdin")
    p.add_argument("--file", help="HAR / storagedump.zip / cookie-editor.json / cookie.txt")
    p.add_argument("--out", help="write cookie to this file (default ~/.config/tweetkit/cookie.txt)")
    p.set_defaults(func=_cmd_import)

    p = sub.add_parser("whoami", help="auth check (no network)")
    p.set_defaults(func=_cmd_whoami)

    p = sub.add_parser("post", help="post a tweet")
    p.add_argument("text")
    p.add_argument("--image", "-i", help="attach an image")
    p.add_argument("--reply-to", help="tweet id to reply to")
    p.set_defaults(func=_cmd_post)

    p = sub.add_parser("thread", help="post a thread from a blank-line-separated file")
    p.add_argument("file")
    p.set_defaults(func=_cmd_thread)

    p = sub.add_parser("delete", help="delete one or more tweet ids")
    p.add_argument("ids", nargs="+")
    p.set_defaults(func=_cmd_delete)

    p = sub.add_parser("tweets", help="list a user's tweets (default: you)")
    p.add_argument("user", nargs="?", help="@username (omit for your own)")
    p.add_argument("--limit", type=int, default=100)
    p.set_defaults(func=_cmd_tweets)

    p = sub.add_parser("search", help="filter a user's tweets (default: yours)")
    p.add_argument("query")
    p.add_argument("user", nargs="?", help="@username (omit for your own)")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--regex", action="store_true", help="treat query as a regex")
    p.set_defaults(func=_cmd_search)

    p = sub.add_parser("searchx", help="search ALL of X (real search, supports operators)")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--latest", action="store_true", help="newest first (else Top)")
    p.set_defaults(func=_cmd_searchx)

    p = sub.add_parser("get", help="fetch a single tweet by id")
    p.add_argument("id")
    p.set_defaults(func=_cmd_get)

    p = sub.add_parser("quote", help="quote-tweet an existing tweet")
    p.add_argument("text")
    p.add_argument("quote_id", help="id of the tweet to quote")
    p.add_argument("--image", "-i", help="attach an image")
    p.set_defaults(func=_cmd_quote)

    for name, method, helptext in [
        ("like", "like", "like tweet(s)"),
        ("unlike", "unlike", "remove like(s)"),
        ("retweet", "retweet", "repost tweet(s)"),
        ("unretweet", "unretweet", "undo repost(s) (pass original id)"),
        ("bookmark", "bookmark", "bookmark tweet(s) (private)"),
        ("unbookmark", "unbookmark", "remove bookmark(s)"),
    ]:
        p = sub.add_parser(name, help=helptext)
        p.add_argument("ids", nargs="+")
        p.set_defaults(func=(lambda m: (lambda a: _engage(a, m)))(method))

    # compose (more)
    p = sub.add_parser("note", help="post a long-form (note) tweet, over 280 chars")
    p.add_argument("text"); p.add_argument("--image", "-i"); p.add_argument("--reply-to")
    p.set_defaults(func=_cmd_note)
    p = sub.add_parser("schedule", help="schedule a tweet for a unix timestamp")
    p.add_argument("text"); p.add_argument("at", type=int, help="unix epoch seconds")
    p.add_argument("--image", "-i"); p.set_defaults(func=_cmd_schedule)
    p = sub.add_parser("unschedule", help="cancel a scheduled tweet")
    p.add_argument("id"); p.set_defaults(func=_cmd_unschedule)

    # reads (more)
    p = sub.add_parser("home", help="your home feed"); p.add_argument("--following", action="store_true")
    p.add_argument("--limit", type=int, default=40); p.set_defaults(func=_cmd_home)
    p = sub.add_parser("replies", help="a tweet's conversation/replies")
    p.add_argument("id"); p.add_argument("--limit", type=int, default=50); p.set_defaults(func=_cmd_replies)
    p = sub.add_parser("bookmarks", help="your bookmarks")
    p.add_argument("--limit", type=int, default=100); p.set_defaults(func=_cmd_bookmarks)
    p = sub.add_parser("likes", help="tweets a user has liked")
    p.add_argument("user"); p.add_argument("--limit", type=int, default=100); p.set_defaults(func=_cmd_likes)
    p = sub.add_parser("notifications", help="your notifications")
    p.add_argument("--limit", type=int, default=40); p.set_defaults(func=_cmd_notifications)
    p = sub.add_parser("profile", help="a user's full profile")
    p.add_argument("user"); p.set_defaults(func=_cmd_profile)
    p = sub.add_parser("followers", help="a user's followers")
    p.add_argument("user"); p.add_argument("--limit", type=int, default=100); p.set_defaults(func=_cmd_followers)
    p = sub.add_parser("following", help="who a user follows")
    p.add_argument("user"); p.add_argument("--limit", type=int, default=100); p.set_defaults(func=_cmd_following)
    p = sub.add_parser("likers", help="who liked a tweet")
    p.add_argument("id"); p.add_argument("--limit", type=int, default=100); p.set_defaults(func=_cmd_likers)
    p = sub.add_parser("retweeters", help="who retweeted a tweet")
    p.add_argument("id"); p.add_argument("--limit", type=int, default=100); p.set_defaults(func=_cmd_retweeters)

    # social graph — user actions
    for name, method in [("follow", "follow"), ("unfollow", "unfollow"), ("block", "block"),
                         ("unblock", "unblock"), ("mute", "mute"), ("unmute", "unmute")]:
        p = sub.add_parser(name, help=f"{name} a user")
        p.add_argument("user")
        p.set_defaults(func=(lambda m: (lambda a: _user_action(a, m)))(method))
    # pin/unpin — tweet actions
    for name, method in [("pin", "pin"), ("unpin", "unpin")]:
        p = sub.add_parser(name, help=f"{name} a tweet")
        p.add_argument("id")
        p.set_defaults(func=(lambda m: (lambda a: _tweet_action(a, m)))(method))

    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        return a.func(a)
    except CookieError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
