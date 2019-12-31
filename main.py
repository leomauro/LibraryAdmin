#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import locale
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

from PyQt5.QtCore import (Qt,
                          pyqtSlot,
                          QDateTime,
                          QMimeData,
                          QModelIndex,
                          QPoint,
                          QRegExp,
                          QSettings,
                          QSize,
                          QSortFilterProxyModel,
                          QUrl)
from PyQt5.QtGui import (QCloseEvent,
                         QDrag,
                         QIcon,
                         QStandardItem,
                         QStandardItemModel)
from PyQt5.QtWidgets import (qApp,
                             QAction,
                             QApplication,
                             QCheckBox,
                             QGridLayout,
                             QHeaderView,
                             QLabel,
                             QLineEdit,
                             QMainWindow,
                             QRadioButton,
                             QTreeView,
                             QWidget)

from appdata import ApplicationData
from database import Database
from fmt import HumanBytes

LIBRARY = os.path.expanduser("~/Library")
COLLECTIONS = ("Documents", "PROC", "Books", "Papers", "Slides")


def item_file(item: QModelIndex) -> str:
    model = item.model()
    t = model.index(item.row(), 0).data()
    w = model.index(item.row(), 1).data()
    n = model.index(item.row(), 2).data().replace("/", "%2f")
    return os.path.join(LIBRARY, w, os.path.extsep.join((n, t)))


