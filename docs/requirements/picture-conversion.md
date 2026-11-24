# File picture conversion: requirements

What turning a user's picture file into a tile picture must do. The engine is `core/conversion.py`,
run by the convert worker in `core/thumbnails.py`, cached by `core/texture_library.py`. Where
pictures are kept and when a file is tried again is TP-29; a late picture is TP-26; a reload while
converting is TP-14, in the [tile pictures](tile-pictures.md) list. The levels and the rules for
tests are in the [README](README.md).

## Catastrophe

- CV-01 Catastrophe: Converting only reads the user's file: nothing is written, moved or removed beside it, and every temporary file is removed, whether it works, fails or is cancelled.

## Severe

- CV-10 Severe: Converting never crashes or holds up Houdini: a picture over 1 GB once decoded is declined, a converter is stopped after 30 seconds or on cancel, Houdini never waits more than half a second for one that will not die, and a file whose reads hang gets no second converter.

## Wrong output

- CV-20 Wrong output: A file any converter reads gets a picture no larger than asked, in its own shape.
- CV-21 Wrong output: A converter's blank output is never taken as the picture; a file that is truly one colour still gets its own.
- CV-22 Wrong output: A conversion that was cancelled, timed out, or whose converter did not start is not a verdict: the file is not marked unreadable.
