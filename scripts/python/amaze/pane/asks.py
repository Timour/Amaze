"""What the pane engine asks of the window it is shown in; every ask answers through a callback."""

import collections

SaveQuestion = collections.namedtuple(    # what the Save dialog opens with
    "SaveQuestion", "categories current name name_enabled sections section categories_for "
                    "language language_sections")
SaveAnswer = collections.namedtuple("SaveAnswer", "section name categories tags fav language")

CodeQuestion = collections.namedtuple(    # what the code editor opens with; None keeps the editor's own
    "CodeQuestion", "categories name language category code versions_on tags title",
    defaults=(None,) * 2)
CodeAnswer = collections.namedtuple("CodeAnswer", "code name language category tags")

CustomizeQuestion = collections.namedtuple(    # what Customize opens with
    "CustomizeQuestion", "icon stroke tile_name tile_name_enabled tile_tags categories "
                         "tile_category face faces can_preview")
CustomizeAnswer = collections.namedtuple("CustomizeAnswer", "spec name tags category")


def answers(host, ask: str) -> bool:
    """Whether `host` gives its own answer to `ask`, not the protocol's NotImplementedError."""
    return getattr(type(host), ask, None) is not getattr(Asks, ask, None)


class Asks:
    """The host's side: each `then` is called once, None for a cancel; a modal host calls it at once."""

    def ask_name(self, title: str, default: str, then) -> None:
        """A name: `then(text)`, "" for a cleared field."""
        raise NotImplementedError

    def ask_colour(self, start: str, title: str, then) -> None:
        """A colour picked from `start`: `then("#rrggbb")`."""
        raise NotImplementedError

    def ask_drop_choice(self, labels: list, then, at) -> None:
        """One of `labels` picked in a menu at screen point `at`: `then(its place in labels)`."""
        raise NotImplementedError

    def open_versions(self, name: str, listed: list, active: int, then) -> None:
        """The Versions dialog over `listed`: `then(the version number picked)`."""
        raise NotImplementedError

    def open_save(self, question, then) -> None:
        """The Save dialog for a SaveQuestion: `then(SaveAnswer)`."""
        raise NotImplementedError

    def open_code(self, question, apply) -> None:
        """The code editor for a CodeQuestion: each Apply calls `apply(CodeAnswer)`."""
        raise NotImplementedError

    def open_customize(self, question, apply) -> None:
        """Customize for a CustomizeQuestion: Apply and Accept call `apply(CustomizeAnswer)`."""
        raise NotImplementedError

    def show_prefs(self, page: str = "") -> None:
        """Preferences, on `page` when one is named."""
        raise NotImplementedError

    def show_comments(self) -> None:
        """The Comments pane, opened or closed as its toolbar button does."""
        raise NotImplementedError

    def after_drawn(self, then) -> None:
        """`then()` once what the pane just changed is on screen, before work that holds the main thread."""
        raise NotImplementedError

    @staticmethod
    def os_file_icon(path: str, side: int):
        """The system's icon for `path`'s file type, a QImage `side` square; held by shared models."""
        raise NotImplementedError
