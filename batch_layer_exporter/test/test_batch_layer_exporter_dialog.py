# -*- coding: utf-8 -*-
"""Basic interface smoke tests for Batch Layer Exporter.

Copyright (c) 2077 Amlan Patnaik. All rights reserved.
"""

import unittest

from qgis.PyQt.QtWidgets import QPushButton
from batch_layer_exporter_dialog import BatchLayerExporterDialog
from utilities import get_qgis_app

QGIS_APP = get_qgis_app()


class BatchLayerExporterDialogTest(unittest.TestCase):
    def setUp(self):
        self.dialog = BatchLayerExporterDialog(None)

    def tearDown(self):
        self.dialog.close()
        self.dialog = None

    def test_dialog_title_and_actions(self):
        self.assertEqual(self.dialog.windowTitle(), "Batch Layer Exporter")
        self.assertIsInstance(self.dialog.export_button, QPushButton)
        self.assertIsInstance(self.dialog.close_button, QPushButton)

    def test_layer_selection_controls_exist(self):
        self.assertEqual(self.dialog.layer_table.columnCount(), 4)
        self.assertIsNotNone(self.dialog.select_all_button)
        self.assertIsNotNone(self.dialog.deselect_all_button)


if __name__ == "__main__":
    unittest.main(verbosity=2)
