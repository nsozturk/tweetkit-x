# AGENTS.md — tweetkit-x

Contract for coding agents (Claude Code, Codex, Gemini CLI, Cursor, OpenCode, Antigravity) that install, call or
change tweetkit-x.

tweetkit-x is a free, open-source Python library, CLI and MCP server that posts, deletes and reads on X (Twitter) with your own logged-in web session, including images and threads, with no paid API.

- Version: 0.5.0 · Python 3.10+ · MIT
- Repo: https://github.com/nsozturk/tweetkit-x · Docs: https://nsozturk.github.io/tweetkit-x/
- Code: `tweetkit_x/client.py` (the `TweetKit` class), `tweetkit_x/mcp_server.py` (48 MCP tools),
  `tweetkit_x/cli.py` (the `tweetkit` command), `tweetkit_x/cookie.py` (cookie loading),
  `tweetkit_x/importer.py` (HAR / zip / JSON parsing), `tweetkit_x/constants.py` (GraphQL query ids),
  `tweetkit_x/store.py` (local SQLite for account suggestions).

---

## 1. Rules that come first

1. **Posting is public and acts on a real account.** Before any write (post, thread, quote, note, schedule,
   delete, like, retweet, follow, block, mute, pin, bell, bulk action), show the user the exact text, the exact
   files and the exact ids or handles, and get a yes. Deletes cannot be undone.
2. **Never print, log, commit or echo the cookie** (`auth_token`, `ct0`, or the whole `Cookie:` header). The
   importers report only cookie names and lengths; keep it that way.
3. **Account risk is real.** Automating the web session is against X's Terms of Service. X can rate-limit, lock
   or suspend the account. Do not promise otherwise.
4. **Respect rate limits.** On HTTP 429 or X error codes 88 / 161 / 185 / 326 / 64, stop writing and tell the
   user to wait (usually hours). Never retry in a loop.
5. Prefer `dry_run=True` first wherever a tool offers it (`follow_user`, `set_user_notifications`,
   `set_user_retweets`, `bulk_follow`, `bulk_set_notifications`).

---

## 2. Install

```bash
# 0.5.0 from the GitHub release tag (PyPI still serves 0.3.0, without the 0.5.0 MCP media features)
pip install "tweetkit-x[mcp] @ git+https://github.com/nsozturk/tweetkit-x@v0.5.0"

# library + CLI only (no MCP dependency)
pip install "tweetkit-x @ git+https://github.com/nsozturk/tweetkit-x@v0.5.0"

# from a checkout
pip install -e ".[mcp]"
```

Console scripts: `tweetkit` (CLI) and `tweetkit-mcp` (MCP server over stdio). Also `python -m tweetkit_x.mcp_server`.

MCP client config:

```json
{
  "mcpServers": {
    "tweetkit": {
      "command": "uvx",
      "args": ["--from", "tweetkit-x[mcp] @ git+https://github.com/nsozturk/tweetkit-x@v0.5.0", "tweetkit-mcp"],
      "env": { "TWEETKIT_COOKIE_KEYCHAIN": "tweetkit" }
    }
  }
}
```

---

## 3. Auth

The only secret is the X session cookie. Required: `auth_token` (HttpOnly, so `document.cookie` does not show it)
and `ct0` (CSRF token, sent as `x-csrf-token`). Recommended: `twid` (`u=<id>`, gives the user id without a lookup).

Cookie sources, first hit wins (`tweetkit_x/cookie.py:load_cookie`):

1. explicit `cookie=` argument
2. env `TWEETKIT_COOKIE` (the full cookie string)
3. explicit `cookie_file=` argument / CLI `--cookie-file`
4. env `TWEETKIT_COOKIE_FILE`
5. `./cookie.txt` (current directory)
6. `~/.config/tweetkit/cookie.txt`
7. macOS Keychain service `<slug>` from `keychain_slug=` / CLI `--keychain` / env `TWEETKIT_COOKIE_KEYCHAIN`
   (read with `security find-generic-password`; macOS only)

None found → `CookieError`. Found but `auth_token` or `ct0` missing → `ValueError` from `TweetKit(...)`.

How the user gets the cookie (pick one):

- **Paste the header**: x.com logged in → DevTools (F12) → Network → any x.com request → Request Headers → copy the
  whole `cookie:` value. CLI: `tweetkit import --paste` (stdin, then Ctrl-D). MCP: `set_session_cookie(cookie_header)`.
