# Changelog

## 1.11.13

- A test checks that every drawn button is wide enough for its label; nothing changes in the app.

## 1.11.12

- The drawn Add-On tab lists the store's eight add-ons; nothing changes in the app.

## 1.11.11

- The code's own notes call Update Render by its name; nothing changes in the app.

## 1.11.10

- The Material section's Houdini code is kept apart from its list of materials; nothing changes in the app.

## 1.11.9

- Other files in the File section now show their system icon by default instead of the generic file icon.

## 1.11.8

- The File section's Houdini code is kept apart from its list of files; nothing changes in the app.

## 1.11.7

- The Node section's Houdini code is kept apart from its list of assets; nothing changes in the app.

## 1.11.6

- Long tooltips on tiles, list rows and sidebar rows now wrap at one width, file and folder paths included.

## 1.11.5

- The Capture, Updates and Reload shelf tools run their steps inside Amaze, where the test suite checks them.

## 1.11.4

- The message shown when Amaze starts with no user picked now only says what to do.

## 1.11.3

- Manage Libraries names the open library at its top, and a library picked for removal shows in red.

## 1.11.2

- The old user picker is removed; nothing changes in the app.

## 1.11.1

- Amaze opens a library only with a user picked. When it starts without one, it says so and offers Open Preferences, where a user is picked or created on the Library tab. Amaze no longer names a user itself.

## 1.11.0

- Preferences ▸ Library picks a library and its user together. Library lists the libraries this computer has opened, the most recent first; Add puts a library folder in the list, or an empty folder for a new library, and Manage takes libraries off it. Apply opens the picked library with the picked user, and Accept does the same and closes Preferences.
- The User list shows the picked library's users and picks the one with the same name as the current user, or the library's only user. A new user is made when you press Apply.
- Format shows the picked library's version. The line beside Apply says when applying updates an older library; a library from a newer Amaze cannot be applied.
- Library ▸ Set Library opens Preferences on the Library tab.
- Test Library uses the user with the same name in the test library, and creates it there when it is missing.

## 1.10.25

- Amaze keeps a list of the libraries it opens, for the Library list coming to Preferences; nothing changes in the app yet.

## 1.10.24

- Two users in one library can no longer have the same name; Preferences says so when you try.

## 1.10.23

- Picking a library whose index has not arrived yet now says so every time, and leaves the folder untouched.

## 1.10.22

- A library with a missing index no longer shows an error. Amaze opens without a library, and switching to one keeps your current library.

## 1.10.21

- Switching to a library with a damaged index now asks Repair or Cancel. Cancel keeps your current library.

## 1.10.20

- You can no longer choose the root of a disk as the Library Path.

## 1.10.19

- When the library index cannot be read, the pane opens first and then asks whether to Repair it or Open Without Library.

## 1.10.18

- Turning Test Library on or off now says when the library's list has not arrived yet, as opening the pane already did.

## 1.10.17

- After changing the Library Path or turning Test Library on or off, closing Preferences no longer reads the library a second time.

## 1.10.16

- After changing the Library Path or turning Test Library on or off, a thumbnail rendered while Preferences is still open takes its textures from the new library.

## 1.10.15

- A refused drag writes `Amaze: The action was canceled.` in Houdini's status bar, as information rather than a warning.

## 1.10.14

- A drag that ends in the red cross says why in Houdini's status bar: `Nothing here takes a material`, or a node asset, snippet, file or palette.

## 1.10.13

- The list of the files an asset owns has one home, which the library and its versions both read; nothing changes in the app.

## 1.10.12

- With developer reloading on, reopening the pane also reloads the code that opens a library; nothing changes in the app.

## 1.10.11

- Repair's dialogs call its checks' helpers by their public names; nothing changes in the app.

## 1.10.10

- Installing an add-on checks it against the running Houdini, which Update on the Add-On tab passes in; nothing changes in the app.

## 1.10.9

- Repair's questions and messages are kept apart from its checks; nothing changes in the app.

## 1.10.8

- Clean Up Library's work is kept apart from the pane that asks first and reports after; nothing changes in the app.

## 1.10.7

- The debug log no longer opens dialogs itself: the pane and each shelf tool give it Houdini's dialog and status line when they start; nothing changes in the app.

## 1.10.6

- The steps that ready, update and seed a library when it opens are kept apart from the pane; nothing changes in the app.

## 1.10.5

- Checking for and installing add-ons is kept apart from the Add-On tab that shows it; nothing changes in the app.

## 1.10.4

- The questions and messages around installing an update are kept apart from the code that installs it; nothing changes in the app.

## 1.10.3

- The test suite checks that each part of Amaze uses only the parts below it; nothing changes in the app.

## 1.10.2

- The manual's slider picture is no longer part of the install; it sits with the manual's other pictures.

## 1.10.1

- The Reload tool on the Amaze shelf has its own icon.

## 1.10.0

