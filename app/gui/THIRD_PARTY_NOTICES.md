# Desktop interface dependencies

Mines Bursar Automation uses Qt, PySide6 Essentials, and Shiboken6 6.10.2.
Copyright (C) The Qt Company Ltd. and other contributors. This project uses
their LGPLv3 option. This notice does not change the ownership or licensing of
the application's own code.

The interface imports QtCore, QtGui, and QtWidgets. The development tests also
use QtTest. We do not install PySide6 Addons or use GPL-only Qt add-on modules.
Qt's dependencies have additional notices; preserve those supplied with the
upstream packages.

- [LGPLv3 license text](licenses/LGPL-3.0.txt)
- [GPLv3 text incorporated by LGPLv3](licenses/GPL-3.0.txt)
- [Qt licensing and third-party notices](https://doc.qt.io/qt-6/licensing.html)
- [PySide6 Essentials distribution](https://pypi.org/project/PySide6-Essentials/6.10.2/)
- [Shiboken6 distribution](https://pypi.org/project/shiboken6/6.10.2/)
- [Qt for Python 6.10.2 source archives](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.2-src/)
- [Qt 6.10.2 source archives](https://download.qt.io/official_releases/qt/6.10/6.10.2/single/)

## Current launcher deployment

Setup installs the unmodified libraries into the repository's Python virtual
environment. The application loads these libraries dynamically; no frozen
executable or static linkage is introduced. Recipients may replace the LGPL
libraries with compatible modified versions and debug those modifications.
For example, the Windows environment's interpreter can install a compatible
replacement wheel:

```powershell
.\.venv\Scripts\python.exe -m pip install --force-reinstall C:\path\to\replacement.whl
```

Retain the matching PySide6/Shiboken6 versions when rebuilding the bindings.
Follow upstream's build instructions for modified versions. Application
updates or rerunning setup can reinstall the pinned versions.

## If distributing a bundled release outside Mines

The source links above identify upstream releases; they are not a substitute
for arranging a compliant corresponding-source delivery or source offer.
Before distributing a frozen installer, review the exact bundled modules,
third-party notices, corresponding library sources, and replacement/relinking
instructions for that artifact. Keep this notice and license texts in the
release. Do not assume adding an arbitrary Qt module preserves these terms.
