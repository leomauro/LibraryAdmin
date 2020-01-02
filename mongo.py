#!/usr/bin/env python3

import argparse
import hashlib
import os
import sys

from pymongo import MongoClient, ASCENDING

from bookrepo import BookRepo


def filehash(path):
    return hashlib.md5(open(path, 'rb').read()).hexdigest()


class Books(BookRepo):
    def __init__(self, db_dir, book_dirs):
        super().__init__(db_dir, book_dirs)
        self.client = MongoClient()
        self.db = self.client.books
        self.books = self.db.books

    def findbyhash(self, hash):
        self.books.create_index([('hash', ASCENDING)])
        yield from self.books.find({'hash': hash})

    def findbytitle(self, title):
        self.books.create_index([('title', ASCENDING)],
                                collation={'locale': 'en_US', 'strength': 2})
        yield from self.books.find({'title': title},
                                   collation={'locale': 'en_US', 'strength': 2})

    def checknew(self):
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
        print(f"      I {item.title()}", file=sys.stderr)
        try:
            hash = filehash(os.path.join(self.db_dir, item.path()))
        except OSError as e:
            print(f"** Error: {e}", file=sys.stderr)
            return
        self.books.insert_one({'title':     item.title(),
                               'type':      item.type,
                               'directory': item.dir,
                               'size':      item.size,
                               'mtime':     item.mtime,
                               'hash':      hash})

    def update(self, doc, item):
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
        print(f"Cleaning up{' and checking hashes' if check_hash else ''}...",
              file=sys.stderr)
        addnweline = False
        for i, doc in enumerate(list(self.books.find()), start=1):
            path = os.path.join(self.db_dir,
                                doc['directory'],
                                doc['title'].replace("/", "%2f") +
                                os.path.extsep + doc['type'])
            if not os.path.exists(path):
                print(f"      R {doc['directory']}/{doc['title']}", file=sys.stderr)
                self.remove(doc)
            elif check_hash:
                sys.stderr.write("%7d" % i)
                fhash = filehash(path)
                sys.stderr.write('\r')
                addnweline = True
                if doc['hash'] != fhash:
                    print(f"      H {doc['title']}", file=sys.stderr)
                    addnweline = False
        if addnweline:
            sys.stderr.write('\n')

    def dumpfilename(self, fd):
        titles = set()
        for doc in list(self.books.find()):
            titles.add(doc['title'])
        for title in titles:
            print(title, file=fd)
        return len(titles)

    def remove(self, doc):
        self.books.delete_one({'_id': doc['_id']})

    def book_count(self):
        return self.books.estimated_document_count()

    def docpath(self, doc):
        return os.path.join(self.db_dir,
                            doc['directory'],
                            doc['title'].replace("/", "%2f") +
                            os.path.extsep + doc['type'])


def main():
    parser = argparse.ArgumentParser(description="Access and manipulate Mongo Database")
    parser.add_argument("-n", "--new", action="store_true", help="scan for new books")
    parser.add_argument("-c", "--check", action="store_true", help="check hashes")
    parser.add_argument("-d", "--dump", type=str, help="dump Database titles to file")

    args = parser.parse_args()

    library = os.path.expanduser("~/Library")
    book_db = Books(library,
                    ("Documents", "PROC", "Books", "Papers", "Slides"))
    if args.new:
        book_db.checknew()
    book_db.cleanup(args.check)
    print(f"{book_db.book_count()} documents")
    if args.dump:
        print(f"Dumping Database titles to {args.dump}", file=sys.stderr)
        with open(args.dump, "wt") as fd:
            numtitles = book_db.dumpfilename(fd)
            print(f"Dumped {numtitles} titles")


if __name__ == '__main__':
    main()
