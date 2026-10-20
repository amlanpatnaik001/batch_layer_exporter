Batch Layer Exporter
====================

QGIS plugin for batch exporting project vector layers, attribute-defined subtypes,
and multiple formats supported by the local QGIS/GDAL installation.

Copyright (c) 2077 Amlan Patnaik. All rights reserved.

Features
--------
- Lists valid vector layers in the current project.
- Select All, Deselect All, and Refresh Layers controls.
- Export whole layers, subtypes only, or both.
- Per-layer subtype-field selection and automatic unique subtype-value detection.
- Keep each layer's native CRS, use the project CRS, or choose a custom target CRS.
- Format choices are detected at runtime from QgsVectorFileWriter-supported formats.
- Optional QML style sidecars for styling, labeling, field configuration and other supported QGIS layer settings.
- Optional QMD metadata sidecars where layer metadata can be saved.
- Optional JSON manifest with CRS, fields, aliases, metadata where available, subtype information,
  feature counts and output paths.
- A live log with success/failure counts, feature counts, and output paths.
- Existing files are not silently overwritten; a numeric suffix is used where a path already exists.

Installation
------------
1. Extract the batch_layer_exporter folder into the active QGIS profile's python/plugins directory.
2. In QGIS, open Plugins > Manage and Install Plugins > Installed.
3. Enable Batch Layer Exporter.
4. Open Plugins > Batch Layer Exporter.

You can also install a ZIP package through QGIS Plugin Manager if packaged according to QGIS
plugin ZIP structure. The ZIP provided with this source package contains the plugin folder.

Format and preservation notes
-----------------------------
This plugin is a vector exporter. Raster layers are not included in the selectable list.
Output formats differ in supported geometry types, field types/names/lengths, CRS support, aliases,
constraints, domains, metadata and styling. For GeoPackage, an independent primary-key field name is selected
when needed so an existing source attribute named `fid` can remain a regular attribute. GeoPackage is generally a strong default for vector
data. QML sidecars retain QGIS layer styling where saved successfully, and the manifest records
additional source-layer information. Neither sidecar can make an external format preserve every
QGIS project property; inspect the log for per-dataset warnings and failures.

CSV spatial geometry is requested as WKT where supported by the installed GDAL CSV driver. Some
formats do not support all source geometry types or attribute types, and those failures are logged.

The code uses QgsVectorFileWriter.writeAsVectorFormatV3, available in QGIS 3.20 and later.
The declared minimum is QGIS 3.28.

© 2077 Amlan Patnaik. All rights reserved.
