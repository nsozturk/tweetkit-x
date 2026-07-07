<!-- mcp-name: io.github.nsozturk/tweetkit-x -->

<p align="center">
  <img src="assets/header.png" alt="tweetkit-x — post, delete and read on X (Twitter) from Python & MCP using your own web session" width="100%">
</p>

<h1 align="center">tweetkit-x</h1>

<p align="center">
  <b>Post, delete &amp; read on X (Twitter) — from Python <i>and</i> as an MCP server — using your own logged-in browser session.</b><br>
  No paid API. No developer app. No OAuth dance. Just your session cookie.
</p>

<p align="center">
  <img alt="PyPI" src="https://img.shields.io/pypi/v/tweetkit-x?style=flat-square&color=1d9bf0&label=pypi">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10+-1d9bf0?style=flat-square">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-3fb950?style=flat-square">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-server%20included-7856ff?style=flat-square">
  <img alt="X API" src="https://img.shields.io/badge/X%20API-not%20required-3fb950?style=flat-square">
  <img alt="Runs with" src="https://img.shields.io/badge/runs%20with-Claude%20%7C%20Cursor%20%7C%20uvx-111318?style=flat-square">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#getting-your-session-cookie">Get your cookie</a> ·
  <a href="#python-usage">Python</a> ·
  <a href="#cli-usage">CLI</a> ·
  <a href="#mcp-server">MCP server</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#disclaimer">Disclaimer</a>
</p>

---

## Why

Since **February 6, 2026**, X's official API has **no free tier for new developers** — it's pay-per-use: **~$0.015 per post, ~$0.20 per post with a link**, plus per-read charges. For publishing *your own* tweets (a bot posting your content, a scheduled thread, a cleanup script that deletes old posts), that's a recurring bill for something your browser already does for free.

**tweetkit-x** skips the API entirely. It replays the exact internal HTTP calls your browser makes when you click **Post**, **Delete**, or scroll your profile — authenticated with the session cookie you already have. Post, delete, and read the full timeline, at **zero API cost**.

> ⚠️ Automating your web session is **against X's Terms of Service**. This is a grey-area tool for personal automation. **Account risk is entirely yours.** See the [Disclaimer](#disclaimer).

---

## Features

- ✅ **Post** — text, images (chunked `INIT`/`APPEND`/`FINALIZE` upload), replies, and full **threads**
- 🗑️ **Delete** — one id, a list of ids, or "find matching &amp; delete" cleanup loops
- 📖 **Read** — your own timeline or any `@user`'s, paginated; **local search/regex** over tweets
- 🔌 **MCP server** — drop into Claude Desktop / Claude Code / Cursor; tools that **explain the cookie** and set it up with one paste
- 🔑 **Frictionless auth** — paste a `Cookie:` header, drop a **HAR** file, or a **storage-dump zip**; store in a file or the macOS **Keychain**
- 🐍 **Python API** *and* a **CLI** (`tweetkit …`)
- 🪶 Tiny footprint — no headless browser, no Selenium

---

## Quick start

```bash
pip install "tweetkit-x[mcp]"      # or: pip install tweetkit-x   (library + CLI only)

# 1. Import your session cookie (three ways — see the next section)
tweetkit import --paste                       # paste the Cookie: header, Ctrl-D
#   or:  tweetkit import --file x.com.har
#   or:  tweetkit import --file storagedump_x.com.zip --keychain tweetkit

# 2. Verify (no network call)
tweetkit whoami
# {"ready": true, "user_id": "1986...", "ct0_len": 160}

# 3. Use it
tweetkit post "hello world 👋"
tweetkit search "xmr|monero" --regex          # your tweets that match
tweetkit delete 2063240404980445603
```

---

## Getting your session cookie

The **only** secret tweetkit needs is your X **session cookie** — the same `Cookie:` header your logged-in browser sends. It must contain **at least two** values:

| Cookie | What it is | Required | HttpOnly? |
|---|---|---|---|
| `auth_token` | your login/session token | **yes** | **yes** (hidden from `document.cookie`) |
| `ct0` | CSRF token (sent back as `x-csrf-token`) | **yes** | no |
| `twid` | your user id (`u=<id>`) — lets tweetkit read *your* timeline with no extra lookup | recommended | no |
| `guest_id`, `kdt`, `att`, `personalization_id` | misc session state | optional | mixed |

