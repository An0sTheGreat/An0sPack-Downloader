"""An0sPack Downloader - themed Nexus modlist downloader (UI, wizard layout)."""
import ctypes, os, subprocess, sys, threading

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
                               QSizeGrip, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import core
import installer

VERSION = "1.0"
RES = getattr(sys, "_MEIPASS", core.APP)
ICON = os.path.join(RES, "assets", "An0sPack.ico")
THUMB = os.path.join(RES, "assets", "thumb.jpg")

THEMES = {
    "Rustic": dict(dark=True, bg="#211a14", panel="#2a221a", panel2="#3a3025", input="#18130e", text="#efe3cc", muted="#a39478",
                   accent="#d18b2c", accent_text="#1b1208", border="#6b5843", hover="#4a3c2c", danger="#e0674f", ok="#7fae52",
                   sel="#5a4524", scroll="#7a6247", font="Bahnschrift"),
    "Dark": dict(dark=True, bg="#363636", panel="#2d2d2d", panel2="#464646", input="#2a2a2a", text="#f2f2f2", muted="#a0a0a0",
                 accent="#2fb5aa", accent_text="#06201d", border="#6e6e6e", hover="#555555", danger="#ff6a5c", ok="#5cb85c",
                 sel="#1f4b48", scroll="#6a6a6a", font="Segoe UI"),
    "Light": dict(dark=False, bg="#eeeeee", panel="#fafafa", panel2="#dedede", input="#ffffff", text="#222222", muted="#666666",
                  accent="#12958b", accent_text="#ffffff", border="#9a9a9a", hover="#d2d2d2", danger="#c9382f", ok="#3d9a50",
                  sel="#c6ece8", scroll="#b4b4b4", font="Segoe UI"),
}
P = THEMES["Dark"]  # active palette

QSS = """
* { font-family:"%(font)s"; font-size:12px; color:%(text)s; }
#root, #dlg { background:%(bg)s; border:1px solid %(border)s; }
#titlebar, #statusbar { background:%(bg)s; border:none; }
#statusbar { border-top:1px solid %(border)s; }
#statusbar QLabel { font-size:11px; }
#title, #ver { font-size:15px; }
#pagetitle { font-size:17px; }
#heading { font-size:14px; font-weight:600; color:%(accent)s; }
#muted { color:%(muted)s; }
#panel, #help { background:transparent; border:1px solid %(border)s; }
#help QLabel { border:none; background:transparent; }
#banner { background:%(ok)s; border:2px solid %(text)s; }
#banner[warn="true"] { background:%(accent)s; border:none; }
#banner[bad="true"] { background:%(danger)s; border:none; }
#banner QLabel { background:transparent; border:none; color:#ffffff; font-size:13px; font-weight:600; }
#bannertitle { font-size:19px !important; font-weight:400 !important; }
QPushButton { background:%(bg)s; border:1px solid %(muted)s; border-radius:0; padding:8px 22px; }
QPushButton:hover:enabled { border-color:%(accent)s; background:%(hover)s; }
QPushButton:pressed { background:%(sel)s; }
QPushButton:disabled { color:%(muted)s; border-color:%(border)s; }
QPushButton[nav="true"] { border-color:%(text)s; font-weight:600; }
QPushButton[side="true"] { color:%(accent)s; font-weight:700; background:%(panel)s; }
QPushButton[side="true"]:disabled { color:%(muted)s; }
QPushButton[primary="true"] { background:%(accent)s; color:%(accent_text)s; border-color:%(accent)s; font-weight:700; }
QPushButton[primary="true"]:hover:enabled { border-color:%(text)s; background:%(accent)s; }
QPushButton[primary="true"]:disabled { background:%(panel2)s; color:%(muted)s; border-color:%(border)s; }
QPushButton[danger="true"]:hover:enabled { border-color:%(danger)s; color:%(danger)s; }
QPushButton#winbtn, QPushButton#closebtn { border:none; padding:0; min-width:46px; max-width:46px; min-height:36px; background:transparent; font-size:14px; }
QPushButton#winbtn:hover:enabled { background:%(hover)s; }
QPushButton#closebtn:hover:enabled { background:%(danger)s; color:#ffffff; }
QPushButton#rowx { padding:0; min-width:24px; max-width:24px; min-height:20px; }
QPushButton#browse { padding:0; min-width:28px; max-width:28px; min-height:24px; color:%(accent)s; font-weight:700; }
QLineEdit, QSpinBox, QComboBox { background:%(input)s; border:1px solid %(border)s; border-radius:0; padding:4px 7px; selection-background-color:%(accent)s; selection-color:%(accent_text)s; }
QComboBox { background:%(panel2)s; border-color:%(panel2)s; padding:5px 8px; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QComboBox:on { border-color:%(accent)s; }
QComboBox::drop-down { border:none; width:26px; }
QComboBox::down-arrow { image:url(%(i_down)s); width:12px; height:12px; }
QComboBox QAbstractItemView, QListView#popup { background:%(panel2)s; border:1px solid %(accent)s; selection-background-color:%(accent)s; selection-color:%(accent_text)s; outline:0; }
QSpinBox::up-button, QSpinBox::down-button { border:none; width:20px; background:transparent; }
QSpinBox::up-arrow { image:url(%(i_up)s); width:10px; height:10px; }
QSpinBox::down-arrow { image:url(%(i_down)s); width:10px; height:10px; }
QCheckBox::indicator, QAbstractItemView::indicator { width:16px; height:16px; image:url(%(i_box)s); }
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked { image:url(%(i_boxon)s); }
QTableWidget, QListWidget, QTreeView, QListView { background:%(input)s; alternate-background-color:%(input)s; border:1px solid %(border)s; border-radius:0; outline:0; selection-background-color:%(sel)s; selection-color:%(text)s; }
QTableWidget::item { padding:2px 6px; border-bottom:1px solid %(bg)s; }
QTableWidget::item:selected, QTreeView::item:selected, QListView::item:selected { background:%(sel)s; color:%(text)s; }
QListWidget#cards { background:transparent; border:none; }
QListWidget#cards::item { border:none; margin:0 0 2px 0; padding:0; }
QListWidget#cards::item:selected { background:%(accent)s; }
QListWidget#cards::item:hover:!selected { background:%(hover)s; }
QTreeView::item:hover, QListView::item:hover { background:%(hover)s; }
QHeaderView { background:%(panel2)s; border:none; }
QHeaderView::section { background:%(bg)s; border:none; border-right:1px solid %(border)s; border-bottom:1px solid %(border)s; padding:7px 8px; font-weight:600; }
QTableCornerButton::section { background:%(bg)s; border:none; }
QScrollBar:vertical { background:%(input)s; width:14px; margin:0; border-left:1px solid %(bg)s; }
QScrollBar:horizontal { background:%(input)s; height:14px; margin:0; }
QScrollBar::handle:vertical { background:%(scroll)s; min-height:30px; margin:2px; }
QScrollBar::handle:horizontal { background:%(scroll)s; min-width:30px; margin:2px; }
QScrollBar::handle:hover { background:%(accent)s; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; width:0; border:none; background:none; }
QScrollBar::add-page, QScrollBar::sub-page { background:none; }
QProgressBar { background:%(panel2)s; border:none; min-height:18px; max-height:18px; text-align:center; color:%(text)s; }
QProgressBar::chunk { background:%(accent)s; }
QToolTip { background:%(panel2)s; color:%(text)s; border:1px solid %(accent)s; padding:4px; }
QToolButton { background:%(panel2)s; border:1px solid %(border)s; padding:4px; }
QToolButton:hover { border-color:%(accent)s; }
QSizeGrip { background:transparent; }
QMenu { background:%(panel)s; border:1px solid %(accent)s; } QMenu::item:selected { background:%(accent)s; color:%(accent_text)s; }
QLabel a { color:%(accent)s; }
"""

