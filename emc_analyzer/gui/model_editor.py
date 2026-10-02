"""Generic tree + property editor for the dataclass design model.

Works for any dataclass in core.models (and new ones added later) by
introspection, so the GUI does not need changing when the model grows.
"""
from __future__ import annotations

import dataclasses
import typing

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..core.units import parse_si

ROLE = Qt.UserRole


def _unwrap_optional(tp):
    if typing.get_origin(tp) is typing.Union:
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        return args[0], True
    return tp, False


def _is_list_of_dc(tp):
    tp, _ = _unwrap_optional(tp)
    if typing.get_origin(tp) in (list, typing.List):
        args = typing.get_args(tp)
        return bool(args) and dataclasses.is_dataclass(args[0]), (args[0] if args else None)
    return False, None


def _is_dc(tp):
    tp, _ = _unwrap_optional(tp)
    return dataclasses.is_dataclass(tp), tp


def _label(obj) -> str:
    name = getattr(obj, "name", "") or ""
    return f"{type(obj).__name__}: {name}" if name else type(obj).__name__


_DEFAULTS = {
    "FilterElement": {"kind": "C", "value": 1e-9, "position": "shunt"},
    "Aperture": {"name": "aperture", "length_m": 0.01},
    "Seam": {"name": "seam", "length_m": 0.1},
    "CurrentLoop": {"name": "loop", "source": "", "area_m2": 1e-4},
}


def _default_instance(cls):
    if cls.__name__ in _DEFAULTS:
        return cls(**_DEFAULTS[cls.__name__])
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:  # type: ignore
            tp, _ = _unwrap_optional(typing.get_type_hints(cls)[f.name])
            kwargs[f.name] = {str: f"new_{cls.__name__.lower()}", float: 0.0, int: 0, bool: False}.get(tp, None)
    return cls(**kwargs)


