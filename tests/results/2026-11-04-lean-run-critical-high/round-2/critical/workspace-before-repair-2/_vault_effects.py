"""Connection-local verification of the transfer's logical row delta.

OLD/NEW values stay in SQLite. In particular, this does not query or fetch
unrelated stored accounts, even when a trigger changes another tenant's rows.
"""

import sqlite3
import uuid


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _tokens(sql):
    """Yield token spans, retaining SQLite's identifier/whitespace boundaries.

    This only locates possible insertion points; SQLite validates the resulting
    trigger grammar. Quoted tokens and comments must never be rewritten.
    """
    i = 0
    while i < len(sql):
        start = i
        char = sql[i]
        if char in " \t\n\r\f\ufeff":
            i += 1
            continue
        if sql.startswith("--", i):
            end = sql.find("\n", i + 2)
            i = len(sql) if end < 0 else end + 1
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = len(sql) if end < 0 else end + 2
            continue
        if char in "'\"`[":
            delimiter = "]" if char == "[" else char
            i += 1
            while i < len(sql):
                if sql[i] == delimiter:
                    i += 1
                    if char != "[" and i < len(sql) and sql[i] == delimiter:
                        i += 1
                        continue
                    break
                i += 1
            yield start, i, "quoted"
            continue
        if char.isascii() and (char.isalnum() or char == "_") or ord(char) >= 128:
            i += 1
            while i < len(sql):
                char = sql[i]
                if not (char.isascii() and (char.isalnum() or char in "_$") or ord(char) >= 128):
                    break
                i += 1
            word = sql[start:i]
            yield start, i, word.upper() if word.isascii() else "identifier"
            continue
        i += 1
        yield start, i, char


