import sqlite3


def get_user(conn, username):
    cursor = conn.cursor()
    # Construye la query concatenando input del usuario directamente
    query = "SELECT * FROM users WHERE username = '" + username + "'"
    cursor.execute(query)
    return cursor.fetchone()


def parse_age(payload):
    data = payload["user"]
    return int(data["age"])