- Amaze updates a library to version 2 the first time it opens it, without asking. 1.9.0 asked first: its dialog could come up black, with the pane waiting behind it until it was closed, and Later left the library on version 1.
- A library that a newer Amaze has updated does not open. Amaze offers to update itself instead.
- When a newer Amaze would also update the library, Check for Updates turns Install Update red, and the version line names the library version it updates to. Install Update, and the Updates tool on the shelf, then ask to Continue or Cancel.
- Preferences ▸ Library shows the library's new version as soon as an update finishes, also while the window is open.

## 1.9.0

- Any tile can show a capture, a picture of the Scene View. Capture on a tile's right-click menu takes one, and so does the Capture button, which the toolbar now shows in every section. A scene can be captured while it is the open scene.
- Customize ▸ Icon lists Render, Capture, Generic and Custom. Render was called Preview.
- Update Preview on the right-click menus is called Update Render.
- The Capture button has a new icon.
- Captures are stored in the library's `captures` folder, so every computer using the library shows them.
- Libraries have a version of their own, on Preferences ▸ Library. Amaze 1.9.0 updates a library to version 2: on a computer with scene captures from an older Amaze, it asks before moving them into the library, and the originals go to Amaze's holding folder for 30 days.
- Show ▸ Pathname shows a renamed folder's path.
- The Capture tool on the Amaze shelf works again.

## 1.8.2

- Online source tabs open their lists faster; SimReady's, the longest, opens about thirty times faster.
- In every section, going back to All after a category, clearing a search and clicking a column heading are many times faster.
- SimReady's list updates from NVIDIA's site in about a third of the time: only the archives that changed are read again.
- Two Amaze panes on the same library share each section's sort order.
- In List view, pointing at any cell of a row shows that row's tooltip.

## 1.8.1

- Preferences ▸ Show/Hide has two sub-tabs: Renderer holds the renderer switches, Sections the section switches.

## 1.8.0

- Preferences ▸ About ▸ Add-On beta versions: when on, Check for Updates on the Add-On tab installs the newest beta of each add-on instead of its release; when off, it installs the release again.
- The Test Library folder sits beside its switch in Preferences ▸ About.

## 1.7.0

- Preferences ▸ Add-On, a new tab between Look and About, lists the nodes of each installed add-on with a picture, version, author and short description. Each has a switch that turns it off or on from the next Houdini start.
- Check for Updates on the Add-On tab finds new add-ons and newer versions in the Amaze store, and Update installs them.
- The `Amaze.json` template loads Amaze's add-ons with one `package_path` line, written out in full; copy the new template from the README.

## 1.6.3

- The `Amaze.json` template lists the folder Amaze's add-ons will install into, and uses `hpath` in place of the retired `path` key; copy the new template from the README.
- An Octane material's thumbnail no longer comes out black when it is saved or re-rendered.

## 1.6.2

- A renderer switched off in Preferences ▸ Show/Hide is gone from the Filter menu, Convert to, Import to Materials and Import to Scene, and its Samples row leaves the Render tab.
- Opening the Amaze pane builds the panel in about half the time.
- Amaze's code loads about five times faster when the pane first opens: it stays compiled after an update, and the dialogs, converters and render code load only when used.
- A library folder written without its trailing slash in the settings file opens.
- Amaze is developed and tested on Houdini 22.0.

## 1.6.1

- The Label and Copy Color submenus draw their colour chips 2 px lower.
- Convert to, Import to Materials and Import to Scene show each renderer with the icon the Material Filter menu gives it.

## 1.6.0

- Convert to ▸ Octane: a MaterialX or Redshift material becomes an Octane material, built in Octane's own material builder.
- Convert to ▸ MaterialX and ▸ Redshift take Octane materials too.
- The online Import to Materials and Import to Scene can build a material as Octane.
- Copy To ▸ /stage takes an Octane material saved in the classic Octane container, rebuilt into Octane's Solaris builder on the way in.
- Convert to greys a renderer whose plugin is not loaded, whether it is the material's own or the one it would become.

## 1.5.0

- The category menu in the Material, Color, Node and Code sidebars reads Add, Rename, Delete, Sort by name, Label and Export Category. Label colours a category Red, Yellow, Blue, Green or a Custom colour; Remove takes the colour off.
- The File sidebar menu reads Add, Locate, Rename, Remove, Show and Label. Rename ▸ Edit names a location, and Set to Default goes back to the folder's own name.
- Show ▸ sets what a location lists: Pathname names it by its full path, Subfolder lists the folders inside it, and Other Files, Images, Geometry and HIP are the kinds of file, in any combination. A new location lists Images, Geometry and HIP, the Import location a package creates lists every kind, and a location added before keeps what it listed.
- Preferences ▸ Look no longer has All show unknown files; Show ▸ Other Files sets it per location.
- The edit badge's underline is thinner at rest and wider under the pointer, and the comment badge's outline turns a brighter purple under the pointer.

## 1.4.1

- The test suite starts each Houdini version with its own setup; nothing in the app changes.

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
