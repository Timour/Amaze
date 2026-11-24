# Add-ons: requirements

What installing, updating and turning off add-ons must do. An add-on is a Houdini package in Amaze's
own install, `addons/<folder>`, outside the library. The engine is `core/addons.py`,
`actions/addons.py` and the Add-On page; the container is shared with [packages](packages.md); an
Amaze update keeps them (UP-05, in [updates](updates.md)). The levels and the rules for tests are
in the [README](README.md).

## Catastrophe

- AO-01 Catastrophe: An install, update or switch writes and removes only inside `addons/`: its own folder, its scratch folders and its package file; a member path that leaves its folder refuses the package.

## Severe

- AO-10 Severe: An update is all or nothing: cut off at any moment, a crash included, it leaves one whole version installed, the old or the new, never none; a crash between the swap's two renames is put right the next time the add-ons are read.
- AO-11 Severe: A package that cannot be installed whole changes nothing: a damaged zip, a missing or unlisted member, a newer format, a wrong field, more than 512 MB unpacked, or a Houdini older than it needs is refused with the reason before the first write.
- AO-12 Severe: A package never replaces an installed add-on of another name: it is refused, naming both, and the installed one stays.

## Wrong output

- AO-20 Wrong output: Check offers each add-on whose store version is newer than the one installed, or of the other kind when the Betas switch is set; releases and betas are never offered together.
- AO-21 Wrong output: Update installs what Check found and names each one installed; an error or Esc stops the rest and still names those installed.
- AO-22 Wrong output: Turning a row off moves all its node files where Houdini does not load them, and on moves them all back; an update keeps an off row off; both apply at Houdini's next start, which the page says.
- AO-23 Wrong output: Houdini loads each installed add-on once, through its package file in `addons/`.
- AO-24 Wrong output: The page lists one row per group, or per node in no group; an add-on whose manifest does not read is not listed.
