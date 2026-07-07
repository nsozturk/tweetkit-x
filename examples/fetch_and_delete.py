"""Find your own tweets matching a term and delete them (loop until clean).

This mirrors the real workflow tweetkit was born from: "delete all my $XMR
tweets". Because self-threads can hide siblings between fetches, we loop until
two consecutive scans come back empty.
"""
from tweetkit_x import TweetKit

tk = TweetKit(keychain_slug="tweetkit")

TERM = r"xmr|monero"      # regex
clean_rounds = 0
while clean_rounds < 2:
    matches = tk.search(TERM, regex=True, limit=500)
    if not matches:
        clean_rounds += 1
        continue
    clean_rounds = 0
    for t in matches:
        res = tk.delete(t["id"])
        print(f"{'✓' if res.get('ok') else '✗'} {t['id']}  {t['text'][:60]!r}")

print("done — no matching tweets remain.")
