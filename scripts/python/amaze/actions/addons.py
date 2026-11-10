"""Checking the store for newer add-ons and installing them; the Add-On tab calls both."""

from amaze import messages
from amaze.core import addons, packages, updater
from amaze.helpers import hostver


def check(betas: bool) -> tuple:
    """What the store has newer than what is installed, as (name, version, url), and the sentence."""
    try:
        store = addons.store_versions(betas)
    except (OSError, ValueError) as exc:
        return [], messages.ADDONS_STORE_UNREACHABLE % exc
    root = updater.install_root()
    have = {m["name"]: m["version"] for _f, m in (addons.installed_all(root) if root else [])}
    found = [(name, version, url) for name, (version, url) in sorted(store.items())
             if addons.wanted(have.get(name), version)]
    return found, (messages.ADDONS_AVAILABLE % ", ".join("%s %s" % f[:2] for f in found)
                   if found else messages.ADDONS_UP_TO_DATE)


def install(found, root: str) -> str:
    """Install what `check` found into the Amaze at `root`; the sentence saying what happened."""
    import functools
    import hou
    from amaze.helpers import helpers
    done = []
    running = hostver.houdini_version()
    temp_dir = hou.getenv("HOUDINI_TEMP_DIR")    # Houdini's scratch, as the thumbnail jobs use
    downloading = functools.partial(helpers.download_operation, messages.DOWNLOADING_ADDONS)
    try:
        for name, version, url in found:
            addons.fetch_and_install(url, root, running, temp_dir=temp_dir, downloading=downloading)
            done.append("%s %s" % (name, version))
    except (packages.PackageError, OSError) as exc:
        if not done:
            return str(exc)
        rest = messages.ADDONS_REST_STOPPED if str(exc) == messages.DOWNLOAD_STOPPED else str(exc)
        return "%s %s" % (messages.ADDONS_INSTALLED % ", ".join(done), rest)    # what landed is said
    return messages.ADDONS_INSTALLED % ", ".join(done)