class Effects:
    def __init__(self, con):
        self.con = con
        self.prefix = "vault_" + uuid.uuid4().hex
        self.log = _quote(self.prefix + "_delta")
        self.internal_changes = 0
        # Context is (active original triggers, explicit DELETE statement).
        # IGNORE restores the caller here, even when SQLite skips an epilogue.
        self.context = ((), False)
        self.callers = {}
        self.recursive = con.execute("PRAGMA recursive_triggers").fetchone()[0]
        self.originals = con.execute(
            "SELECT name, sql FROM sqlite_schema WHERE type='trigger' ORDER BY rowid"
        ).fetchall()
        for name, argc, function in (
            ("allow", 2, self._allow),
            ("enter", 1, self._enter),
            ("statement", 2, self._statement),
            ("leave", 1, self._leave),
            ("ignore", 1, self._leave),
            ("observed", 1, self._observed),
        ):
            con.create_function(self.prefix + "_" + name, argc, function)
        # Observer INSERTs must not change what existing triggers see through
        # total_changes(). SQLite itself saves changes()/last_insert_rowid()
        # across trigger calls; our control statements are SELECTs only.
        con.create_function("total_changes", 0, lambda: con.total_changes - self.internal_changes)
        con.execute("PRAGMA recursive_triggers=ON")
        if not self.recursive:
            replacements = [self._instrument(sql, i) for i, (_, sql) in enumerate(self.originals)]
            for name, _ in self.originals:
                con.execute("DROP TRIGGER " + _quote(name))
            for sql in replacements:
                con.execute(sql)

        fields = ", ".join(f"t{i} TEXT, v{i}" for i in range(5))
        con.execute(f"CREATE TEMP TABLE {self.log} (tab INTEGER, sign INTEGER, {fields})")
        self.tables = (
            ("accounts", ("tenant", "name", "balance")),
            ("transfers", ("tenant", "key", "source", "target", "amount")),
            ("audit", ("tenant", "key", "source", "target", "amount")),
        )
        for tab, (table, columns) in enumerate(self.tables):
            for action, images in (
                ("INSERT", ((1, "NEW"),)),
                ("DELETE", ((-1, "OLD"),)),
                ("UPDATE", ((-1, "OLD"), (1, "NEW"))),
            ):
                rows = []
                for sign, source in images:
                    values = [f"{source}.{_quote(column)}" for column in columns]
                    values += ["NULL"] * (5 - len(values))
                    rows.append(f"({tab}, {sign}, {self._encoded(values)})")
                con.execute(
                    f"CREATE TEMP TRIGGER {_quote(self.prefix + table + action)} "
                    f"AFTER {action} ON main.{_quote(table)} BEGIN "
                    f"INSERT INTO {self.log} VALUES {', '.join(rows)}; "
                    f"SELECT {self._function('observed')}({len(images)}); END"
                )

    def _function(self, name):
        return _quote(self.prefix + "_" + name)

    @staticmethod
    def _encoded(values):
        # Keep type tags: integer 1, REAL 1.0, TEXT '1' and BLOB X'31'
        # are different stored values. Encode TEXT inside SQLite in the main
        # database's encoding, including NULs and undecodable legacy text.
        return ", ".join(
            f"typeof({value}), CASE WHEN typeof({value})='text' "
            f"THEN CAST({value} AS BLOB) ELSE {value} END" for value in values
        )

    def _allow(self, trigger, delete):
        active, explicit_delete = self.context
        return trigger not in active and (not delete or explicit_delete)

    def _enter(self, trigger):
        self.callers[trigger] = self.context
        self._statement(trigger, False)
        return 1

    def _statement(self, trigger, delete):
        self.context = (self.callers[trigger][0] + (trigger,), bool(delete))
        return 1

    def _leave(self, trigger):
        self.context = self.callers[trigger]
        return 1

    def _observed(self, count):
        self.internal_changes += count
        return 1

    def _instrument(self, sql, trigger):
        tokens = list(_tokens(sql))
        # The fixed CREATE TRIGGER prefix is enough to replace the name for
        # EXPLAIN. Body/WHEN boundaries are selected by the native SQL parser,
        # so identifiers such as begin/end/when do not act as delimiters.
        name_index = next(i for i, token in enumerate(tokens) if token[2] == "TRIGGER") + 1
        if [token[2] for token in tokens[name_index:name_index + 3]] == ["IF", "NOT", "EXISTS"]:
            name_index += 3
        name_start, name_end, _ = tokens[name_index]
        event_index = name_index + 1
        if tokens[event_index][2] == ".":
            name_end = tokens[event_index + 1][1]
            event_index += 2
        if tokens[event_index][2] in ("BEFORE", "AFTER"):
            event_index += 1
        elif tokens[event_index][2] == "INSTEAD":
            event_index += 2
        delete = int(tokens[event_index][2] == "DELETE")
        end = next(token[0] for token in reversed(tokens) if token[2] == "END")
        for begin_index in range(event_index + 1, len(tokens)):
            begin_start, begin_end, word = tokens[begin_index]
            if word != "BEGIN" or begin_start >= end:
                continue
            body_tokens = [token for token in tokens[begin_index + 1:] if token[0] < end]
            body = self._body(sql, begin_end, end, body_tokens, trigger)
            whens = [token for token in tokens[event_index + 1:begin_index] if token[2] == "WHEN"]
            for when in [*whens, None]:
                guard = f"WHEN {self._function('allow')}({trigger}, {delete})"
                if when is None:
                    header = sql[:begin_start] + " " + guard + " "
                else:
                    header = sql[:when[0]] + guard + " AND (" + sql[when[1]:begin_start] + ") "
                candidate = header + sql[begin_start:begin_end] + body + sql[end:]
                probe = candidate[:name_start] + _quote(self.prefix + "_probe") + candidate[name_end:]
                try:
                    self.con.execute("EXPLAIN " + probe)
                except sqlite3.Error:
                    continue
                return candidate
        raise sqlite3.DatabaseError("cannot observe storage effects")

    def _body(self, sql, start, end, tokens, trigger):
        parts = [f"\nSELECT {self._function('enter')}({trigger});\n"]
        statement_start = start
        statement_tokens = []
        for token in tokens:
            if token[2] != ";":
                statement_tokens.append(token)
                continue
            # DELETE is a distinct trigger command. SELECT, VALUES and WITH
            # SELECT bodies are copied verbatim, including compound SELECTs.
            delete = int(bool(statement_tokens) and statement_tokens[0][2] == "DELETE")
            parts.append(f"SELECT {self._function('statement')}({trigger}, {delete});\n")
            cursor = statement_start
            for i in range(len(statement_tokens) - 3):
                group = statement_tokens[i:i + 4]
                if [item[2] for item in group] == ["RAISE", "(", "IGNORE", ")"]:
                    parts.append(sql[cursor:group[0][0]])
                    parts.append(f"(CASE WHEN {self._function('ignore')}({trigger}) THEN RAISE(IGNORE) END)")
                    cursor = group[-1][1]
            parts.append(sql[cursor:token[1]])
            parts.append(f"\nSELECT {self._function('statement')}({trigger}, 0);\n")
            statement_start = token[1]
            statement_tokens = []
        parts.append(sql[statement_start:end])
        parts.append(f"\nSELECT {self._function('leave')}({trigger});\n")
        return "".join(parts)

    def verify(self, tenant, source, target, funds, target_funds, amount, key):
        # Subtract the intended logical delta. A zero multiset proves both the
        # required writes and preservation, allowing ignored attempts, no-ops,
        # delete/reinsert and rowid moves that leave logical rows unchanged.
        expected = (
            (0, 1, (tenant, source, funds)),
            (0, -1, (tenant, source, funds - amount)),
            (0, 1, (tenant, target, target_funds)),
            (0, -1, (tenant, target, target_funds + amount)),
            (1, -1, (tenant, key, source, target, amount)),
            (2, -1, (tenant, key, source, target, amount)),
        )
        for tab, sign, values in expected:
            values += (None,) * (5 - len(values))
            self.con.execute(
                f"INSERT INTO {self.log} SELECT ?, ?, {self._encoded([f'?{i + 3}' for i in range(5)])}",
                (tab, sign, *values),
            )
        fields = ", ".join(f"t{i}, v{i} COLLATE BINARY" for i in range(5))
        mismatch = self.con.execute(
            f"SELECT EXISTS(SELECT 1 FROM {self.log} GROUP BY tab, {fields} HAVING sum(sign) != 0)"
        ).fetchone()[0]
        if mismatch:
            raise sqlite3.IntegrityError("unexpected storage effects")
        if not self.recursive:
            for name, _ in self.originals:
                self.con.execute("DROP TRIGGER " + _quote(name))
            for _, sql in self.originals:
                self.con.execute(sql)