> ❗ `auth_token` is **HttpOnly**, so a `document.cookie` copy in the JS console will **NOT** include it. Use one of the reliable methods below.

### Method A — copy the `Cookie:` header (most reliable, one paste)

1. Open **x.com** while logged in.
2. Open **DevTools (F12)** → the **Network** tab.
3. Click any request to `x.com` (e.g. `HomeTimeline`).
4. Under **Request Headers**, find **`cookie:`** and copy the **entire** value.
5. Feed it in:

```bash
tweetkit import --paste
# paste the cookie header, then press Ctrl-D
```

### Method B — an F12 "Preserve log" HAR file

1. Open **x.com** logged in → **DevTools (F12)** → **Network**.
2. Tick **"Preserve log"**, then reload / click around so requests are captured.
3. **Right-click any request → "Save all as HAR"** (or use the ⬇ export icon).
4. Import it:

```bash
tweetkit import --file ~/Downloads/x.com.har
```

> Modern Chrome can **redact cookies** from exported HARs. If tweetkit reports `auth_token` missing, either enable **"Allow to generate HAR with sensitive data"** in the Network settings, or fall back to **Method A** / **Method C**.

### Method C — a storage-dump browser extension (zip)

Some browser extensions export browser storage (they use the `chrome.cookies` API, which **can** read HttpOnly cookies) as a `.zip` containing a `cookies.json`. tweetkit reads that directly:

```bash
tweetkit import --file storagedump_x.com_2026-07-05.zip
```

It accepts `cookies.json` shaped as `{ "data": [ { "key": "...", "value": "..." }, ... ] }` (the common storage-dump format), a plain list, or a `{name: value}` map. Cookie-Editor / EditThisCookie JSON exports (`--file export.json`) work too.

### Where the cookie is stored

By default `tweetkit import` writes **`~/.config/tweetkit/cookie.txt`** (chmod `600`; also git-ignored). Prefer the **macOS Keychain**? Add `--keychain <slug>`:

```bash
tweetkit import --paste --keychain tweetkit
export TWEETKIT_COOKIE_KEYCHAIN=tweetkit
```

Resolution order at runtime (first hit wins): explicit arg → `TWEETKIT_COOKIE` → `TWEETKIT_COOKIE_FILE` → `./cookie.txt` → `~/.config/tweetkit/cookie.txt` → Keychain (`TWEETKIT_COOKIE_KEYCHAIN`).

---

## Python usage

```python
from tweetkit_x import TweetKit

tk = TweetKit(keychain_slug="tweetkit")          # or cookie="auth_token=...; ct0=..."

tk.whoami()                                       # {'ready': True, 'user_id': '...', 'ct0_len': 160}

# post
tk.post("hello world")
tk.post("with a picture", image_path="chart.png")
tk.post("a reply", reply_to="1800000000000000000")

# thread — strings or (text, image_path) tuples; each replies to the previous
tk.post_thread(["1/ intro", ("2/ chart", "chart.png"), "3/ outro"])

# read
mine = tk.get_tweets(limit=100)                   # your tweets, newest first
theirs = tk.get_tweets(username="jack", limit=50) # anyone's

# search (local filter over the timeline — no paid search API)
hits = tk.search("monero")                        # substring
hits = tk.search(r"xmr|monero", regex=True)       # regex

# delete
tk.delete("1800000000000000000")
tk.delete_many([t["id"] for t in hits])
```

Every write returns `{'ok': True, 'id': '...', 'url': '...'}` on success, or `{'ok': False, 'status': ..., 'error': '...'}` on failure — easy to log or retry.

See [`examples/`](examples/) for a full "find my $XMR tweets and delete them" cleanup loop.

---

## CLI usage

```bash
tweetkit whoami
tweetkit post "just some text"
tweetkit post "text + media" --image pic.png
tweetkit post "a reply" --reply-to 1800000000000000000
tweetkit thread thread.txt                 # tweets separated by blank lines
tweetkit delete 1800000000000000000 1800000000000000001
tweetkit tweets --limit 100                # your tweets
tweetkit tweets @jack --limit 50           # someone else's
tweetkit search monero                     # your tweets containing "monero"
tweetkit search "xmr|monero" --regex
```

A `thread.txt` is just tweets separated by **blank lines**.

---

## MCP server

tweetkit ships a first-class **MCP server** so an AI client can post/delete/read for you — and it **walks the user through auth**, explaining what the cookie is and setting it up with a single paste.

