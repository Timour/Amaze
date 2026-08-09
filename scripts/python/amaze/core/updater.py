"""Is there a newer Amaze, and can this one become it?

Never runs by itself: the shelf tool, the About tab and the
format-ahead refusal all ask. Nothing is fetched at launch.

Four facts this rests on are measured, not assumed
(research.md > TLS & HTTP under Houdini): Houdini's Python has no CA
chain so every https request fails without certifi, the verification
error subclasses the generic one so no downgrade may key on it, a
truncated body does NOT raise, and contexts are expensive so there is
exactly one - `matx_sources.ssl_context`.
"""

import json
import os
import shutil
import urllib.error
import urllib.request

from amaze import branding
from amaze.core import debug

#: The release feed. The repo is public, so this is unauthenticated and
#: rate-limited per IP; a check the user asked for costs one call.
RELEASES_URL = "https://api.github.com/repos/Timour/Amaze/releases/latest"
TIMEOUT = 20
USER_AGENT = "%s/%s" % (branding.APP_NAME, branding.APP_VERSION)

#: Verdicts `check` can answer with.
UP_TO_DATE = "up-to-date"
NEWER = "newer"
NO_RELEASE = "no-release"
UNREACHABLE = "unreachable"


class Update:
    """One verdict, with everything a caller needs to act or explain."""

    def __init__(self, verdict, version="", url="", sentence=""):
        self.verdict = verdict
        self.version = version
        self.url = url
        self.sentence = sentence

    def __bool__(self):
        return self.verdict == NEWER


def parts(version: str):
    """A version as comparable integers; unreadable pieces sort last."""
    cleaned = str(version or "").strip().lstrip("vV")
    out = []
    for piece in cleaned.split("."):
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    """Strictly newer, comparing on equal length so 1.0 < 1.0.1."""
    left, right = parts(candidate), parts(current)
    width = max(len(left), len(right))
    left = left + (0,) * (width - len(left))
    right = right + (0,) * (width - len(right))
    return left > right


def _open(url):
    """THE package's single `urlopen`, not a second one.

    `fixture_panel` blocks `matx_sources._request` to keep the suite
    off the network (practice.md), so a private door here would be
    unblocked - a constructed panel could reach GitHub from a test.
    It also inherits the verified context and the no-downgrade rule.
    """
    from amaze.core import matx_sources
    return matx_sources._request(url)


def check(current: str = "") -> Update:
    """Ask the release feed what the newest published version is."""
    current = current or branding.APP_VERSION
    try:
        with _open(RELEASES_URL) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # NOT an error: the repo is public and simply has no
            # tagged release yet, which is true until 1.0 ships.
            return Update(NO_RELEASE, sentence=(
                "No release has been published yet, so there is nothing "
                "to update to. You are running %s." % current))
        return Update(UNREACHABLE, sentence=_unreachable_sentence(exc))
    except Exception as exc:                                  # noqa: BLE001
        return Update(UNREACHABLE, sentence=_unreachable_sentence(exc))

    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        return Update(NO_RELEASE, sentence=(
            "The newest release did not say which version it is, so it "
            "cannot be compared with the %s you are running." % current))
    # AN UPLOADED ZIP IF THERE IS ONE, ELSE THE SOURCE ARCHIVE GitHub
    # generates for every tag. Measured: `assets` is empty on plenty of
    # real releases, so looking only there offers an update with no
    # download (research.md > GitHub's release feed).
    url = ""
    for asset in payload.get("assets") or []:
        if str(asset.get("name") or "").endswith(".zip"):
            url = str(asset.get("browser_download_url") or "")
            break
    url = url or str(payload.get("zipball_url") or "")
    if not is_newer(tag, current):
        return Update(UP_TO_DATE, version=tag, sentence=(
            "You are running %s, which is the newest release." % current))
    return Update(NEWER, version=tag, url=url, sentence=(
        "Amaze %s is available. You are running %s." % (tag, current)))


def _unreachable_sentence(exc) -> str:
    debug.event("updater", "release feed unreachable", error=str(exc))
    return ("The release list could not be reached, so it is not known "
            "whether a newer Amaze exists. Check the connection and try "
            "again; nothing has been changed.")


def download(url: str, into: str) -> str:
    """Stream a release to `into`, returning the file written.

    LENGTH-CHECKED. A short body closes the connection and the read
    loop ends NORMALLY (research.md), so a rename-on-success scheme
    promotes a truncated archive without noticing. A missing
    Content-Length is UNKNOWN, never zero.
    """
    os.makedirs(into, exist_ok=True)
    target = os.path.join(into, "amaze-update.zip")
    read = 0
    with _open(url) as response:
        declared = response.headers.get("Content-Length")
        with open(target, "wb") as handle:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                handle.write(chunk)
                read += len(chunk)
    if declared is not None and read != int(declared):
        os.remove(target)
        raise OSError(
            "the download stopped early - %d bytes of %s. Nothing has "
            "been changed." % (read, declared))
    if not read:
        os.remove(target)
        raise OSError("the download was empty. Nothing has been changed.")
    return target


def apply_update(staged: str, install: str) -> str:
    """Put `staged` where `install` is, keeping the old one as .backup.

    The previous install is MOVED aside rather than deleted, so a bad
    release is undone by moving it back. Houdini caches modules per
    session, so nothing here takes effect until a restart - the caller
    says so.
    """
    if not os.path.isdir(staged):
        raise OSError("the staged update is not there: %s" % staged)
    backup = install.rstrip("/\\") + ".backup"
    if os.path.exists(backup):
        shutil.rmtree(backup)
    os.rename(install, backup)
    try:
        os.rename(staged, install)
    except OSError:
        # PUT IT BACK. The window between the two renames is the only
        # moment this is not whole, and leaving it open would cost the
        # user a working install for a failed update.
        os.rename(backup, install)
        raise
    debug.event("updater", "update applied", install=install, backup=backup)
    return backup
