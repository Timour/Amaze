"""Find and install a newer Amaze, only when asked ▸p/updater-shape ▸r/tls-http"""

import hashlib
import json
import os
import platform
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from amaze import branding
from amaze.core import debug

RELEASES_URL = "https://api.github.com/repos/Timour/Amaze/releases/latest"    # unauthenticated, rate-limited per IP ▸p/updater-shape
REPO_URL = "https://github.com/Timour/Amaze"    # the About page's address
NEW_ISSUE_URL = "https://github.com/Timour/Amaze/issues/new"    # the repo URLs are defined HERE; pre-fillable with `?body=` ▸r/github-issue-url
LIBRARY_POLICY_URL = "https://raw.githubusercontent.com/Timour/Amaze/%s/scripts/python/amaze/core/library_policy.py"    # a release's own code


def bug_report_url() -> str:
    """The new-issue URL with this machine's three versions pre-filled in its `body` parameter."""
    import hou
    body = ("Amaze: %s\nHoudini: %s\nOS: %s\n\nWhat happened:\n"
            % (branding.APP_VERSION, hou.applicationVersionString(),
               platform.platform()))
    return NEW_ISSUE_URL + "?body=" + urllib.parse.quote(body, safe="")


UP_TO_DATE = "up-to-date"    # the verdicts `check` can return
NEWER = "newer"
NO_RELEASE = "no-release"
UNREACHABLE = "unreachable"


class Update:
    """One verdict, with everything a caller needs to act or explain."""

    def __init__(self, verdict, version="", url="", sentence="",
                 digest="", size=0, library_version=0, library_since="", formats=(0, 0)):
        self.verdict = verdict
        self.version = version
        self.url = url
        self.sentence = sentence
        self.digest = digest    # `sha256:<hex>` for an uploaded asset, empty for the zipball ▸r/release-digest
        self.size = size        # the asset's declared byte count, 0 when unknown
        self.library_version = library_version    # what the release updates libraries to; 0 when not read
        self.library_since = library_since or version    # the first Amaze that reads that version
        self.formats = tuple(formats)    # the release's database and record formats; 0 when not read

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
    """The package's single `urlopen`; never add another ▸p/updater-shape"""
    from amaze.core import matx_sources
    return matx_sources._request(url)


def check(current: str = "") -> Update:
    """Ask the release feed what the newest published version is."""
    current = current or branding.APP_VERSION
    try:
        with _open(RELEASES_URL) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:    # NOT an error: the repo is public and simply has no tagged release yet
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
    url, digest, size = "", "", 0    # an uploaded zip if any, else the zipball ▸r/release-digest
    for asset in payload.get("assets") or []:
        if str(asset.get("name") or "").endswith(".zip"):
            url = str(asset.get("browser_download_url") or "")
            digest = str(asset.get("digest") or "")
            size = int(asset.get("size") or 0)
            break
    url = url or str(payload.get("zipball_url") or "")
    if not is_newer(tag, current):
        return Update(UP_TO_DATE, version=tag, sentence=(
            "You are running %s, which is the newest release." % current))
    library_version, library_since, formats = release_library(tag)
    return Update(NEWER, version=tag, url=url, digest=digest, size=size,
                  library_version=library_version, library_since=library_since, formats=formats,
                  sentence=(
        "Amaze %s is available. You are running %s." % (tag, current)))