- **HAR**: DevTools → Network → "Preserve log" → right-click → "Save all as HAR". Chrome may strip cookies; then use
  the header. CLI: `tweetkit import --file x.com.har`. MCP: `import_cookie_from_file(path)`.
- **storage-dump `.zip`** (contains `cookies.json`) or a Cookie-Editor / EditThisCookie `.json` export: same commands.

Saving: `tweetkit import` writes `~/.config/tweetkit/cookie.txt` (chmod 600) unless `--out <file>`; with the
**global** `--keychain <slug>` it writes the Keychain instead. The MCP server saves to the Keychain when
`TWEETKIT_COOKIE_KEYCHAIN` is set, else to `~/.config/tweetkit/cookie.txt`.

`--keychain` and `--cookie-file` are top-level options and must come **before** the subcommand:
`tweetkit --keychain tweetkit import --paste` works; `tweetkit import --paste --keychain tweetkit` exits 2.

Check without network: `tweetkit whoami` / `TweetKit().whoami()` / MCP `auth_status()`.

---

## 4. MCP tools (48)

`?` = optional. Defaults in brackets where they matter.

### Auth (3)

| Tool | Does |
|---|---|
| `auth_status()` | `{authenticated, user_id, ct0_len}` or `{authenticated: false, help}`. Call first |
| `set_session_cookie(cookie_header)` | Parse a pasted `Cookie:` header, save it, activate it |
| `import_cookie_from_file(path)` | Same from a `.har`, storage-dump `.zip` or cookie `.json` |

### Post and delete (8)

| Tool | Does |
|---|---|
| `post_tweet(text, image_path?, reply_to?, images?, alt_texts?)` | One tweet. `images` = up to 4 local files, `alt_texts` parallel list. If `images` is given, `image_path` is ignored |
| `post_thread(tweets)` | Thread. Item = text, or `{"text", "images", "alt_texts"}` (also `image_path`), up to 4 files per tweet |
| `quote_tweet(text, quote_tweet_id, image_path?)` | Quote-tweet, one optional image |
| `post_note(text, image_path?, reply_to?)` | Long-form note tweet (over 280 characters), one optional image |
| `schedule_tweet(text, at_epoch)` | Schedule for a unix timestamp in seconds (no media through MCP) |
| `unschedule_tweet(scheduled_tweet_id)` | Cancel a scheduled tweet |
| `delete_tweet(tweet_id)` | Delete one of your tweets. Irreversible |
| `delete_tweets(tweet_ids)` | Delete several. Irreversible |

### Engage (8)

| Tool | Does |
|---|---|
| `like_tweet(tweet_id)` | Like |
| `unlike_tweet(tweet_id)` | Remove like |
| `retweet(tweet_id)` | Repost |
| `unretweet(tweet_id)` | Undo repost; pass the ORIGINAL tweet id |
| `bookmark_tweet(tweet_id)` | Bookmark (private) |
| `unbookmark_tweet(tweet_id)` | Remove bookmark |
| `pin_tweet(tweet_id)` | Pin your tweet to your profile |
| `unpin_tweet(tweet_id)` | Unpin |

### Read and search (10)

| Tool | Does |
|---|---|
| `get_my_tweets(limit? [100])` | Your tweets, newest first |
| `get_user_tweets(username, limit? [100])` | A user's tweets, newest first |
| `search_my_tweets(query, regex? [false], limit? [200])` | Local filter over your timeline (regex is case-insensitive) |
| `get_tweet(tweet_id)` | One tweet: text, author, counts, url |
| `search_x(query, latest? [false], limit? [40])` | X's real search; operators like `from:`, `min_faves:`, `filter:media`, `since:` |
| `get_home_timeline(following? [false], limit? [40])` | Home feed: For You, or Following when `following=True` |
| `get_replies(tweet_id, limit? [50])` | A tweet's conversation |
| `get_bookmarks(limit? [100])` | Your bookmarks |
| `get_user_likes(username, limit? [100])` | Tweets a user liked |
| `get_notifications(limit? [40])` | Your notifications |

### People (6)

| Tool | Does |
|---|---|
| `get_user_profile(username)` | Name, bio, follower/following/tweet counts, verified, created_at |
| `get_followers(username, limit? [100])` | A user's followers |
| `get_following(username, limit? [100])` | Accounts a user follows |
| `get_likers(tweet_id, limit? [100])` | Users who liked a tweet |
| `get_retweeters(tweet_id, limit? [100])` | Users who retweeted a tweet |
| `get_friendship(username)` | following, followed_by, follow_requested, notifications, live_notifications, want_retweets, muting, blocking |