NOT_NX = "Not downloadable - not found on Nexus"
STATUS_COLOR = {"Building": "accent", "Done": "ok", "Failed": "danger", "Not on Nexus": "danger", "Skipped": "ok", "Cancelled": "muted", "Downloading": "accent"}
pts = lambda *a: [QPoint(*t) for t in a]


def make_icons(name, p):
    """draw arrow/checkbox PNGs for the theme (QSS can't theme these natively)"""
    d = os.path.join(core.DATA, "cache", name)
    os.makedirs(d, exist_ok=True)
    out = {}

    def draw(fn, w, paint):
        pm = QPixmap(w, w)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.Antialiasing)
        paint(q)
        q.end()
        path = os.path.join(d, fn)
        pm.save(path)
        return path.replace("\\", "/")

    pen = QPen(QColor(p["text"]), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    out["i_down"] = draw("down.png", 12, lambda q: (q.setPen(pen), q.drawPolyline(pts((2, 4), (6, 8), (10, 4)))))
    out["i_up"] = draw("up.png", 12, lambda q: (q.setPen(pen), q.drawPolyline(pts((2, 8), (6, 4), (10, 8)))))

    def box(on):
        def f(q):
            q.setPen(QPen(QColor(p["accent"] if on else p["muted"]), 1.5))
            q.setBrush(QColor(p["accent"] if on else p["input"]))
            q.drawRect(1, 1, 14, 14)
            if on:
                q.setPen(QPen(QColor(p["accent_text"]), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                q.drawPolyline(pts((4, 8), (7, 11), (12, 5)))
        return f
    out["i_box"] = draw("box.png", 16, box(False))
    out["i_boxon"] = draw("boxon.png", 16, box(True))
    return out


def dwm(w):
    """colour the native title bar of OS dialogs (file pickers) to match the theme (Win11)"""
    try:
        h = int(w.winId())
        rgb = lambda c: ctypes.c_int(QColor(c).red() | QColor(c).green() << 8 | QColor(c).blue() << 16)
        for a, v in ((20, ctypes.c_int(int(P["dark"]))), (35, rgb(P["bg"])), (36, rgb(P["text"])), (34, rgb(P["border"]))):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(h, a, ctypes.byref(v), 4)
    except Exception:
        pass


class ThemeFilter(QObject):
    def eventFilter(self, o, e):
        if e.type() == QEvent.Show and isinstance(o, QWidget) and o.isWindow():
            dwm(o)
        return False


class TitleBar(QWidget):
    def __init__(self, win, text, extra=None, minmax=True, right=""):
        super().__init__()
        self.win = win
        self.setObjectName("titlebar")
        self.setAttribute(Qt.WA_StyledBackground)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 0, 0)
        lay.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(QIcon(ICON).pixmap(22, 22))
        self.title = QLabel(text)
        self.title.setObjectName("title")
        lay.addWidget(logo)
        lay.addWidget(self.title)
        lay.addStretch()
        self.ver = QLabel(right)
        self.ver.setObjectName("ver")
        if right:
            lay.addWidget(self.ver)
            lay.addSpacing(16)
        if extra:
            lay.addWidget(extra)
            lay.addSpacing(8)
        if minmax:
            for t, fn in (("—", win.showMinimized), ("☐", self.toggle)):
                b = QPushButton(t)
                b.setObjectName("winbtn")
                b.clicked.connect(fn)
                lay.addWidget(b)
        c = QPushButton("✕")
        c.setObjectName("closebtn")
        c.clicked.connect(win.close)
        lay.addWidget(c)

    def toggle(self):
        self.win.showNormal() if self.win.isMaximized() else self.win.showMaximized()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.win.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        if not isinstance(self.win, QDialog):
            self.toggle()


class Dlg(QDialog):
    """themed frameless popup"""

    def __init__(self, parent, title, width=460):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.setObjectName("dlg")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setMinimumWidth(width)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        outer.addWidget(TitleBar(self, title, minmax=False))
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(18, 12, 18, 16)
        self.body.setSpacing(12)
        outer.addWidget(body)

    def buttons(self, *specs):
        row = QHBoxLayout()
        row.addStretch()
        for text, fn, primary in specs:
            b = QPushButton(text)
            b.setProperty("primary" if primary else "nav", True)
            b.clicked.connect(fn)
            row.addWidget(b)
        self.body.addLayout(row)


def msg(parent, title, text, ask=False):
    d = Dlg(parent, title)
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.RichText)
    d.body.addWidget(lbl)
    if ask:
        d.buttons(("Cancel", d.reject, False), ("OK", d.accept, True))
    else:
        d.buttons(("OK", d.accept, True))
    return d.exec() == QDialog.Accepted


def ask_text(parent, title, label, default=""):
    d = Dlg(parent, title)
    d.body.addWidget(QLabel(label))
    e = QLineEdit(default)
    d.body.addWidget(e)
    d.buttons(("Cancel", d.reject, False), ("OK", d.accept, True))
    return e.text().strip() if d.exec() == QDialog.Accepted and e.text().strip() else None


def pick_file(parent, title, start, filt):
    return QFileDialog.getOpenFileName(parent, title, start, filt, options=QFileDialog.DontUseNativeDialog)[0]


def pick_dir(parent, title, start):
    return QFileDialog.getExistingDirectory(parent, title, start, QFileDialog.DontUseNativeDialog | QFileDialog.ShowDirsOnly)


def report(parent, fails, cancelled=0):
    d = Dlg(parent, "Download report", 900)
    h = QLabel(f"{len(fails)} mod(s) could not be downloaded" + (f"  ·  {cancelled} cancelled" if cancelled else ""))
    h.setObjectName("heading")
    d.body.addWidget(h)
    t = QTableWidget(len(fails), 3)
    t.setHorizontalHeaderLabels(["Mod", "Reason", "Where to get it"])
    t.verticalHeader().hide()
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionMode(QAbstractItemView.NoSelection)
    t.setWordWrap(True)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
    t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
    t.setColumnWidth(0, 220)
    for r, (n, why, src) in enumerate(fails):
        t.setItem(r, 0, QTableWidgetItem(n))
        t.setItem(r, 1, QTableWidgetItem(why))
        s = QLabel(f'<a href="{src}">{src}</a>' if src.startswith("http") else src)
        s.setWordWrap(True)
        s.setOpenExternalLinks(True)
        s.setContentsMargins(6, 2, 6, 2)
        t.setCellWidget(r, 2, s)
    t.resizeRowsToContents()
    t.setMinimumHeight(320)
    d.body.addWidget(t)
    text = "\n".join(f"{n}\n  Reason: {why}\n  Source: {src}\n" for n, why, src in fails)

    def save():
        p = QFileDialog.getSaveFileName(d, "Save report", os.path.join(core.APP, "download-report.txt"), "Text (*.txt)",
                                        options=QFileDialog.DontUseNativeDialog)[0]
        if p:
            open(p, "w", encoding="utf8").write(text)

    d.buttons(("Copy", lambda: QApplication.clipboard().setText(text), False), ("Save…", save, False), ("Close", d.accept, True))
    d.exec()


def steam_step(parent, man, game, install):
    """Skyrim isn't 1.6.1170: walk the user through Steam's own console download (3 commands); the files are found in Steam's cache or in <install>/Stock Game"""
    if installer.depots_ready(man, game, install):
        return True
    stock = os.path.join(install, installer.STOCK)
    os.makedirs(os.path.join(install, installer.MARK), exist_ok=True)  # marks the folder as ours so it still counts as empty-enough later
    os.makedirs(stock, exist_ok=True)
    cmds = "\n".join(installer.STEAM_COMMANDS)
    d = Dlg(parent, "Skyrim 1.6.1170 needed", 680)
    t = QLabel("An0sPack is built for Skyrim Special Edition <b>1.6.1170</b>, but your game is a different version. Your own game is never changed - "
               "you download the 1.6.1170 files once (about 20 GB), straight from Steam:<br><br>"
               "<b>1.</b> Press <b>Open Steam console</b> (Steam must be running and logged in).<br>"
               "<b>2.</b> Press <b>Copy commands</b>, paste them into the console and press Enter. Wait until all three say <i>Depot download complete</i>.<br>"
               "<b>3.</b> Press <b>Check again</b> - the installer looks in Steam's download cache by itself.<br><br>"
               "If it can't find them (different Steam library, another PC...), copy the <b>contents</b> of the three <i>depot_...</i> folders Steam names in the "
               f"console into <b>{stock}</b> and check again.")
    t.setWordWrap(True)
    t.setTextFormat(Qt.RichText)
    d.body.addWidget(t)
    box = QLabel(cmds.replace("\n", "<br>"))
    box.setTextInteractionFlags(Qt.TextSelectableByMouse)
    box.setStyleSheet(f"background:{P['input']}; border:1px solid {P['border']}; padding:8px; font-family:Consolas;")
    d.body.addWidget(box)
    st = QLabel("")
    st.setObjectName("muted")
    st.setWordWrap(True)
    d.body.addWidget(st)

    def check():
        if installer.depots_ready(man, game, install):
            d.accept()
        else:
            st.setText("The 1.6.1170 files aren't there yet - wait for all three downloads to finish, then check again.")
    d.buttons(("Open Steam console", lambda: os.startfile("steam://nav/console"), False),
              ("Copy commands", lambda: QApplication.clipboard().setText(cmds), False),
              ("Open Stock Game folder", lambda: os.startfile(stock), False), ("Check again", check, True), ("Cancel", d.reject, False))
    return d.exec() == QDialog.Accepted


def set_bar(bar, done, total):
    """progress bar from byte counts: QProgressBar is 32-bit too, so big totals are shown in KiB"""
    sh = 10 if total >= 1 << 30 else 0
    bar.setRange(0, max(1, total >> sh))
    bar.setValue(min(done >> sh, total >> sh))


def steam_login_dialog(parent, man, game, install):
    """'' when nothing is needed, the Steam account name to download with, 'manual' for the Steam-console route, or None if cancelled"""
    if installer.depots_ready(man, game, install):
        return ""
    d = Dlg(parent, "Skyrim version needed", 660)
    t = QLabel("This modlist is built for Skyrim Special Edition <b>1.6.1170</b>, but your game is a different version. An0sPack gets the right files "
               "for you straight from Steam (about 20 GB, once). Your own game is never changed.<br><br>"
               "<b>Your Steam login is NOT stored.</b> A download window opens and you type your password and Steam Guard code there. They go only to "
               "Steam, are used just to fetch the game files this installation needs, and are forgotten when the window closes. "
               "An0sPack never sees, saves or sends them, and the account name below is not saved either.<br><br>"
               "Prefer not to type a password? Use <b>Scan a QR code</b>: the download window shows a QR code that you approve in the Steam mobile app.")
    t.setWordWrap(True)
    t.setTextFormat(Qt.RichText)
    d.body.addWidget(t)
    d.body.addWidget(QLabel("Steam account name (the one that owns Skyrim):"))
    e = QLineEdit()
    d.body.addWidget(e)
    err = QLabel("")
    err.setObjectName("muted")
    d.body.addWidget(err)

    def go():
        if e.text().strip() and '"' not in e.text():
            d.accept()
        else:
            err.setText("Enter your Steam account name.")
    d.buttons(("Cancel", d.reject, False), ("Do it manually instead…", lambda: d.done(2), False), ("Scan a QR code", lambda: d.done(3), False), ("Continue", go, True))
    r = d.exec()
    return e.text().strip() if r == QDialog.Accepted else "manual" if r == 2 else installer.QR if r == 3 else None


class Bridge(QObject):  # worker threads -> UI thread
    ev = Signal(int, str, object, object, str)  # sizes are Python ints: Qt's int is 32-bit and wrapped above 2 GiB
    done = Signal()
    val = Signal(int, object, object)
    cat = Signal(int, int, str)
    inst = Signal(str, object, object, str)
    instdone = Signal(object, object)
    gamedone = Signal(object)


C_PRIO, C_MOD, C_VER, C_ID, C_STATUS, C_PROG, C_X = range(7)


class Main(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Window)
        self.setObjectName("root")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setWindowIcon(QIcon(ICON))
        self.setWindowTitle("An0sPack Downloader")
        self.resize(1180, 820)
        self.setMinimumSize(980, 640)
        self.cfg = core.load_cfg()
        self.rows, self.engine, self.fails, self.status = [], None, [], {}
        self.collapsed, self.hdr, self.fetching, self.premium, self.user, self.prof, self.profiles = set(), {}, False, None, "", None, []
        self.br = Bridge()
        self.br.ev.connect(self.on_event)
        self.br.done.connect(self.on_done)
        self.br.val.connect(self.on_validated)
        self.br.cat.connect(self.on_cats)
        self.br.inst.connect(self.on_inst)
        self.br.instdone.connect(self.on_inst_done)
        self.br.gamedone.connect(self.on_game_done)
        self.installing, self.cancel_inst, self.manifest, self.pkg, self.hidden, self.extra, self.steam_user = False, threading.Event(), None, "", {}, "", ""

        self.themebox = QComboBox()
        self.themebox.setView(QListView())
        self.themebox.addItems(list(THEMES))
        self.themebox.setCurrentText(self.cfg["theme"] if self.cfg["theme"] in THEMES else "Dark")
        self.themebox.setFixedWidth(110)
        self.tb = TitleBar(self, "An0sPack Downloader - [Mod List Downloader]", self.themebox, right=f"v{VERSION}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        outer.addWidget(self.tb)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        self.names = ["Profile Selection", "Install Settings", "Mod List"]
        self.pages.addWidget(self.build_profiles_page())
        self.pages.addWidget(self.build_settings_page())
        self.pages.addWidget(self.build_mods_page())
        self.pages.currentChanged.connect(lambda i: self.sb_page.setText(self.names[i]))

        sb = QWidget()
        sb.setObjectName("statusbar")
        sb.setAttribute(Qt.WA_StyledBackground)
        sl = QHBoxLayout(sb)
        sl.setContentsMargins(8, 3, 4, 3)
        self.sb_page = QLabel(self.names[0])
        sl.addWidget(self.sb_page, 1)
        self.sb_user = QLabel("")
        sl.addWidget(self.sb_user)
        sl.addWidget(QSizeGrip(self))
        outer.addWidget(sb)

        if not self.game.text().strip():
            found = installer.detect_game()
            self.game.setText(found[0] if found else "")
        if not self.dest.text().strip() and self.inst.text().strip():
            self.dest.setText(self.default_dest())
        self.save_settings()
        self.themebox.currentTextChanged.connect(self.apply_theme)
        self.apply_theme(self.themebox.currentText())
        self.reload_profiles(self.cfg.get("profile"))
        if self.key.text():
            self.validate()

    # ---- page scaffolding
    def scaffold(self, title):
        """page = title + [panel | help]; returns (page, panel layout, help text label, help button layout)"""
        pg = QWidget()
        v = QVBoxLayout(pg)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("pagetitle")
        v.addWidget(t)
        row = QHBoxLayout()
        row.setSpacing(8)
        v.addLayout(row, 1)
        panel = QFrame()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 12, 12, 12)
        row.addWidget(panel, 1)
        help_ = QFrame()
        help_.setObjectName("help")
        help_.setFixedWidth(300)
        hl = QVBoxLayout(help_)
        hl.setContentsMargins(8, 8, 8, 8)
        ht = QLabel()
        ht.setWordWrap(True)
        ht.setAlignment(Qt.AlignTop)
        ht.setTextFormat(Qt.RichText)
        hl.addWidget(ht)
        hl.addStretch()
        hb = QVBoxLayout()
        hb.setSpacing(6)
        hl.addLayout(hb)
        row.addWidget(help_)
        return pg, pl, ht, hb

    @staticmethod
    def nav(text, fn, side=False, primary=False):
        b = QPushButton(text)
        b.setProperty("side" if side else "primary" if primary else "nav", True)
        b.clicked.connect(fn)
        return b

    def navrow(self, prev, cont):
        r = QHBoxLayout()
        r.addStretch()
        if prev:
            r.addWidget(self.nav("Previous", prev))
        r.addWidget(self.nav("Continue", cont))
        return r

    def go(self, i):
        self.pages.setCurrentIndex(i)

    def goto_settings(self):
        if self.prof:
            self.go(1)
        else:
            msg(self, "No profile", "Import or select a profile first.")

    # ---- page 0: profiles
    def build_profiles_page(self):
        pg, pl, ht, hb = self.scaffold("Profile Selection")
        self.plist = QListWidget()
        self.plist.setObjectName("cards")
        self.plist.currentRowChanged.connect(self.select_profile)
        self.plist.currentRowChanged.connect(lambda _: self.style_cards())
        self.plist.itemDoubleClicked.connect(lambda _: self.goto_settings())
        pl.addWidget(self.plist)
        ht.setText("Welcome to An0sPack Downloader.<br><br>Select a profile, or import a MO2 <b>modlist.txt</b> to create a new one.<br><br>"
                   "A profile remembers the full mod list - every Nexus mod and file - so you can download or re-download the whole "
                   "list any time.<br><br>Mods that are not on Nexus are listed separately and reported at the end.")
        hb.addWidget(self.nav("Import modlist.txt…", self.import_clicked, side=True))
        self.bdel = self.nav("Delete profile", self.delete_clicked)
        self.bdel.setProperty("danger", True)
        hb.addWidget(self.bdel)
        hb.addLayout(self.navrow(None, self.goto_settings))
        return pg

    def card(self, p):
        w = QWidget()
        w.setAttribute(Qt.WA_TranslucentBackground)
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 4, 8, 4)
        h.setSpacing(10)
        th = QLabel()
        th.setFixedSize(104, 104)
        th.setPixmap(QPixmap(THUMB).scaled(104, 104, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        bl = QVBoxLayout(th)
        bl.setContentsMargins(3, 3, 0, 0)
        badge = QLabel(f" {len(p['mods'])} mods ")
        badge.setStyleSheet("background:rgba(0,0,0,190); color:#ffffff; font-size:10px;")
        bl.addWidget(badge, 0, Qt.AlignTop | Qt.AlignLeft)
        h.addWidget(th)
        v = QVBoxLayout()
        v.setSpacing(2)
        n = QLabel(p["name"])
        n.setStyleSheet("font-size:16px; background:transparent;")
        w.labels = [n]
        nx = sum(1 for m in p["mods"] if core.dlable(m))
        d = QLabel(f"{nx} mods on Nexus, {len(p['mods']) - nx} not downloadable. Imported {p['imported'].replace('T', ' ')} from {p['source']}")
        d.setWordWrap(True)
        d.setStyleSheet("background:transparent;")
        w.labels.append(d)
        v.addWidget(n)
        v.addWidget(d)
        v.addStretch()
        h.addLayout(v, 1)
        return w

    # ---- page 1: settings
    def build_settings_page(self):
        pg, pl, ht, hb = self.scaffold("Install Settings")
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(14)
        g.setColumnStretch(1, 1)

        def path_row(r, label, edit, fn):
            g.addWidget(QLabel(label), r, 0)
            edit.editingFinished.connect(fn)
            g.addWidget(edit, r, 1)
            b = QPushButton("…")
            b.setObjectName("browse")
            b.clicked.connect(lambda: self.browse(edit, label))
            g.addWidget(b, r, 2)
        self.inst = QLineEdit(self.cfg["install"])
        self.inst.setPlaceholderText("Where Mod Organizer 2 and the modlist are installed (a new, empty folder)")
        path_row(0, "Install Directory", self.inst, self.install_changed)
        self.dest = QLineEdit(self.cfg["dest"])
        path_row(1, "Download Directory", self.dest, self.save_settings)
        self.game = QLineEdit(self.cfg["game"])
        self.game.setPlaceholderText("Folder containing SkyrimSE.exe (detected automatically)")
        path_row(2, "Skyrim SE Directory", self.game, self.save_settings)
        self.gstat = QLabel("")
        self.gstat.setObjectName("muted")
        self.gstat.setWordWrap(True)
        g.addWidget(self.gstat, 3, 1, 1, 2)
        g.addWidget(QLabel("Nexus API key"), 4, 0)
        self.key = QLineEdit(core.unprotect(self.cfg["key"]))
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Personal API key (nexusmods.com > Settings > API Keys)")
        self.key.editingFinished.connect(self.save_settings)
        g.addWidget(self.key, 4, 1)
        self.bval = QPushButton("Validate")
        self.bval.clicked.connect(self.validate)
        g.addWidget(self.bval, 4, 2)
        g.addWidget(QLabel("Concurrent downloads"), 5, 0)
        self.workers = QSpinBox()
        self.workers.setRange(1, core.MAX_WORKERS)
        self.workers.setValue(min(self.cfg["workers"], core.MAX_WORKERS))
        self.workers.setFixedWidth(80)
        self.workers.valueChanged.connect(self.save_settings)
        g.addWidget(self.workers, 5, 1, Qt.AlignLeft)
        pl.addLayout(g)
        self.accb = QFrame()
        self.accb.setObjectName("banner")
        self.accb.setProperty("warn", True)
        al = QHBoxLayout(self.accb)
        al.setContentsMargins(14, 12, 14, 12)
        self.acct = QLabel("Enter your Nexus API key and press Validate.")
        self.acct.setWordWrap(True)
        al.addWidget(self.acct)
        pl.addSpacing(8)
        pl.addWidget(self.accb)
        pl.addStretch()
        ht.setText("<b>Install Directory</b> is where Mod Organizer 2, your mods and a copy of Skyrim are set up - pick a new, empty folder "
                   "(not Program Files, Desktop, Downloads or Documents). It needs roughly 130 GB free.<br><br>"
                   "<b>Download Directory</b> defaults to <i>install folder/downloads</i>. Point it elsewhere to keep archives on another drive "
                   "or to reuse an existing downloads folder - archives already there are skipped.<br><br>"
                   "<b>Skyrim SE Directory</b> is your own Skyrim. If it isn't the version the modlist needs (1.6.1170), the installer fetches the right "
                   "files from Steam for you - your game itself is never modified. <b>Your Steam login is never stored</b>: you type it into a "
                   "download window, it goes only to Steam and is forgotten afterwards.<br><br>"
                   "Automatic downloads need a <b>Nexus Premium</b> account. Nexus caps API requests per hour and per day - the "
                   "installer pauses by itself if it hits them.")
        hb.addLayout(self.navrow(lambda: self.go(0), lambda: self.go(2) if self.prof else self.go(0)))
        return pg

    # ---- page 2: mods
    def build_mods_page(self):
        pg = QWidget()
        v = QVBoxLayout(pg)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(8)
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(8, 6, 8, 6)
        lg = QLabel()
        lg.setPixmap(QIcon(ICON).pixmap(30, 30))
        bl.addWidget(lg)
        self.btitle = QLabel("")
        self.btitle.setObjectName("bannertitle")
        bl.addWidget(self.btitle, 1)
        v.addWidget(self.banner)
        row = QHBoxLayout()
        row.setSpacing(8)
        v.addLayout(row, 1)
        left = QVBoxLayout()
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Priority", "Mod", "Version", "Nexus ID", "Status", "Progress", ""])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(C_MOD, QHeaderView.Stretch)
        for c, w in ((C_PRIO, 64), (C_VER, 110), (C_ID, 80), (C_STATUS, 160), (C_PROG, 170), (C_X, 36)):
            hh.setSectionResizeMode(c, QHeaderView.Fixed)
            self.table.setColumnWidth(c, w)
        self.table.cellClicked.connect(self.cell_clicked)
        left.addWidget(self.table, 1)
        bot = QHBoxLayout()
        self.overall = QProgressBar()
        self.overall.setFixedWidth(240)
        bot.addWidget(self.overall)
        self.summary = QLabel("")
        bot.addWidget(self.summary, 1)
        left.addLayout(bot)
        row.addLayout(left, 1)
        side = QVBoxLayout()
        side.setSpacing(8)
        self.binstall = self.nav("Install", self.install_clicked, primary=True)
        self.bstart = self.nav("Download only", self.start, side=True)
        self.bcancel = self.nav("Cancel all", self.cancel_all, side=True)
        self.bcancel.setEnabled(False)
        self.brep = self.nav("Last report", lambda: report(self, self.fails), side=True)
        self.brep.setEnabled(False)
        self.bsettings = self.nav("Settings", lambda: self.go(1), side=True)
        self.bback = self.nav("Back to profiles", lambda: self.go(0), side=True)
        self.bopen = self.nav("Open folder", self.open_install, side=True)
        self.bmo2 = self.nav("Open MO2", self.open_mo2, side=True)
        self.brefresh = self.nav("Refresh", self.refresh, side=True)
        for b in (self.binstall, self.bstart, self.bcancel, self.nav("Expand", lambda: self.fold_all(False), side=True), self.nav("Collapse", lambda: self.fold_all(True), side=True),
                  self.nav("Select all", lambda: self.check_all(True), side=True), self.nav("Select none", lambda: self.check_all(False), side=True),
                  self.brefresh, self.brep, self.bsettings, self.bback, self.bopen, self.bmo2):
            b.setFixedWidth(150)
            side.addWidget(b)
        side.addStretch()
        row.addLayout(side)
        return pg

    # ---- theme / settings
    def apply_theme(self, name):
        global P
        P = THEMES[name]
        pal = QApplication.instance().palette()
        pal.setColor(QPalette.Link, QColor(P["accent"]))
        QApplication.instance().setPalette(pal)
        QApplication.instance().setStyleSheet(QSS % {**P, **make_icons(name, P)})
        for w in QApplication.topLevelWidgets():
            dwm(w)
        for r, s in self.status.items():
            self.paint_status(r, s)
        self.paint_headers()
        self.style_cards()
        self.cfg["theme"] = name
        core.save_cfg(self.cfg)

    def paint_status(self, r, s):
        it = self.table.item(r, C_STATUS)
        if it:
            it.setForeground(QColor(P[STATUS_COLOR.get(s, "text")]))

    def default_dest(self):
        i = self.inst.text().strip()
        return os.path.normpath(os.path.join(i, "downloads")) if i else ""

    def save_settings(self, *_):
        d = self.dest.text().strip()
        self.cfg.update(install=self.inst.text().strip(), dest=d, game=self.game.text().strip(), key=core.protect(self.key.text().strip()),
                        workers=self.workers.value(), dest_custom=bool(d) and os.path.normcase(os.path.normpath(d)) != os.path.normcase(self.default_dest()))
        core.save_cfg(self.cfg)
        self.check_game_dir()

    def install_changed(self):
        if not self.cfg.get("dest_custom") or not self.dest.text().strip():
            self.dest.setText(self.default_dest())  # the download folder follows the install folder until the user picks another
        self.save_settings()

    def browse(self, edit, label):
        d = pick_dir(self, f"Select {label.lower()}", edit.text() or core.APP)
        if d:
            edit.setText(os.path.normpath(d))
            self.install_changed() if edit is self.inst else self.save_settings()

    def check_game_dir(self):
        """cheap, non-blocking hint under the Skyrim folder field"""
        g = self.game.text().strip()
        if not g:
            self.gstat.setText("Not found automatically - select the folder that contains SkyrimSE.exe.")
        elif not os.path.exists(os.path.join(g, "SkyrimSE.exe")):
            self.gstat.setText("SkyrimSE.exe not found in that folder.")
        else:
            self.gstat.setText("Skyrim Special Edition found. The version is verified when the install starts.")

    def banner_state(self, text, state):
        self.acct.setText(text)
        self.accb.setProperty("warn", state == "warn")
        self.accb.setProperty("bad", state == "bad")
        self.accb.style().unpolish(self.accb)
        self.accb.style().polish(self.accb)

    def validate(self):
        self.save_settings()
        key = self.key.text().strip()
        if not key:
            return self.banner_state("Enter your Nexus API key and press Validate.", "warn")
        self.banner_state("Checking key…", "warn")

        def work():
            try:
                s, j, h = core.Engine(key, "", 1, lambda *a: 0, lambda: 0).validate()
                self.br.val.emit(s, j, dict(h))
            except Exception as e:
                self.br.val.emit(0, {"error": str(e)}, {})
        threading.Thread(target=work, daemon=True).start()

    def on_validated(self, s, j, h):
        if s == 200:
            self.premium, self.user = bool(j.get("is_premium")), j.get("name", "")
            left = f"Requests left today: {h.get('x-rl-daily-remaining', '?')}  ·  this hour: {h.get('x-rl-hourly-remaining', '?')}"
            if self.premium:
                self.banner_state(f"Signed in as {self.user} (Premium)  ·  {left}", "ok")
            else:
                self.banner_state(f"Signed in as {self.user} - FREE account: Nexus only allows automatic downloads for Premium.  ·  {left}", "bad")
            self.tb.ver.setText(f"v{VERSION} | {self.user}")
            self.sb_user.setText(f"[DPI:{int(self.devicePixelRatio() * 100)}%]   {self.user} ({'Premium' if self.premium else 'Free'})")
        else:
            self.banner_state("Invalid API key" if s in (401, 403) else f"Could not reach Nexus ({s or j.get('error', '')})", "bad")
        self.fetch_cats()

    # ---- profiles
    def reload_profiles(self, select=None):
        self.profiles = core.list_profiles()
        self.plist.blockSignals(True)
        self.plist.clear()
        for p in self.profiles:
            it = QListWidgetItem()
            it.setSizeHint(QSize(100, 114))
            self.plist.addItem(it)
            self.plist.setItemWidget(it, self.card(p))
        self.plist.blockSignals(False)
        self.style_cards()
        idx = next((i for i, p in enumerate(self.profiles) if p["name"] == select), 0 if self.profiles else -1)
        self.plist.setCurrentRow(idx)
        self.select_profile(idx)

    def style_cards(self):
        for i in range(self.plist.count()):
            w = self.plist.itemWidget(self.plist.item(i))
            col = P["accent_text"] if i == self.plist.currentRow() else P["text"]
            for l in w.labels:
                l.setStyleSheet(l.styleSheet().split("color:")[0] + f"color:{col};")

    def select_profile(self, i):
        self.prof = self.profiles[i] if 0 <= i < len(self.profiles) else None
        self.bdel.setEnabled(bool(self.prof) and self.prof["name"] != core.DEFAULT_PROFILE)
        if not self.prof:
            self.btitle.setText("No profile selected")
            self.table.setRowCount(0)
            return
        p = self.prof
        self.pkg, self.manifest = core.package_path(p["name"]), None
        self.binstall.setEnabled(True)
        self.binstall.setToolTip("" if self.pkg else "Imported modlist: downloads every mod and installs each as a simple extract (best effort - no FOMOD choices).")
        self.cfg["profile"] = p["name"]
        core.save_cfg(self.cfg)
        nx = sum(1 for m in p["mods"] if core.dlable(m))
        self.btitle.setText(f"{p['name']}  -  {len(p['mods'])} mods ({nx} on Nexus)")
        self.collapsed = set()
        core.apply_cached_cats(p["mods"])
        self.build_table()
        self.fetch_cats()

    def build_table(self):
        p = self.prof
        self.table.clearSpans()
        self.table.setRowCount(0)
        self.rows, self.status, self.hdr = [], {}, {}
        groups = {}
        for n, m in enumerate(p["mods"], 1):
            m["prio"] = n
            if core.dlable(m):
                groups.setdefault(m.get("cat") or "Uncategorized", []).append(m)
        order = sorted(groups.items(), key=lambda kv: kv[0].lower())
        nonnx = [m for m in p["mods"] if not core.dlable(m)]
        if nonnx:
            order.insert(0, (NOT_NX, nonnx))
        self.table.setRowCount(len(p["mods"]) + len(order))
        r = 0
        for g, ms in order:
            self.add_header(r, g, len(ms))
            self.rows.append(None)
            r += 1
            for m in ms:
                self.add_row(r, m)
                self.rows.append(m)
                r += 1
        self.paint_headers()
        for r in list(self.hdr):
            if self.hdr[r][0] in self.collapsed:
                self.hide_group(r)

    def add_header(self, r, g, n):
        it = QTableWidgetItem()
        it.setFlags(Qt.ItemIsEnabled)
        self.table.setItem(r, 0, it)
        self.table.setSpan(r, 0, 1, 7)
        self.hdr[r] = (g, n)
        self.table.setRowHeight(r, 30)
        self.set_header_text(r)

    def set_header_text(self, r):
        g, n = self.hdr[r]
        self.table.item(r, 0).setText(f"{'⌄' if g not in self.collapsed else '›'}    {g.upper()} ( {n} Mods )")

    def paint_headers(self):
        f = self.table.font()
        f.setBold(True)
        for r, (g, n) in self.hdr.items():
            it = self.table.item(r, 0)
            it.setFont(f)
            it.setForeground(QColor(P["danger"] if g == NOT_NX else P["text"]))
            it.setBackground(QColor(P["panel2"]))

    def hide_group(self, r):
        hide = self.hdr[r][0] in self.collapsed
        k = r + 1
        while k < len(self.rows) and self.rows[k] is not None:
            self.table.setRowHidden(k, hide)
            k += 1

    def cell_clicked(self, r, c):
        if r in self.hdr:
            self.collapsed ^= {self.hdr[r][0]}
            self.set_header_text(r)
            self.hide_group(r)

    def fold_all(self, collapse):
        self.collapsed = {g for g, n in self.hdr.values()} if collapse else set()
        for r in self.hdr:
            self.set_header_text(r)
            self.hide_group(r)

    def add_row(self, r, m):
        T = self.table
        T.setItem(r, C_PRIO, QTableWidgetItem(str(m["prio"])))
        label = m["name"] + (f"  (+{len(m['also'])} more)" if m.get("also") else "")
        it = QTableWidgetItem(label)
        it.setToolTip("\n".join([m["name"]] + m.get("also", []) + ([m["note"]] if m.get("note") else [])))
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable if core.dlable(m) else Qt.ItemIsEnabled)
        if core.dlable(m):
            it.setCheckState(Qt.Checked)
        T.setItem(r, C_MOD, it)
        T.setItem(r, C_VER, QTableWidgetItem(m["version"]))
        T.setItem(r, C_ID, QTableWidgetItem(core.source_label(m)))
        st = "" if core.dlable(m) else "Not on Nexus"
        T.setItem(r, C_STATUS, QTableWidgetItem(st))
        self.status[r] = st
        self.paint_status(r, st)
        if not core.dlable(m):
            f = QPushButton("Find")
            f.setToolTip("Open the folder this mod sits in")
            f.setProperty("side", True)
            f.clicked.connect(lambda _=False, m=m: self.find_mod(m))
            T.setCellWidget(r, C_PROG, f)
            return
        pb = QProgressBar()
        pb.setValue(0)
        w = QWidget()  # centres the 18px bar in the 32px row
        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 7, 6, 7)
        lay.addWidget(pb)
        w.bar = pb
        T.setCellWidget(r, C_PROG, w)
        x = QPushButton("✕")
        x.setObjectName("rowx")
        x.setEnabled(False)
        x.setToolTip("Cancel this download")
        x.clicked.connect(lambda _=False, r=r: self.engine and self.engine.cancel(r))
        T.setCellWidget(r, C_X, x)

    def find_mod(self, m):
        root = self.prof.get("root")
        path = os.path.normpath(os.path.join(root, "mods", m["name"])) if root else ""
        if not path or not os.path.isdir(path):
            return msg(self, "Folder not found", f"Can't locate <b>{m['name']}</b> on disk" + ("." if root else " - this profile has no MO2 folder recorded."))
        subprocess.Popen(["explorer", f"/select,{path}"])

    # ---- categories / refresh
    def fetch_cats(self):
        p, key = self.prof, self.key.text().strip()
        if self.fetching or not self.bstart.isEnabled() or not p or not key or all(m.get("cat") or not m["modid"] for m in p["mods"]):
            return
        self.fetching = True

        def work():
            try:
                core.fetch_categories(key, p["mods"], lambda d, t: self.br.cat.emit(d, t, ""))
                self.br.cat.emit(-2, 0, "")
            except Exception as e:
                self.br.cat.emit(-1, 0, str(e)[:100])
        threading.Thread(target=work, daemon=True).start()

    def on_cats(self, d, t, err):
        if d >= 0:
            return self.summary.setText(f"Reading Nexus categories… {d}/{t}")
        self.fetching = False
        self.summary.setText("" if d == -2 else f"Category lookup failed: {err}")
        if self.prof:
            core.save_profile(self.prof)
            self.build_table()

    def refresh(self):
        if not self.prof or not self.bstart.isEnabled():
            return
        src = self.prof["source"]
        if not os.path.exists(src):
            return msg(self, "Source missing", f"The original modlist.txt is gone:<br>{src}<br><br>Import it again to rebuild this profile.")
        name = self.prof["name"]
        core.import_modlist(src, self.prof.get("root") or None, name)
        self.reload_profiles(name)
        if self.key.text().strip():
            self.validate()

    def import_clicked(self):
        path = pick_file(self, "Select modlist.txt", self.cfg.get("last_dir", ""), "MO2 modlist (modlist.txt);;Text (*.txt)")
        if not path:
            return
        self.cfg["last_dir"] = os.path.dirname(path)
        root = core.find_root(path)
        if not root:
            if msg(self, "MO2 folder needed", "This modlist.txt isn't inside an MO2 instance, so Nexus mod IDs can't be read.<br><br>"
                   "Select the MO2 folder (the one containing <b>mods</b> and <b>downloads</b>) to read them from.", ask=True):
                root = pick_dir(self, "Select MO2 folder", core.APP) or None
            if not root:
                msg(self, "Imported without IDs", "Without the MO2 folder, mods will be listed but none can be downloaded.")
        name = ask_text(self, "Profile name", "Name for this download profile:", os.path.basename(os.path.dirname(path)))
        if not name:
            return
        if any(p["name"] == name for p in core.list_profiles()) and not msg(self, "Replace profile?", f"A profile named <b>{name}</b> exists. Replace it?", ask=True):
            return
        core.import_modlist(path, root, name)
        self.reload_profiles(name)

    def delete_clicked(self):
        if self.prof and self.prof["name"] == core.DEFAULT_PROFILE:
            return msg(self, "Default profile", f"<b>{core.DEFAULT_PROFILE}</b> is the built-in profile and can't be deleted.")
        if self.prof and msg(self, "Delete profile", f"Delete profile <b>{self.prof['name']}</b>? (Downloaded files are not touched.)", ask=True):
            core.delete_profile(self.prof["name"])
            self.reload_profiles()

    def check_all(self, on):
        for r, m in enumerate(self.rows):
            if m and core.dlable(m):
                self.table.item(r, C_MOD).setCheckState(Qt.Checked if on else Qt.Unchecked)

    # ---- downloading
    def set_busy(self, busy):
        for w in (self.binstall, self.bstart, self.bsettings, self.bback, self.brefresh, self.themebox):
            w.setEnabled(not busy)
        self.bcancel.setEnabled(busy)

    def start(self):
        self._begin(False)

    def install_clicked(self):
        """full automated install: validate -> download everything -> install into the install folder"""
        self.check_all(True)  # the install needs every archive, whatever was unticked
        self.save_settings()
        i, d, g = self.inst.text().strip(), self.dest.text().strip(), self.game.text().strip()
        err = installer.check_dirs(i, d, g)
        if err:
            return msg(self, "Install folder", err)
        if not self.pkg:
            return self.simple_install_clicked(i, d, g)
        try:
            self.manifest = self.manifest or installer.load(self.pkg)
        except Exception as e:
            return msg(self, "Install package", f"Can't read this profile's install package:<br>{e}")
        err = installer.check_game(self.manifest, g)
        if err:
            return msg(self, "Skyrim Special Edition", err)
        steam_user = ""
        if installer.game_needs_depots(self.manifest, g):
            r = steam_login_dialog(self, self.manifest, g, i)
            if r is None or (r == "manual" and not steam_step(self, self.manifest, g, i)):
                return
            steam_user = "" if r == "manual" else r
        need_i, need_d = installer.space_report(self.manifest, i, d)
        gb = lambda n: f"{n / 1e9:.0f} GB"
        same = os.path.splitdrive(os.path.abspath(i))[0].lower() == os.path.splitdrive(os.path.abspath(d))[0].lower()
        if installer.free(i) < need_i + (need_d if same else 0) or (not same and installer.free(d) < need_d):
            return msg(self, "Not enough disk space", f"The install needs about {gb(need_i)} in the install folder and {gb(need_d)} more to download"
                       + (" (same drive: " + gb(need_i + need_d) + " total)." if same else "."))
        miss = installer.missing_manual(self.manifest, d)
        note = ("<br><br><b>These mods have no download source and will be skipped</b> (add the file to the download folder and press Install again to include them):<br>"
                + "<br>".join(miss)) if miss else ""
        if not msg(self, "Install " + self.prof["name"], f"Install into <b>{i}</b>?<br><br>Download: about {gb(need_d)} to <b>{d}</b><br>"
                   f"Disk space needed for the install: about {gb(need_i)}<br><br>This can take hours. You can cancel and run it again - finished work is kept.{note}", ask=True):
            return
        self.steam_user = steam_user
        if steam_user:  # the game comes first so the Steam login happens up front and the rest can run unattended
            self.fetch_game(steam_user, g, i)
        else:
            self._begin(True)

    def open_install(self):
        i = self.inst.text().strip()
        if i and os.path.isdir(i):
            os.startfile(i)
        else:
            msg(self, "Install folder", "The install folder doesn't exist yet - press Install first.")

    def open_mo2(self):
        exe = os.path.join(self.inst.text().strip(), "ModOrganizer.exe")
        if os.path.exists(exe):
            subprocess.Popen([exe], cwd=os.path.dirname(exe))
        else:
            msg(self, "Mod Organizer 2", "Mod Organizer 2 isn't installed in the install folder yet - press Install first.")

    def simple_install_clicked(self, i, d, g):
        """imported modlist.txt (no author package): download everything, then install each archive as a simple extract"""
        err = installer.check_game(None, g)
        if err:
            return msg(self, "Skyrim Special Edition", err)
        if installer.free(i) < 20e9:
            return msg(self, "Not enough disk space", "Less than 20 GB is free in the install folder.")
        if not msg(self, "Install " + self.prof["name"], f"Install into <b>{i}</b>?<br><br>This profile came from a modlist.txt, so the install is <b>best effort</b>: every "
                   "mod is downloaded and extracted as a simple install into its own folder. FOMOD choices, edited files and the plugin order can't be reproduced "
                   "(plugins start enabled - run LOOT afterwards). Your Skyrim folder is used as it is and not modified.<br><br>"
                   f"Archives go to <b>{d}</b>. You can cancel and run it again - finished work is kept.", ask=True):
            return
        self.manifest, self.steam_user = installer.simple_base(), ""
        self._begin(True)

    def fetch_game(self, user, game, install):
        self.cancel_inst.clear()
        self.installing = True
        self.set_busy(True)
        self.bcancel.setEnabled(True)
        man = self.manifest

        def work():
            try:
                installer.ensure_game_files(man, game, install, user, lambda ph, d, t, n="": self.br.inst.emit(ph, d, t, n), self.cancel_inst.is_set)
                self.br.gamedone.emit(None)
            except installer.Cancelled:
                self.br.gamedone.emit("cancelled")
            except Exception as e:
                self.br.gamedone.emit(f"{type(e).__name__}: {e}")
        self.overall.setRange(0, 1)
        self.overall.setValue(0)
        threading.Thread(target=work, daemon=True).start()

    def on_game_done(self, err):
        self.set_busy(False)
        if err == "cancelled":
            self.installing = False
            return msg(self, "Cancelled", "Cancelled. Press Install again to continue.")
        if err:
            self.installing = False
            return msg(self, "Skyrim download", f"{err}<br><br>Press Install again to retry.")
        self._begin(True)

    def _tasks(self):
        return {r: dict(name=m["name"], game=m["game"] or "skyrimspecialedition", modid=m["modid"], fileid=m["fileid"], file=m["file"], version=m["version"],
                        dl=m.get("dl", ""), script=m.get("script", ""), src=m.get("src", ""))
                for r, m in enumerate(self.rows) if m and core.dlable(m) and self.table.item(r, C_MOD).checkState() == Qt.Checked}

    def _begin(self, install):
        self.cancel_inst.clear()
        self.save_settings()
        if not self.prof:
            return msg(self, "No profile", "Import or select a profile first.")
        if not self.key.text().strip():
            self.go(1)
            return msg(self, "API key needed", "Enter your Nexus API key first.")
        dest = self.dest.text().strip()
        if not dest:
            self.go(1)
            return msg(self, "Download folder", "Choose a download folder first.")
        try:
            os.makedirs(dest, exist_ok=True)
        except OSError as e:
            return msg(self, "Download folder", f"Can't use that folder:<br>{e}")
        tasks = self._tasks()
        self.hidden = {}
        if install:  # archives the package needs that have no row in the table (Mod Organizer itself, Root Builder, ...)
            have = {(t["modid"], t["fileid"]) for t in tasks.values() if t["modid"]} | {t["dl"] for t in tasks.values() if t["dl"]}
            for k, t in installer.download_tasks(self.manifest).items():
                if (t["modid"] and (t["modid"], t["fileid"]) in have) or (t["dl"] and t["dl"] in have) or t["script"]:
                    continue
                tasks[k] = t
                self.hidden[k] = t["name"]
        elif not tasks:
            return msg(self, "Nothing selected", "Tick at least one mod to download.")
        for r in tasks:
            if r not in self.hidden:
                self.set_status(r, "Queued", 0, 0, "")
                self.table.cellWidget(r, C_X).setEnabled(True)
        self.installing = install
        self.total, self.finished, self.counts = len(tasks), 0, {}
        self.overall.setRange(0, self.total)
        self.overall.setValue(0)
        self.fails = []
        self.set_busy(True)
        self.engine = core.Engine(self.key.text().strip(), dest, self.workers.value(), self.br.ev.emit, self.br.done.emit)
        self.engine.start(tasks)
        self.update_summary()

    def cancel_all(self):
        if self.engine:
            self.engine.cancel_all()
        self.cancel_inst.set()
        self.summary.setText("Cancelling…")

    def set_status(self, r, s, done, total, note):
        self.status[r] = s
        it = self.table.item(r, C_STATUS)
        it.setText(f"Downloading {done * 100 // total}%" if s == "Downloading" and total else s)
        it.setToolTip(note or (f"{done / 1048576:.1f} / {total / 1048576:.1f} MB" if total else ""))
        self.paint_status(r, s)
        pb = self.table.cellWidget(r, C_PROG).bar
        if total:
            set_bar(pb, done, total)
        elif s in ("Resolving", "Queued"):
            pb.setRange(0, 1)
            pb.setValue(0)

    def on_event(self, r, s, done, total, note):
        hidden = r in self.hidden  # package-only archives (Mod Organizer itself ...) have no table row
        if hidden:
            self.extra = f"{self.hidden[r]}: {s} {done * 100 // total}%" if s == "Downloading" and total else f"{self.hidden[r]}: {s}"
        else:
            self.set_status(r, s, done, total, note)
        if s in ("Done", "Skipped", "Failed", "Cancelled"):
            if not hidden:
                self.table.cellWidget(r, C_X).setEnabled(False)
            self.finished += 1
            self.counts[s] = self.counts.get(s, 0) + 1
            self.overall.setValue(self.finished)
            if s in ("Done", "Skipped") and not hidden:
                self.table.cellWidget(r, C_PROG).bar.setRange(0, 1)
                self.table.cellWidget(r, C_PROG).bar.setValue(1)
        self.update_summary()

    def update_summary(self):
        c = self.counts
        self.summary.setText(f"{self.finished}/{self.total} finished  ·  {c.get('Done', 0)} downloaded  ·  {c.get('Skipped', 0)} already present  ·  "
                             f"{c.get('Failed', 0)} failed  ·  {c.get('Cancelled', 0)} cancelled" + (f"  ·  {self.extra}" if self.extra and self.installing else ""))

    def on_done(self):
        e = self.engine
        fails = [(self.hidden.get(r) or self.rows[r]["name"], why, src) for r, (why, src) in sorted(e.fails.items())]
        cancelled = self.counts.get("Cancelled", 0)
        if self.installing and not fails and not cancelled:
            self.brep.setEnabled(False)
            return self.run_install()  # every archive is in place -> unpack them
        self.set_busy(False)
        if not self.installing:
            for r, m in enumerate(self.rows):
                if m and not core.dlable(m):
                    fails.append((m["name"], "Not a Nexus mod (custom, generated or third-party content)",
                                  m["url"] or "No source recorded - regenerate it with its original tool or copy it from your existing mods folder"))
        self.fails = fails
        self.brep.setEnabled(bool(fails))
        if fails:
            report(self, fails, cancelled)
            if self.installing:
                msg(self, "Install not started", "Some archives could not be downloaded, so nothing was installed. Fix the problems in the report "
                    "(a Nexus Premium account is required for automatic downloads) and press Install again - finished downloads are kept.")
        elif cancelled:
            msg(self, "Cancelled", "Cancelled. Press Install again to continue where it stopped.")
        else:
            msg(self, "Finished", f"Everything finished: {self.counts.get('Done', 0)} downloaded, {self.counts.get('Skipped', 0)} already present.")
        self.fetch_cats()

    # ---- unpacking (the install proper)
    def run_install(self):
        self.cancel_inst.clear()
        self.bcancel.setEnabled(True)
        pkg, i, d, g = self.pkg, self.inst.text().strip(), self.dest.text().strip(), self.game.text().strip()
        prof = self.prof

        def work():
            try:
                if not pkg:
                    pkg_ = installer.simple_manifest(prof, d, g, lambda ph, dn, tot, note="": self.br.inst.emit(ph, dn, tot, note), self.cancel_inst.is_set)
                else:
                    pkg_ = pkg
                warn = installer.install(pkg_, i, d, g, lambda ph, dn, tot, note="": self.br.inst.emit(ph, dn, tot, note), self.cancel_inst.is_set, None, self.steam_user)
                self.br.instdone.emit(None, warn)
            except installer.Cancelled:
                self.br.instdone.emit("cancelled", [])
            except Exception as e:
                self.br.instdone.emit(f"{type(e).__name__}: {e}", [])
        self.overall.setRange(0, 1)
        self.overall.setValue(0)
        threading.Thread(target=work, daemon=True).start()

    def on_inst(self, phase, done, total, note):
        set_bar(self.overall, min(done, total), max(total, 1))
        mb = lambda n: f"{n / 1e9:.1f} GB"
        self.summary.setText(f"{phase}: {mb(done)} / {mb(total)}  ·  {note}" if phase == "Copying game files" else f"{phase}: {done}/{total}  ·  {note}")

    def on_inst_done(self, err, warn):
        self.set_busy(False)
        self.installing = False
        if err == "cancelled":
            return msg(self, "Cancelled", "Install cancelled. Press Install again to continue - finished work is kept.")
        if err:
            return msg(self, "Install failed", f"The install stopped:<br><br>{err}<br><br>Press Install again to retry - finished work is kept.")
        self.summary.setText("Install complete.")
        extra = ("<br><br>Notes:<br>" + "<br>".join(warn[:12]) + ("<br>..." if len(warn) > 12 else "")) if warn else ""
        msg(self, "Install complete", f"{self.prof['name']} is installed in <b>{self.inst.text().strip()}</b>.<br><br>Start <b>An0sPack - MO2</b> from that folder "
            f"(a shortcut was created) and launch the game through the SKSE entry.{extra}")


def main():
    if "--import" in sys.argv:  # headless seeding: --import <modlist.txt> [profile name]
        a = sys.argv[sys.argv.index("--import") + 1:]
        p = core.import_modlist(a[0], name=a[1] if len(a) > 1 else None)
        print(p["name"], len(p["mods"]), "downloads,", sum(1 for m in p["mods"] if core.dlable(m)), "downloadable")
        return
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(ICON))
    flt = ThemeFilter()
    app.installEventFilter(flt)
    w = Main()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
