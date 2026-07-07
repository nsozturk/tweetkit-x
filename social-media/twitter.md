# tweetkit-x — launch thread (English)

Posting order + image per tweet. Each tweet is ≤280 chars.

---

**1/** _[image: screenshots/01-header.png]_

Introducing tweetkit-x 🧵

Post, delete & read on X — from Python AND as an MCP server — using your own logged-in web session.

No paid API. No dev app. No OAuth. Just your session cookie.

pip install tweetkit-x

---

**2/**

Why it exists:

Since Feb 2026, X's API has no free tier — pay-per-use, ~$0.015 per post (~$0.20 with a link).

tweetkit skips the API entirely. It replays the exact internal calls your browser makes when you hit Post. Zero API cost.

---

**3/** _[image: screenshots/02-usage.png]_

What it does:

✍️ post — text, images, replies, threads
🗑️ delete — one, many, or find-and-delete
📖 read — your timeline or anyone's
🔎 search — local regex over your own tweets

From Python or a one-line CLI.

---

**4/** _[image: screenshots/03-mcp.png]_

The part I'm most excited about: it's also an MCP server.

Drop it into Claude or Cursor and say:
"find my old $XMR tweets and delete them."

It runs the search + delete for you — and it's on the official MCP registry.

---

**5/**

Auth is just your session cookie (auth_token + ct0). Grab it 3 ways:

• paste the Cookie header
• an F12 "Preserve log" HAR file
• a storage-dump zip

Kept in your macOS Keychain. It never leaves your machine.

---

**6/**

MIT-licensed. On PyPI + the official MCP registry:

pip install tweetkit-x
→ github.com/nsozturk/tweetkit-x

⚠️ Automating your web session is against X's ToS. Personal-use, grey-area tool. Your account, your risk.

---

**7/**

P.S. — this entire thread was posted with tweetkit-x itself. A launch thread dogfooding its own post engine. 🐝

(The write-up went out the same way. I'm not touching the X compose box like it's 2009.)

#Python #MCP #AI #buildinpublic #opensource
