"""Models for the Nodes section - standalone node-network assets, saved from and restored into any context Houdini has. ▸p/nodes-section"""

import hou
from PySide6 import QtCore

from amaze.core import debug, library, category, material
from amaze.render import nodes, thumbs


def default_face(renderer: str):
    """The Node section's face for a row with no thumbnail: the node icon for anything unrenderable (see RENDERABLE), the base missing face otherwise - the one rule, shared with the online browser."""
    if str(renderer or "").upper() not in CopLibrary.RENDERABLE:
        return CopLibrary._placeholder_image("icon_nodes.svg")
    return CopLibrary._placeholder_image("missing_thumbnail.svg")


class CopCategories(category.Categories):
    """The Cop section's category sidebar - same model, own database."""

    DB_FILENAME = "cops.json"


class CopLibrary(library.AssetLibrary):
    """The Cop section's asset model - the shared engine over cops.json."""

    NOTES_SECTION = "cop"    # the section was Copernicus-only once, so every `cop` name here and in the saved data is load-bearing and stayed put when the section widened

    DB_FILENAME = "cops.json"    # its own database in the material library's directory, but the asset FILES share that library's folders - `<id>.mat`, `<id>.interface` and `<id>.png` under globally unique ids - so `cleanup_db` unions the ids of BOTH databases before calling any file an orphan

    CONTAINER_FOR = {    # Houdini's child-type category -> the container node type to CREATE when a saved network needs a home; the fallback only, because the saved `.interface` records the REAL type (a sopnet rather than a geo) whenever that record can be read ▸r/node-graph
        "Cop": "copnet",
        "Sop": "geo",
        "Dop": "dopnet",
        "Lop": "lopnet",
        "Top": "topnet",
        "Chop": "chopnet",
        "Vop": "matnet",
        "Object": "subnet",
    }

    SAVE_CONTEXTS = ("Sop", "Cop", "Lop", "Dop", "Top", "Chop", "Object")    # what this section saves and restores; `Vop` is absent because a material builder is a material and the material section owns it, and `OPmenu.xml` keeps a literal copy of this tuple so a right-click never has to import the package

    RENDERABLE = ("SOP", "COP", "")    # contexts whose tiles can hold a rendered picture at all; every other one gets the node icon, and the empty string is the pre-context COP assets ▸p/nodes-section

    CONTAINER_TYPES = ("geo", "copnet", "dopnet", "lopnet", "topnet",
                       "chopnet", "subnet", "sopnet", "objnet")    # node types whose INTERIOR is what saving the network means - a whitelist, not has-children ▸r/node-graph - and anything outside it is saved as itself. `OPmenu.xml`'s `saveCopToAssetLib` mirrors this tuple as `TYPES`, because it has to predict this decision to label its menu entry before the panel makes it

    NATIVE_HOST = {    # (destination category, asset context) -> the node Houdini itself uses to host that pairing, where a generic container would be wrong rather than merely unusual
        ("Lop", "Sop"): "sopcreate",
    }

    @staticmethod
    def load_target_in(container: hou.Node, context: str) -> hou.Node:
        """Where inside `container` the saved nodes actually go - the container itself, or the editable network a wrapper HDA declares, which for a SOP Create is `sopnet/create`, two levels down. It never answers None: `container` is the answer when nothing better is found, and the asset stays LOCKED either way. ▸r/hda-wrappers"""
        try:
            if container.childTypeCategory().name() == context:
                return container
        except (AttributeError, hou.OperationFailed):
            return container

        for section in ("EditableNodes", "DiveTarget"):    # what the wrapper says about itself, in preference order
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

        for child in container.children():    # not an HDA, or it declares nothing useful: one level down
            try:
                if child.childTypeCategory().name() == context:
                    return child
            except (AttributeError, hou.OperationFailed):
                continue
        return container

    @classmethod
    def container_type_in(cls, dest: hou.Node, context: str,
                          preferred: str = "") -> str | None:
        """Which node type, created inside `dest`, could HOLD `context` nodes? The asset's own saved container type when it fits there (a sopnet comes back a sopnet), else the generic one for that context, else Houdini's own host for the pairing, else the canonical network type - and else None, which means `dest` genuinely cannot hold them, so the caller must refuse rather than build something. ▸r/node-graph"""
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

        for candidate in (preferred, cls.CONTAINER_FOR.get(context, "")):    # the asset's own container type first, then the generic one - a sopnet should come back a sopnet
            if candidate and _holds(candidate):
                return candidate

        native = cls.NATIVE_HOST.get((category.name(), context))    # Houdini's OWN host for this pairing: SOPs in Solaris belong in a SOP Create, the node that turns geometry into USD, and its SOPs sit two levels in, which load_target_in() handles
        if native and hou.nodeType(category, native) is not None:
            return native

        for candidate in ("%snet" % context.lower(), "subnet"):    # then the canonical network-of-X type, which is how Houdini names them almost everywhere: sopnet, copnet, lopnet, dopnet, topnet, chopnet
            if _holds(candidate):
                return candidate

        return None    # and then stop. Scanning the registry for ANY type that holds this context does find one - `/stage` answered `copytopoints` and a `geo` answered a third-party LYNX HDA when measured ▸p/nodes-section - and a container the user has never heard of is a worse answer than a refusal naming the context to open first

    @classmethod
    def is_container(cls, node: hou.Node) -> bool:
        """Is this node a network this section can put nodes INTO? The drop target test - an empty geo is a fine place to land, which is why emptiness is not part of it."""
        return (node.type().name() in cls.CONTAINER_TYPES
                and cls.context_of(node) in cls.SAVE_CONTEXTS)

    @classmethod
    def saves_whole_network(cls, node: hou.Node) -> bool:
        """Would clicking THIS node alone save its interior? True for a non-empty network container in a supported context - an empty one, or any other node, is saved as itself instead."""
        return cls.is_container(node) and bool(node.children())

    @staticmethod
    def context_of(node: hou.Node, items: list | None = None) -> str:
        """Which Houdini context these nodes live in - `Sop`, `Cop`, `Lop` and so on - taken from the network that CONTAINS them, so a selection and its whole network agree. It becomes the asset's `renderer` field, which already held the literal `COP` when this section was Copernicus-only, so every existing asset reads correctly with no migration. Answers the empty string when the node has no child category."""
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
        """Register a node network as a library asset - the whole container when `items` is None, or a SELECTION of items inside one, where a single node is a one-item selection. Works in ANY context, and `name` is the save dialog's editable Name field, falling back to the node's own name when empty. Returns the uppercase context label it recorded in the asset's renderer field - the field that decides where the asset may be imported back and what its tile subtitle says - or the empty string on failure."""
        handler = nodes.NodeHandler(self.preferences)
        new_mat = material.Material()
        tags = self.sanitize_tags(tags)
        context = self.context_of(node, items)
        label = (context or "NODE").upper()
        new_mat.set_data(name.strip() or node.name(), cats, tags, fav, label)
        new_mat.node_color = nodes.custom_node_color(node)

        if not handler.save_node_cop(node, new_mat.mat_id, items=items):
            return ""
        new_mat.cop_net = handler.cop_info    # for COP assets this carries the recorded thumbnail source node name under `thumb_node`, read from the LIVE network's display flag at save time because flags do not reliably survive the items-file round-trip
        row = len(self._assets)
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        self._assets.append(new_mat)
        self.endInsertRows()
        self._add_thumb_paths(row)
        if not self.save():
            self.report_refused_index_write(new_mat)
        try:
            node.setUserData("assetlib_id", str(new_mat.mat_id))
        except hou.OperationFailed:
            pass
        return label

    def _missing_thumb_image(self, row: int = -1):
        """The node icon for anything unrenderable - see RENDERABLE. A CHOSEN tile icon outranks it, since a user who picked one has given us a picture, so the base class answers in that case."""
        if self.tile_icon(row):
            return super()._missing_thumb_image(row)
        if 0 <= row < len(self._assets):
            return default_face(
                getattr(self._assets[row], "renderer", ""))
        return super()._missing_thumb_image(row)

    def import_asset_to_scene(
        self, index, target: str = "auto", context_node=None
    ):
        """Recreate the saved network in the scene. `target` is accepted for signature compatibility and ignored; `context_node` optionally pins the destination, which is the drag release point."""
        handler = nodes.NodeHandler(self.preferences)
        return handler.import_cop_asset(
            self._assets[index.row()], context_node=context_node
        )

    def render_thumbnail(self, row) -> None:
        """Rerender one COP asset's thumbnail from its saved files - replaces the material version's shaderball pipeline with the network's own output image, and notes a sentence instead when the asset's context has no picture to take."""
        try:
            asset = self._assets[row]
            info = getattr(asset, "cop_net", {}) or {}
            thumber = thumbs.ThumbNailRenderer(self.preferences)
            context = str(getattr(asset, "renderer", "") or "").upper()
            outcome = thumber.render_network_thumbnail(    # the Cop-or-Sop decision lives there, the one home shared with the save side; it answers None for a context with no picture, which is the branch below
                context, str(asset.mat_id),
                str(info.get("thumb_node", "")))
            if outcome is None:
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
            self._add_thumb_paths(row)
