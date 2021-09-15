#!/usr/bin/env python3

import os
import sys
import mimetypes
from collections import Counter

from fileitem import FileItem


class BookRepo:
    """The book repository."""

    def __init__(self, db_dir, book_dirs):
        self.db_dir = db_dir
        self.book_dirs = book_dirs
        self.count = None
        self.sumcount = None
        self.total = None
        mimetypes.init()

    def clear_summary(self):
        """Invalidate summary."""

        self.count = None
        self.sumcount = None
        self.total = None

    def summary(self):
        """Ensure we have a valid summary."""

        if self.count is None:
            return False
        if self.total is None or self.sumcount is None:
            self.total = sum(self.count.values())
            self.sumcount = Counter()
            for directory, cnt in self.count.items():
                self.sumcount += Counter({directory.split('/')[0]: cnt})
        return True

    def find_books(self):
        """Iterator that yields every book in each book directory
           as a FileItem object.
        """

        # Iterate over the base-directory list, recursively yielding from its
        # contents.
        self.count = Counter()
        for directory in self.book_dirs:
            yield from self._find_in(directory)

    def _find_in(self, directory):
        """Iterator that yields every book in the given directory, recursing
           over subdirectories.
        """

        path = os.path.join(self.db_dir, directory)
        print(f"    Scanning {directory}")
        if directory not in self.count:
            self.count[directory] = 0

        try:
            # Scan all entries in directory. Files are yielded as FileItems,
            # directories are added to a list to be scanned later.
            subdirs = []
            for dirent in os.scandir(path):
                if dirent.is_dir():
                    subdirs.append(dirent.name)
                    continue
                if not dirent.is_file():
                    continue

                # Determine the file type and encoding, and using that split
                # the filename into a file part and an "extension".
                filename = dirent.name
                filetype = ""
                mimetype, encoding = mimetypes.guess_type(filename, False)
                if mimetype:
                    extensions = mimetypes.guess_all_extensions(mimetype, False)
                    if encoding == "gzip":
                        extensions = [ext + ".gz" for ext in extensions]
                    for ext in extensions:
                        if filename.endswith(ext):
                            filename = filename[:-len(ext)]
                            filetype = ext[1:]
                            break

                self.count[directory] += 1
                yield FileItem(dir=directory,
                               file=filename,
                               type=filetype,
                               size=dirent.stat().st_size,
                               mtime=dirent.stat().st_mtime,
                               entry=dirent)

            # All regular files have been processed.
            #
            # Now, recursively yield the contents of the (sorted)
            # subdirectories.
            for subdir in sorted(subdirs):
                yield from self._find_in(os.path.join(directory, subdir))

        # There's something weird in the neighborhood...
        except OSError as ex:
            print(f"{ex.filename}: {ex.strerror}")


def main():
    counting = False
    if len(sys.argv) == 2:
        if sys.argv[1] == '-c':
            counting = True
        else:
            print("Usage:", sys.argv[0], "[ -c ]")
            sys.exit(1)

    library = os.path.expanduser("~/Library")
    book_repo = BookRepo(library,
                         ("Documents", "PROC", "Books", "Papers", "Slides"))

    for book in book_repo.find_books():
        if not counting:
            print(book)

    if counting:
        def display(caption, counts, total):
            print()
            print(f"{caption}:")
            for item in sorted(counts):
                ctr = counts[item]
                percent = ctr / total * 100
                print(f"  {item:16s} {ctr:6d} {percent:6.2f}%")
            print(f"  {'Total':16s} {total:6d}")

        assert book_repo.summary()
        display("Detailed", book_repo.count, book_repo.total)
        display("Summary", book_repo.sumcount, book_repo.total)


if __name__ == '__main__':
    main()
