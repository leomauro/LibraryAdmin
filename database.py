#!/usr/bin/env python3

import os
import sys
from collections import Counter
from sqlite3 import dbapi2 as sqlite

from bookrepo import BookRepo


class Database(BookRepo):
    """The book database."""

    def __init__(self, db_dir, book_dirs):
        super().__init__(db_dir, book_dirs)
        self.db_file = os.path.join(self.db_dir, "book-list.sqlite")
        self.con = None

    def open(self):
        """Open the SQLite database, if not already open."""

        if self.con is None:
            self.con = sqlite.connect(self.db_file)

    def close(self):
        """Close the SQLite database, if not already closed."""

        try:
            self.con.close()
        except:
            pass
        self.con = None

    def remove(self):
        """Remove the SQLite database file."""

        self.close()
        self.clear_summary()
        try:
            os.remove(self.db_file)
        except:
            pass

    def create(self):
        """Create and populate the SQLite database."""

        print(f"Creating database {self.db_file}")
        self.open()
        cur = self.con.cursor()
        cur.execute(
                """
                create table books (
                    type    varchar(8),
                    dir     varchar(16),
                    title   varchar(256),
                    fsize   int,
                    mtime   int,
                    hash    blob
                )
                """)

        print("  Populating...")
        cur.executemany(
                "insert into books (type, dir, title, fsize, mtime) values (?,?,?,?,?)",
                self.find_books())

        print("  Indexing...")
        for index in ("title", "dir", "type"):
            print(f"    {index}")
            cur.execute(f"create index {index}s on books ({index} asc)")

        print("  Commiting...")
        self.con.commit()
        cur.close()
        self.close()

        print("Done")

    def find_books(self):
        """Iterator that yields every book in each book directory
           as a (type, dir, title, fsize, mtime) tuple.
        """

        for item in super().find_books():
            yield (item.type, item.dir, item.title(), item.size, item.mtime)

    def books(self):
        """
            Iterator that yields all books in the database.
            The database is created and populated if it doesn't exist.
        """

        if not os.path.exists(self.db_file):
            self.create()

        self.open()
        cur = self.con.cursor()
        cur.execute("select type, dir, title from books order by title")
        yield from cur
        cur.close()

    def summary(self):
        """Ensure we have a valid summary."""

        if not super().summary():
            self.count = Counter()
            for item in self.books():
                self.count[item[1]] += 1
        return super().summary()


def main():
    counting = False
    if len(sys.argv) == 2:
        if sys.argv[1] == '-c':
            counting = True
        else:
            print("Usage:", sys.argv[0], "[ -c ]")
            sys.exit(1)

    library = os.path.expanduser("~/Library")
    book_db = Database(library,
                       ("Documents", "PROC", "Books", "Papers", "Slides"))

    if not counting:
        book_db.remove()
        book_db.create()

    def display(caption, counts, total):
        print()
        print(f"{caption}:")
        for item in sorted(counts):
            ctr = counts[item]
            percent = ctr / total * 100
            print(f"  {item:16s} {ctr:6d} {percent:6.2f}%")
        print(f"  {'Total':16s} {total:6d}")

    assert book_db.summary()
    display("Detailed", book_db.count, book_db.total)
    display("Summary", book_db.sumcount, book_db.total)


if __name__ == '__main__':
    main()
