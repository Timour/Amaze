"""
Models for the Nodes section - standalone node-network assets.

Copernicus only, once (hence every `cop` name in here and in the saved
data - the keys are load-bearing and were left alone when the section
widened). It now saves node setups from any context Houdini has: a
whole network, a selection, or a single node, in SOP, COP, LOP, DOP,
TOP, CHOP or at object level. Each asset records ITS context in the
`renderer` field - the one that held the literal "COP" before, so old
assets read correctly with no migration - and that field decides both
where the asset may be imported back and what its tile subtitle says.

A second, fully independent material-style library over its own
cops.json database in the same library directory: CopLibrary and
CopCategories subclass the material machinery (MaterialLibrary /
Categories with a different DB_FILENAME), so categories, favorites,
tags, thumbnail loading/delivery, deletion and the proxy filtering all
come from the proven material code paths. Only what genuinely differs
is overridden here: the save chain (the context label instead of
renderer detection), the import (recreates the network, refusing a
context that cannot hold those nodes, instead of routing to MAT/LOP)
and the thumbnail (the COP network's own output image, a SOP asset's
geometry, the node icon for everything else - no shaderball).

Asset files share the material library's asset/img directories
(<id>.mat / <id>.interface / <id>.png with globally unique ids);
cleanup_db unions ids across both databases so neither library's
cleanup treats the other's files as orphans.
"""

import hou
from PySide6 import QtCore

from amaze.core import debug, library, category, material
from amaze.render import nodes, thumbs


class CopCategories(category.Categories):
    """The Cop section's category sidebar - same model, own database."""

    DB_FILENAME = "cops.json"