class ModelTree(QTreeWidget):
    selected = Signal(object)      # emits dataclass object or None
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Design model"])
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemSelectionChanged.connect(self._sel)
        self.product = None

    def set_product(self, product):
        self.product = product
        self.rebuild()

    def rebuild(self):
        expanded = {self._path(i) for i in self._iter() if i.isExpanded()}
        self.clear()
        if self.product is None:
            return
        root = QTreeWidgetItem([_label(self.product)])
        root.setData(0, ROLE, ("obj", self.product, None, None))
        self.addTopLevelItem(root)
        self._fill(root, self.product)
        root.setExpanded(True)
        for i in self._iter():
            if self._path(i) in expanded:
                i.setExpanded(True)

    def _iter(self):
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            it = stack.pop()
            yield it
            stack.extend(it.child(i) for i in range(it.childCount()))

    @staticmethod
    def _path(item):
        parts = []
        while item is not None:
            parts.append(item.text(0))
            item = item.parent()
        return "/".join(reversed(parts))

    def _fill(self, item, obj):
        hints = typing.get_type_hints(type(obj))
        for f in dataclasses.fields(obj):
            tp = hints[f.name]
            is_list, elem = _is_list_of_dc(tp)
            is_dc, dc_t = _is_dc(tp)
            val = getattr(obj, f.name)
            if is_list:
                folder = QTreeWidgetItem([f"{f.name} ({len(val)})"])
                folder.setData(0, ROLE, ("list", obj, f.name, elem))
                item.addChild(folder)
                for child in val:
                    ci = QTreeWidgetItem([_label(child)])
                    ci.setData(0, ROLE, ("obj", child, val, None))
                    folder.addChild(ci)
                    self._fill(ci, child)
            elif is_dc:
                if val is None:
                    ci = QTreeWidgetItem([f"{f.name}: <none>  (right-click to add)"])
                    ci.setData(0, ROLE, ("none", obj, f.name, dc_t))
                else:
                    ci = QTreeWidgetItem([f"{f.name} - {_label(val)}"])
                    ci.setData(0, ROLE, ("obj", val, obj, f.name))
                    self._fill(ci, val)
                item.addChild(ci)

    def _sel(self):
        items = self.selectedItems()
        if not items:
            self.selected.emit(None)
            return
        kind, obj, *_ = items[0].data(0, ROLE)
        self.selected.emit(obj if kind == "obj" else None)

    def _menu(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return
        kind, obj, a, b = item.data(0, ROLE)
        menu = QMenu(self)
        if kind == "list":
            act = menu.addAction(f"Add {b.__name__}")
            act.triggered.connect(lambda: self._add_to_list(obj, a, b))
        elif kind == "none":
            act = menu.addAction(f"Create {b.__name__}")
            act.triggered.connect(lambda: self._create(obj, a, b))
        elif kind == "obj" and a is not None:
            act = menu.addAction("Delete")
            act.triggered.connect(lambda: self._delete(obj, a, b))
            if isinstance(a, list):
                dup = menu.addAction("Duplicate")
                dup.triggered.connect(lambda: self._duplicate(obj, a))
        if not menu.isEmpty():
            menu.exec(self.viewport().mapToGlobal(pos))

    def _add_to_list(self, parent, fname, cls):
        getattr(parent, fname).append(_default_instance(cls))
        self.rebuild()
        self.changed.emit()

    def _create(self, parent, fname, cls):
        setattr(parent, fname, _default_instance(cls))
        self.rebuild()
        self.changed.emit()

    def _delete(self, obj, container, fname):
        if QMessageBox.question(self, "Delete", f"Delete {_label(obj)}?") != QMessageBox.Yes:
            return
        if isinstance(container, list):
            container.remove(obj)
        else:
            setattr(container, fname, None)
        self.rebuild()
        self.changed.emit()

    def _duplicate(self, obj, container):
        new = type(obj).from_dict(obj.to_dict())
        if hasattr(new, "name"):
            new.name = f"{new.name}_copy"
        container.append(new)
        self.rebuild()
        self.changed.emit()


class PropertyEditor(QWidget):
    """Form editor for the scalar / dict fields of one dataclass instance."""
    applied = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.obj = None
        self.editors = {}
        outer = QVBoxLayout(self)
        self.title = QLabel("Select an item in the design tree")
        self.title.setStyleSheet("font-weight:600")
        outer.addWidget(self.title)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        outer.addWidget(self.scroll, 1)
        row = QHBoxLayout()
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self.apply)
        self.apply_btn.setEnabled(False)
        row.addStretch(1)
        row.addWidget(self.apply_btn)
        outer.addLayout(row)

    def set_object(self, obj):
        self.obj = obj
        self.editors = {}
        host = QWidget()
        form = QFormLayout(host)
        self.scroll.setWidget(host)
        self.apply_btn.setEnabled(obj is not None)
        if obj is None:
            self.title.setText("Select an item in the design tree")
            return
        self.title.setText(_label(obj))
        hints = typing.get_type_hints(type(obj))
        for f in dataclasses.fields(obj):
            tp = hints[f.name]
            if _is_list_of_dc(tp)[0] or _is_dc(tp)[0]:
                continue
            base, _ = _unwrap_optional(tp)
            val = getattr(obj, f.name)
            if base is bool:
                w = QCheckBox()
                w.setChecked(bool(val))
            elif typing.get_origin(base) in (dict, typing.Dict) or typing.get_origin(base) in (list, typing.List):
                import yaml
                w = QPlainTextEdit(yaml.safe_dump(val, default_flow_style=None).strip() if val else "")
                w.setFixedHeight(70)
            elif typing.get_origin(base) in (tuple, typing.Tuple):
                w = QLineEdit(", ".join(f"{x:g}" if isinstance(x, float) else str(x) for x in (val or ())))
            else:
                w = QLineEdit("" if val is None else (f"{val:g}" if isinstance(val, float) else str(val)))
            w.setToolTip(f"{f.name}: {getattr(base, '__name__', str(base))}")
            form.addRow(f.name, w)
            self.editors[f.name] = (w, tp)

    def apply(self):
        if self.obj is None:
            return
        errors = []
        for name, (w, tp) in self.editors.items():
            base, optional = _unwrap_optional(tp)
            try:
                if isinstance(w, QCheckBox):
                    val = w.isChecked()
                elif isinstance(w, QPlainTextEdit):
                    import yaml
                    txt = w.toPlainText().strip()
                    val = (yaml.safe_load(txt) if txt else
                           ({} if typing.get_origin(base) in (dict, typing.Dict) else []))
                else:
                    txt = w.text().strip()
                    if txt == "" and optional:
                        val = None
                    elif typing.get_origin(base) in (tuple, typing.Tuple):
                        val = tuple(parse_si(x) for x in txt.split(","))
                    elif base is float:
                        val = parse_si(txt)
                    elif base is int:
                        val = int(parse_si(txt))
                    else:
                        val = txt
                setattr(self.obj, name, val)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        if errors:
            QMessageBox.warning(self, "Some values were not applied", "\n".join(errors))
        self.applied.emit()
