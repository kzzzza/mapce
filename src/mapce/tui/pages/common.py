"""Shared TUI helpers and confirmation dialog."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


def human_bytes(value: int | float | None) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class ConfirmScreen(ModalScreen[bool]):
    def __init__(self, title: str, message: str) -> None:
        super().__init__(classes="modal-backdrop")
        self.dialog_title = title
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(classes="confirm-dialog"):
            yield Static(self.dialog_title, classes="page-title")
            yield Static(self.message)
            with Horizontal(classes="confirm-actions"):
                yield Button("取消", id="cancel")
                yield Button("确认", id="confirm", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")