### Configure your client

**Claude Desktop / Claude Code / Cursor** — add to your MCP config (`claude_desktop_config.json`, `.mcp.json`, …):

```jsonc
{
  "mcpServers": {
    "tweetkit": {
      "command": "uvx",
      "args": ["--from", "tweetkit-x[mcp]", "tweetkit-mcp"],
      "env": { "TWEETKIT_COOKIE_KEYCHAIN": "tweetkit" }
    }
  }
}
```

Already `pip install`ed? Use the console script directly:

```jsonc
{ "mcpServers": { "tweetkit": { "command": "tweetkit-mcp",
  "env": { "TWEETKIT_COOKIE_KEYCHAIN": "tweetkit" } } } }
```

If you don't set any cookie env var, that's fine — the server starts unauthenticated and asks the user to set the cookie from inside the chat (below).

### Frictionless auth, from inside the chat

The server **describes each value** and offers the lowest-effort path. A typical first run:

1. The client calls **`auth_status`** → *not authenticated*.
2. The server’s instructions tell the assistant to ask you for your cookie and explain **what `auth_token` and `ct0` are** and how to copy them.
3. You paste the `Cookie:` header once → **`set_session_cookie("<paste>")`** → stored (Keychain or file) and activated. Or point **`import_cookie_from_file("~/Downloads/x.com.har")`** at a HAR / storage-dump zip.

The raw cookie is never echoed back.

### Tools

| Tool | What it does |
|---|---|
| `auth_status` | Is a valid session loaded? (call first) |
| `set_session_cookie(cookie_header)` | Set auth from a pasted `Cookie:` header — explains exactly what to copy |
| `import_cookie_from_file(path)` | Set auth from a HAR / storage-dump `.zip` / cookie JSON |
| `post_tweet(text, image_path?, reply_to?)` | Post a tweet (optional image / reply) |
| `post_thread(tweets[])` | Post a thread |
| `delete_tweet(tweet_id)` / `delete_tweets(ids[])` | Delete tweets |
| `get_my_tweets(limit?)` / `get_user_tweets(username, limit?)` | Read a timeline |
| `search_my_tweets(query, regex?, limit?)` | Find your own tweets (great for cleanup) |

---

## How it works

When you act in the browser, x.com calls a handful of internal endpoints. tweetkit reproduces them 1:1:

1. **`x-client-transaction-id`** — X requires an anti-bot header derived from the page's `ondemand.s` JS and a home fetch. Generated with the standalone [`x-client-transaction-id`](https://pypi.org/project/x-client-transaction-id/) package.
2. **Media upload** (images) — `POST upload.x.com/i/media/upload.json` as `INIT` → `APPEND` → `FINALIZE`, yielding a `media_id`.
3. **Write / delete** — `POST /i/api/graphql/<queryId>/CreateTweet` and `.../DeleteTweet`.
4. **Read** — `GET /i/api/graphql/<queryId>/UserTweets` (paginated by cursor), plus `UserByScreenName` to resolve `@handles`.

Auth is just your **cookie** + the public web **bearer** token (the same non-secret bearer embedded in x.com for every visitor) + the **`ct0`** CSRF value echoed as `x-csrf-token`.

```
your cookie ──► x-client-transaction-id ──► CreateTweet / DeleteTweet / UserTweets ──► result
```

> The GraphQL **query IDs** live in [`tweetkit_x/constants.py`](tweetkit_x/constants.py). X rotates them every few weeks; if a call starts failing, refresh them from a fresh HAR (the file has step-by-step notes).

---

## Security

- The cookie is the only secret. It's stored **chmod 600** in `~/.config/tweetkit/cookie.txt` or the macOS **Keychain**, and `.gitignore` blocks `cookie.txt`, `.env`, `*.har`, and `*.zip`.
- tweetkit **never prints** the cookie value — importers report only which cookies were found and their lengths.
- The bundled **bearer** is X's public web bearer, identical for every visitor — not a secret.

---

## Disclaimer

This project automates your **own** X web session for **personal** use. Automating the web session is **against X's Terms of Service**, and using it may put your account at risk of rate-limiting, suspension, or ban. **You are solely responsible** for how you use it. Provided **as-is**, without warranty. Not affiliated with X Corp.

## License

[MIT](LICENSE) © 2026 ns0bj
