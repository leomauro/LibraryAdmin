#!/usr/bin/env python3

import locale
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt

import fmt
from database import Database


@dataclass
class ApplicationData:
    name: str
    mail: str
    company: str
    application: str
    icon: str
    home: str


LIBRARY = os.path.expanduser("~/Library")
COLLECTIONS = ("Documents", "PROC", "Books", "Papers", "Slides")


def item_file(item) -> str:
    model = item.model()
    t = model.index(item.row(), 0).data()
    w = model.index(item.row(), 1).data()
    n = model.index(item.row(), 2).data().replace("/", "%2f")
    return os.path.join(LIBRARY, w, os.path.extsep.join((n, t)))


class BookView(QtWidgets.QTreeView):
    def __init__(self, *args):
        super().__init__(*args)

        policy = self.sizePolicy()
        policy.setVerticalStretch(1)
        self.setSizePolicy(policy)
        self.setMinimumSize(QtCore.QSize(0, 235))

        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setAllColumnsShowFocus(True)
        self.setSelectionMode(BookView.ExtendedSelection)
        self.setSelectionBehavior(BookView.SelectRows)
        self.setEditTriggers(BookView.NoEditTriggers)
        self.setSortingEnabled(True)
        self.setMouseTracking(True)

        self.setDragDropMode(QtWidgets.QTreeView.DragDrop)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.dragStart = QtCore.QPoint()

    def resetView(self):
        self.sortByColumn(2, Qt.AscendingOrder)
        self.resizeColumnToContents(0)
        self.resizeColumnToContents(1)
        self.resizeColumnToContents(2)
        self.header().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.header().setStretchLastSection(False)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.dragStart = event.pos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            dist = (event.pos() - self.dragStart).manhattanLength()
            if dist >= QtWidgets.QApplication.startDragDistance():
                data = QtCore.QMimeData()
                data.setUrls([QtCore.QUrl.fromLocalFile(item_file(index))
                              for index in self.selectionModel().selectedRows()])
                drag = QtGui.QDrag(self)
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


class BookFilterProxyModel(QtCore.QSortFilterProxyModel):
    """The Book filter proxy that drives our Book view."""

    # The identifiers for the various available search "syntaxes".
    SyntaxSubstring = 0
    SyntaxWords = 1
    SyntaxRE = 2

    def __init__(self, *args):
        super().__init__(*args)

        # The sorting style.
        self.setDynamicSortFilter(True)
        self.setSortLocaleAware(True)
        self.setSortCaseSensitivity(Qt.CaseInsensitive)
        self.setFilterKeyColumn(2)


