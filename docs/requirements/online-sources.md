# Online sources: requirements

What importing from the online sources must do: the catalogues, a download saved into the library,
and a build in the scene. The engine is `core/matx_sources.py`, `core/matx_import.py`,
`core/matx_translate.py`, `core/matx_usd.py`, `core/matx_library.py`, `render/generator.py` and
`pane/online_import.py`. A store `.amazepkg` is in [packages](packages.md); the save is SL; the
folder and textures are LS-36 and LS-37 in [library storage](library-storage.md); a converted
import's report is MC-26. The levels and the rules for tests are in the [README](README.md).

## Catastrophe

- ON-01 Catastrophe: A download writes only into its own new folder, in the temporary folder for an import into the library or in `$HIP/tex` for Import to Scene, and the library takes its files only through the new material's save, never over a file already there; a path from a catalogue, archive or document that leads outside the download's folder is skipped and reported.
- ON-02 Catastrophe: A download arrives whole or not at all: cut off, short, over the size cap or stopped with Esc, it leaves no row, no folder and no stray file.

## Severe

- ON-10 Severe: Only https is fetched, redirects included; a certificate that cannot be verified refuses the fetch, never retried unverified.
- ON-11 Severe: An import into the library leaves the scene as it was: what it builds is off the undo list and removed when it ends.
- ON-12 Severe: An import never freezes Houdini: it shows its progress, Esc stops it, and nothing over the cap is read into memory.

## Wrong output

- ON-20 Wrong output: Each source lists its materials; a source that cannot be reached is named, and the others still list.
- ON-21 Wrong output: The resolution chosen in Preferences is fetched; when a material lacks it, the nearest is fetched and the status line says so; a material with none is refused, named.
- ON-22 Wrong output: An import into the library is always its own download; Import to Scene reuses a download already in `$HIP/tex` only when it was made at the same resolution.
- ON-23 Wrong output: The new material is MaterialX, or the renderer picked, with its name, category, tags, licence, source and source id, and a comment crediting the source, author and page.
- ON-24 Wrong output: A texture the document names but the download lacks is matched by name where it can be; one that cannot is named, and the rest still imports.
- ON-25 Wrong output: One failing record does not stop the batch; one message names each failure; after Esc the saved materials stay, with their pictures.
- ON-26 Wrong output: Import to Scene builds into the Material Library the editor is in, else its material network, else /mat, as one undo step; the last one is current and selected; its download is kept in `$HIP/tex`, and texture paths are written as Write Paths As says.
- ON-27 Wrong output: Generate builds one random material in the scene as one undo step, its provenance in its comment, and adds nothing to the library.
