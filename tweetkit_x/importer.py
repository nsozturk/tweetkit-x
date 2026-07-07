"""Turn whatever your browser gives you into a tweetkit cookie string.

Four sources, all reduced to the same `{name: value}` dict → cookie string:

  * a pasted `Cookie:` header           from_cookie_header()
  * a HAR file (F12 → Preserve log)      from_har()
  * a storage-dump .zip (cookies.json)   from_storagedump()
  * a Cookie-Editor / EditThisCookie JSON export   from_cookie_editor_json()

`summarize()` reports which cookies were found and their lengths — never values.
"""
import json
import os
import zipfile

# Cookies worth keeping if present. auth_token + ct0 are the only *required* ones.
WANTED = ["auth_token", "ct0", "twid", "kdt", "att", "guest_id", "personalization_id"]
REQUIRED = ("auth_token", "ct0")


def _filter(pairs):
    """Keep only the cookies we care about, dropping empties."""
    return {k: pairs[k] for k in WANTED if pairs.get(k)}


def to_cookie_string(pairs):
    return "; ".join(f"{k}={v}" for k, v in pairs.items() if v)


def summarize(pairs):
    """Return {name: length} plus which required cookies are missing. No values."""
    found = {k: len(str(v)) for k, v in pairs.items()}
    missing = [k for k in REQUIRED if not pairs.get(k)]
    return {"found": found, "missing_required": missing, "ok": not missing}


# --------------------------------------------------------------------------- #
def from_cookie_header(header):
    """Parse a raw `Cookie:` header value (as copied from DevTools → Network)."""
    header = header.strip()
    if header.lower().startswith("cookie:"):
        header = header.split(":", 1)[1].strip()
    pairs = {}
    for part in header.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            pairs[name] = value
    return _filter(pairs)


# --------------------------------------------------------------------------- #
def from_har(path):
    """Extract cookies from a HAR file.

    Chrome/Firefox HARs store request cookies two ways; we read both:
      * entry.request.cookies  → [{name, value}, ...]
      * the raw `Cookie:` request header

    NOTE: modern Chrome *redacts* cookies in exported HARs unless you enable
    "Allow to generate HAR with sensitive data". If auth_token comes back
    missing, your HAR was scrubbed — copy the `Cookie:` header by hand
    (Method A in the README) or use a storage-dump zip instead.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        har = json.load(f)
    pairs = {}
    for entry in har.get("log", {}).get("entries", []):
        req = entry.get("request", {})
        host = req.get("url", "")
        if "x.com" not in host and "twitter.com" not in host:
            continue
        for c in req.get("cookies", []):
            if c.get("name") and c.get("value"):
                pairs[c["name"]] = c["value"]
        for h in req.get("headers", []):
            if h.get("name", "").lower() == "cookie":
                pairs.update(from_cookie_header(h.get("value", "")))
    return _filter(pairs)


# --------------------------------------------------------------------------- #
def _cookies_from_dump_obj(obj):
    """Accept the many shapes a storage-dump/cookie export can take."""
    # {"data": [{"key":..,"value":..}, ...]}  (common storage-dump format)
    if isinstance(obj, dict) and isinstance(obj.get("data"), list):
        items = obj["data"]
    elif isinstance(obj, list):
        items = obj
    elif isinstance(obj, dict) and "cookies" in obj:
        items = obj["cookies"]
    elif isinstance(obj, dict):
        # plain {name: value} map
        return {k: v for k, v in obj.items() if isinstance(v, str)}
    else:
        items = []
    pairs = {}
    for c in items:
        if not isinstance(c, dict):
            continue
        name = c.get("key") or c.get("name")
        value = c.get("value")
        if name and value is not None:
            pairs[name] = value
    return pairs


def from_storagedump(zip_path):
    """Extract cookies from a storage-dump .zip that contains `cookies.json`.

    Works with the `{ "data": [ { "key": ..., "value": ... }, ... ] }` shape
    exported by storage-dump browser extensions, as well as plain lists/maps.
    """
    with zipfile.ZipFile(zip_path) as z:
        name = next((n for n in z.namelist() if n.endswith("cookies.json")), None)
        if not name:
            raise ValueError("no cookies.json inside the zip")
        obj = json.loads(z.read(name).decode("utf-8", "replace"))
    return _filter(_cookies_from_dump_obj(obj))


def from_cookie_editor_json(path):
    """Cookie-Editor / EditThisCookie export: a list of {name, value} objects."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        obj = json.load(f)
    return _filter(_cookies_from_dump_obj(obj))


# --------------------------------------------------------------------------- #
def autodetect(path):
    """Import from a file path, guessing the format from its extension/content."""
    lower = path.lower()
    if lower.endswith(".zip"):
        return from_storagedump(path)
    if lower.endswith(".har"):
        return from_har(path)
    if lower.endswith(".json"):
        return from_cookie_editor_json(path)
    # fall back: treat the file contents as a pasted Cookie header
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return from_cookie_header(f.read())
