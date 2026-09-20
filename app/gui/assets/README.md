# App logo

`app-logo.png` currently contains the unmodified transparent PNG downloaded from the
[Colorado School of Mines website](https://www.mines.edu/media/minesedu/admin-media/logos/Mines-Logo-triangle-blue.png).

The GUI displays it beside MINES on a white tile to preserve contrast against the
navy sidebar. The image is loaded relative to the GUI module, independent of the
working directory. This university artwork is not covered by the application's
software license; use remains subject to Mines branding requirements.

## Replacing the logo

Replace `app-logo.png` with the approved artwork using the same filename, then
restart the application. No Python changes are needed. Use a transparent PNG
with reasonable padding; the GUI scales it while preserving its proportions.
Update the source attribution above whenever the artwork changes.

The white background tile is styled separately by `brandLogo` in `app/gui/theme.py`
and can be adjusted if future artwork needs a different backdrop.
