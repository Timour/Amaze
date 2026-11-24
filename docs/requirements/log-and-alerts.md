# Log and alerts: requirements

What the debug log and the alerts must do. The engine is `core/debug.py`. The log keeps file
paths and asset names, so a bug report can name what failed. The levels and the rules for tests
are in the [README](README.md).

## Catastrophe

- LG-01 Catastrophe: Exporting the log never writes over a file in the folder chosen.

## Severe

- LG-10 Severe: Logging never crashes or holds up Houdini and never fills the disk: a write that fails is dropped, each file stops at 32 MB with one older copy kept, and a failure repeating in a loop is written only a few times.

## Wrong output

- LG-20 Wrong output: An uncaught error in Amaze is recorded with Debug Mode on or off, and Houdini's own handling still runs; with Debug Mode off nothing else is written.
- LG-21 Wrong output: A repeated failure's count is exact, from any number of threads, and its total is written when it goes quiet or Houdini quits.
- LG-22 Wrong output: Each alert shows once per session, however often its condition comes back; it is logged every time.
- LG-23 Wrong output: A failed action is said on the status line; damage to the library opens a dialog, never inside a mouse release.
- LG-24 Wrong output: Export copies the whole log, named for the computer, system, Houdini and time; with no log, an empty log, or a folder it cannot write, it says why and writes nothing.
