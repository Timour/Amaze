# Changelog

## 1.4.0

- Materials built in Octane's own material builder save and import as Octane materials, and their tiles name the shader.
- Octane thumbnails render with Octane in Solaris, with a Samples (Octane) row in Preferences ▸ Render.
- Karma and Octane thumbnails render in the background, one render per batch: the bar shows progress, Cancel stops it, and each tile fills in as its picture lands.
- An Octane material saved as loose nodes imports into its holder.
- A MaterialX material saved with its own output connectors imports with one set of wires.

## 1.3.0

- A SimReady tab in the online browser: NVIDIA's OpenPBR materials, imported as MaterialX or Redshift materials with their textures and tags.
- Online tiles with no preview show the Generic icon.
- Imports to Redshift keep a texture's tiling and offset, and an OpenPBR material's normal maps.
- In a Redshift import, a texture Karma reads as data stays Raw.

## 1.2.1

- PolyHaven materials in the online browser show their previews again.

## 1.2.0

Amaze 1.2.0 adds Run and Edit buttons to Code tiles, new tile badges, a reworked Comments pane, Step Size, and a Reload tool on the shelf.

### Tiles

- Code tiles have an Edit button. Python snippets also have a Run button, which runs the snippet with the arguments a shelf tool receives.
- Every badge has new art, and the favourite badge is a heart. Badges take their colour under the pointer.
- Every tile shows a comment badge: filled when the tile has comments, an outline when it has none. Clicking it shows or hides the Comments pane, the same as the Comments button in the toolbar.
- A tile with no picture shows its section's face. Customize picks the face from its Icon menu.
- Two quick clicks on a badge are two clicks, and no longer import the tile.

### Comments

- The Comments pane has a one-row header. Its + button adds a bullet point or an image.
- The Comments button in the toolbar is purple while the pane is open.
- With nothing selected, the pane goes back to its empty state.

### Browsing

- Step Size, in Preferences ▸ Look, makes the tile size slider move from mark to mark: every 64 pixels, from 64 to 512.
- Karma is shown as MaterialX in the Filter menu, Convert to, the online Import menus and Preferences.
- The Material Filter menu shows an icon for each renderer, with All set apart.
- The File sidebar lists a package's Import folder with a live count, and counts folders in the background.
- An empty category or File location shows its empty grid, where right-clicking opens the menu.

### Saving and the shelf

- Save to Amaze is one entry on every node. The save dialog's Section row picks where the save goes.
- After a save, the saved node stays selected, and the save adds nothing to the undo stack.
- Reload, on the shelf, installs any new asset file from the packages on the Houdini path and reloads every loaded asset definition without a restart.
- Repair can restore settings.json from its saved copies.

### Libraries shared between machines

- Saves merge the edits, deletions, categories, colours, comments and thumbnails made on another machine.

### Fixes

- Clean Up Library keeps the stars on Material, Node, Code and Color assets.
- A half-written library file no longer empties stars, comments or users.
- Removing a nested File location keeps its comments, stars and icons.
- Fixed crashes in Houdini 21 during converts, imports and category edits, and when importing an online tile while previews load.
- Converting a Redshift material to MaterialX keeps its normal map's strength, and a blend with no base material is reported instead of failing the convert.
- Ctrl+Z after Update Preview no longer puts the material back into /mat. Without a Scene Viewer, Update Preview says what it needs.
- A node dropped into a network lands where its outline snapped, and a drop onto a wire undoes in one step.
- A failed material import leaves nothing in the scene or the library.
- A bad render size or sample count in the settings no longer breaks Preferences.
- Starring, customizing or deleting a selection saves each library file once.
