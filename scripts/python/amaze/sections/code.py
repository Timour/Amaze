"""The Code section: snippets in a language, applied to a node or run, edited in D11."""

from __future__ import annotations

import hou
from PySide6 import QtGui

from amaze.actions import code as code_actions
from amaze.core import debug, section_list
from amaze.helpers import wording
from amaze.pane import asks
from amaze.sections import base


class CodeSection(base.AssetSection):
    """Saved code snippets, each tagged with a language, previewed as rendered text."""

    offers_preview_update = False    # no Update Render: the preview key is content-addressed, so an edit redraws it

    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        if count == 1:
            return ("Delete this snippet? It is deleted permanently. Code "
                    "already applied to a node is not affected.")
        return ("Delete %d snippets? They are deleted permanently. Code already "
                "applied to a node is not affected." % count)

    key = "code"
    label = section_list.label(key)
    empty_noun = "snippet"
    GRID_MENU = (    # Import and Edit act on one snippet; New File needs no selection and stays enabled
        base.MenuEntry("New File", handler="menu_new_snippet", needs="always", opens="open_code",
                       glyph="file"),
        base.SEPARATOR,
        base.MenuEntry("Import", handler="menu_import", needs="one", glyph="upload_simple"),
        base.MenuEntry("Edit", handler="menu_edit", needs="one", opens="open_code", glyph="code"),
        base.SEPARATOR,
    ) + base.GRID_MENU_TAIL

    DROP = base.DropRule(on_node="drop_code_at_release",    # to the node under the cursor; on empty space a holder node is created
                    on_space="create_code_node_in",
                    click_on_node="drop_code_at_release")

    holder_node_type_method = "code_holder_node_type"    # per language AND per network kind, so a method returns it

    CODE_HOLDER_NODE_TYPES = {    # the node type created per language and network kind; an absent pair creates nothing
        "vex": {"Sop": "attribwrangle", "Lop": "attribwrangle",
                "Cop": "wrangle"},
        "opencl": {"Sop": "opencl", "Cop": "opencl"},
        "python": {"Sop": "python"},
    }

    def _code_asset(self, index) -> tuple:
        """(row, snippet) under a grid index, or (None, None) where no snippet is."""
        model = self.pane.code_model
        if not model or index is None or not index.isValid():
            return None, None
        row = self.pane.code_sorted_model.mapToSource(index).row()
        if not 0 <= row < len(model.assets):
            return None, None
        return row, model.assets[row]

    def _holder_node_type_for(self, asset, dest) -> str:
        """The node type `asset` becomes in `dest`, or "" where that network kind has none."""
        if asset is None or dest is None:
            return ""
        language = str(getattr(asset, "renderer", "") or "").lower()
        try:
            category = dest.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return ""
        return self.CODE_HOLDER_NODE_TYPES.get(language, {}).get(
            category.name() if category is not None else "", "")

    def code_holder_node_type(self, index, dest) -> str:
        """WHICH node type a snippet becomes in `dest`: the drag preview shows this type."""
        return self._holder_node_type_for(self._code_asset(index)[1], dest)

    def create_code_node_in(self, index, dest, position=None) -> bool:
        """A holder node for the snippet in `dest`, where that network kind has one, loaded with it."""
        from amaze.helpers import helpers
        _row, asset = self._code_asset(index)
        type_name = self._holder_node_type_for(asset, dest)
        if not type_name:
            return False
        name = wording.sanitize_usd_path(str(getattr(asset, "name", "") or "")) or "snippet"
        return self.pane.drop_placement.create_holder_node(
            dest, type_name, name, position, helpers.find_code_parm, asset.code,
            "Amaze Create Code Node")

    def drop_code_at_release(self, index, node: hou.Node) -> bool:
        """Apply a dropped snippet to the node under the cursor; no code parm shows a reason."""
        from amaze.core import dragengine
        pane = self.pane
        if not pane.code_model or index is None or node is None:
            return False
        try:
            source_index = pane.code_sorted_model.mapToSource(index)
        except Exception:
            return False
        with dragengine.drop_group("Amaze Apply Code Snippet"):
            ok, reason = code_actions.apply_to_node(
                pane.code_model, source_index.row(), node
            )
        if not ok:
            if reason:
                debug.refuse(reason)    # the miss icon shows the failure, the status line the reason ▸p/refuse-vs-alert
            return False
        return True

    def menu_new_snippet(self, indexes, current, payload=None) -> None:
        self.pane.saving.new_code_snippet()

    def _code_row(self, current):
        """The code model's row under a grid index, or None."""
        return self._code_asset(current)[0]

    def menu_edit(self, indexes, current, payload=None) -> None:
        row = self._code_row(current)
        if row is not None:
            self._edit_code_row(row)

    def menu_run(self, indexes, current, payload=None) -> None:
        """Run the snippet in this Houdini; why it did not run or stopped is on the status line."""
        row = self._code_row(current)
        if row is None:
            return
        asset = self.pane.code_model.assets[row]
        problem = code_actions.run(asset.name, asset.code, asset.renderer,
                                   QtGui.QGuiApplication.keyboardModifiers())
        if problem:
            debug.refuse(problem)

    def _edit_code_row(self, row: int) -> None:
        pane = self.pane
        asset = pane.code_model.assets[row]
        question = asks.CodeQuestion(
            categories=pane.code_category_model.choices(),
            name=asset.name,
            language=asset.renderer,
            category=asset.categories[0] if asset.categories else "",
            tags=", ".join(asset.tags),
            code=asset.code,
            title="Edit Snippet",
            versions_on=False,    # a snippet keeps no versions: Apply saves it
        )
        self.run_code_editor(question, str(asset.mat_id))

    def run_code_editor(self, question, mat_id: str) -> None:
        """Each Apply saves snippet `mat_id`, a new one while it is empty; the editor stays open."""
        pane = self.pane
        saved = {"id": mat_id}

        def apply(answer):
            got = pane.code_model.save_from_editor(    # NO layout pair: it emits its own model signals
                saved["id"], answer.code, answer.name, answer.language, answer.category, answer.tags)
            pane.sidebar.refresh()
            if got:
                saved["id"] = got

        pane.ui.open_code(question, apply)
    library_model_attrs = ("code_model", "code_category_model")
    model_attr = "code_model"
    proxy_attr = "code_sorted_model"
    selection_attr = "code_selection_model"
    category_attr = "code_category_model"
    sidebar_attr = "code_category_sorted_model"
    delegate_attr = "code_delegate"
    tile_badges = ("favourite", "execute", "versions", "comment")
    list_columns = ("name", "type", "category", "favorite", "comments", "tags", "license", "date",
                    "id")    # no Version column: a snippet's name is its active version's name
    filter_tooltip = "Show snippets in one language."

    FILTER_CHOICES = (    # the stored language strings, "Code" the catch-all; not imported from code_dialog
        base.FilterEntry("VEX", "VEX", "VEX"),
        base.FilterEntry("OpenCL", "OpenCL", "OpenCL"),
        base.FilterEntry("Python", "Python", "Python"),
        base.FilterEntry("Code", "Code", "Code"),
    )

    takes_language = True

    def can_save(self, nodes) -> bool:
        from amaze.helpers import helpers
        parm = helpers.find_code_parm(nodes[0]) if len(nodes) == 1 else None
        return parm is not None and bool(parm.eval().strip())    # an empty snippet saves nothing

    def commit_save(self, nodes, node, answer) -> None:
        """The snippet is the current value of the node's code parm."""
        from amaze.helpers import helpers
        parm = helpers.find_code_parm(node)
        self.pane.code_model.add_asset(    # no layout wrapper: add_asset emits its own row-insert signals
            parm.eval(),
            answer.name or node.name(),
            answer.language or helpers.code_parm_language(parm),
            answer.categories,
            answer.tags,
            False,
        )
        self.pane.sidebar.refresh()

    @classmethod
    def save_rank(cls, nodes) -> int:
        return 1
