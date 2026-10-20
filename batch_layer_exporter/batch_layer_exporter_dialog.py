# -*- coding: utf-8 -*-
"""User interface and export engine for Batch Layer Exporter.

Copyright (c) 2077 Amlan Patnaik. All rights reserved.

The plugin exports vector data using QGIS/GDAL vector writers. Dataset formats
have different capabilities; QML style sidecars and a JSON manifest are saved
where possible to retain useful QGIS-specific information alongside outputs.
The dialog is resizable and its configuration area has a vertical scrollbar.
Subtype datasets are named after the subtype value (e.g. Handhole.gpkg).
"""

import json
import os
import re
from datetime import date, datetime

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsProjectionSelectionDialog


COPYRIGHT = "© 2077 Amlan Patnaik. All rights reserved."


class BatchLayerExporterDialog(QDialog):
    """Dialog for selecting and batch-exporting QGIS vector layers."""

    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.project = QgsProject.instance()
        self.layer_rows = {}
        self.format_checks = []
        self.custom_target_crs = None
        self._refreshing_target_combo = False
        self._build_ui()
        self.refresh_layers()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        """Build a compact, resizable dialog with a vertical form scrollbar."""
        self.setWindowTitle("Batch Layer Exporter")
        self.setMinimumSize(620, 440)
        self.resize(800, 620)
        self.setSizeGripEnabled(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 7)
        root.setSpacing(5)

        title = QLabel("BATCH LAYER EXPORTER")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)

        intro = QLabel(
            "Batch export vector layers and subtypes to multiple formats. "
            "Format capabilities vary; QGIS-specific properties may need sidecars."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        # All configuration sections live inside a scroll area. The action
        # buttons remain visible when the dialog is resized to a short height.
        self.main_scroll = QScrollArea()
        self.main_scroll.setObjectName("batchExporterMainScroll")
        self.main_scroll.setWidgetResizable(True)
        self.main_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.main_scroll.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        content.setObjectName("batchExporterScrollableContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 6, 2)
        content_layout.setSpacing(6)
        self.main_scroll.setWidget(content)
        root.addWidget(self.main_scroll, 1)

        # 1. Layer selection
        layer_box = QGroupBox("1. Select layers and subtype fields")
        layer_layout = QVBoxLayout(layer_box)
        layer_layout.setContentsMargins(8, 8, 8, 8)
        layer_layout.setSpacing(5)
        layer_note = QLabel(
            "Choose the vector layers to export. Select a subtype field for each selected layer "
            "if you plan to export its distinct values."
        )
        layer_note.setWordWrap(True)
        layer_layout.addWidget(layer_note)

        select_row = QHBoxLayout()
        select_row.setSpacing(4)
        self.select_all_button = QPushButton("Select All")
        self.deselect_all_button = QPushButton("Deselect All")
        self.refresh_button = QPushButton("Refresh")
        for button in (self.select_all_button, self.deselect_all_button, self.refresh_button):
            button.setMinimumHeight(25)
            select_row.addWidget(button)
        select_row.addStretch(1)
        layer_layout.addLayout(select_row)

        self.layer_table = QTableWidget(0, 4)
        self.layer_table.setHorizontalHeaderLabels(["Export", "Layer", "Geometry", "Subtype field"])
        self.layer_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.layer_table.setAlternatingRowColors(True)
        self.layer_table.setSortingEnabled(False)
        self.layer_table.verticalHeader().setVisible(False)
        self.layer_table.setMinimumHeight(130)
        self.layer_table.setMaximumHeight(205)
        self.layer_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.layer_table.setColumnWidth(0, 52)
        self.layer_table.setColumnWidth(1, 180)
        self.layer_table.setColumnWidth(2, 100)
        self.layer_table.horizontalHeader().setStretchLastSection(True)
        layer_layout.addWidget(self.layer_table)
        content_layout.addWidget(layer_box)

        self.select_all_button.clicked.connect(lambda: self._set_all_layers_checked(True))
        self.deselect_all_button.clicked.connect(lambda: self._set_all_layers_checked(False))
        self.refresh_button.clicked.connect(self.refresh_layers)

        # 2. Export mode
        mode_box = QGroupBox("2. Export mode")
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.setContentsMargins(8, 7, 8, 7)
        mode_layout.setSpacing(3)
        self.mode_whole = QRadioButton("Whole layer only")
        self.mode_subtypes = QRadioButton("Subtypes only")
        self.mode_both = QRadioButton("Both whole layer and subtypes")
        self.mode_whole.setChecked(True)
        for radio in (self.mode_whole, self.mode_subtypes, self.mode_both):
            mode_layout.addWidget(radio)
        content_layout.addWidget(mode_box)

        # 3. CRS
        crs_box = QGroupBox("3. Coordinate reference system (CRS)")
        crs_layout = QGridLayout(crs_box)
        crs_layout.setContentsMargins(8, 7, 8, 7)
        crs_layout.setHorizontalSpacing(8)
        crs_layout.setVerticalSpacing(5)
        source_value = QLabel("Automatic — each layer's own CRS")
        source_value.setToolTip("Each layer is exported from its own source CRS.")
        crs_layout.addWidget(QLabel("Source CRS"), 0, 0)
        crs_layout.addWidget(source_value, 0, 1)
        crs_layout.addWidget(QLabel("Target CRS"), 1, 0)
        self.target_crs_combo = QComboBox()
        self.target_crs_combo.addItem("Keep each layer's source CRS", "source")
        project_crs = self.project.crs()
        project_label = "Project CRS ({})".format(project_crs.authid() or project_crs.description())
        self.target_crs_combo.addItem(project_label, "project")
        self.target_crs_combo.addItem("Choose target CRS…", "choose")
        self.target_crs_combo.setCurrentIndex(0)
        crs_layout.addWidget(self.target_crs_combo, 1, 1)
        crs_hint = QLabel("A target CRS transforms spatial data during export. The source-CRS option keeps each layer's native CRS.")
        crs_hint.setWordWrap(True)
        crs_layout.addWidget(crs_hint, 2, 0, 1, 2)
        self.target_crs_combo.currentIndexChanged.connect(self._target_crs_changed)
        content_layout.addWidget(crs_box)

        # 4. Output formats
        format_box = QGroupBox("4. Output formats — select one or more")
        format_layout = QVBoxLayout(format_box)
        format_layout.setContentsMargins(8, 7, 8, 7)
        format_layout.setSpacing(4)
        self.format_summary = QLabel("Available formats are detected from this QGIS/GDAL installation.")
        format_layout.addWidget(self.format_summary)
        self.format_scroll = QScrollArea()
        self.format_scroll.setWidgetResizable(True)
        self.format_scroll.setMinimumHeight(95)
        self.format_scroll.setMaximumHeight(150)
        self.format_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.format_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.format_container = QWidget()
        self.format_grid = QGridLayout(self.format_container)
        self.format_grid.setContentsMargins(4, 4, 4, 4)
        self.format_grid.setHorizontalSpacing(10)
        self.format_grid.setVerticalSpacing(3)
        self.format_scroll.setWidget(self.format_container)
        format_layout.addWidget(self.format_scroll)
        content_layout.addWidget(format_box)
        self._populate_format_checks()

        # 5. Output folder and sidecars
        output_box = QGroupBox("5. Output folder and preservation options")
        output_layout = QGridLayout(output_box)
        output_layout.setContentsMargins(8, 7, 8, 7)
        output_layout.setHorizontalSpacing(6)
        output_layout.setVerticalSpacing(4)
        output_layout.addWidget(QLabel("Output folder"), 0, 0)
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Choose output folder…")
        output_layout.addWidget(self.output_path_edit, 0, 1)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self._choose_output_folder)
        output_layout.addWidget(self.browse_button, 0, 2)

        self.save_qml_check = QCheckBox("Save QML style sidecar where possible")
        self.save_qml_check.setChecked(True)
        self.save_qml_check.setToolTip("Stores the source layer's QGIS style in a separate QML file.")
        output_layout.addWidget(self.save_qml_check, 1, 0, 1, 3)
        self.save_qmd_check = QCheckBox("Save QMD metadata sidecar where possible")
        self.save_qmd_check.setChecked(True)
        self.save_qmd_check.setToolTip("Stores QGIS layer metadata in a separate QMD file where supported.")
        output_layout.addWidget(self.save_qmd_check, 2, 0, 1, 3)
        self.save_manifest_check = QCheckBox("Save JSON manifest with CRS, fields, aliases, subtype values, counts, and paths")
        self.save_manifest_check.setChecked(True)
        output_layout.addWidget(self.save_manifest_check, 3, 0, 1, 3)
        content_layout.addWidget(output_box)

        # 6. Export log
        log_box = QGroupBox("6. Export log")
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(8, 7, 8, 7)
        log_layout.setSpacing(4)
        self.summary_label = QLabel("Layers exported: 0 | Output datasets: 0 | Features written: 0")
        self.summary_label.setWordWrap(True)
        log_layout.addWidget(self.summary_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximumHeight(18)
        log_layout.addWidget(self.progress_bar)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(75)
        self.log_text.setMaximumHeight(135)
        self.log_text.setPlaceholderText("Export messages, output paths, warnings, and errors appear here.")
        log_layout.addWidget(self.log_text)
        content_layout.addWidget(log_box)
        content_layout.addStretch(1)

        # Always-visible footer and action buttons
        footer = QLabel(COPYRIGHT)
        footer.setAlignment(Qt.AlignRight)
        footer.setStyleSheet("color: palette(mid); font-size: 10px;")
        root.addWidget(footer)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addStretch(1)
        self.export_button = QPushButton("Export Selected Layers")
        self.export_button.setDefault(True)
        self.close_button = QPushButton("Close")
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.close_button)
        root.addLayout(buttons)
        self.export_button.clicked.connect(self.run_export)
        self.close_button.clicked.connect(self.close)

    def _populate_format_checks(self):
        """Display every unique QGIS vector writer format reported by QGIS."""
        while self.format_grid.count():
            item = self.format_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.format_checks = []
        formats = []
        seen = set()
        try:
            details_list = QgsVectorFileWriter.supportedFiltersAndFormats()
        except Exception:
            details_list = []

        for details in details_list:
            driver = str(getattr(details, "driverName", "") or "").strip()
            filter_string = str(getattr(details, "filterString", "") or "").strip()
            globs = list(getattr(details, "globs", []) or [])
            extension = ""
            for glob in globs:
                match = re.search(r"\*\.([A-Za-z0-9][A-Za-z0-9._-]*)", str(glob))
                if match:
                    extension = match.group(1).split(".")[0].lower()
                    break
            if not driver or not extension:
                continue
            key = (driver.casefold(), extension)
            if key in seen:
                continue
            seen.add(key)
            display = filter_string.split("(")[0].strip() if "(" in filter_string else driver
            formats.append({"label": "{} (.{})".format(display, extension), "driver": driver, "extension": extension})

        # Fallback for unusual builds where filter details were not exposed.
        if not formats:
            fallback = [
                ("GeoPackage", "GPKG", "gpkg"),
                ("ESRI Shapefile", "ESRI Shapefile", "shp"),
                ("GeoJSON", "GeoJSON", "geojson"),
                ("CSV", "CSV", "csv"),
                ("KML", "KML", "kml"),
                ("GML", "GML", "gml"),
                ("GPX", "GPX", "gpx"),
                ("FlatGeobuf", "FlatGeobuf", "fgb"),
            ]
            try:
                supported = {str(e).lower().lstrip(".") for e in QgsVectorFileWriter.supportedFormatExtensions()}
            except Exception:
                supported = {"gpkg", "shp", "geojson", "csv"}
            for label, driver, extension in fallback:
                if extension in supported:
                    formats.append({"label": "{} (.{})".format(label, extension), "driver": driver, "extension": extension})

        formats.sort(key=lambda item: (0 if item["extension"] == "gpkg" else 1 if item["extension"] == "shp" else 2, item["label"].lower()))
        for index, fmt in enumerate(formats):
            checkbox = QCheckBox(fmt["label"])
            checkbox.setProperty("driverName", fmt["driver"])
            checkbox.setProperty("extension", fmt["extension"])
            checkbox.setToolTip("QGIS/GDAL driver: {}".format(fmt["driver"]))
            row, col = divmod(index, 3)
            self.format_grid.addWidget(checkbox, row, col)
            self.format_checks.append(checkbox)
        self.format_summary.setText("{} vector output formats available on this computer.".format(len(formats)))

    # ----------------------------------------------------------- layer list
    def refresh_layers(self):
        self.layer_table.setRowCount(0)
        self.layer_rows = {}
        vector_layers = [layer for layer in self.project.mapLayers().values() if isinstance(layer, QgsVectorLayer) and layer.isValid()]
        vector_layers.sort(key=lambda layer: layer.name().casefold())
        self.layer_table.setRowCount(len(vector_layers))

        for row, layer in enumerate(vector_layers):
            checked_item = QTableWidgetItem()
            checked_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            checked_item.setCheckState(Qt.Unchecked)
            checked_item.setData(Qt.UserRole, layer.id())
            self.layer_table.setItem(row, 0, checked_item)

            name_item = QTableWidgetItem(layer.name())
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            name_item.setData(Qt.UserRole, layer.id())
            self.layer_table.setItem(row, 1, name_item)

            try:
                geom_desc = QgsWkbTypes.displayString(layer.wkbType())
                if layer.wkbType() == QgsWkbTypes.NoGeometry:
                    geom_desc = "No geometry / table"
            except Exception:
                geom_desc = "Vector"
            geom_item = QTableWidgetItem(geom_desc)
            geom_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.layer_table.setItem(row, 2, geom_item)

            field_combo = QComboBox()
            field_combo.addItem("— Select field —", "")
            field_names = [field.name() for field in layer.fields()]
            for field_name in field_names:
                field_combo.addItem(field_name, field_name)
            probable_names = {"type", "subtype", "category", "structure_type", "facility_type", "asset_type", "layer_type"}
            for idx, field_name in enumerate(field_names, start=1):
                if field_name.casefold() in probable_names:
                    field_combo.setCurrentIndex(idx)
                    break
            self.layer_table.setCellWidget(row, 3, field_combo)
            self.layer_rows[layer.id()] = {"row": row, "layer": layer, "field_combo": field_combo}

        self.layer_table.resizeRowsToContents()
        if not vector_layers:
            self._log("No valid vector layers found in the current QGIS project.")
        else:
            self._log("Layer list refreshed: {} vector layer(s) available.".format(len(vector_layers)))

    def _set_all_layers_checked(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.layer_table.rowCount()):
            item = self.layer_table.item(row, 0)
            if item:
                item.setCheckState(state)

    def _selected_layer_configs(self):
        selected = []
        for layer_id, entry in self.layer_rows.items():
            row = entry["row"]
            check_item = self.layer_table.item(row, 0)
            if check_item and check_item.checkState() == Qt.Checked:
                selected.append({
                    "layer": entry["layer"],
                    "subtype_field": entry["field_combo"].currentData() or "",
                })
        return selected

    # --------------------------------------------------------- CRS handling
    def _target_crs_changed(self, index):
        if self._refreshing_target_combo:
            return
        value = self.target_crs_combo.itemData(index)
        if value != "choose":
            return
        dialog = QgsProjectionSelectionDialog(self)
        if self.custom_target_crs and self.custom_target_crs.isValid():
            dialog.setCrs(self.custom_target_crs)
        else:
            dialog.setCrs(self.project.crs())
        if dialog.exec_():
            chosen_crs = dialog.crs()
            if chosen_crs.isValid():
                self.custom_target_crs = chosen_crs
                label = "Custom CRS ({})".format(chosen_crs.authid() or chosen_crs.description())
                self._refreshing_target_combo = True
                custom_index = -1
                for i in range(self.target_crs_combo.count()):
                    if self.target_crs_combo.itemData(i) == "custom":
                        custom_index = i
                        break
                if custom_index < 0:
                    custom_index = self.target_crs_combo.count()
                    self.target_crs_combo.addItem(label, "custom")
                else:
                    self.target_crs_combo.setItemText(custom_index, label)
                self.target_crs_combo.setItemData(custom_index, "custom")
                self.target_crs_combo.setCurrentIndex(custom_index)
                self._refreshing_target_combo = False
                self._log("Target CRS selected: {}".format(label))
                return
        # User cancelled: return to source-CRS mode.
        self._refreshing_target_combo = True
        self.target_crs_combo.setCurrentIndex(0)
        self._refreshing_target_combo = False

    def _resolve_target_crs(self):
        value = self.target_crs_combo.currentData()
        if value == "project":
            crs = self.project.crs()
            if crs.isValid():
                return crs
            raise ValueError("The QGIS project CRS is not valid. Choose another target CRS.")
        if value == "custom":
            if self.custom_target_crs and self.custom_target_crs.isValid():
                return self.custom_target_crs
            raise ValueError("The selected custom target CRS is not valid.")
        return None  # Keep each layer's original CRS.

    # ------------------------------------------------------------ file path
    def _choose_output_folder(self):
        start = self.output_path_edit.text().strip() or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Choose export folder", start)
        if folder:
            self.output_path_edit.setText(folder)

    @staticmethod
    def _safe_name(value):
        value = str(value or "layer").strip()
        value = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_.-")
        return value or "layer"

    @staticmethod
    def _unique_path(path):
        """Return a non-existing path, never silently overwriting prior output."""
        if not os.path.exists(path):
            return path
        folder, filename = os.path.split(path)
        stem, ext = os.path.splitext(filename)
        counter = 2
        while True:
            candidate = os.path.join(folder, "{}__{}{}".format(stem, counter, ext))
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    @staticmethod
    def _json_value(value):
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        try:
            return str(value)
        except Exception:
            return repr(value)

    @staticmethod
    def _field_description(layer):
        fields = []
        for index, field in enumerate(layer.fields()):
            fields.append({
                "name": field.name(),
                "alias": layer.attributeAlias(index),
                "type_name": field.typeName(),
                "length": field.length(),
                "precision": field.precision(),
                "comment": field.comment(),
            })
        return fields

    def _selected_formats(self):
        return [
            {
                "label": checkbox.text(),
                "driver": checkbox.property("driverName"),
                "extension": checkbox.property("extension"),
            }
            for checkbox in self.format_checks
            if checkbox.isChecked()
        ]

    def _selected_mode(self):
        if self.mode_subtypes.isChecked():
            return "subtypes"
        if self.mode_both.isChecked():
            return "both"
        return "whole"

    # ---------------------------------------------------------- subtype data
    @staticmethod
    def _is_null_value(value):
        if value is None:
            return True
        try:
            return bool(value.isNull())
        except Exception:
            return False

    def _distinct_values(self, layer, field_name):
        index = layer.fields().indexFromName(field_name)
        if index < 0:
            raise ValueError("Field '{}' is not present in layer '{}'.".format(field_name, layer.name()))
        values = []
        seen = set()
        for feature in layer.getFeatures():
            value = feature[index]
            if self._is_null_value(value):
                key = ("null", "")
                value = None
            else:
                try:
                    key = (type(value).__name__, repr(value))
                except Exception:
                    key = (type(value).__name__, str(value))
            if key not in seen:
                seen.add(key)
                values.append(value)
        return values

    @staticmethod
    def _subtype_label(value):
        if value is None:
            return "NULL"
        if isinstance(value, str) and value == "":
            return "empty"
        return str(value)

    def _make_subtype_layer(self, source, field_name, value, layer_name):
        """Copy matching features into a temporary memory layer without altering the source."""
        source_crs = source.crs().authid()
        if source.wkbType() == QgsWkbTypes.NoGeometry:
            uri = "None"
        else:
            geom_name = QgsWkbTypes.displayString(source.wkbType()) or "Unknown"
            uri = geom_name + ("?crs={}".format(source_crs) if source_crs else "")
        memory_layer = QgsVectorLayer(uri, layer_name, "memory")
        if not memory_layer.isValid():
            # Fallback: remove only a trailing Z/M dimensional marker, not letters
            # inside geometry names such as MultiPolygon.
            geometry_name = QgsWkbTypes.displayString(source.wkbType())
            geometry_name = re.sub(r"(?:ZM|Z|M|25D)$", "", geometry_name)
            fallback_uri = (geometry_name + ("?crs=" + source_crs if source_crs else "")) if source.wkbType() != QgsWkbTypes.NoGeometry else "None"
            memory_layer = QgsVectorLayer(fallback_uri, layer_name, "memory")
        if memory_layer.isValid() and source.crs().isValid() and memory_layer.crs() != source.crs():
            memory_layer.setCrs(source.crs())
        if not memory_layer.isValid():
            raise RuntimeError("Could not create a temporary layer for subtype '{}' in '{}'.".format(self._subtype_label(value), source.name()))

        provider = memory_layer.dataProvider()
        provider.addAttributes([QgsField(field) for field in source.fields()])
        memory_layer.updateFields()
        field_index = source.fields().indexFromName(field_name)
        matches = []
        for feature in source.getFeatures():
            feature_value = feature[field_index]
            is_match = self._is_null_value(feature_value) if value is None else (feature_value == value)
            if is_match:
                copied = QgsFeature(memory_layer.fields())
                if source.wkbType() != QgsWkbTypes.NoGeometry and not feature.geometry().isNull():
                    copied.setGeometry(feature.geometry())
                copied.setAttributes(feature.attributes())
                matches.append(copied)
        if matches:
            ok, _ = provider.addFeatures(matches)
            if not ok:
                raise RuntimeError("The temporary subtype layer could not accept all matching features.")
        memory_layer.updateExtents()
        return memory_layer, len(matches)

    # ----------------------------------------------------------- export work
    def _log(self, message):
        if hasattr(self, "log_text"):
            self.log_text.append(str(message))
            scrollbar = self.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            self.log_text.repaint()

    def _process_events(self):
        try:
            from qgis.PyQt.QtWidgets import QApplication
            QApplication.processEvents()
        except Exception:
            pass

    def _write_dataset(self, source_layer, output_path, fmt, target_crs):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = str(fmt["driver"])
        options.fileEncoding = "UTF-8"
        options.onlySelectedFeatures = False
        # Explicitly request every attribute. Leaving this implicit can lead to
        # confusion across QGIS/GDAL versions and provider implementations.
        options.attributes = list(range(source_layer.fields().count()))
        options.skipAttributeCreation = False
        if target_crs is not None and source_layer.crs().isValid() and source_layer.crs() != target_crs:
            options.ct = QgsCoordinateTransform(source_layer.crs(), target_crs, self.project.transformContext())
        driver_name = str(fmt["driver"])
        # Prevent the GeoPackage primary-key column from masking a real source
        # attribute named "fid". Preserve the source attribute as ordinary data.
        if driver_name.casefold() == "gpkg":
            occupied = {field.name().casefold() for field in source_layer.fields()}
            fid_column = "qgis_export_pk"
            while fid_column.casefold() in occupied:
                fid_column += "_"
            options.layerOptions = ["FID={}".format(fid_column)]
        # Preserve spatial geometry in CSV as WKT when the GDAL CSV driver accepts it.
        elif driver_name.casefold() == "csv" and source_layer.wkbType() != QgsWkbTypes.NoGeometry:
            options.layerOptions = ["GEOMETRY=AS_WKT"]
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            source_layer,
            output_path,
            self.project.transformContext(),
            options,
        )
        err = result[0] if isinstance(result, (tuple, list)) else result
        no_error = getattr(QgsVectorFileWriter, "NoError", None)
        if no_error is None:
            no_error = getattr(QgsVectorFileWriter.WriterError, "NoError", 0)
        if err == no_error or str(err).endswith("NoError"):
            actual_path = output_path
            if isinstance(result, (tuple, list)):
                # QGIS bindings vary slightly in which optional output values they return.
                for value in result[1:]:
                    if isinstance(value, str) and value and (os.path.isabs(value) or value.lower().endswith("." + fmt["extension"].lower())):
                        if os.path.exists(value):
                            actual_path = value
                            break
            return actual_path, ""
        messages = [str(value) for value in result[1:] if value not in (None, "")]
        error_message = "; ".join(messages) or "QgsVectorFileWriter returned error {}".format(err)
        raise RuntimeError(error_message)

    def _save_style_sidecar(self, layer, output_path):
        style_path = os.path.splitext(output_path)[0] + ".qml"
        try:
            # When the same stem is exported to several formats, reuse the same
            # QML sidecar so that names such as Structures.shp + Structures.qml
            # remain associated as QGIS expects.
            if os.path.exists(style_path):
                self._log("    QML style (shared): {}".format(style_path))
                return style_path, ""
            result = layer.saveNamedStyle(style_path)
            if isinstance(result, (tuple, list)) and len(result) > 1 and isinstance(result[1], bool):
                message, success = result[0], result[1]
            else:
                success = bool(result[0]) if isinstance(result, (tuple, list)) else bool(result)
                message = result[1] if isinstance(result, (tuple, list)) and len(result) > 1 else ""
            if success and os.path.exists(style_path):
                self._log("    QML style: {}".format(style_path))
                return style_path, ""
            return "", str(message or "QGIS did not save the QML style sidecar.")
        except Exception as exc:
            return "", str(exc)

    def _save_metadata_sidecar(self, layer, output_path):
        metadata_path = os.path.splitext(output_path)[0] + ".qmd"
        try:
            # A single metadata sidecar can be shared by formats with the same stem.
            if os.path.exists(metadata_path):
                self._log("    QMD metadata (shared): {}".format(metadata_path))
                return metadata_path, ""
            result = layer.saveNamedMetadata(metadata_path)
            if isinstance(result, (tuple, list)) and len(result) > 1 and isinstance(result[1], bool):
                message, success = result[0], result[1]
            else:
                success = bool(result[0]) if isinstance(result, (tuple, list)) else bool(result)
                message = result[1] if isinstance(result, (tuple, list)) and len(result) > 1 else ""
            if success and os.path.exists(metadata_path):
                self._log("    QMD metadata: {}".format(metadata_path))
                return metadata_path, ""
            return "", str(message or "QGIS did not save the QMD metadata sidecar.")
        except Exception as exc:
            return "", str(exc)

    def _audit_written_dataset(self, output_path, fmt, expected_layer, expected_count):
        """Check the written file's schema and feature count where QGIS can reopen it."""
        try:
            reopened = QgsVectorLayer(output_path, "Batch export verification", "ogr")
            if not reopened.isValid():
                return {"verified": False, "missing_fields": [], "count_mismatch": None,
                        "note": "Output was written but QGIS could not reopen it for automatic verification."}
            expected_names = [field.name() for field in expected_layer.fields()]
            actual_names = [field.name() for field in reopened.fields()]
            actual_folded = {name.casefold() for name in actual_names}
            missing = [name for name in expected_names if name.casefold() not in actual_folded]
            try:
                actual_count = reopened.featureCount()
                count_mismatch = int(actual_count) != int(expected_count)
            except Exception:
                actual_count = None
                count_mismatch = None
            note_parts = []
            if missing:
                note_parts.append("Fields not present in output: {}".format(", ".join(missing)))
            if count_mismatch:
                note_parts.append("Feature count mismatch (expected {}, found {}).".format(expected_count, actual_count))
            return {"verified": not missing and count_mismatch is not True,
                    "missing_fields": missing,
                    "count_mismatch": count_mismatch,
                    "actual_feature_count": actual_count,
                    "actual_fields": actual_names,
                    "note": " ".join(note_parts)}
        except Exception as exc:
            return {"verified": False, "missing_fields": [], "count_mismatch": None,
                    "note": "Automatic output verification failed: {}".format(exc)}

    def _write_one(self, source_layer, fmt, base_stem, target_crs, layer_config, subtype_value=None, subtype_field=""):
        stem = self._safe_name(base_stem)
        output_path = os.path.join(self.output_path_edit.text().strip(), stem + "." + fmt["extension"])
        output_path = self._unique_path(output_path)
        # Use a temporary filtered layer for subtype output, leaving the source layer untouched.
        export_layer = source_layer
        feature_count = source_layer.featureCount()
        temporary_layer = None
        if subtype_field:
            temporary_layer, feature_count = self._make_subtype_layer(
                source_layer,
                subtype_field,
                subtype_value,
                stem,
            )
            export_layer = temporary_layer
        try:
            actual_path, _ = self._write_dataset(export_layer, output_path, fmt, target_crs)
        finally:
            if temporary_layer is not None:
                # The layer object remains alive through the write; release after completion.
                temporary_layer = None

        self._log("  SUCCESS: {} features → {}".format(feature_count, actual_path))
        audit = self._audit_written_dataset(actual_path, fmt, export_layer, feature_count)
        if audit.get("verified"):
            self._log("    VERIFY: {} fields and {} features checked.".format(
                len(audit.get("actual_fields", [])), audit.get("actual_feature_count", feature_count)))
        else:
            self._log("    WARNING: Output schema/count could not be fully verified for this format.")
            if audit.get("note"):
                self._log("    WARNING: {}".format(audit["note"]))
        sidecar_path = ""
        sidecar_warning = ""
        if self.save_qml_check.isChecked():
            sidecar_path, sidecar_warning = self._save_style_sidecar(source_layer, actual_path)
            if sidecar_warning:
                self._log("    WARNING: Style sidecar not saved: {}".format(sidecar_warning))

        metadata_sidecar_path = ""
        metadata_sidecar_warning = ""
        if self.save_qmd_check.isChecked():
            metadata_sidecar_path, metadata_sidecar_warning = self._save_metadata_sidecar(source_layer, actual_path)
            if metadata_sidecar_warning:
                self._log("    WARNING: Metadata sidecar not saved: {}".format(metadata_sidecar_warning))

        try:
            layer_metadata = source_layer.metadata()
            metadata_info = {
                "title": layer_metadata.title(),
                "identifier": layer_metadata.identifier(),
                "abstract": layer_metadata.abstract(),
                "author": layer_metadata.author(),
                "licenses": list(layer_metadata.licenses()),
            }
        except Exception:
            metadata_info = {}

        target_for_dataset = target_crs.authid() if target_crs and target_crs.isValid() else source_layer.crs().authid()
        return {
            "source_layer": source_layer.name(),
            "source_layer_id": source_layer.id(),
            "subtype_field": subtype_field or None,
            "subtype_value": self._json_value(subtype_value) if subtype_field else None,
            "format": fmt["label"],
            "driver": fmt["driver"],
            "feature_count": int(feature_count),
            "schema_verification": audit,
            "source_field_count": len(source_layer.fields()),
            "source_crs": source_layer.crs().authid() or source_layer.crs().description(),
            "output_crs": target_for_dataset,
            "output_path": actual_path,
            "style_sidecar": sidecar_path or None,
            "metadata_sidecar": metadata_sidecar_path or None,
            "fields": self._field_description(source_layer),
            "layer_metadata": metadata_info,
            "copyright": COPYRIGHT,
        }

    def run_export(self):
        selected_layers = self._selected_layer_configs()
        selected_formats = self._selected_formats()
        output_folder = self.output_path_edit.text().strip()
        mode = self._selected_mode()

        if not selected_layers:
            QMessageBox.warning(self, "Batch Layer Exporter", "Select at least one vector layer to export.")
            return
        if not selected_formats:
            QMessageBox.warning(self, "Batch Layer Exporter", "Select at least one output format.")
            return
        if not output_folder:
            QMessageBox.warning(self, "Batch Layer Exporter", "Choose an output folder before exporting.")
            return
        try:
            os.makedirs(output_folder, exist_ok=True)
        except Exception as exc:
            QMessageBox.critical(self, "Batch Layer Exporter", "Cannot create the output folder:\n{}".format(exc))
            return

        if mode in ("subtypes", "both"):
            missing_fields = [item["layer"].name() for item in selected_layers if not item["subtype_field"]]
            if missing_fields:
                QMessageBox.warning(
                    self,
                    "Subtype field required",
                    "Choose a subtype field for each selected layer:\n\n{}".format("\n".join(missing_fields)),
                )
                return

        try:
            target_crs = self._resolve_target_crs()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid target CRS", str(exc))
            return

        # Preflight obvious subtype-field problems before creating any outputs.
        try:
            if mode in ("subtypes", "both"):
                for item in selected_layers:
                    self._distinct_values(item["layer"], item["subtype_field"])
        except Exception as exc:
            QMessageBox.warning(self, "Subtype field error", str(exc))
            return

        self.log_text.clear()
        self.progress_bar.setValue(0)
        self.export_button.setEnabled(False)
        self._log("Batch Layer Exporter started.")
        self._log(COPYRIGHT)
        self._log("Output folder: {}".format(output_folder))
        self._log("Mode: {}".format({"whole": "Whole layer only", "subtypes": "Subtypes only", "both": "Whole layer and subtypes"}[mode]))
        self._log("Formats: {}".format(", ".join(fmt["label"] for fmt in selected_formats)))
        self._log("Target CRS: {}".format("Each layer's source CRS" if target_crs is None else (target_crs.authid() or target_crs.description())))

        manifests = []
        exported_layer_ids = set()
        successful_datasets = 0
        failed_datasets = 0
        total_features_written = 0
        warnings = 0

        tasks = []
        for item in selected_layers:
            layer = item["layer"]
            if mode in ("whole", "both"):
                tasks.append({"layer": layer, "subtype_field": "", "subtype_value": None, "stem": self._safe_name(layer.name()), "item": item})
            if mode in ("subtypes", "both"):
                try:
                    values = self._distinct_values(layer, item["subtype_field"])
                    for value in values:
                        label = self._subtype_label(value)
                        # Subtype exports use the subtype's own name, not a
                        # parent/field prefix. For example, Structure / type =
                        # Handhole becomes Handhole.gpkg. If two layers produce
                        # the same name, _unique_path() adds a safe numeric suffix.
                        subtype_stem = self._safe_name(label)
                        tasks.append({"layer": layer, "subtype_field": item["subtype_field"], "subtype_value": value, "stem": subtype_stem, "item": item})
                except Exception as exc:
                    self._log("ERROR: Could not read subtypes from '{}': {}".format(layer.name(), exc))
                    failed_datasets += 1

        total_tasks = len(tasks) * len(selected_formats)
        if total_tasks == 0:
            self._log("No export datasets to process.")
            self.export_button.setEnabled(True)
            return
        current_task = 0
        self.progress_bar.setRange(0, total_tasks)
        self.progress_bar.setValue(0)

        try:
            for task in tasks:
                layer = task["layer"]
                subtype_field = task["subtype_field"]
                subtype_value = task["subtype_value"]
                label = layer.name()
                if subtype_field:
                    label += " | {} = {}".format(subtype_field, self._subtype_label(subtype_value))
                self._log("\nLayer: {}".format(label))
                for fmt in selected_formats:
                    current_task += 1
                    self._log("  Format: {}".format(fmt["label"]))
                    try:
                        record = self._write_one(
                            layer,
                            fmt,
                            task["stem"],
                            target_crs,
                            task["item"],
                            subtype_value=subtype_value,
                            subtype_field=subtype_field,
                        )
                        manifests.append(record)
                        successful_datasets += 1
                        total_features_written += record["feature_count"]
                        exported_layer_ids.add(layer.id())
                    except Exception as exc:
                        failed_datasets += 1
                        self._log("  FAILED: {}".format(exc))
                    self.progress_bar.setValue(current_task)
                    self._process_events()
        finally:
            self.export_button.setEnabled(True)

        manifest_path = ""
        if self.save_manifest_check.isChecked():
            try:
                manifest_data = {
                    "plugin": "Batch Layer Exporter",
                    "copyright": COPYRIGHT,
                    "created": datetime.now().isoformat(timespec="seconds"),
                    "export_mode": mode,
                    "target_crs": target_crs.authid() if target_crs and target_crs.isValid() else "per-layer source CRS",
                    "selected_formats": [fmt["label"] for fmt in selected_formats],
                    "summary": {
                        "source_layers_exported": len(exported_layer_ids),
                        "output_datasets_succeeded": successful_datasets,
                        "output_datasets_failed": failed_datasets,
                        "features_written_across_datasets": total_features_written,
                    },
                    "exports": manifests,
                }
                manifest_path = self._unique_path(os.path.join(output_folder, "batch_export_manifest.json"))
                with open(manifest_path, "w", encoding="utf-8") as file_obj:
                    json.dump(manifest_data, file_obj, indent=2, ensure_ascii=False, default=self._json_value)
                self._log("\nManifest: {}".format(manifest_path))
            except Exception as exc:
                warnings += 1
                self._log("WARNING: Could not write manifest: {}".format(exc))

        self.summary_label.setText(
            "Layers exported: {}   |   Output datasets: {} succeeded / {} failed   |   Features written: {}".format(
                len(exported_layer_ids), successful_datasets, failed_datasets, total_features_written
            )
        )
        self._log("\n================ EXPORT SUMMARY ================")
        self._log("Distinct source layers exported: {}".format(len(exported_layer_ids)))
        self._log("Output datasets succeeded: {}".format(successful_datasets))
        self._log("Output datasets failed: {}".format(failed_datasets))
        self._log("Total features written across all output datasets: {}".format(total_features_written))
        self._log("Output directory: {}".format(output_folder))
        if manifest_path:
            self._log("Manifest: {}".format(manifest_path))
        self._log(COPYRIGHT)

        if failed_datasets:
            QMessageBox.warning(
                self,
                "Export completed with errors",
                "Export finished with {} successful dataset(s) and {} failed dataset(s). Review the log for details.".format(successful_datasets, failed_datasets),
            )
        else:
            QMessageBox.information(
                self,
                "Export completed",
                "Successfully wrote {} output dataset(s) from {} source layer(s).\nFeatures written across outputs: {}".format(successful_datasets, len(exported_layer_ids), total_features_written),
            )