### Social graph (6)

| Tool | Does |
|---|---|
| `follow_user(username, notify? [false], dry_run? [false])` | Follow; `notify=True` also turns the bell on |
| `unfollow_user(username)` | Unfollow |
| `block_user(username)` | Block |
| `unblock_user(username)` | Unblock |
| `mute_user(username)` | Mute (silent) |
| `unmute_user(username)` | Unmute |

### Notifications and bulk (4)

| Tool | Does |
|---|---|
| `set_user_notifications(username, on? [true], kind? ["posts"], dry_run? [false])` | Per-account bell; `kind` = `posts` or `live` |
| `set_user_retweets(username, on? [true], dry_run? [false])` | Show / hide a user's reposts in your timeline |
| `bulk_follow(usernames, notify? [true], max_actions? [5], journal_path?, dry_run? [false], capture_suggestions? [true])` | Follow a list; at most `max_actions` writes per call; call again with the same `journal_path` to continue |
| `bulk_set_notifications(usernames, on? [true], kind? ["posts"], max_actions? [10], journal_path?, dry_run? [false])` | Bell on/off for a list, resumable the same way |

### Account suggestions (3)

| Tool | Does |
|---|---|
| `get_suggestions(source? ["follow"], username?, limit? [20], save? [true])` | X's suggestions (`follow` / `sidebar` need `username`; `connect` = Who to follow); saved to SQLite |
| `list_saved_suggestions(for_username?, source?, distinct? [true], limit? [200])` | Read the local store (no X call, no auth) |
| `export_saved_suggestions(path, for_username?, source?, distinct? [true])` | Write the store to `.csv` / `.json` / `.jsonl` (no X call, no auth) |

### Media and threads (0.5.0)

```python
post_thread(tweets=[
  {"text": "1/ I built a thing", "images": ["/abs/path/banner.png"], "alt_texts": ["Project banner"]},
  "2/ how it works ...",
  {"text": "3/ the result", "images": ["/abs/path/a.png", "/abs/path/b.png"]}
])
```

- Files are local paths on the machine running the MCP server; `~` is expanded. Use absolute paths.
- Types by extension: `.png .jpg .jpeg .webp .gif .mp4` (also `.mov .m4v`); an unknown extension is uploaded as
  `image/png`. Video and GIF uploads wait for X's processing.
- Up to 4 media per tweet. Alt text is optional, cut to 1,000 characters; extra alt texts are ignored.
- Every tweet is checked before the first one is posted: empty text, a missing file or more than 4 media →
  error, nothing posted.
- That check is not a transaction. Once posting starts, an upload or API failure stops the thread and the tweets
  already posted stay up. Read the returned list and report which tweets exist.
- Text is required on every tweet; there are no media-only tweets.

---

## 5. CLI

Global options (before the subcommand): `--cookie-file <path>`, `--keychain <slug>`.

