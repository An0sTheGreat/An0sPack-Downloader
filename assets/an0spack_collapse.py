"""An0sPack: collapse every separator in the mod list when Mod Organizer 2 starts.

MO2 2.5.x only restores the collapsed state of separators when the profile is switched, never at first start, so this tiny plugin does it once the
main window is up. After that MO2 manages the state itself (it remembers what you expand or collapse during the session)."""
import mobase
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QTreeView


class An0sPackCollapse(mobase.IPlugin):
    def __init__(self):
        super().__init__()
        self._organizer = None

    def init(self, organizer):
        self._organizer = organizer
        organizer.onUserInterfaceInitialized(self._ready)
        return True

    def name(self):
        return "An0sPack - collapse separators"

    def author(self):
        return "An0sPack"

    def description(self):
        return "Collapses all separators in the mod list when Mod Organizer starts."

    def version(self):
        return mobase.VersionInfo(1, 0, 0)

    def settings(self):
        return []

    def _ready(self, window):
        def collapse():
            view = window.findChild(QTreeView, "modList")
            if view is not None:
                view.collapseAll()
        QTimer.singleShot(1500, collapse)  # after MO2 has filled and restored the list


def createPlugin():
    return An0sPackCollapse()