class BookSearchWidget(QtWidgets.QWidget):
    """The Book Search widget occupying our window's central widget."""

    def __init__(self, *args):
        super().__init__(*args)

        # We have no cached Book Database or Book model (yet) ...
        self._book_db = None
        self.model = None

        # ... and our item-type subset selection is empty, defaulting to False
        # for any selection.
        self.selection = defaultdict(bool)

        # Initialize our current search parameters to "undefined". In this way,
        # as soon as we input something or change the settings we will notice
        # and the filter proxy will be set up to produce the appropriate
        # filtered model.
        self.currSearch = None
        self.currCase = None
        self.currSyntax = None
        self.currSelection = None

        # We also keep track of the most recent model item to have its tooltip
        # displayed. We don't want to waste time recomputing the tooltip as the
        # mouse moves, unless the item changes due to the movement. See
        # itemEntered().
        self.lastItem = None

        #
        # Set up the UI by hand.
        # (GUI builders create such a convoluted and complex mess... Sigh!)
        #

        # Line editor widget for search input. It restarts the redisplay timer
        # whenever it changes.
        lblSearch = QtWidgets.QLabel(self.tr("&Search:"))
        self.search = QtWidgets.QLineEdit()
        self.search.textChanged.connect(self.timer)
        lblSearch.setBuddy(self.search)

        # Display area for the search results.
        self.results = QtWidgets.QLabel("")

        # Create a button group consisting of a set of exclusive ...
        self.syntaxGroup = QtWidgets.QButtonGroup()
        self.syntaxGroup.setExclusive(True)

        # ... radio buttons ...
        self.useSubstring = QtWidgets.QRadioButton(self.tr("&Substring"))
        self.useSubstring.setChecked(True)
        self.useSubstring.clicked.connect(self.timer)
        self.syntaxGroup.addButton(self.useSubstring,
                                   BookFilterProxyModel.SyntaxSubstring)

        self.useWords = QtWidgets.QRadioButton(self.tr("&Words"))
        self.useWords.clicked.connect(self.timer)
        self.useWords.setEnabled(False)  # For the time being
        self.syntaxGroup.addButton(self.useWords,
                                   BookFilterProxyModel.SyntaxWords)

        self.useRE = QtWidgets.QRadioButton(self.tr("&Regular expression"))
        self.useRE.clicked.connect(self.timer)
        self.syntaxGroup.addButton(self.useRE,
                                   BookFilterProxyModel.SyntaxRE)

        # ... and an independent checkbox. They all restart the display timer
        # whenever they change.
        self.ignCase = QtWidgets.QCheckBox(self.tr("&Ignore case"))
        self.ignCase.setChecked(True)
        self.ignCase.stateChanged.connect(self.timer)

        # Lay out the widgets in the group ...
        vbox = QtWidgets.QVBoxLayout()
        vbox.addWidget(self.useSubstring)
        vbox.addWidget(self.useWords)
        vbox.addWidget(self.useRE)
        vbox.addSpacing(8)
        vbox.addWidget(self.ignCase)
        vbox.addStretch(1)

        # ... and set the group's layout.
        # self.syntaxGroup.setLayout(vbox)

        # Now we create the the viewer for the Book model. It responds to
        # double-clicks and mouse entering/leaving an item. See itemCalled()
        # and itemEntered() respectively.
        self.view = BookView()
        self.view.doubleClicked.connect(self.itemCalled)
        self.view.entered.connect(self.itemEntered)

        # And finally, we create a simple grid-like layout to bind everything
        # together.
        grid = QtWidgets.QGridLayout(self)
        grid.addWidget(lblSearch, 0, 0)
        grid.addWidget(self.search, 0, 1)
        grid.addWidget(self.results, 1, 1)
        grid.addLayout(vbox, 0, 2, 2, 1)
        grid.addWidget(self.view, 2, 0, 1, -1)

        # Now we set up a proxy to filter and sort our model. This way we don't
        # have to modify the underlying Book model, which is usually loaded
        # just once, initially, but that can be forced to be reloaded if we
        # want to recompute the Book Database.
        self.proxyModel = BookFilterProxyModel()
        self.view.setModel(self.proxyModel)

        # We're done!
        #
        # We start a short timer to delay a little bit the initial database and
        # model loading. This is done in order to avoid "freezing" the UI when
        # we start the program and the model simultaneously tries to load and
        # display.
        self.timerId = self.startTimer(500)

    def db(self):
        """Return the Book Database, loading and caching it the first time."""
        if self._book_db is None:
            self._book_db = Database(LIBRARY, COLLECTIONS)
        return self._book_db

    def display(self, reload=False):
        """Display the (filtered) model."""

        #
        # First we collect and process the filter parameters.
        #

        # Determine the syntax of the filter to use and whether case is relevant.
        syntax = self.syntaxGroup.checkedId()
        #       if self.useSubstring.isChecked():
        #           syntax = BookFilterProxyModel.SyntaxSubstring
        #       if self.useWords.isChecked():
        #           syntax = BookFilterProxyModel.SyntaxWords
        #       if self.useRE.isChecked():
        #           syntax = BookFilterProxyModel.SyntaxRE
        ignore_case = self.ignCase.isChecked()

        # Obtain and normalize the filtering (search) text.
        search_text = self.search.text().strip()
        search_words = search_text.split()
        if syntax == BookFilterProxyModel.SyntaxSubstring:
            search_text = ' '.join(search_words)

        # If we're not being asked to reload and nothing has changed, do
        # nothing.
        if not reload and \
                syntax == self.currSyntax and \
                search_text == self.currSearch and \
                ignore_case == self.currCase and \
                self.selection == self.currSelection:
            return

        #
        # If we got this far, we must display the (filtered) model.
        #

        # Put up a Wait Cursor.
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)

        # Remember the filtering parameters so we can detect changes at a later
        # time.
        self.currSyntax = syntax
        self.currSearch = search_text
        self.currCase = ignore_case
        self.currSelection = self.selection.copy()

        # Load the model if we don't have one yet or we've been asked to
        # reload.
        if self.model is None or reload:
            self.loadModel()

        # Setup the filtering and apply it to the proxy model.
        # @TODO
        reg_exp = QtCore.QRegExp(search_text,
                                 Qt.CaseInsensitive
                                 if ignore_case else
                                 Qt.CaseSensitive,
                                 QtCore.QRegExp.RegExp
                                 if syntax == BookFilterProxyModel.SyntaxRE else
                                 QtCore.QRegExp.FixedString
                                 )
        self.proxyModel.setFilterRegExp(reg_exp)

        # We're done!
        #
        # Just a few final cosmetic/convenience details, like displaying the
        # filtering statistics ...
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

        # ... and making sure the tooltip mechanism has been appropriately
        # reset (since the view has changed due to the proxy filtering having
        # been recomputed).
        self.lastItem = None
        self.setToolTip("")

        # Now we can restore the cursor.
        QtWidgets.QApplication.restoreOverrideCursor()

    def loadModel(self):
        """Load a new Book model."""

        # Disassociate any pre-existing model from the proxy.
        self.proxyModel.setSourceModel(None)

        # If we don't have an instantiated model yet we create an empty one.
        # Otherwise we clear the one we have (less garbage collection...).
        if self.model is None:
            self.model = QtGui.QStandardItemModel(0, 3, self)
        else:
            self.model.clear()

        # Setup the model's header labels. The Model Viewer will detect clicks
        # on these labels and sort the (proxy) model for us.
        self.model.setHorizontalHeaderLabels([self.tr("Type"),
                                              self.tr("Where"),
                                              self.tr("Name")])

        # Populate the model from the Book Database.
        for book in self.db().books():
            self.model.appendRow([QtGui.QStandardItem(book[0]),
                                  QtGui.QStandardItem(book[1]),
                                  QtGui.QStandardItem(book[2])])

        # Associate the model with the proxy. Note that at this point the proxy
        # will apply any filtering we have programmed into it.
        self.proxyModel.setSourceModel(self.model)

        # Finally, we reset the view so it displays the newly loaded model (via
        # the proxy).
        self.view.resetView()

    def itemEntered(self, item):
        """Event triggered when a view's item has been entered with the mouse.

           A tooltip displaying the item's file size and modification time is
           associated with the view widget.
        """

        # Don't waste time recomputing the tooltip if the mouse has re-entered
        # the last visited item---the mouse could have left the view widget
        # altogether, and then re-entered it within the same item's area.
        if item != self.lastItem:
            self.lastItem = item

            # Get the file's stat() data. Do nothing if it cannot be obtained.
            try:
                st = os.stat(item_file(item))
            except:
                return

            # Format the size and modification time using the app's locale, and
            # set it as the widget's tooltip.
            # applocale = KGlobal.locale()
            # size = applocale.formatByteSize(st.st_size, 1)
            # time = applocale.formatDateTime(datetime.fromtimestamp(st.st_mtime))
            size = fmt.HumanBytes(st.st_size)
            time = QtCore.QDateTime(datetime.fromtimestamp(st.st_mtime)).toString()
            self.setToolTip("<br/>".join((size, time)))

    def itemCalled(self, item):
        """Event triggered when a view's item has been double-clicked.

           We spawn xdg-open to try and display the file.
        """
        subprocess.Popen(["xdg-open", item_file(item)])

    def reload(self):
        """Event triggered when the "reload" action in the main window is
           activated.

           The Book Database is caused to be rebuilt. We do that by removing it
           and then forcing the model to be re-displayed.
        """
        if self._book_db is not None:
            self._book_db.remove()
            self._book_db = None
        self.display(reload=True)

    def clear(self):
        """Event triggered when the "clear" action in the main window is
           activated.

           The search parameters are cleared to their initial state and the
           redisplay timer is started as the parameters might have changed.
        """
        self.search.clear()
        self.search.setFocus()
        self.useSubstring.setChecked(True)
        self.ignCase.setChecked(True)
        self.timer()

    def select(self, name, checked):
        """Event triggered when the item-type selecting actions in the main
           window are activated.

           The selection state is updated and the redisplay timer is started.
        """
        self.selection[name] = checked
        self.timer()

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


