"""MAPCE TUI visual system."""

APP_CSS = """
Screen {
    background: #0b111b;
    color: #d8e2ef;
}

Header {
    background: #111c2b;
    color: #66e3d2;
    text-style: bold;
}

Footer {
    background: #111c2b;
}

#main-tabs {
    height: 1fr;
}

TabbedContent > ContentSwitcher {
    background: #0b111b;
    padding: 0 1;
}

TabPane {
    padding: 1;
}

.page-title {
    color: #66e3d2;
    text-style: bold;
    margin-bottom: 1;
}

.section-title {
    color: #8eb9ff;
    text-style: bold;
    margin-top: 1;
}

.card-grid {
    grid-size: 3;
    grid-columns: 1fr 1fr 1fr;
    grid-gutter: 1;
    height: auto;
    margin-bottom: 1;
}

.card {
    background: #111c2b;
    border: round #263950;
    padding: 1 2;
    height: 6;
}

.toolbar {
    height: auto;
    margin-bottom: 1;
}

.toolbar Input {
    width: 1fr;
    margin-right: 1;
}

.toolbar Select {
    width: 22;
    margin-right: 1;
}

.toolbar Button {
    margin-right: 1;
}

.filters Input {
    width: 18;
}

Button.-primary {
    background: #167c73;
    color: #ffffff;
}

Button.-warning {
    background: #8c6422;
    color: #ffffff;
}

Button.-error {
    background: #8f3545;
    color: #ffffff;
}

DataTable {
    background: #0e1724;
    border: round #263950;
    height: 1fr;
}

.split {
    height: 1fr;
}

.split-left {
    width: 3fr;
    margin-right: 1;
}

.split-right {
    width: 2fr;
    background: #111c2b;
    border: round #263950;
    padding: 1 2;
}

.status-line {
    height: 3;
    color: #a8b7c9;
    padding: 0 1;
}

.pager {
    height: 3;
    align-horizontal: center;
}

.pager Button {
    min-width: 10;
    margin: 0 1;
}

.form-box {
    background: #111c2b;
    border: round #263950;
    padding: 1 2;
    margin-bottom: 1;
    height: auto;
}

.form-row {
    height: 3;
    margin-bottom: 1;
}

.form-row Input {
    width: 1fr;
    margin-right: 1;
}

.form-row Select {
    width: 22;
    margin-right: 1;
}

#small-screen-warning {
    display: none;
    background: #8c6422;
    color: white;
    border: heavy #f0b35a;
    padding: 2 4;
    width: 100%;
    height: 100%;
    content-align: center middle;
    text-align: center;
}

.modal-backdrop {
    align: center middle;
    background: #000000 65%;
}

.confirm-dialog {
    width: 64;
    height: auto;
    background: #111c2b;
    border: round #f0b35a;
    padding: 2 3;
}

.confirm-actions {
    height: 3;
    align-horizontal: right;
    margin-top: 1;
}

.confirm-actions Button {
    margin-left: 1;
}

#system-output, #system-logs, #paper-detail {
    overflow-y: auto;
}

.system-panel {
    height: 15;
    background: #111c2b;
    border: round #263950;
    padding: 1 2;
}

.system-log-panel {
    height: 1fr;
    min-height: 8;
    background: #070c13;
    border: round #263950;
    padding: 1 2;
}
"""