def release_library(tag: str) -> tuple:
    """Release `tag`'s library version, the first Amaze reading it, and its two formats; 0 if unread."""
    try:
        with _open(LIBRARY_POLICY_URL % tag) as response:
            text = response.read().decode("utf-8", "replace")
    except Exception as exc:                                  # noqa: BLE001
        debug.event("updater", "release library version unread", tag=tag, error=str(exc))
        return 0, "", (0, 0)
    version = re.search(r"^LIBRARY_VERSION\s*=\s*(\d+)", text, re.MULTILINE)
    since = re.search(r"^LIBRARY_VERSION_SINCE\s*=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
    formats = tuple(int(found.group(1)) if found else 0 for found in (
        re.search(r"^%s\s*=\s*(\d+)" % name, text, re.MULTILINE)
        for name in ("DATABASE_FORMAT", "RECORD_FORMAT")))
    return (int(version.group(1)) if version else 1), (since.group(1) if since else ""), formats


def release_formats(found) -> tuple:
    """(library version, database format, record format) of a release; 0 for one its file omits."""
    return (int(getattr(found, "library_version", 0) or 0),) + tuple(
        getattr(found, "formats", (0, 0)))


def updates_library(found, library_dir: str) -> bool:
    """Whether installing `found` updates the library at `library_dir`: the red Install Update."""
    from amaze.core import library_policy, library_settings
    wanted = release_formats(found)
    if not (found and library_dir and wanted[0]):    # an unread release format announces nothing
        return False
    wanted = [one or base for one, base in zip(wanted, library_policy.FORMAT_3_0)]
    return any(one > here for one, here in zip(wanted, library_settings.library_formats(library_dir)))


def configured_library() -> str:
    """The library the settings name; empty when unreadable, since no setting may block an update."""
    try:
        from amaze.prefs import prefs as prefs_module
        preferences = prefs_module.Prefs()
        preferences.load()
        return str(getattr(preferences, "dir", "") or "")
    except Exception as exc:                                  # noqa: BLE001
        debug.event("updater", "library unread", error=str(exc))
        return ""


def offer_line(found, library_dir: str) -> str:
    """The check's result in one line, worded as P06 shows it when the library is updated too."""
    from amaze import messages
    from amaze.core import library_settings
    if updates_library(found, library_dir):
        return messages.UPDATE_LIBRARY_AVAILABLE % (
            found.version, library_settings.version_label(release_formats(found)))
    return found.sentence


def _unreachable_sentence(exc) -> str:
    debug.event("updater", "release feed unreachable", error=str(exc))
    return ("The release list could not be reached, so it is not known "
            "whether a newer Amaze exists. Check the connection and try "
            "again; nothing has been changed.")


MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024    # the largest download a release may be ▸r/release-digest
MAX_UNPACKED_BYTES = 512 * 1024 * 1024


def _verify_digest(path: str, digest: str) -> None:
    """Raise OSError unless `path` hashes to `digest` (`sha256:<hex>`); none raises ▸r/release-digest"""
    algorithm, _, expected = str(digest or "").partition(":")
    if not expected:
        raise OSError(
            "the release did not say what the download should hash to, so "
            "it cannot be verified. Nothing has been changed.")
    try:
        hasher = hashlib.new(algorithm)
    except (ValueError, TypeError):
        raise OSError(
            "the release names a checksum this Amaze cannot compute (%s). "
            "Nothing has been changed." % algorithm)
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    actual = hasher.hexdigest()
    if actual != expected.strip().lower():
        raise OSError(
            "the download does not match the checksum the release "
            "published, so it is not the file that was released. Nothing "
            "has been changed.")


def download(url: str, into: str, digest: str = "", size: int = 0, on_bytes=None) -> str:
    """Stream a release to `into`: the file, or OSError ▸r/release-digest ▸p/updater-shape"""
    from amaze.core import matx_sources
    from amaze.helpers import hostos

    os.makedirs(into, exist_ok=True)
    target = os.path.join(into, "amaze-update.zip")
    ceiling = min(size, MAX_DOWNLOAD_BYTES) if size else MAX_DOWNLOAD_BYTES

    def check_size_limit(read, total):
        if read > ceiling:
            raise OSError(
                "the download is larger than a release should "
                "be (over %d bytes). Nothing has been changed."
                % ceiling)
        if on_bytes is not None:
            on_bytes(read, total or size)

    with hostos.scratch_beside(target) as scratch:
        try:
            read = matx_sources.stream_into(url, scratch, check_size_limit)
        except matx_sources.ShortDownload as short:
            raise OSError(
                "the download stopped early - %d bytes of %d. Nothing has "
                "been changed." % (short.read, short.total)) from short
        if not read:
            raise OSError(
                "the download was empty. Nothing has been changed.")
        if size and read != size:
            raise OSError(
                "the download is %d bytes but the release said %d, so it "
                "is not the file that was released. Nothing has been "
                "changed." % (read, size))
        if digest:
            _verify_digest(scratch, digest)
    return target


INSTALL_ENTRIES = ("scripts", "python_panels", "toolbar", "OPmenu.xml")    # what a staged update must contain; also in sync-install.sh ▸p/updater-shape


def _archive_root(names) -> str:
    """The single top-level folder of an archive, or empty when it is flat ▸p/updater-shape"""
    tops = {name.split("/", 1)[0] for name in names if name.strip("/")}
    return tops.pop() if len(tops) == 1 else ""


def stage_release(archive: str, into: str) -> str:
    """Unzip `archive`, paths kept inside, size-capped: staged path ▸p/updater-shape ▸r/release-digest"""
    import zipfile

    from amaze.helpers import hostos

    if os.path.isdir(into):
        shutil.rmtree(into, ignore_errors=True)
    unpacked = into + ".unpacked"
    shutil.rmtree(unpacked, ignore_errors=True)
    os.makedirs(unpacked, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            for name in names:
                hostos.contained_join(unpacked, name)    # raises rather than skips: a release that cannot be unpacked whole is not installed in part
            expanded = sum(info.file_size for info in bundle.infolist())
            if expanded > MAX_UNPACKED_BYTES:    # checked before extracting ▸r/release-digest
                raise OSError(
                    "the release archive unpacks to more than a release "
                    "should (%d bytes). Nothing has been changed."
                    % expanded)
            bundle.extractall(unpacked)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(unpacked, ignore_errors=True)
        raise OSError(
            "the downloaded file is not a zip archive (%s). Nothing has "
            "been changed." % exc)
    except hostos.PathOutsideBase as exc:
        shutil.rmtree(unpacked, ignore_errors=True)
        raise OSError(
            "the release archive holds a file that would be written "
            "outside the update folder (%s). Nothing has been changed."
            % exc)

    root = os.path.join(unpacked, _archive_root(names))
    missing = [entry for entry in INSTALL_ENTRIES
               if not os.path.exists(os.path.join(root, entry))]
    if missing:
        shutil.rmtree(unpacked, ignore_errors=True)
        raise OSError(
            "the release is missing %s, so it is not an Amaze install. "
            "Nothing has been changed." % ", ".join(missing))

    os.makedirs(into, exist_ok=True)
    for entry in INSTALL_ENTRIES:
        source = os.path.join(root, entry)
        target = os.path.join(into, entry)
        if os.path.isdir(source):
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    shutil.rmtree(unpacked, ignore_errors=True)
    debug.event("updater", "release staged", staged=into,
                entries=len(INSTALL_ENTRIES))
    return into


def fetch_and_stage(url: str, workspace: str,
                    digest: str = "", size: int = 0, on_bytes=None) -> str:
    """Download and stage a release; without `digest` and `size` it is unverified ▸r/release-digest"""
    archive = download(url, workspace, digest=digest, size=size, on_bytes=on_bytes)
    try:
        return stage_release(archive, os.path.join(workspace, "staged"))
    finally:    # the archive is always removed
        try:
            os.remove(archive)
        except OSError:
            pass


def install_root() -> str:
    """Where this Amaze is installed, from `$AMAZE`; `""` when it cannot be found."""
    try:
        import hou
    except ImportError:
        return os.environ.get("AMAZE", "")
    return hou.getenv("AMAZE") or ""    # from hou only, never the environment


def install(found, into: str = "") -> None:
    """Fetch, verify, stage and swap in `found`; OSError on failure, changing nothing ▸p/updater-shape"""
    from amaze import messages

    if not found or not getattr(found, "url", ""):
        raise OSError(messages.NO_RELEASE_TO_INSTALL)
    into = into or install_root()
    if not into or not os.path.isdir(into):
        raise OSError(messages.INSTALL_LOCATION_UNKNOWN)
    into = into.rstrip("/\\")
    from amaze.helpers import helpers, hostos
    with hostos.file_lock(into) as held:    # one update of an install at a time on this computer
        if not held:
            raise OSError(messages.UPDATE_ALREADY_RUNNING)
        workspace = tempfile.mkdtemp(    # beside the install, so the swap never crosses a drive
            prefix=os.path.basename(into) + ".update.", dir=os.path.dirname(into))
        try:
            with helpers.download_operation(messages.DOWNLOADING_UPDATE) as on_bytes:
                staged = fetch_and_stage(found.url, workspace,
                                         digest=getattr(found, "digest", ""),
                                         size=getattr(found, "size", 0), on_bytes=on_bytes)
            return apply_update(staged, into)    # Esc cannot cancel this: a stopped rename leaves a partial install
        finally:    # the workspace is always removed
            shutil.rmtree(workspace, ignore_errors=True)


def apply_update(staged: str, install: str, disk=None) -> None:
    """Put `staged`, with every add-on, where `install` is; the old one goes once the new one is in."""
    from amaze.core import guard
    if not os.path.isdir(staged):
        raise OSError("the staged update is not there: %s" % staged)
    install = install.rstrip("/\\")
    if os.path.isdir(install + guard.ASIDE) and os.path.isdir(install):
        _copy_addons(install + guard.ASIDE, install)    # an older build left the only copy there
    _copy_addons(install, staged)    # part of the swap: if the add-on copy fails, nothing is installed
    guard.swap_folder(staged, install, disk)
    debug.event("updater", "update applied", install=install)


def _copy_addons(old: str, new: str) -> None:
    """Copy the add-ons `new` lacks out of `old`; raises OSError with a complete sentence."""
    from amaze.core import addons
    try:
        addons.copy_addons(old, new)
    except OSError as exc:
        debug.event("updater", "add-ons not copied", error=str(exc), kept=old)
        raise OSError(
            "the installed add-ons could not be copied into the update (%s), "
            "so it was not installed. Nothing has been changed." % exc) from exc
