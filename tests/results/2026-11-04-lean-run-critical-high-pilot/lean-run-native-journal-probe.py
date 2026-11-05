#!/usr/bin/env python3
"""Installed-engine checks for ordered TEMP AFTER observations.

This compares a candidate reconciliation rule with independent table snapshots
on small synthetic databases. It does not implement the application observer
or assert portability for SQLite's undefined same-row BEFORE trigger behavior.
"""
from collections import Counter
from contextlib import closing
import json
import sqlite3


SCHEMA = """
CREATE TABLE records(name TEXT UNIQUE, payload INTEGER UNIQUE);
INSERT INTO records(rowid,name,payload) VALUES(1,'a',10),(2,'b',20),(3,'c',30);
CREATE TEMP TABLE events(old_slot,old_name,old_value,new_slot,new_name,new_value);
CREATE TEMP TRIGGER track_i AFTER INSERT ON main.records BEGIN
  INSERT INTO events VALUES(NULL,NULL,NULL,NEW.rowid,NEW.name,NEW.payload);
END;
CREATE TEMP TRIGGER track_u AFTER UPDATE ON main.records BEGIN
  INSERT INTO events VALUES(OLD.rowid,OLD.name,OLD.payload,NEW.rowid,NEW.name,NEW.payload);
END;
CREATE TEMP TRIGGER track_d AFTER DELETE ON main.records BEGIN
  INSERT INTO events VALUES(OLD.rowid,OLD.name,OLD.payload,NULL,NULL,NULL);
END;
"""

BEFORE = """
PRAGMA recursive_triggers=OFF;
CREATE TABLE audit(tag);
CREATE TRIGGER early BEFORE UPDATE ON records
WHEN OLD.name='a' AND OLD.payload=11 AND NEW.payload=10 BEGIN
  UPDATE records SET payload=10 WHERE name=OLD.name;
END;
CREATE TRIGGER touch AFTER INSERT ON audit BEGIN
  UPDATE records SET payload=11 WHERE name='a';
  UPDATE records SET payload=10 WHERE name='a';
  {extra}
END;
INSERT INTO audit VALUES(1);
"""

AFTER = """
PRAGMA recursive_triggers=ON;
CREATE TRIGGER nested AFTER UPDATE ON records WHEN NEW.payload=11 BEGIN
  UPDATE records SET rowid=4,payload=12 WHERE rowid=NEW.rowid;
END;
UPDATE records SET payload=11 WHERE rowid=1;
"""

SCENARIOS = {
    'nested_before_restore': BEFORE.format(extra=''),
    'nested_before_corruption': BEFORE.format(extra="UPDATE records SET payload=11 WHERE name='a';"),
    'nested_after_row_move': AFTER,
    'row_slot_swap': """
        UPDATE records SET rowid=4 WHERE rowid=1;
        UPDATE records SET rowid=1 WHERE rowid=2;
        UPDATE records SET rowid=2 WHERE rowid=4;
    """,
    'ignored_row_move': 'UPDATE OR IGNORE records SET rowid=1 WHERE rowid=2;',
    'replace_update_with_rowid_and_unique_victims': """
        PRAGMA recursive_triggers=ON;
        UPDATE OR REPLACE records SET rowid=1,payload=30 WHERE rowid=2;
    """,
    'replace_insert_with_rowid_and_unique_victims': """
        PRAGMA recursive_triggers=ON;
        INSERT OR REPLACE INTO records(rowid,name,payload) VALUES(1,'b',30);
    """,
    'delete_reinsert': """
        DELETE FROM records WHERE rowid=1;
        INSERT INTO records(rowid,name,payload) VALUES(1,'a',10);
    """,
}


def rows(con):
    return Counter(con.execute('SELECT name,payload FROM records'))


def nonzero(delta):
    return [[*key, count] for key, count in sorted(delta.items()) if count]


def exercise(case, sql):
    with closing(sqlite3.connect(':memory:')) as con:
        con.executescript(SCHEMA)
        before = rows(con)
        con.executescript(sql)
        native = rows(con)
        native.subtract(before)
        events = con.execute('SELECT * FROM events ORDER BY rowid').fetchall()

    first, last = {}, {}
    raw = Counter()
    for old_slot, old_name, old_value, new_slot, new_name, new_value in events:
        if old_slot is not None:
            old_image = (old_name, old_value)
            first.setdefault(old_slot, old_image)
            last[old_slot] = None
            raw[old_image] -= 1
        if new_slot is not None:
            new_image = (new_name, new_value)
            first.setdefault(new_slot, None)
            last[new_slot] = new_image
            raw[new_image] += 1
    journal = Counter(image for image in last.values() if image is not None)
    journal.subtract(image for image in first.values() if image is not None)
    return {
        'case': case, 'events': events, 'native_delta': nonzero(native),
        'raw_delta': nonzero(raw), 'journal_delta': nonzero(journal),
        'pass': nonzero(journal) == nonzero(native),
    }


def main():
    results = [exercise(case, sql) for case, sql in SCENARIOS.items()]
    failed = [item['case'] for item in results if not item['pass']]
    print(json.dumps({'sqlite_version': sqlite3.sqlite_version, 'failed_cases': len(failed),
                      'failed_case_names': failed, 'cases': results}, indent=2))
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
