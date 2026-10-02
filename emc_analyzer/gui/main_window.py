"""PySide6 main window.

Layout (modelled on classic EMC assessment tools such as EAS):
  left   : Description | Standards & Environment | Design model (tree + properties) | YAML
  right  : Summary | Graph | Mitigations | Next steps | Log
  bottom : Run analysis
"""
from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
                               QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import __version__
from ..core.models import Product
from ..core.results import Report
from ..engine import AnalysisEngine
from ..importers import file_filter, import_design
from ..importers.project import save_project
from ..report import STATUS_COLORS, export_csv, export_html, export_json
from .model_editor import ModelTree, PropertyEditor

APP_TITLE = "EMC Analyzer"
CLASSIFICATIONS = ["Unclassified", "Official", "Official-Sensitive", "Commercial-in-Confidence", "Protected",
                   "Restricted", "Confidential", "Secret"]


class Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, engine, product, standards, environment, settings):
        super().__init__()
        self.args = (engine, product, standards, environment, settings)

    def run(self):
        engine, product, standards, env, settings = self.args
        try:
            self.finished.emit(engine.run(product, standards, env, settings))
        except Exception:
            self.failed.emit(traceback.format_exc())


def _open_folder(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class MainWindow(QMainWindow):
    def __init__(self, project: str = None):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} v{__version__}")
        self.resize(1400, 860)
        self.project_path: Path | None = None
        self.product = Product()
        self.report: Report | None = None
        self.engine = AnalysisEngine()
        self._thread = None
        self._build_ui()
        self._build_menu()
        self._load_standards_tree()
        self._load_environments()
        self.set_product(self.product)
        for m in self.engine.plugin_messages + self.engine.standards.errors:
            self.log(m)
        if project:
            self.open_path(Path(project))

    # ------------------------------------------------------------------ UI construction
    def _build_ui(self):
        split = QSplitter(Qt.Horizontal)
        self.setCentralWidget(split)

        # ---------------- left
        self.left_tabs = QTabWidget()
        split.addWidget(self.left_tabs)

        desc = QWidget()
        f = QFormLayout(desc)
        self.ed_name = QLineEdit()
        self.ed_platform = QLineEdit()
        self.ed_system = QLineEdit()
        self.cb_class = QComboBox()
        self.cb_class.addItems(CLASSIFICATIONS)
        self.cb_class.setEditable(True)
        self.sp_dist = QDoubleSpinBox()
        self.sp_dist.setRange(0.1, 100)
        self.sp_dist.setSuffix(" m")
        self.ed_desc = QPlainTextEdit()
        for lbl, w in (("Product / design", self.ed_name), ("Platform / vehicle", self.ed_platform),
                       ("Weapon / system", self.ed_system), ("Classification", self.cb_class),
                       ("Default measurement distance", self.sp_dist), ("Description", self.ed_desc)):
            f.addRow(lbl, w)
        for w in (self.ed_name, self.ed_platform, self.ed_system):
            w.editingFinished.connect(self._desc_to_model)
        self.cb_class.currentTextChanged.connect(self._desc_to_model)
        self.sp_dist.valueChanged.connect(self._desc_to_model)
        self.ed_desc.textChanged.connect(self._desc_to_model)
        self.left_tabs.addTab(desc, "Description")

        stdw = QWidget()
        v = QVBoxLayout(stdw)
        v.addWidget(QLabel("Standards / limit lines to assess against:"))
        self.std_tree = QTreeWidget()
        self.std_tree.setHeaderLabels(["Standard", "Type", "Unit"])
        self.std_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        v.addWidget(self.std_tree, 1)
        self.std_info = QLabel()
        self.std_info.setWordWrap(True)
        self.std_info.setStyleSheet("color:#555")
        v.addWidget(self.std_info)
        self.std_tree.currentItemChanged.connect(self._std_selected)
        g = QGroupBox("RF environment & settings")
        gf = QFormLayout(g)
        self.cb_env = QComboBox()
        self.cb_model = QComboBox()
        self.cb_model.addItems(["dipole", "matched"])
        self.cb_model.setToolTip("EED coupling: 'dipole' = physical lead-antenna model, 'matched' = worst-case "
                                 "conjugate-matched aperture")
        self.chk_am = QCheckBox("Include 80% AM peak factor for immunity levels")
        self.chk_am.setChecked(True)
        self.sp_se = QDoubleSpinBox()
        self.sp_se.setRange(0, 140)
        self.sp_se.setValue(40)
        self.sp_se.setSuffix(" dB")
        gf.addRow("RF environment", self.cb_env)
        gf.addRow("EED coupling model", self.cb_model)
        gf.addRow("Required enclosure SE", self.sp_se)
        gf.addRow(self.chk_am)
        v.addWidget(g)
        self.left_tabs.addTab(stdw, "Standards")

        model = QSplitter(Qt.Vertical)
        self.tree = ModelTree()
        self.props = PropertyEditor()
        model.addWidget(self.tree)
        model.addWidget(self.props)
        model.setSizes([420, 380])
        self.tree.selected.connect(self.props.set_object)
        self.tree.changed.connect(self._model_changed)
        self.props.applied.connect(self._model_changed)
        self.left_tabs.addTab(model, "Design model")

        yw = QWidget()
        yv = QVBoxLayout(yw)
        self.yaml_edit = QPlainTextEdit()
        self.yaml_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt")
        yv.addWidget(self.yaml_edit, 1)
        hb = QHBoxLayout()
        b1 = QPushButton("Refresh from model")
        b1.clicked.connect(self._model_to_yaml)
        b2 = QPushButton("Apply YAML to model")
        b2.clicked.connect(self._yaml_to_model)
        hb.addWidget(b1)
        hb.addWidget(b2)
        yv.addLayout(hb)
        self.left_tabs.addTab(yw, "YAML")

        # ---------------- right
        right = QWidget()
        rv = QVBoxLayout(right)
        self.right_tabs = QTabWidget()
        rv.addWidget(self.right_tabs, 1)
        split.addWidget(right)
        split.setSizes([480, 920])

        summ = QWidget()
        sv = QVBoxLayout(summ)
        self.lbl_overall = QLabel("No analysis run yet.")
        self.lbl_overall.setStyleSheet("font-size:16px;font-weight:600")
        sv.addWidget(self.lbl_overall)
        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(["Status", "Check", "Standard", "Margin dB", "Worst f", "Detail"])
        self.tbl.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl.cellDoubleClicked.connect(self._show_graph_for_row)
        sv.addWidget(self.tbl, 1)
        self.right_tabs.addTab(summ, "Summary")

        gw = QWidget()
        gv = QVBoxLayout(gw)
        top = QHBoxLayout()
        top.addWidget(QLabel("Plot:"))
        self.cb_plot = QComboBox()
        self.cb_plot.currentIndexChanged.connect(self._draw_plot)
        top.addWidget(self.cb_plot, 1)
        self.chk_auto = QCheckBox("Auto Y")
        self.chk_auto.setChecked(True)
        self.sp_ymin = QDoubleSpinBox()
        self.sp_ymax = QDoubleSpinBox()
        for s, val in ((self.sp_ymin, -20), (self.sp_ymax, 120)):
            s.setRange(-300, 300)
            s.setValue(val)
            s.valueChanged.connect(self._draw_plot)
        self.chk_auto.toggled.connect(self._draw_plot)
        top.addWidget(self.chk_auto)
        top.addWidget(QLabel("Y min"))
        top.addWidget(self.sp_ymin)
        top.addWidget(QLabel("Y max"))
        top.addWidget(self.sp_ymax)
        gv.addLayout(top)
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
            from matplotlib.figure import Figure
            self.fig = Figure(figsize=(8, 5))
            self.canvas = FigureCanvasQTAgg(self.fig)
            gv.addWidget(NavigationToolbar2QT(self.canvas, gw))
            gv.addWidget(self.canvas, 1)
        except Exception as exc:  # pragma: no cover
            self.fig = None
            gv.addWidget(QLabel(f"matplotlib Qt backend unavailable: {exc}"))
        self.right_tabs.addTab(gw, "Graph")

        self.tbl_mit = QTableWidget(0, 6)
        self.tbl_mit.setHorizontalHeaderLabels(["Pri", "Mitigation", "Applies to", "Category", "Expected", "Effort"])
        self.tbl_mit.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_mit.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_mit.setWordWrap(True)
        self.right_tabs.addTab(self.tbl_mit, "Mitigations")

        self.txt_next = QTextBrowser()
        self.right_tabs.addTab(self.txt_next, "Next steps")

        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.right_tabs.addTab(self.txt_log, "Log")

        hb = QHBoxLayout()
        self.btn_run = QPushButton("Run analysis  ▶")
        self.btn_run.setStyleSheet("font-weight:600;padding:6px 18px")
        self.btn_run.clicked.connect(self.run_analysis)
        btn_html = QPushButton("Export HTML report")
        btn_html.clicked.connect(lambda: self.export("html"))
        hb.addStretch(1)
        hb.addWidget(btn_html)
        hb.addWidget(self.btn_run)
        rv.addLayout(hb)
        self.statusBar().showMessage("Ready")

    def _build_menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")

        def act(menu, text, fn, shortcut=None):
            a = QAction(text, self)
            a.triggered.connect(fn)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            menu.addAction(a)
            return a

        act(fm, "New project", self.new_project, "Ctrl+N")
        act(fm, "Open project / design...", self.open_dialog, "Ctrl+O")
        act(fm, "Import into current design (Python / MATLAB / SPICE)...", self.import_dialog, "Ctrl+I")
        fm.addSeparator()
        act(fm, "Save project", self.save, "Ctrl+S")
        act(fm, "Save project as...", self.save_as)
        fm.addSeparator()
        em = fm.addMenu("Export results")
        act(em, "HTML report...", lambda: self.export("html"))
        act(em, "CSV...", lambda: self.export("csv"))
        act(em, "JSON...", lambda: self.export("json"))
        fm.addSeparator()
        act(fm, "Exit", self.close, "Ctrl+Q")

        am = mb.addMenu("&Analysis")
        act(am, "Run analysis", self.run_analysis, "F5")
        act(am, "Select project default standards", self._select_project_standards)
        act(am, "List registered analyses", self._list_analyses)

        sm = mb.addMenu("&Standards")
        act(sm, "Reload standards, environments && plugins", self.reload_libraries)
        act(sm, "Open user standards folder", lambda: _open_folder(Path.home() / ".emc_analyzer" / "standards"))
        act(sm, "Open user environments folder",
            lambda: _open_folder(Path.home() / ".emc_analyzer" / "environments"))
        act(sm, "Open built-in standards folder",
            lambda: _open_folder(Path(__file__).resolve().parent.parent / "standards" / "library"))

        pm = mb.addMenu("&Plugins")
        act(pm, "Open user plugins folder", lambda: _open_folder(Path.home() / ".emc_analyzer" / "plugins"))
        act(pm, "Reload plugins", self.reload_libraries)

        hm = mb.addMenu("&Help")
        act(hm, "About", lambda: QMessageBox.about(
            self, APP_TITLE,
            f"<b>{APP_TITLE} {__version__}</b><br>EMI/EMC design assessment for circuits, enclosures and "
            "products.<br><br>Estimates are first-order analytical models to rank risk and guide design; they do "
            "not replace pre-compliance or accredited testing."))

    # ------------------------------------------------------------------ libraries
    def _load_standards_tree(self):
        checked = set(self.selected_standards()) if self.std_tree.topLevelItemCount() else set(self.product.standards)
        self.std_tree.clear()
        fams = {}
        for s in self.engine.standards.list():
            fam = fams.get(s.family)
            if fam is None:
                fam = QTreeWidgetItem([s.family or "Other"])
                fam.setFlags(fam.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
                self.std_tree.addTopLevelItem(fam)
                fams[s.family] = fam
            it = QTreeWidgetItem([s.name, s.type.replace("_", " "), s.unit])
            it.setData(0, Qt.UserRole, s.id)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked if s.id in checked else Qt.Unchecked)
            it.setToolTip(0, f"{s.id}\n{s.notes}")
            fam.addChild(it)
        self.std_tree.expandAll()

    def _load_environments(self):
        cur = self.cb_env.currentText()
        self.cb_env.clear()
        self.cb_env.addItem("(none)")
        if self.product.environment is not None:
            self.cb_env.addItem(f"[project] {self.product.environment.name}")
        self.cb_env.addItems(self.engine.environments.names())
        i = self.cb_env.findText(cur)
        if i >= 0:
            self.cb_env.setCurrentIndex(i)
        elif self.product.environment is not None:
            self.cb_env.setCurrentIndex(1)

    def selected_standards(self):
        ids = []
        for i in range(self.std_tree.topLevelItemCount()):
            fam = self.std_tree.topLevelItem(i)
            for j in range(fam.childCount()):
                it = fam.child(j)
                if it.checkState(0) == Qt.Checked:
                    ids.append(it.data(0, Qt.UserRole))
        return ids

    def _set_checked_standards(self, ids):
        ids = set(ids)
        for i in range(self.std_tree.topLevelItemCount()):
            fam = self.std_tree.topLevelItem(i)
            for j in range(fam.childCount()):
                it = fam.child(j)
                it.setCheckState(0, Qt.Checked if it.data(0, Qt.UserRole) in ids else Qt.Unchecked)

    def _std_selected(self, item, _prev=None):
        if item is None or item.data(0, Qt.UserRole) is None:
            self.std_info.setText("")
            return
        s = self.engine.standards.get(item.data(0, Qt.UserRole))
        segs = "; ".join(f"{a / 1e6:g}-{b / 1e6:g} MHz: {c:g}->{d:g} {s.unit}" for a, b, c, d in s.segments)
        verify = "<br><b style='color:#b35'>Verify values against the current edition.</b>" if s.verify else ""
        self.std_info.setText(f"<b>{s.id}</b> ({s.detector} {'' if s.distance_m is None else f'@ {s.distance_m:g} m'})"
                              f"<br>{segs}<br>{s.notes}<br><small>{s.source_file}</small>{verify}")

    def reload_libraries(self):
        extra = [self.project_path.parent] if self.project_path else []
        self.engine = AnalysisEngine([d / "standards" for d in extra], [d / "environments" for d in extra],
                                     [d / "plugins" for d in extra])
        self._load_standards_tree()
        self._load_environments()
        for m in self.engine.plugin_messages + self.engine.standards.errors + self.engine.environments.errors:
            self.log(m)
        self.log(f"Loaded {len(self.engine.standards.standards)} standards, "
                 f"{len(self.engine.environments.environments)} environments")

    # ------------------------------------------------------------------ model sync
    def set_product(self, product: Product):
        self.product = product
        self._model_to_desc()
        self.tree.set_product(product)
        self.props.set_object(None)
        self._model_to_yaml()
        self._load_environments()
        if product.standards:
            self._set_checked_standards(product.standards)
        self._update_title()

    def _model_to_desc(self):
        p = self.product
        for w, v in ((self.ed_name, p.name), (self.ed_platform, p.platform), (self.ed_system, p.system)):
            w.blockSignals(True)
            w.setText(v)
            w.blockSignals(False)
        self.cb_class.blockSignals(True)
        self.cb_class.setCurrentText(p.classification)
        self.cb_class.blockSignals(False)
        self.sp_dist.blockSignals(True)
        self.sp_dist.setValue(p.measurement_distance_m)
        self.sp_dist.blockSignals(False)
        self.ed_desc.blockSignals(True)
        self.ed_desc.setPlainText(p.description)
        self.ed_desc.blockSignals(False)
        if "required_se_db" in (p.enclosure.extra if p.enclosure else {}):
            self.sp_se.setValue(float(p.enclosure.extra["required_se_db"]))

    def _desc_to_model(self):
        p = self.product
        p.name = self.ed_name.text()
        p.platform = self.ed_platform.text()
        p.system = self.ed_system.text()
        p.classification = self.cb_class.currentText()
        p.measurement_distance_m = self.sp_dist.value()
        p.description = self.ed_desc.toPlainText()
        self._update_title()

    def _model_changed(self):
        self.tree.rebuild()
        self._model_to_yaml()

    def _model_to_yaml(self):
        import yaml
        self.yaml_edit.setPlainText(yaml.safe_dump(self.product.to_dict(), sort_keys=False, default_flow_style=None))

    def _yaml_to_model(self):
        import yaml
        try:
            data = yaml.safe_load(self.yaml_edit.toPlainText())
            self.set_product(Product.from_dict(data))
            self.log("YAML applied to model")
        except Exception as exc:
            QMessageBox.critical(self, "YAML error", str(exc))

    def _update_title(self):
        name = self.project_path.name if self.project_path else "unsaved"
        self.setWindowTitle(f"{APP_TITLE} v{__version__} - {self.product.name} [{name}]")

    # ------------------------------------------------------------------ file ops
    def new_project(self):
        self.project_path = None
        self.report = None
        self.set_product(Product())
        self._show_report()

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project or design", str(self._start_dir()), file_filter())
        if path:
            self.open_path(Path(path))

    def import_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import into current design", str(self._start_dir()),
                                              file_filter())
        if path:
            try:
                self.set_product(import_design(path, self.product))
                self.log(f"Imported {path}")
            except Exception as exc:
                QMessageBox.critical(self, "Import failed", f"{exc}\n\n{traceback.format_exc()}")

    def open_path(self, path: Path):
        try:
            product = import_design(path, None)
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", f"{exc}\n\n{traceback.format_exc()}")
            return
        if path.suffix.lower() in (".yaml", ".yml", ".json"):
            self.project_path = path
            self.reload_libraries()
        self.report = None
        self.set_product(product)
        self._show_report()
        self.log(f"Opened {path}: {product.summary()}")

    def save(self):
        if self.project_path is None:
            return self.save_as()
        self.product.standards = self.selected_standards()
        save_project(self.product, self.project_path)
        self.log(f"Saved {self.project_path}")
        self.statusBar().showMessage(f"Saved {self.project_path}", 4000)

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save project", str(self._start_dir() / "project.yaml"),
                                              "Project (*.yaml *.json)")
        if path:
            self.project_path = Path(path)
            self.save()
            self._update_title()

    def _start_dir(self) -> Path:
        if self.project_path:
            return self.project_path.parent
        ex = Path(__file__).resolve().parents[2] / "examples"
        return ex if ex.is_dir() else Path.cwd()

    def export(self, kind):
        if self.report is None:
            QMessageBox.information(self, "Export", "Run an analysis first.")
            return
        ext = {"html": "HTML (*.html)", "csv": "CSV (*.csv)", "json": "JSON (*.json)"}[kind]
        default = self._start_dir() / f"{self.product.name.replace(' ', '_')}_emc.{kind}"
        path, _ = QFileDialog.getSaveFileName(self, "Export", str(default), ext)
        if not path:
            return
        fn = {"html": lambda: export_html(self.report, self.product, path),
              "csv": lambda: export_csv(self.report, path), "json": lambda: export_json(self.report, path)}[kind]
        out = fn()
        self.log(f"Exported {out}")
        if kind == "html":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))

    # ------------------------------------------------------------------ analysis
    def _select_project_standards(self):
        self.product.standards = self.selected_standards()
        self.log("Project default standards: " + ", ".join(self.product.standards))

    def _list_analyses(self):
        txt = "\n".join(f"{a.id}: {a.title}" for a in self.engine.analyses().values())
        QMessageBox.information(self, "Registered analyses", txt)

    def run_analysis(self):
        if self._thread is not None and self._thread.isRunning():
            return
        self._desc_to_model()
        stds = self.selected_standards()
        env_txt = self.cb_env.currentText()
        self._saved_env = self.product.environment
        if env_txt == "(none)":
            env = None
            self.product.environment = None      # explicit none: don't fall back to project environment
        elif env_txt.startswith("[project] "):
            env = self.product.environment
        else:
            env = self.engine.environments.get(env_txt)
        settings = {"eed_coupling_model": self.cb_model.currentText(), "include_am": self.chk_am.isChecked(),
                    "required_se_db": self.sp_se.value()}
        self.btn_run.setEnabled(False)
        self.statusBar().showMessage("Running analysis...")
        self._thread = QThread(self)
        self._worker = Worker(self.engine, self.product, stds, env, settings)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_done)     # bound QObject methods -> queued to GUI thread
        self._worker.failed.connect(self._on_fail)
        self._thread.start()

    def _on_done(self, rep):
        self.product.environment = self._saved_env
        self.report = rep
        self._show_report()
        self.btn_run.setEnabled(True)
        self.statusBar().showMessage(f"Analysis complete: {rep.overall}", 6000)
        self._thread.quit()
        self._thread.wait()

    def _on_fail(self, tb):
        self.product.environment = self._saved_env
        self.btn_run.setEnabled(True)
        self.log(tb)
        QMessageBox.critical(self, "Analysis failed", tb)
        self._thread.quit()
        self._thread.wait()

    # ------------------------------------------------------------------ results display
    def _show_report(self):
        rep = self.report
        self.tbl.setRowCount(0)
        self.tbl_mit.setRowCount(0)
        self.cb_plot.blockSignals(True)
        self.cb_plot.clear()
        self.cb_plot.blockSignals(False)
        self.txt_next.clear()
        if rep is None:
            self.lbl_overall.setText("No analysis run yet.")
            if self.fig is not None:
                self.fig.clear()
                self.canvas.draw_idle()
            return
        c = rep.counts()
        self.lbl_overall.setText(
            f"Overall: <span style='color:{STATUS_COLORS[rep.overall]}'>{rep.overall}</span> &nbsp; "
            f"<small>{c['FAIL']} fail · {c['MARGINAL']} marginal · {c['PASS']} pass · {c['INFO']} info</small>")
        self.lbl_overall.setTextFormat(Qt.RichText)
        from ..core.units import fmt_freq
        for f in rep.findings:
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            vals = [f.status, f.title, f.standard or "", "" if f.margin_db is None else f"{f.margin_db:+.1f}",
                    fmt_freq(f.worst_freq_hz) if f.worst_freq_hz else "", f.detail]
            for col, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if col == 0:
                    it.setBackground(QBrush(QColor(STATUS_COLORS.get(f.status, "#888"))))
                    it.setForeground(QBrush(QColor("white")))
                it.setToolTip(f.detail)
                self.tbl.setItem(r, col, it)
        self.tbl.resizeColumnsToContents()
        self.tbl.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self._plot_items = [f for f in rep.findings if f.traces]
        self.cb_plot.blockSignals(True)
        for f in self._plot_items:
            self.cb_plot.addItem(f"[{f.status}] {f.title} - {f.standard or ''}")
        self.cb_plot.blockSignals(False)
        self._draw_plot()
        for m in rep.mitigations:
            r = self.tbl_mit.rowCount()
            self.tbl_mit.insertRow(r)
            for col, v in enumerate([f"P{m.priority}", f"{m.title}\n{m.rationale}", m.applies_to, m.category,
                                     m.expected_improvement_db or "", m.effort]):
                self.tbl_mit.setItem(r, col, QTableWidgetItem(v))
        self.tbl_mit.resizeRowsToContents()
        html = []
        for s in rep.next_steps:
            html.append(f"<h3>{s['phase']} — {s['title']}</h3><ul>" +
                        "".join(f"<li>{a}</li>" for a in s["actions"]) + "</ul>")
        html.append("<hr><p style='color:#666;font-size:small'>" + "<br>".join(rep.notes) + "</p>")
        self.txt_next.setHtml("".join(html))

    def _show_graph_for_row(self, row, _col):
        f = self.report.findings[row]
        if f in self._plot_items:
            self.cb_plot.setCurrentIndex(self._plot_items.index(f))
            self.right_tabs.setCurrentIndex(1)

    def _draw_plot(self, *_):
        if self.fig is None or not getattr(self, "_plot_items", None):
            return
        i = self.cb_plot.currentIndex()
        if i < 0:
            return
        from ..report.plotting import plot_finding
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        plot_finding(ax, self._plot_items[i])
        if not self.chk_auto.isChecked():
            f = self._plot_items[i]
            if f.y_log:
                ax.set_ylim(10 ** self.sp_ymin.value(), 10 ** self.sp_ymax.value())
            else:
                ax.set_ylim(self.sp_ymin.value(), self.sp_ymax.value())
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def log(self, msg: str):
        self.txt_log.appendPlainText(str(msg))


def main(project: str = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    win = MainWindow(project)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
