from collections import namedtuple


class FileItem(namedtuple('FileItem', 'dir, file, type, size, mtime, entry')):
    _title = None
    def title(self):
        if self._title is None:
            self._title = self.file.replace("%2f", "/")
        return self._title

    def path(self):
        return self.entry.path
