"""
Módulo de autenticación — SQLite + Flask-Login
"""

import sqlite3
import os
from flask_login import LoginManager, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = "users.db"

# ─────────────────────────────────────────────
# MODELO DE USUARIO
# ─────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, id, username, password_hash, is_admin=False):
        self.id            = str(id)
        self.username      = username
        self.password_hash = password_hash
        self.is_admin      = bool(is_admin)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {"id": self.id, "username": self.username, "is_admin": self.is_admin}


# ─────────────────────────────────────────────
# BASE DE DATOS
# ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Crea la tabla de usuarios si no existe y agrega columna is_admin si falta."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    UNIQUE NOT NULL,
                password_hash TEXT    NOT NULL,
                is_admin      INTEGER DEFAULT 0,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)
        # Migración: agregar is_admin si la tabla ya existía sin esa columna
        try:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        except Exception:
            pass
        conn.commit()


def create_user(username: str, password: str, is_admin: bool = False) -> tuple[bool, str]:
    """Crea un usuario nuevo. Devuelve (ok, mensaje)."""
    if len(username.strip()) < 3:
        return False, "El usuario debe tener al menos 3 caracteres."
    if len(password) < 6:
        return False, "La contraseña debe tener al menos 6 caracteres."
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
                (username.strip().lower(), generate_password_hash(password), int(is_admin))
            )
            conn.commit()
        return True, "Usuario creado correctamente."
    except sqlite3.IntegrityError:
        return False, "Ese nombre de usuario ya existe."


def get_user_by_id(user_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return User(row["id"], row["username"], row["password_hash"], row["is_admin"]) if row else None


def get_user_by_username(username: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip().lower(),)
        ).fetchone()
    return User(row["id"], row["username"], row["password_hash"], row["is_admin"]) if row else None


def get_all_users():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, is_admin, created_at FROM users ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_user(user_id: str) -> bool:
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return True


# ─────────────────────────────────────────────
# SETUP DE FLASK-LOGIN
# ─────────────────────────────────────────────

def setup_login_manager(app):
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = ""

    @login_manager.user_loader
    def load_user(user_id):
        return get_user_by_id(user_id)

    return login_manager
