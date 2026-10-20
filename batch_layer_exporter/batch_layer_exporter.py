# -*- coding: utf-8 -*-
"""QGIS plugin entry point for Batch Layer Exporter.

Copyright (c) 2077 Amlan Patnaik. All rights reserved.
"""

import os

from qgis.PyQt.QtCore import QCoreApplication, QLocale, QTranslator
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsSettings

from .batch_layer_exporter_dialog import BatchLayerExporterDialog


COPYRIGHT = "© 2077 Amlan Patnaik. All rights reserved."


class BatchLayerExporter:
    """Batch export vector layers and attribute-defined subtypes."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.translator = None

        locale = QgsSettings().value("locale/userLocale", QLocale().name())[0:2]
        locale_path = os.path.join(self.plugin_dir, "i18n", "{}.qm".format(locale))
        if os.path.exists(locale_path):
            self.translator = QTranslator()
            if self.translator.load(locale_path):
                QCoreApplication.installTranslator(self.translator)

        self.actions = []
        self.menu = self.tr("&Batch Layer Exporter")
        self.dlg = None

    def tr(self, message):
        return QCoreApplication.translate("BatchLayerExporter", message)

    def add_action(self, icon_path, text, callback, parent=None):
        action = QAction(QIcon(icon_path), text, parent)
        action.triggered.connect(callback)
        action.setStatusTip(self.tr("Batch export vector layers and subtypes"))
        action.setWhatsThis(COPYRIGHT)
        self.iface.addPluginToMenu(self.menu, action)
        self.iface.addToolBarIcon(action)
        self.actions.append(action)
        return action

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        self.add_action(
            icon_path,
            self.tr("Batch Layer Exporter"),
            self.run,
            self.iface.mainWindow(),
        )

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        self.actions = []
        if self.dlg is not None:
            self.dlg.close()
            self.dlg = None
        if self.translator is not None:
            QCoreApplication.removeTranslator(self.translator)
            self.translator = None

    def run(self):
        if self.dlg is None:
            self.dlg = BatchLayerExporterDialog(self.iface, self.iface.mainWindow())
        self.dlg.refresh_layers()
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()
        self.dlg.exec_()