class CopLibrary(library.MaterialLibrary):
    """The Cop section's asset model - material machinery over cops.json."""

    NOTES_SECTION = "cop"

    DB_FILENAME = "cops.json"

    #: Houdini's child-type category -> the container node type that
    #: can hold those nodes when one has to be created. The saved
    #: .interface records the REAL type (a sopnet vs a geo, say); this
    #: is only the fallback when that record is unreadable.
    CONTAINER_FOR = {
        "Cop": "copnet",
        "Sop": "geo",
        "Dop": "dopnet",
        "Lop": "lopnet",
        "Top": "topnet",
        "Chop": "chopnet",
        "Vop": "matnet",
        "Object": "subnet",
    }

    #: Contexts this section saves and restores. Vop is absent on
    #: purpose - a material builder is a material, and the material
    #: section owns it.
    SAVE_CONTEXTS = ("Sop", "Cop", "Lop", "Dop", "Top", "Chop", "Object")

    #: Contexts whose tiles can hold a rendered picture at all. The
    #: rest get the node icon - a LOP or DOP asset has no image, and
    #: "Missing Thumbnail" would read as a failure rather than as the
    #: normal state it is. "" is the pre-context COP assets.
    RENDERABLE = ("SOP", "COP", "")

    #: Node types whose INTERIOR is what "save the network" means.
    #: A whitelist, not "anything with children": a light carries 33
    #: internal SOPs and a camera 3, so has-children reads every light
    #: in the scene as a network waiting to be saved. Anything outside
    #: this list - an HDA, a light, a leaf node - is saved as itself.
    #: Kept in step with the TYPES tuple in OPmenu.xml's
    #: saveCopToAssetLib item, which has to predict this decision to
    #: label the menu entry before the panel makes it.
    CONTAINER_TYPES = ("geo", "copnet", "dopnet", "lopnet", "topnet",
                       "chopnet", "subnet", "sopnet", "objnet")

    #: (destination category, asset context) -> the node Houdini
    #: itself uses to host that pairing, where a generic container
    #: would be wrong rather than merely unusual.
    NATIVE_HOST = {
        ("Lop", "Sop"): "sopcreate",
    }

    @staticmethod
    def load_target_in(container: hou.Node, context: str) -> hou.Node:
        """Where inside `container` the saved nodes actually go.

        Usually the container itself. A native host is a WRAPPER: a SOP
        Create is a LOP whose SOPs live at `sopnet/create`, two levels
        down, beside machinery that is not the user's business.

        The wrapper TELLS US where that is. An HDA definition carries a
        DiveTarget section - the path the network editor jumps to on
        double-click - and an EditableNodes section naming what may be
        modified inside the locked asset. For a SOP Create both read
        `sopnet/create`. Asking the definition beats guessing:

        - The first version descended to the first child whose child
          category matched, which for a SOP Create is `sopnet` - the
          level ABOVE the editable area. Nodes landed beside `create`
          and `OUT`, and since OUT's input is `create`, the stage got
          empty geometry (reported live: "not as it should").
        - It also called allowEditingOfContents() to write there, which
          was BOTH unnecessary and the cause of the visible mess: an
          unlocked asset dives to its raw internals, so double-clicking
          showed sopimport/sopnet/xform instead of the user's SOPs.
          Writing to a declared editable node needs no unlock at all -
          the asset stays locked and its dive target keeps working.
        """
        try:
            if container.childTypeCategory().name() == context:
                return container
        except (AttributeError, hou.OperationFailed):
            return container

        # What the wrapper says about itself, in preference order.
        for section in ("EditableNodes", "DiveTarget"):
            try:
                definition = container.type().definition()
                path = definition.sections()[section].contents().strip()
            except (AttributeError, KeyError, hou.Error):
                continue
            if not path:
                continue
            target = container.node(path.split()[0])
            if target is None:
                continue
            try:
                if target.childTypeCategory().name() == context:
                    return target
            except (AttributeError, hou.OperationFailed):
                continue

        # Not an HDA, or it declares nothing useful: one level down.
        for child in container.children():
            try:
                if child.childTypeCategory().name() == context:
                    return child
            except (AttributeError, hou.OperationFailed):
                continue
        return container

    @classmethod
    def container_type_in(cls, dest: hou.Node, context: str,
                          preferred: str = "") -> str | None:
        """Which node type, created inside `dest`, could HOLD `context`
        nodes? The asset's own saved container type when it fits there
        (a sopnet comes back a sopnet), else the generic one for that
        context, else None - meaning dest genuinely cannot hold them.

        Asked of Houdini's type registry rather than of createNode():
        a copnet will happily CREATE a `geo` that could never work
        there, so creation succeeding proves nothing. The real test is
        that the candidate's own child category is the context we need
        housed - which also rejects the trap that every context has a
        `subnet` of its OWN kind, so a SOP subnet is not a home for
        object-level nodes.
        """
        try:
            category = dest.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return None
        if category is None or not context:
            return None

        def _holds(candidate: str) -> bool:
            node_type = hou.nodeType(category, candidate)
            if node_type is None:
                return False
            try:
                child = node_type.childTypeCategory()
            except (AttributeError, hou.OperationFailed):
                return False
            return child is not None and child.name() == context

        # The asset's own container type first, then the generic one -
        # a sopnet should come back a sopnet.
        for candidate in (preferred, cls.CONTAINER_FOR.get(context, "")):
            if candidate and _holds(candidate):
                return candidate

        # Houdini's OWN host for this pairing, where it has one. SOPs
        # in Solaris belong in a SOP Create - that is the node that
        # turns geometry into USD, and a bare sopnet there would be
        # geometry the stage never sees. Two levels deep (the SOPs live
        # in its inner sopnet), which load_target_in() handles.
        native = cls.NATIVE_HOST.get((category.name(), context))
        if native and hou.nodeType(category, native) is not None:
            return native

        # Then the canonical "network of X" type, which is how Houdini
        # names them almost everywhere: sopnet, copnet, lopnet, dopnet,
        # topnet, chopnet. That is what lets a SOP network land inside
        # a Copernicus network - refusing there while accepting the
        # identical nodes saved FROM a sopnet was incoherent.
        for candidate in ("%snet" % context.lower(), "subnet"):
            if _holds(candidate):
                return candidate

        # And then stop. Asking the registry for ANY type that holds
        # this context does find one - /stage's copytopoints holds
        # SOPs, and so does a third-party LYNX fabric HDA, which is
        # what an alphabetical scan actually returned when measured.
        # A container the user has never heard of is a worse answer
        # than "open the matching context first".
        return None

    @classmethod
    def is_container(cls, node: hou.Node) -> bool:
        """Is this node a network this section can put nodes INTO? The
        drop target test - an empty geo is a fine place to land, which
        is why emptiness is not part of it."""
        return (node.type().name() in cls.CONTAINER_TYPES
                and cls.context_of(node) in cls.SAVE_CONTEXTS)

    @classmethod
    def saves_whole_network(cls, node: hou.Node) -> bool:
        """Would clicking THIS node alone save its interior? True for a
        non-empty network container in a supported context - an empty
        one, or any other node, is saved as itself instead."""
        return cls.is_container(node) and bool(node.children())

    @staticmethod
    def context_of(node: hou.Node, items: list | None = None) -> str:
        """Which Houdini context these nodes live in - "Sop", "Cop",
        "Lop"... Taken from the network that CONTAINS them, so a
        selection and its whole network agree.

        This becomes the asset's `renderer` field, which already held
        the literal "COP" when this section was Copernicus-only: every
        existing asset therefore reads correctly with no migration,
        and the tile subtitle keeps working unchanged.
        """
        net = node.parent() if items is not None else node
        try:
            return net.childTypeCategory().name()
        except (AttributeError, hou.OperationFailed):
            return ""

    def add_asset(
        self,
        node: hou.Node,
        cats: str,
        tags: str,
        fav: bool,
        items: list | None = None,
        name: str = "",
    ) -> str:
        """Register a node network as a library asset - the whole
        container (items None), or a SELECTION of items inside one
        (a single node is a one-item selection).

        Works in ANY context: the asset records which one in its
        renderer field ("SOP", "COP", "LOP"...), which is what decides
        where it may be imported and what its tile subtitle reads. The
        asset takes `name` (the save dialog's editable Name field),
        falling back to the node's own name when empty. Returns that
        context label on success, "" on failure."""
        handler = nodes.NodeHandler(self.preferences)
        new_mat = material.Material()
        tags = self.sanitize_tags(tags)
        context = self.context_of(node, items)
        label = (context or "NODE").upper()
        new_mat.set_data(name.strip() or node.name(), cats, tags, fav, label)
        new_mat.node_color = nodes.custom_node_color(node)

        if not handler.save_node_cop(node, new_mat.mat_id, items=items):
            return ""
        # For COP assets the cop_net field carries the recorded
        # thumbnail source node name ({"thumb_node": ...}) - read from
        # the LIVE network's display flag at save time, since flags
        # don't reliably survive the items-file round-trip.
        new_mat.cop_net = handler.cop_info
        row = len(self._assets)
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        self._assets.append(new_mat)
        self.endInsertRows()
        self._add_thumb_paths(self.index(row, 0))
        # The .mat/.interface are already in mat/ by this point
        # (save_node_cop ran above), so a refused list write leaves a
        # tile in the grid that is gone next launch and files no list
        # accounts for. Same asymmetry MaterialLibrary.add_asset has
        # always handled; the shared tail lives on the base class now
        # so this cannot drift apart again.
        if not self.save():
            self.report_refused_index_write(new_mat)
        try:
            node.setUserData("assetlib_id", str(new_mat.mat_id))
        except hou.OperationFailed:
            pass
        return label

    def _missing_thumb_image(self, row: int = -1):
        """The node icon for anything unrenderable - see RENDERABLE.

        A CHOSEN tile icon outranks it: the node icon is the fallback
        for "we have no picture", and a user who picked one has given
        us a picture. Base class first, in that case."""
        if self.tile_icon(row):
            return super()._missing_thumb_image(row)
        if 0 <= row < len(self._assets):
            context = str(
                getattr(self._assets[row], "renderer", "") or ""
            ).upper()
            if context not in self.RENDERABLE:
                return self._placeholder_image("icon_nodes.svg")
        return super()._missing_thumb_image(row)

    def import_asset_to_scene(
        self, index, target: str = "auto", context_node=None
    ):
        """Recreate the saved network in the scene. The target argument
        is accepted for signature compatibility but ignored - a COP
        network has exactly one kind of home. context_node optionally
        pins the destination (drag release point)."""
        handler = nodes.NodeHandler(self.preferences)
        return handler.import_cop_asset(
            self._assets[index.row()], context_node=context_node
        )

    def render_thumbnail(self, index) -> None:
        """Rerender one COP asset's thumbnail from its saved files -
        replaces the material version's shaderball pipeline with the
        network's own output image."""
        try:
            asset = self._assets[index.row()]
            info = getattr(asset, "cop_net", {}) or {}
            thumber = thumbs.ThumbNailRenderer(self.preferences)
            context = str(getattr(asset, "renderer", "") or "").upper()
            with hou.InterruptableOperation(
                "Rendering", "Performing Tasks", open_interrupt_dialog=True
            ):
                if context == "SOP":
                    thumber.create_thumb_sop(str(asset.mat_id))
                elif context in ("COP", ""):
                    # "" covers assets saved before the section knew
                    # about contexts - they are all Copernicus.
                    thumber.create_thumb_cop(
                        str(asset.mat_id), str(info.get("thumb_node", ""))
                    )
                else:
                    # One tile was right-clicked, so the sentence is
                    # about that tile - and it names the two kinds that
                    # CAN be rerendered (RENDERABLE above), because
                    # "this one cannot" with no boundary is a dead end.
                    debug.note(
                        "%s networks have no picture to render, so "
                        "this tile keeps its node icon. Only "
                        "Copernicus and SOP networks can be "
                        "rerendered." % context)
        except Exception as exc:
            debug.note(
                "the thumbnail could not be rerendered (%s). The tile "
                "keeps the picture it had, and the saved network is "
                "unchanged." % exc)
        finally:
            self._add_thumb_paths(index)