class MainWindow(QtWidgets.QMainWindow):
    """The application's main window."""

    def __init__(self, appData: ApplicationData, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.appData = appData

        self.setWindowTitle(self.tr("Library Administrator"))

        settings = QtCore.QSettings(self.appData.company, self.appData.application)
        self.restoreGeometry(settings.value("geometry"))
        self.restoreState(settings.value("windowState"))

        # Instantiate the search widget. It won't be part of the UI yet, since
        # we still don't have one set up, but it will be a children of this
        # main window. In this way we can connect events to its methods.
        search = BookSearchWidget(self)

        #       # Instantiate the "reload" action and add it to the app's action
        #       # collection. When triggered, it will invoke reload() in the search
        #       # widget.
        #       action = self.setupAction("reload", KIcon("view-refresh"),
        #                                 "&Reload", "Reload book database", "F5")
        #       action.triggered.connect(search.reload)
        #
        #       # Instantiate the "clear" action and add it to the app's action
        #       # collection. When triggered, it will invoke clear() in the search
        #       # widget.
        #       action = self.setupAction("clear", KIcon("edit-clean"),
        #                                 "&Clear", "Clear search", Qt.CTRL + Qt.Key_U)
        #       action.triggered.connect(search.clear)
        #
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
        #       # Add the "quit" standard action. When triggered it will invoke the
        #       # class' built-in close() method.
        #       # @TODO
        #       KStandardAction.quit(self, QtCore.SLOT("close()"),
        #       self.actionCollection())

        # The search widget is finally set as the window's "central widget"---that is,
        # everything that's left after the menu bar, tool bar and status bar is allocated.
        self.setCentralWidget(search)


#       # Tie everything together with the XML UI description, adjust widget
#       # metrics and spacings where appropriate to create a visualy pleasing
#       # display, and let it rip...
#       self.setupGUI()

#       # Enable the automatic saving of the app settings on exit and loading
#       # on activation. At the moment this only includes the main window
#       # geometry, but anything can be saved.
#       # @TODO
#       self.setAutoSaveSettings()

#   def setupAction(self, name, icon, label, helpmsg, shortcut):
#       """Setup an action and add it to the action collection.
#          Returns the action for further configuration.
#       """
#       if icon is not None:
#           action = KAction(icon, QCoreApplication.translate(self.__class__.__name__,
#                                                             label), self)
#       else:
#           action = KAction(QCoreApplication.translate(self.__class__.__name__,
#                                                       label), self)
#       action.setHelpText(QCoreApplication.translate(self.__class__.__name__,
#                                                     helpmsg))
#       action.setShortcut(shortcut)
#       self.actionCollection().addAction(name, action)
#       return action

#   def setupCheckableAction(self, name, icon, label, helpmsg, shortcut, method):
#       """Setup an action as per setupAction(), flags it as checkable, and
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

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Event triggered when window closes.

           Ensure saving app state before exiting.
        """
        settings = QtCore.QSettings(self.appData.company, self.appData.application)
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        super().closeEvent(event)


def main():
    locale.setlocale(locale.LC_ALL, '')

    appData = ApplicationData(
            name="Leopoldo Mauro",
            mail="lmauro@usb.ve",
            company="Universidad Simón Bolívar",
            application="LibraryAdmin",
            icon="/usr/share/icons/oxygen/base/64x64/apps/acroread.png",
            home=f"https://github.com/leomauro/LibraryAdmin"
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

    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(appData)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
