"""Tenant isolation by construction for one write transaction.

Inside the caller's IMMEDIATE transaction, every foreign accounts/transfers row
moves into connection-local TEMP storage. User triggers and views then run
unmodified against only the authenticated tenant's rows: invisible rows are
untouched and new foreign rows are rejected (row-level-security semantics).
No user SQL is rewritten, so equivalent SQL spellings cannot bypass the
boundary or break valid local SQL. Before commit, the visible effects are
compared with the expected transfer, foreign rows return with their original
rowids, and the exact trigger definitions are recreated. Foreign values stay
inside SQLite storage and never reach Python. Any failure rolls back all of it.
"""

import sqlite3
import uuid

# Audit rows copy receipt payloads, so they are isolated like receipts. Hiding
# them also keeps new rowids and counts independent of other tenants' history.
PROTECTED = {
    'accounts': ('tenant', 'name', 'balance'),
    'transfers': ('tenant', 'key', 'source', 'target', 'amount'),
    'audit': ('tenant', 'key', 'source', 'target', 'amount'),
}
OBSERVED = PROTECTED
WIDTH = 5


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _row(columns):
    """Typed column list padded to WIDTH, without applying affinity."""
    values = ['+' + _quote(c) for c in columns] + ['NULL'] * (WIDTH - len(columns))
    return ','.join(f'{v} AS v{i}' for i, v in enumerate(values))


class Effects:
    def __init__(self, con, tenant):
        self.con = con
        prefix = '_vault_' + uuid.uuid4().hex
        self.before = prefix + '_before'
        self.expected = prefix + '_expected'
        self.stash = {table: f'{prefix}_{table}' for table in PROTECTED}
        self.triggers = con.execute(
            "SELECT name,sql FROM main.sqlite_schema WHERE type='trigger' AND sql IS NOT NULL ORDER BY rowid"
        ).fetchall()
        # Moving rows must not fire user DELETE triggers.
        self._drop_triggers()
        for table, columns in PROTECTED.items():
            # CTAS copies typed values without affinity and leaves
            # last_insert_rowid(), changes() and total_changes() untouched.
            # The predicate is the exact complement of the application's
            # tenant lookup, including NULL and differently typed tenants.
            con.execute(
                f'CREATE TEMP TABLE {self.stash[table]} AS SELECT rowid AS rid,{_row(columns)} '
                f'FROM main.{table} WHERE (tenant=?) IS NOT 1', (tenant,))
            con.execute(f'DELETE FROM main.{table} WHERE rowid IN (SELECT rid FROM temp.{self.stash[table]})')
        snapshot = ' UNION ALL '.join(
            f"SELECT '{table}' AS t,{_row(columns)} FROM main.{table}" for table, columns in OBSERVED.items())
        con.execute(f'CREATE TEMP TABLE {self.before} AS {snapshot}')
        con.execute(f'CREATE TEMP TABLE {self.expected}(t,sign,{",".join("v" + str(i) for i in range(WIDTH))})')
        self._create_triggers()
        # Present native counters to user SQL: a fresh connection has made no
        # changes yet. The setup DELETEs depend on how many foreign rows exist.
        self.internal_changes = con.total_changes
        con.create_function('total_changes', 0, lambda: con.total_changes - self.internal_changes)
        con.execute(f'DELETE FROM temp.{self.expected} WHERE 0')  # changes() := 0

    def verify(self, tenant, source, target, before, amount, key):
        expected = [
            ('accounts', 1, tenant, source, before[source], None, None),
            ('accounts', 1, tenant, target, before[target], None, None),
            ('accounts', -1, tenant, source, before[source] - amount, None, None),
            ('accounts', -1, tenant, target, before[target] + amount, None, None),
            ('transfers', -1, tenant, key, source, target, amount),
            ('audit', -1, tenant, key, source, target, amount),
        ]
        self.con.executemany(f'INSERT INTO temp.{self.expected} VALUES (?,?,?,?,?,?,?)', expected)
        v = ','.join('v' + str(i) for i in range(WIDTH))
        group = ','.join(f'typeof(v{i}),v{i} COLLATE BINARY' for i in range(WIDTH))
        current = ' UNION ALL '.join(
            f"SELECT '{table}',1,{_row(columns)} FROM main.{table}" for table, columns in OBSERVED.items())
        # Visible rows now are the tenant's rows plus anything user SQL
        # created, including foreign-tenant rows, which are mismatches.
        mismatch = self.con.execute(
            f'WITH effects(t,sign,{v}) AS ('
            f'SELECT t,-1,{v} FROM temp.{self.before} UNION ALL {current} UNION ALL '
            f'SELECT * FROM temp.{self.expected}) '
            f'SELECT 1 FROM effects GROUP BY t,{group} HAVING sum(sign)!=0 LIMIT 1'
        ).fetchone()
        rows = self.con.execute(
            'SELECT name,balance,typeof(balance) FROM accounts WHERE tenant=? AND name IN (?,?)',
            (tenant, source, target),
        ).fetchall()
        final = {row[0]: (row[1], row[2]) for row in rows}
        if mismatch or final != {source: (before[source] - amount, 'integer'),
                                 target: (before[target] + amount, 'integer')}:
            raise sqlite3.IntegrityError('transaction effects rejected')

    def restore(self):
        self._drop_triggers()
        for table, columns in PROTECTED.items():
            stash = 'temp.' + self.stash[table]
            mapping = stash + '_moves'
            # A row created or moved by this transaction may occupy a hidden
            # row's slot. Relocate it above every existing slot, in SQL.
            self.con.execute(
                f'CREATE TEMP TABLE {mapping[5:]} AS SELECT rowid AS old,'
                f'(SELECT max(m) FROM (SELECT max(rowid) AS m FROM main.{table} '
                f'UNION ALL SELECT max(rid) FROM {stash})) + row_number() OVER (ORDER BY rowid) AS new '
                f'FROM main.{table} WHERE rowid IN (SELECT rid FROM {stash})')
            self.con.execute(
                f'UPDATE main.{table} SET rowid=(SELECT new FROM {mapping} WHERE old=main.{table}.rowid) '
                f'WHERE rowid IN (SELECT old FROM {mapping})')
            names = ','.join(_quote(c) for c in columns)
            values = ','.join(f'v{i}' for i in range(len(columns)))
            self.con.execute(f'INSERT INTO main.{table}(rowid,{names}) SELECT rid,{values} FROM {stash} ORDER BY rid')
            self.con.execute(f'DROP TABLE {mapping}')
            self.con.execute(f'DROP TABLE {stash}')
        self.con.execute(f'DROP TABLE temp.{self.before}')
        self.con.execute(f'DROP TABLE temp.{self.expected}')
        self._create_triggers()

    def _drop_triggers(self):
        for name, _ in self.triggers:
            self.con.execute(f'DROP TRIGGER main.{_quote(name)}')

    def _create_triggers(self):
        for _, sql in self.triggers:
            self.con.execute(sql)
