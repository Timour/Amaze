# Requirements

One list per engine: what the engine must do, in plain words. Each line is one requirement: an id,
its level, and what must hold. Each requirement has at most one test, named after its id
(`test_fm01_...`), and a test that proves no listed requirement is not kept.
`tools/check-requirements.py` checks this before every test run.

Levels:
- **Catastrophe**: the library is corrupted or files are lost. Every one is tested, under every
  fault that can reach it: a write cut off halfway, a full disk, a crash mid-change, a file locked
  by another program. Every push runs these tests.
- **Severe**: scene work is lost, an asset is saved over another one, or Houdini crashes.
  Every one is tested, and every push runs these tests.
- **Wrong output**: a wrong result that can be undone. Tested where the engine call is simple,
  and run when its engine changes.
- UI errors are not listed: they are judged in Houdini.

The lists: [library storage](library-storage.md), [file moves](file-moves.md).