| Command | Does |
|---|---|
| `tweetkit import --paste \| --file <har\|zip\|json\|txt> [--out <file>]` | Import and save the cookie |
| `tweetkit whoami` | Auth check, no network |
| `tweetkit post <text> [--image <file>] [--reply-to <id>]` | Post (one file) |
| `tweetkit thread <file>` | Thread from a file, tweets separated by blank lines (text only) |
| `tweetkit delete <id> [<id> ...]` | Delete |
| `tweetkit tweets [@user] [--limit 100]` | List tweets (default: yours) |
| `tweetkit search <query> [@user] [--limit 200] [--regex]` | Local filter over a timeline |
| `tweetkit searchx <query> [--limit 40] [--latest]` | Search all of X |
| `tweetkit get <id>` | One tweet |
| `tweetkit quote <text> <quote_id> [--image <file>]` | Quote-tweet |
| `tweetkit like\|unlike\|retweet\|unretweet\|bookmark\|unbookmark <id> [<id> ...]` | Engage |
| `tweetkit note <text> [--image <file>] [--reply-to <id>]` | Long-form note tweet |
| `tweetkit schedule <text> <epoch> [--image <file>]` | Schedule |
| `tweetkit unschedule <id>` | Cancel a scheduled tweet |
| `tweetkit home [--following] [--limit 40]` | Home feed |
| `tweetkit replies <id> [--limit 50]` | Conversation |
| `tweetkit bookmarks [--limit 100]` | Your bookmarks |
| `tweetkit likes <user> [--limit 100]` | A user's likes |
| `tweetkit notifications [--limit 40]` | Notifications |
| `tweetkit profile <user>` | Profile |
| `tweetkit followers\|following <user> [--limit 100]` | Followers / following |
| `tweetkit likers\|retweeters <id> [--limit 100]` | Who liked / reposted |
| `tweetkit follow <user> [--notify] [--dry-run]` | Follow (+ bell) |
| `tweetkit unfollow\|block\|unblock\|mute\|unmute <user>` | Social graph |
| `tweetkit pin\|unpin <id>` | Pin / unpin |
| `tweetkit friendship <user>` | Relationship + bell / repost settings |
| `tweetkit notify <user> on\|off [--live] [--dry-run]` | Per-account bell |
| `tweetkit retweets <user> on\|off [--dry-run]` | Show / hide reposts |
| `tweetkit bulk-follow <file\|-> [--no-notify] [--no-suggestions] [bulk options]` | Follow a list, resumable |
| `tweetkit bulk-notify <file\|-> on\|off [--live] [bulk options]` | Bell for a list, resumable |
| `tweetkit suggest [@user] [--source follow\|sidebar\|connect] [--limit 20] [--no-save]` | Fetch and save suggestions |
| `tweetkit suggestions [--for <user>] [--source ...] [--all] [--limit 100] [--export <file>] [--db <path>]` | List / export saved suggestions |

Bulk options: `--column <csv column>` (default `x_handle`), `--journal <path>`
(default `~/.config/tweetkit/journals/<action>.jsonl`), `--max N`, `--min-delay S` (default 30), `--max-delay S`
(default 75), `--log <file>`, `--dry-run`. Input: a `.csv`, a one-handle-per-line `.txt`, or `-` for stdin.

Exit codes: `0` success; `1` a write returned `ok: false` (or bad input, e.g. an empty thread file or a cookie
missing `auth_token`/`ct0` on import); `2` no cookie found (`CookieError`) or an argument error.

---

## 6. Python API essentials

```python
from tweetkit_x import TweetKit, CookieError

tk = TweetKit()                                   # or cookie="auth_token=<your auth_token>; ct0=<your ct0>",
                                                  #    cookie_file="~/...", keychain_slug="tweetkit", timeout=30
tk.whoami()                                       # {'ready': True, 'user_id': '...', 'ct0_len': 160} — no network

tk.post("text", image_path=None, reply_to=None, images=None, alt_texts=None)
tk.post_thread(["1/ a", ("2/ b", "b.png"), {"text": "3/ c", "images": ["c1.png", "c2.png"], "alt_texts": ["C1", "C2"]}])
TweetKit.thread_items(items)                      # -> [(text, [paths], [alt_texts])]; raises ValueError; posts nothing
tk.quote(text, quote_tweet_id, image_path=None)
tk.post_note(text, image_path=None, reply_to=None)
tk.schedule(text, at_epoch, image_path=None);  tk.unschedule(scheduled_tweet_id)
tk.delete(tweet_id);  tk.delete_many(ids)

tk.get_tweets(username=None, limit=200)           # your tweets when username is None
tk.search(query, username=None, limit=200, regex=False)
tk.search_x(query, product="Top", limit=40)       # product="Latest" for newest first
tk.get_tweet(tweet_id)

tk.like / unlike / retweet / unretweet / bookmark / unbookmark / pin / unpin (tweet_id)
tk.follow(username, notify=False, dry_run=False);  tk.unfollow / block / unblock / mute / unmute (username)
tk.home_timeline(following=False, limit=40);  tk.get_replies(tweet_id, limit=50);  tk.bookmarks(limit=100)
tk.user_likes(username);  tk.notifications();  tk.user_profile(username)
tk.followers(username);  tk.following(username);  tk.likers(tweet_id);  tk.retweeters(tweet_id)
tk.friendship(username);  tk.set_notifications(username, on=True, kind="posts");  tk.set_retweets(username, on=True)
tk.bulk_follow(usernames, notify=True, journal_path=None, dry_run=False, max_actions=None)
tk.bulk_notifications(usernames, on=True, kind="posts", journal_path=None, dry_run=False, max_actions=None)
tk.suggestions(source="follow", username=None, limit=20, save=True)
```

