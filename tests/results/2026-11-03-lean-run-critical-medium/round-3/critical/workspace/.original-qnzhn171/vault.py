import sqlite3
import time
def init_db(path):
    with sqlite3.connect(path) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS accounts (
          tenant TEXT, name TEXT, balance INTEGER,
          PRIMARY KEY(tenant,name));
        CREATE TABLE IF NOT EXISTS transfers (
          tenant TEXT, key TEXT, source TEXT, target TEXT, amount INTEGER,
          PRIMARY KEY(tenant,key));
        CREATE TABLE IF NOT EXISTS audit (
          tenant TEXT, key TEXT, source TEXT, target TEXT, amount INTEGER);
        ''')
def balance(path, tenant, account):
    with sqlite3.connect(path) as con:
        return con.execute('SELECT balance FROM accounts WHERE name=?', (account,)).fetchone()[0]
def transfer(path, tenant, source, target, amount, key):
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        old=con.execute('SELECT * FROM transfers WHERE key=?',(key,)).fetchone()
        if old:
            return dict(old)
        funds=con.execute('SELECT balance FROM accounts WHERE name=?',(source,)).fetchone()[0]
        if funds < amount:
            raise ValueError('insufficient funds')
        time.sleep(0.02)
        con.execute('UPDATE accounts SET balance=balance-? WHERE name=?',(amount,source))
        con.commit()
        con.execute('UPDATE accounts SET balance=balance+? WHERE name=?',(amount,target))
        con.commit()
        con.execute('INSERT INTO transfers VALUES (?,?,?,?,?)',(tenant,key,source,target,amount))
        con.execute('INSERT INTO audit VALUES (?,?,?,?,?)',(tenant,key,source,target,amount))
        return dict(tenant=tenant,key=key,source=source,target=target,amount=amount)
