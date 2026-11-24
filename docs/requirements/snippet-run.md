# Snippet run: requirements

What running a snippet and setting one on a node must do. The engine is `actions/code.py` and the
run and drop handlers of `sections/code.py`; where a drop lands is DD. The levels and the rules for
tests are in the [README](README.md).

## Severe

- CD-01 Severe: A snippet that fails, by an error or by calling exit, never stops Houdini: its error's last line is shown, and what it changed before the error is one undo step.
- CD-02 Severe: Setting a snippet changes only that node's code parameter, as one undo step; a parameter Houdini will not write is left as it was, with the reason.

## Wrong output

- CD-20 Wrong output: Run runs a Python snippet in this Houdini as one undo step named `Run <name>`, with the `kwargs` a shelf click gives, modifier keys mapped per system.
- CD-21 Wrong output: Only a Python snippet runs; any other language is refused with a reason.
- CD-22 Wrong output: A snippet dropped or double-clicked on a node with a code parameter is set on it exactly as saved, replacing its code with no question; on network space a node for its language is made where that network kind has one, loaded with it; elsewhere nothing is made.