Note: `tk.post(images=[...])` called directly does not validate; it silently uses the first 4 paths. Call
`TweetKit.thread_items([...])` first if you want the same checks the MCP tools apply.

---

## 7. Return shapes and errors

| Call | Success | Failure |
|---|---|---|
| post / quote / note | `{ok: true, id, url}` | `{ok: false, status, error}` |
| schedule | `{ok: true, scheduled_id}` | `{ok: false, status?, error}` |
| delete | `{ok: true, id}` | `{ok: false, status, error}` |
| `delete_tweets` / `delete_many` | list of the above, each with `tweet_id` | per item |
| `post_thread` | list of `{ok, id, url}`, one per posted tweet | stops after the first `ok: false`; a pre-check failure is `[{ok: false, error}]` |
| engage (like, retweet, bookmark, unschedule ...) | `{ok: true, data}` | `{ok: false, status, error}` |
| social / bell / pin writes (follow, block, mute, pin, notify ...) | `{ok: true}`; `follow_user(notify=True)` returns `{ok, follow, notify}` | `{ok: false, status, error, rate_limit_remaining, rate_limit_reset, stop?}` — `stop` set = X signalled a limit |
| tweet lists (MCP) | `[{id, text, created_at, likes, retweets, replies, url}]` | unauthenticated: `[{error}]` (no `ok` key) |
| user lists (MCP) | `[{username, name, followers, verified, url}]` | unauthenticated: `[{error}]` |
| single reads (`get_tweet`, `get_user_profile`, `get_friendship`) | a dict | unauthenticated: `{ok: false, error}` |
| `bulk_follow` / `bulk_set_notifications` | `{journal, counts, left, writes, ...}` | `counts.stopped > 0` = X signalled a limit; wait hours |
| `dry_run=True` | `{ok: true, dry_run: true, method, url, params, data, header_names}` — header names only, never values; nothing sent | — |

- MCP write tools return `{ok: false, error: "Not authenticated yet ..."}` when no cookie is loaded; guide the user
  through `set_session_cookie` / `import_cookie_from_file`.
- A media upload failure raises `RuntimeError` (`media INIT|APPEND|FINALIZE <status>: ...`). In MCP it surfaces as a
  tool error, not `{ok: false}`.
- `list_saved_suggestions` and `export_saved_suggestions` read the local SQLite store
  (`~/.config/tweetkit/suggestions.sqlite`, override `TWEETKIT_DB`) and never check auth.
- Python: `CookieError` = no cookie found; `ValueError` = cookie incomplete, or a bad thread item.

---

## 8. Operational truths

- **Unofficial.** tweetkit replays x.com's internal GraphQL / upload calls with the public web bearer, your cookie,
  `ct0` as `x-csrf-token` and a generated `x-client-transaction-id`. X rotates GraphQL query ids every few weeks:
  if calls that used to work start failing, refresh `tweetkit_x/constants.py` from a fresh HAR.
- **Rate limits.** X does not publish limits for the web session. Stop on 429 or error codes 88 (rate limit),
  161 (follow limit), 185 (daily limit), 326 (locked), 64 (suspended). The bulk tools stop on these themselves,
  pause 30–75 s between writes and 1.5–4 s between reads; these defaults are conservative guesses, not X limits.
- **Account risk.** Fast or bulk writes are the most likely to get an account limited. Keep `max_actions` small,
  run `dry_run=True` first, and only act on lists the user approved.
- **Resumable bulk jobs.** One JSONL journal line per finished account; re-running with the same journal skips
  finished accounts. Dry runs journal to `<journal>.dryrun.jsonl`, so a real run is never pre-skipped.
- **The MCP server logs to stderr.** stdout is the MCP stdio channel; never print to it in server code.
- **Not supported:** DMs, polls, Lists, profile editing, Spaces, hide-reply.

---

## 9. Tests

```bash
python tests/test_media_tools.py        # prints "media tools ok" — no network, no cookie
pytest tests/                            # all tests, no network
```

Tests replace `upload_media` / `create_tweet` with in-memory fakes. Never write a test that reaches X or needs a
real cookie. `python3 scripts/make_screenshots.py` regenerates `docs/assets/screenshots/01-mcp-thread.png` from the
real MCP tools against an in-memory stand-in for X.

When you change the MCP tool list, update the tool tables here and in `README.md`, and keep the count (48) in sync.
