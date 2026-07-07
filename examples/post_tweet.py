"""Post a tweet (and a reply, and a thread) with tweetkit-x."""
from tweetkit_x import TweetKit

tk = TweetKit(keychain_slug="tweetkit")   # or cookie="auth_token=...; ct0=..."

print(tk.whoami())

r = tk.post("hello from tweetkit-x 👋")
print(r)                                   # {'ok': True, 'id': '...', 'url': '...'}

# a reply
tk.post("...and a reply", reply_to=r["id"])

# a thread (strings, or (text, image_path) tuples)
tk.post_thread([
    "1/ tweetkit posts through your own web session",
    ("2/ it can attach images too", "chart.png"),
    "3/ no paid API. NFA 🙂",
])
