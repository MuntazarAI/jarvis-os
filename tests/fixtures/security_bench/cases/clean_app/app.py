import sqlite3

import yaml


def load_settings(path):
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def find_user(conn, user_id):
    return conn.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)).fetchall()


def connect(path):
    return sqlite3.connect(path)


HOST = "127.0.0.1"
DEBUG = False
VERIFY_TLS = True
