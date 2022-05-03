#!/usr/bin/env python3

import argparse
import hashlib
import os
import sys

from pymongo import MongoClient, ASCENDING
from bookrepo import BookRepo


def filehash(path):
    """ Return MD5 hash of given file. """

    return hashlib.md5(open(path, 'rb').read()).hexdigest()


class Books(BookRepo):
    """ Describes books in the repository. """

    def __init__(self, db_dir, book_dirs):
        super().__init__(db_dir, book_dirs)
        self.client = MongoClient()
        self.database = self.client.books
        self.books = self.database.books

    def createhashindex(self):
        """ Create (or re-create) hash index. """

        self.books.create_index([('hash', ASCENDING)])

    def createtitleindex(self):
        """ Create (or re-create) title index. """

        collation = {'locale': 'en_US', 'strength': 2}
        self.books.create_index([('title', ASCENDING)], collation)
        return collation

    def findbyhash(self, hashcode):
        """ Return books in database given a hash code. """

        self.createhashindex()
        yield from self.books.find({'hash': hashcode})

    def findbytitle(self, title):
        """ Return books in database given a title. """

        collation = self.createtitleindex()
        yield from self.books.find({'title': title}, collation)

    def checknew(self):
        """ Scan for new titles and update database. """

        print("Scanning for new documents...", file=sys.stderr)

        self.books.create_index([('title', ASCENDING), ('type', ASCENDING)])
        for item in self.find_books():
            docs = self.books.find({'title': item.title(), 'type': item.type})
            updated = False
            for doc in docs:
                if doc['directory'] == item.dir:
                    self.update(doc, item)
                    updated = True
            if not updated:
                self.insert(item)

    def insert(self, item):
        """ Insert a new item in database. """

        print(f"      I {item.title()}", file=sys.stderr)

        try:
            hashcode = filehash(os.path.join(self.db_dir, item.path()))
        except OSError as error:
            print(f"** Error: {error}", file=sys.stderr)
            return

        self.books.insert_one({'title':     item.title(),
                               'type':      item.type,
                               'directory': item.dir,
                               'size':      item.size,
                               'mtime':     item.mtime,
                               'hash':      hashcode})

    def update(self, doc, item):
        """ Update database with new item. """

        path = os.path.join(self.db_dir, item.path())
        try:
            stat = os.stat(path)
        except OSError:
            print(f"      R {item.dir}/{item.title()}", file=sys.stderr)
            self.remove(doc)
            return

        if doc['size'] != stat.st_size or doc['mtime'] != stat.st_mtime:
            print(f"      U {item.title()} ({stat.st_size - doc['size']:+d})",
                  file=sys.stderr)
            self.books.update_one({'_id': doc['_id']},
                                  {'$set': {'size':  stat.st_size,
                                            'mtime': stat.st_mtime,
                                            'hash':  filehash(path)}})
        elif doc.get('hash') is None:
            print(f"      H {item.title()}", file=sys.stderr)
            self.books.update_one({'_id': doc['_id']},
                                  {'$set': {'hash': filehash(path)}})

    def cleanup(self, check_hash: bool = False):
        """ Cleanup database.

            - Removes non-existing items, and updates hashes if needed.
            - Displays a running progress if hash checking is performed.
        """

        print(f"Cleaning up{' and checking hashes' if check_hash else ''}...",
              file=sys.stderr)

        addnewline = False
        for i, doc in enumerate(list(self.books.find()), start=1):
            path = os.path.join(self.db_dir,
                                doc['directory'],
                                doc['title'].replace("/", "%2f") +
                                os.path.extsep + doc['type'])
            if not os.path.exists(path):
                print(f"      R {doc['directory']}/{doc['title']}",
                      file=sys.stderr)
                self.remove(doc)
            elif check_hash:
                sys.stderr.write("%7d" % i)
                fhash = filehash(path)
                sys.stderr.write('\r')
                addnewline = True
                if doc['hash'] != fhash:
                    print(f"      H {doc['title']}", file=sys.stderr)
                    addnewline = False
        if addnewline:
            sys.stderr.write('\n')

    def dumptofile(self, desc):
        """ Dump out the book database. """

        count = 0
        for doc in self.books.find():
            print(f"{doc['directory']}\t{doc['title']}", file=desc)
            count += 1
        return count

    def remove(self, doc):
        """ Remove a document from database. """

        self.books.delete_one({'_id': doc['_id']})

    def book_count(self):
        """ Return estimated document count in database. """

        return self.books.estimated_document_count()

    def docpath(self, doc):
        """ Return file path of a given document. """

        return os.path.join(self.db_dir,
                            doc['directory'],
                            doc['title'].replace("/", "%2f") +
                            os.path.extsep + doc['type'])


def main():
    """ Parse arguments and run command-line functions. """

    parser = argparse.ArgumentParser(description="Manipulate Mongo Database")
    parser.add_argument("-n", "--new", action="store_true",
                        help="scan for new books")
    parser.add_argument("-c", "--check", action="store_true",
                        help="check hashes")
    parser.add_argument("-d", "--dump", type=str,
                        help="dump Database titles to file")

    args = parser.parse_args()

    library = os.path.expanduser("~/Library")
    book_db = Books(library,
                    ("Documents", "PROC", "Books", "Papers", "Slides"))
    if args.new:
        book_db.checknew()
    book_db.cleanup(args.check)
    if args.new:
        print(f"{book_db.book_count():,d} documents", file=sys.stderr)
    if args.dump:
        print(f"Dumping Database to {args.dump}", file=sys.stderr)
        with open(args.dump, "w") as desc:
            numtitles = book_db.dumptofile(desc)
            print(f"Dumped {numtitles} titles", file=sys.stderr)


if __name__ == '__main__':
    main()
