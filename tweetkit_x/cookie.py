"""Session-cookie loading & parsing for tweetkit-x.

The ONLY secret tweetkit needs is your X (Twitter) **session cookie** — the same
`Cookie:` header your logged-in browser sends. It must contain at least:

    auth_token   your login/session token   (HttpOnly — hidden from document.cookie)
    ct0          CSRF token (echoed back as the x-csrf-token header)

`twid` (your user id, as `u=<id>`) is recommended so tweetkit can read *your*
timeline without an extra lookup.

Resolution order (first hit wins):
  1. explicit argument              load_cookie(cookie="auth_token=...; ct0=...")
  2. env  TWEETKIT_COOKIE           the full cookie string
  3. env  TWEETKIT_COOKIE_FILE      path to a file holding the cookie string
  4. file ./cookie.txt             (current working dir)
  5. file ~/.config/tweetkit/cookie.txt
  6. macOS Keychain, if TWEETKIT_COOKIE_KEYCHAIN=<slug> is set (or slug passed in)

Nothing here ever prints a cookie value.
"""
import os
import subprocess

CONFIG_DIR = os.path.expanduser("~/.config/tweetkit")
DEFAULT_COOKIE_FILE = os.path.join(CONFIG_DIR, "cookie.txt")
DEFAULT_FILES = [os.path.join(os.getcwd(), "cookie.txt"), DEFAULT_COOKIE_FILE]

REQUIRED = ("auth_token", "ct0")


class CookieError(RuntimeError):
    """Raised when no usable session cookie can be found or it is incomplete."""


def parse_cookie(cookie_str):
    """Return {name: value} for a `Cookie:` header / cookie string."""
    out = {}
    for part in cookie_str.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            out[name] = value
    return out


def build_cookie_string(pairs):
    """Serialize {name: value} back into a `Cookie:` header string."""
    return "; ".join(f"{k}={v}" for k, v in pairs.items() if v)


def ct0_of(cookie_str):
    """Extract the ct0 (CSRF) value, or raise."""
    v = parse_cookie(cookie_str).get("ct0")
    if not v:
        raise CookieError("'ct0' not present in cookie (are you logged in?).")
    return v


def user_id_of(cookie_str):
    """Extract your numeric user id from the `twid` cookie (u=<id> / u%3D<id>)."""
    twid = parse_cookie(cookie_str).get("twid", "")
    twid = twid.replace("u%3D", "").replace("u=", "").replace('"', "").strip()
    return twid or None


def has_auth(cookie_str):
    return all(k + "=" in cookie_str for k in REQUIRED)


def missing_required(cookie_str):
    present = parse_cookie(cookie_str)
    return [k for k in REQUIRED if not present.get(k)]


# --------------------------------------------------------------------------- #
# macOS Keychain helpers (no-op / error on other platforms)
# --------------------------------------------------------------------------- #
def keychain_read(slug):
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", slug,
             "-a", os.environ.get("USER", ""), "-w"],
            capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except Exception:
        return None


def keychain_write(slug, value):
    subprocess.run(
        ["security", "add-generic-password", "-s", slug,
         "-a", os.environ.get("USER", ""), "-w", value, "-U"],
        check=True, capture_output=True, text=True, timeout=10)


def load_cookie(cookie=None, cookie_file=None, keychain_slug=None):
    """Return a cookie string from the first available source, or raise CookieError."""
    if cookie:
        return cookie.strip()
    if os.environ.get("TWEETKIT_COOKIE"):
        return os.environ["TWEETKIT_COOKIE"].strip()

    paths = []
    if cookie_file:
        paths.append(cookie_file)
    if os.environ.get("TWEETKIT_COOKIE_FILE"):
        paths.append(os.environ["TWEETKIT_COOKIE_FILE"])
    paths.extend(DEFAULT_FILES)
    for p in paths:
        if p and os.path.isfile(p):
            with open(p) as f:
                val = f.read().strip()
            if val:
                return val

    slug = keychain_slug or os.environ.get("TWEETKIT_COOKIE_KEYCHAIN")
    if slug:
        val = keychain_read(slug)
        if val:
            return val.strip()

    raise CookieError(
        "No session cookie found. Provide one via the TWEETKIT_COOKIE env var, "
        "a ./cookie.txt file, ~/.config/tweetkit/cookie.txt, or the macOS "
        "Keychain (TWEETKIT_COOKIE_KEYCHAIN=<slug>).\n"
        "Run `tweetkit import --help` to import from a HAR file, a storage-dump "
        "zip, or a pasted Cookie header. See the README → 'Getting your cookie'.")


def save_cookie(cookie_str, out_file=None, keychain_slug=None):
    """Persist a cookie string. Returns a human description of where it went."""
    if keychain_slug:
        keychain_write(keychain_slug, cookie_str)
        return f"macOS Keychain (service '{keychain_slug}')"
    path = out_file or DEFAULT_COOKIE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(cookie_str.strip() + "\n")
    os.chmod(path, 0o600)
    return path
