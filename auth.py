"""
Módulo de autenticación — PostgreSQL + Flask-Login
"""

import os
import psycopg2
import psycopg2.extras
from flask_login import LoginManager, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Railway a veces entrega "postgres://" pero psycopg2 requiere "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


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
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no está configurada. Agregá el plugin de PostgreSQL en Railway.")
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def init_db():
    """Crea la tabla de usuarios si no existe."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            SERIAL PRIMARY KEY,
                    username      TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_admin      BOOLEAN DEFAULT FALSE,
                    created_at    TIMESTAMP DEFAULT NOW()
                )
            """)
        conn.commit()


def create_user(username: str, password: str, is_admin: bool = False) -> tuple[bool, str]:
    """Crea un usuario nuevo. Devuelve (ok, mensaje)."""
    if len(username.strip()) < 3:
        return False, "El usuario debe tener al menos 3 caracteres."
    if len(password) < 6:
        return False, "La contraseña debe tener al menos 6 caracteres."
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, %s)",
                    (username.strip().lower(), generate_password_hash(password), is_admin)
                )
            conn.commit()
        return True, "Usuario creado correctamente."
    except psycopg2.errors.UniqueViolation:
        return False, "Ese nombre de usuario ya existe."
    except Exception as e:
        return False, str(e)


def get_user_by_id(user_id: str):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
    if not row:
        return None
    return User(row["id"], row["username"], row["password_hash"], row["is_admin"])


def get_user_by_username(username: str):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM users WHERE username = %s", (username.strip().lower(),)
            )
            row = cur.fetchone()
    if not row:
        return None
    return User(row["id"], row["username"], row["password_hash"], row["is_admin"])


def get_all_users():
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, username, is_admin, created_at FROM users ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def delete_user(user_id: str) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
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