class BookView(QTreeView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        policy = self.sizePolicy()
        policy.setVerticalStretch(1)
        self.setSizePolicy(policy)
        self.setMinimumSize(QSize(0, 235))

        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setAllColumnsShowFocus(True)
        self.setSelectionMode(BookView.ExtendedSelection)
        self.setSelectionBehavior(BookView.SelectRows)
        self.setEditTriggers(BookView.NoEditTriggers)
        self.setSortingEnabled(True)
        self.setMouseTracking(True)

        self.setDragDropMode(QTreeView.DragDrop)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.dragStart = QPoint()

    def resetView(self):
        self.sortByColumn(2, Qt.AscendingOrder)
        self.resizeColumnToContents(0)
        self.resizeColumnToContents(1)
        self.resizeColumnToContents(2)
        self.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.header().setStretchLastSection(False)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.dragStart = event.pos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            dist = (event.pos() - self.dragStart).manhattanLength()
            if dist >= QApplication.startDragDistance():
                data = QMimeData()
                data.setUrls([QUrl.fromLocalFile(item_file(index))
                              for index in self.selectionModel().selectedRows()])
                drag = QDrag(self)
                drag.setMimeData(data)
                action = drag.exec(Qt.MoveAction | Qt.CopyAction | Qt.LinkAction,
                                   Qt.CopyAction)
                if action & Qt.MoveAction:
                    print("Moved")
                if action & Qt.CopyAction:
                    print("Copied")
                if action & Qt.LinkAction:
                    print("Linked")
        else:
            super().mouseMoveEvent(event)


class BookFilterProxyModel(QSortFilterProxyModel):
    """The Book filter proxy that drives our Book view."""

    # The identifiers for the various available search "syntaxes".
    SyntaxSubstring = 0
    SyntaxWords = 1
    SyntaxRE = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # The sorting style.
        self.setDynamicSortFilter(True)
        self.setSortLocaleAware(True)
        self.setSortCaseSensitivity(Qt.CaseInsensitive)
        self.setFilterKeyColumn(2)


class BookSearchWidget(QWidget):
    """The Book Search widget occupying our window's central widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # We have no cached Book Database or Book model (yet) ...
        self._book_db = None
        self.model = None

        # ... and our item-type subset selection is empty, defaulting to False for any
        # selection.
        self.selection = defaultdict(bool)

        # Initialize our current search parameters to "undefined". In this way, as soon as
        # we input something or change the settings we will notice and the filter proxy
        # will be set up to produce the appropriate
        # filtered model.
        self.currSearch = None
        self.currSyntax = None
        self.currCase = None
        self.currAlNum = None
        self.currSelection = None

        # We also keep track of the most recent model item to have its tooltip displayed.
        # We don't want to waste time recomputing the tooltip as the mouse moves, unless
        # the item changes due to the movement. See itemEntered().
        self.lastItem = None

        # Create the search widget's UI, which includes the viewer widget.
        self.setupUI()

        # Set up a proxy to filter and sort our model. This way we don't have to modify
        # the underlying Book model, which is usually loaded just once, initially, but
        # that can be forced to be reloaded if we want to recompute the Book Database.
        self.proxyModel = BookFilterProxyModel()
        self.view.setModel(self.proxyModel)

        # We're done!
        #
        # Start a short timer to delay a little bit the initial database and model
        # loading. This is done in order to avoid "freezing" the UI when we start the
        # program and the model simultaneously tries to load and display.
        self.setStatusTip(self.tr("Initializing..."))
        self.timerId = self.startTimer(500)

    def setupUI(self):
        """ Set up the UI by hand.
            (GUI builders create such a convoluted and complex mess... Sigh!)
        """

        # The grid layout we'll use to assemble the whole composite widget.
        grid = QGridLayout(self)
        grid.setVerticalSpacing(2)

        # The line editor widget for the search input.
        # It restarts the redisplay timer whenever it changes.
        lbl_find = QLabel(self.tr("&Find:"))
        self.find = QLineEdit()
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self.timer)
        lbl_find.setBuddy(self.find)

        grid.addWidget(lbl_find, 0, 0)
        grid.addWidget(self.find, 0, 1)

        # The type-of-search controls.
        # Any changes restart the redisplay timer.
        self.syntax_strng = QRadioButton(self.tr("&Substring"))
        self.syntax_strng.setStatusTip(self.tr("Search for a substring"))
        self.syntax_strng.setChecked(True)
        self.syntax_strng.toggled.connect(self.timer)
        self.syntax_words = QRadioButton(self.tr("&Words"))
        self.syntax_words.setStatusTip(self.tr("Search for individual words"))
        self.syntax_words.setDisabled(True)  # For the time being
        self.syntax_words.toggled.connect(self.timer)
        self.syntax_RegEx = QRadioButton(self.tr("&Regular Expression"))
        self.syntax_RegEx.setStatusTip(self.tr("Search for Regular Expression"))
        self.syntax_RegEx.toggled.connect(self.timer)

        self.syntax_ICase = QCheckBox(self.tr("&Ignore Case"))
        self.syntax_ICase.setStatusTip(self.tr("Search ignores character case"))
        self.syntax_ICase.setChecked(True)
        self.syntax_ICase.toggled.connect(self.timer)
        self.syntax_INonA = QCheckBox(self.tr("Only &Alphanumeric"))
        self.syntax_INonA.setStatusTip(
            self.tr("Search ignores non-alphanumeric characters"))
        self.syntax_INonA.toggled.connect(self.timer)

        grid.addWidget(self.syntax_strng, 0, 3)
        grid.addWidget(self.syntax_words, 1, 3)
        grid.addWidget(self.syntax_RegEx, 2, 3)
        grid.addWidget(self.syntax_ICase, 3, 3)
        grid.addWidget(self.syntax_INonA, 4, 3)

        # Create the display area for the search statistics.
        self.results = QLabel()
        self.results.setStyleSheet("background-color: lightgray;")
        grid.addWidget(self.results, 1, 0, -1, 2)

        # Now we create the viewer for the Book model. It responds to double-clicks and
        # mouse entering/leaving an item. See itemCalled() and itemEntered() respectively.
        self.view = BookView(self)
        self.view.doubleClicked.connect(self.itemCalled)
        self.view.entered.connect(self.itemEntered)
        grid.addWidget(self.view, 5, 0, -1, -1)

    def db(self):
        """Return the Book Database, loading and caching it the first time."""
        if self._book_db is None:
            self.setStatusTip(self.tr("Loading Library Database..."))
            self._book_db = Database(LIBRARY, COLLECTIONS)
        return self._book_db

    def display(self, reload=False):
        """Display the (filtered) model."""

        # Collect and process the filter parameters.
        if self.syntax_strng.isChecked():
            syntax = BookFilterProxyModel.SyntaxSubstring
        if self.syntax_words.isChecked():
            syntax = BookFilterProxyModel.SyntaxWords
        if self.syntax_RegEx.isChecked():
            syntax = BookFilterProxyModel.SyntaxRE
        ignore_case = self.syntax_ICase.isChecked()
        only_alnum = self.syntax_INonA.isChecked()

        # Obtain and normalize the search text.
        search_text = self.find.text().strip()
        search_words = search_text.split()
        if syntax == BookFilterProxyModel.SyntaxSubstring:
            search_text = ' '.join(search_words)

        # If we're not being asked to reload and nothing has changed, do nothing.
        if not reload and \
                search_text == self.currSearch and \
                syntax == self.currSyntax and \
                ignore_case == self.currCase and \
                only_alnum == self.currAlNum and \
                self.selection == self.currSelection:
            return

        # If we got this far, we must display the (filtered) model.
        #
        # Put up a Wait Cursor.
        QApplication.setOverrideCursor(Qt.WaitCursor)

        # Remember the filtering parameters so we can detect changes at a later time.
        self.currSearch = search_text
        self.currSyntax = syntax
        self.currCase = ignore_case
        self.currAlNum = only_alnum
        self.currSelection = self.selection.copy()

        # Load the model if we don't have one yet or we've been asked to reload.
        if self.model is None or reload:
            self.loadModel()

        # Setup the filtering and apply it to the proxy model.
        # @TODO
        self.setStatusTip(self.tr("Searching database..."))
        re = QRegExp(search_text,
                     Qt.CaseInsensitive if ignore_case else
                     Qt.CaseSensitive,
                     QRegExp.RegExp if syntax == BookFilterProxyModel.SyntaxRE else
                     QRegExp.FixedString)
        self.proxyModel.setFilterRegExp(re)

        # We're done!
        #
        # Just a few final cosmetic/convenience details, like displaying the filtering
        # statistics...
        modelCount = self.model.rowCount()
        proxyCount = self.proxyModel.rowCount()
        lines = []

        line = [self.tr("{:n} titles").format(modelCount)]
        if modelCount != proxyCount:
            line.append(self.tr("{:n} matched").format(proxyCount))
        lines.append(line)

        # Convenience function
        def fmt_summary(item, cnt):
            return "{}: {:n} ({:.2%})".format(self.tr(item), cnt, cnt / modelCount)

        line = []
        self.db().summary()
        for item in ("Books", "Papers", "Slides"):
            cnt = self.db().sumcount[item]
            line.append(fmt_summary(self.tr(item), cnt))
        lines.append(line)

        line = []
        total = 0
        for item in ("Documents", "PROC"):
            cnt = self.db().sumcount[item]
            total += cnt
            line.append(fmt_summary(self.tr(item), cnt))
        line.append(fmt_summary(self.tr("Total"), total))
        lines.append(line)

        self.results.setText("\n".join(", ".join(line) for line in lines))

        # ... and making sure the tooltip mechanism has been appropriately reset (since
        # the view has changed due to the proxy filtering having been recomputed).
        self.lastItem = None
        self.setToolTip("")

        # Now we can restore the cursor and status.
        self.setStatusTip("Ready")
        QApplication.restoreOverrideCursor()

    def loadModel(self):
        """Load a new Book model."""

        self.setStatusTip(self.tr("Loading database..."))

        # Disassociate any pre-existing model from the proxy.
        self.proxyModel.setSourceModel(None)

        # If we don't have an instantiated model yet we create an empty one. Otherwise we
        # clear the one we have (less garbage collection...).
        if self.model is None:
            self.model = QStandardItemModel(0, 3, self)
        else:
            self.model.clear()

        # Setup the model's header labels. The Model Viewer will detect clicks on these
        # labels and sort the (proxy) model for us.
        self.model.setHorizontalHeaderLabels([self.tr("Type"),
                                              self.tr("Where"),
                                              self.tr("Name")])

        # Populate the model from the Book Database.
        for book in self.db().books():
            self.model.appendRow([QStandardItem(book[0]),
                                  QStandardItem(book[1]),
                                  QStandardItem(book[2])])

        # Associate the model with the proxy. Note that at this point the proxy will apply
        # any filtering we have programmed into it.
        self.proxyModel.setSourceModel(self.model)

        # Finally, we reset the view so it displays the newly loaded model (via the
        # proxy).
        self.view.resetView()

        self.setStatusTip(self.tr("Ready"))

    @pyqtSlot(QModelIndex)
    def itemEntered(self, item: QModelIndex):
        """Event triggered when a view's item has been entered with the mouse.

           A tooltip displaying the item's file size and modification time is associated
           with the view widget.
        """

        # Don't waste time recomputing the tooltip if the mouse has re-entered the last
        # visited item---the mouse could have left the view widget altogether, and then
        # re-entered it within the same item's area.
        if item != self.lastItem:
            self.lastItem = item

            # Get the file's stat() data. Do nothing if it cannot be obtained.
            try:
                st = os.stat(item_file(item))
            except:
                return

            # Format the size and modification time using the app's locale, and set it as
            # the widget's tooltip.
            # applocale = KGlobal.locale()
            # size = applocale.formatByteSize(st.st_size, 1)
            # time = applocale.formatDateTime(datetime.fromtimestamp(st.st_mtime))
            size = HumanBytes(st.st_size)
            time = QDateTime(datetime.fromtimestamp(st.st_mtime)).toString()
            self.setToolTip("<br/>".join((size, time)))

    @pyqtSlot(QModelIndex)
    def itemCalled(self, item: QModelIndex):
        """Event triggered when a view's item has been double-clicked.

           We spawn xdg-open to try and display the file.
        """
        subprocess.Popen(["xdg-open", item_file(item)])

    def reload(self):
        """Event triggered when the "reload" action in the main window is activated.

           The Book Database is caused to be rebuilt. We do that by removing it and then
           forcing the model to be re-displayed.
        """
        if self._book_db is not None:
            self._book_db.remove()
            self._book_db = None
        self.display(reload=True)

    def clear(self):
        """Event triggered when the "clear" action in the main window is activated.

           The search parameters are cleared to their initial state and the redisplay
           timer is started as the parameters might have changed.
        """
        self.find.clear()
        self.find.setFocus()
        self.syntax_strng.setChecked(True)
        self.ignCase.setChecked(True)
        self.onlyAlNum.setChecked(False)
        self.timer()

    def select(self, name, checked):
        """Event triggered when the item-type selecting actions in the main window are
           activated.

           The selection state is updated and the redisplay timer is started.
        """
        self.selection[name] = checked
        self.timer()

    @pyqtSlot()
    def timer(self):
        """Start/restart the redisplay timer."""

        if self.timerId is not None:
            self.killTimer(self.timerId)
        self.timerId = self.startTimer(1000)

    def timerEvent(self, event):
        """The redisplay timer has been triggered, redisplay the model."""
        self.killTimer(event.timerId())
        self.timerId = None
        self.display()


class MainWindow(QMainWindow):
    """The application's main window."""

    def __init__(self, appData: ApplicationData, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.appData = appData
        self.settings = QSettings(self.appData.company, self.appData.application)

        # Restore application window to last saved state.
        self.setWindowTitle(self.tr("Library Administrator"))
        self.restoreGeometry(self.settings.value('geometry'))
        self.restoreState(self.settings.value('windowState'))

        # Instantiate the search widget as the window's "central widget"---that is,
        # everything left after the menu bar, tool bar and status bar is allocated.
        self.search = BookSearchWidget(self)
        self.setCentralWidget(self.search)
        self.setupMenu()
        self.statusBar()

    def setupMenu(self):
        """ Create the menu bar. """

        # Make an action with the indicated parameters.
        def mkaction(item: str,
                     help: str,
                     icon: str = None,
                     shortcut: str = None,
                     slot: object = None) -> QAction:
            if icon is not None:
                action = QAction(QIcon.fromTheme(icon), self.tr(item), self)
            else:
                action = QAction(self.tr(item), self)
            action.setStatusTip(self.tr(help))
            if shortcut is not None:
                action.setShortcut(self.tr(shortcut))
            if slot is not None:
                action.triggered.connect(slot)
            return action

        # File menu.
        file = self.menuBar().addMenu(self.tr('&File'))
        file.addAction(mkaction('E&xit',
                                'Exit Library Administrator',
                                'application-exit',
                                'Ctrl+Q',
                                qApp.quit))

        # Search menu.
        search = self.menuBar().addMenu(self.tr('&Search'))
        search.addAction(mkaction('Clear and &Reset',
                                  'Clear and reset search',
                                  'edit-clear',
                                  'Ctrl+U',
                                  self.search.clear))
        search.addSeparator()
        search.addAction(mkaction('&Undo',
                                  'Undo changes to search',
                                  'edit-undo',
                                  'Ctrl+Z',
                                  self.search.find.undo))
        search.addAction(mkaction('Cu&t',
                                  'Cut selection to clipboard',
                                  'edit-cut',
                                  'Ctrl+X',
                                  self.search.find.cut))
        search.addAction(mkaction('&Copy',
                                  'Copy search string to clipboard',
                                  'edit-copy',
                                  'Ctrl+C',
                                  self.search.find.copy))
        search.addAction(mkaction('&Paste',
                                  'Paste clipboard',
                                  'edit-paste',
                                  'Ctrl+V',
                                  self.search.find.paste))
        search.addAction(mkaction('Select All',
                                  'Select the whole search string',
                                  'edit-select-all',
                                  'Ctrl+A',
                                  self.search.find.selectAll))
        search.addSeparator()
        search.addAction(mkaction('&Reload',
                                  'Reload library database',
                                  'view-refresh',
                                  'F5',
                                  self.search.reload))

        # Help menu.
        help = self.menuBar().addMenu(self.tr('&Help'))
        help.addAction(mkaction('&Help',
                                'Program Documentation',
                                'help-contents',
                                'F1'))
        help.addSeparator()
        help.addAction(mkaction('&About',
                                'Show information about Library Administrator',
                                'help-about'))

    #       # Instantiate the Book Database item-type subsetting actions. Each
    #       # action is added to the app's action collection and invokes select()
    #       # in the search widget when triggered.
    #       #
    #       # These actions can be toggled between their checked and unchecked
    #       # states, and this information is passed to the select() method via a
    #       # "capturing proxy".
    #       self.setupCheckableAction("books", None, "&Books", "Select books",
    #                                 Qt.CTRL + Qt.Key_B, search.select)
    #
    #       self.setupCheckableAction("papers", None, "&Papers", "Select papers",
    #                                 Qt.CTRL + Qt.Key_P, search.select)
    #
    #       self.setupCheckableAction("slides", None, "&Slides", "Select slides",
    #                                 Qt.CTRL + Qt.Key_S, search.select)
    #
    #       self.setupCheckableAction("documents", None, "&Documents", "Select
    #       documents",
    #                                 Qt.CTRL + Qt.Key_D, search.select)
    #
    #       self.setupCheckableAction("proc", None, "P&ROC", "Select PROC",
    #                                 Qt.CTRL + Qt.Key_R, search.select)
    #

    #   def setupCheckableAction(self, name, icon, label, helpmsg, shortcut, method):
    #       """Setup an action as per _mkaction(), flags it as checkable, and
    #          sets it as checked.
    #       """
    #       action = self.setupAction(name, icon, label, helpmsg, shortcut)
    #       action.setCheckable(True)
    #       action.setChecked(True)
    #
    #       def proxy():
    #           return method(name, action.isChecked())
    #
    #       action.triggered.connect(proxy)
    #       proxy()

    #   def select(self):
    #       """Event triggered by the various checkable actions.
    #
    #          Create a dictionary of the action names and their check state to
    #          pass to the search widget.
    #       """
    #       self.centralWidget().select({name: action.isChecked()
    #                                    for name, action in self.checkable.items()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Event triggered when window closes.

           Ensure saving app state before exiting.
        """
        settings = QSettings(self.appData.company, self.appData.application)
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        super().closeEvent(event)


def main():
    locale.setlocale(locale.LC_ALL, '')

    appdir = os.path.split(sys.argv[0])[0]

    appData = ApplicationData(
            name="Leopoldo Mauro",
            mail="lmauro@usb.ve",
            company="Universidad Simón Bolívar",
            application="LibraryAdmin",
            appdir=appdir,
            icon=os.path.join(appdir, "resources/book.png"),
            home="https://github.com/leomauro/LibraryAdmin"
    )

    #    aboutData = KAboutData("kbooksearch",
    #                           "",
    #                           ki18n("Book Search"),
    #                           "1.00",
    #                           ki18n("Search book database"),
    #                           KAboutData.License_GPL_V3,
    #                           ki18n("(C) 2010-2019 " + name),
    #                           ki18n(""),
    #                           home + "/kbooksearch",
    #                           mail)
    #    aboutData.addAuthor(ki18n(name), ki18n("Author"), mail, home)
    #    aboutData.setProgramIconName(APP_ICON)
    #
    #    KCmdLineArgs.init(sys.argv, aboutData)

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(appData.icon))

    win = MainWindow(appData)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
