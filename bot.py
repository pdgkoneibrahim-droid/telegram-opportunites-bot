import os
import sqlite3
import threading
import logging
import re
from datetime import datetime

from flask import Flask
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_ID = int(
    os.getenv("ADMIN_ID", "5056571209")
)

CHANNEL_ID = os.getenv(
    "CHANNEL_ID",
    "@canalRM24"
).strip()

PORT = int(
    os.getenv("PORT", "10000")
)

DB_PATH = os.getenv(
    "DB_PATH",
    "opportunites.db"
)

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN est absent. "
        "Ajoute-le dans Render > Environment."
    )


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format=(
        "%(asctime)s - "
        "%(name)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# FLASK POUR RENDER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "🤖 Bot Opportunités Telegram actif."


@app.route("/health")
def health():
    return "OK"


# ============================================================
# BASE DE DONNÉES
# ============================================================

db_lock = threading.Lock()


def db():
    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    with db_lock:

        conn = db()

        conn.execute("""
            CREATE TABLE IF NOT EXISTS offres (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                categorie TEXT NOT NULL,
                titre TEXT NOT NULL,
                description TEXT,
                lien TEXT,
                telegram_message_id INTEGER,
                date_creation TEXT NOT NULL
            )
        """)

        conn.commit()
        conn.close()

    logger.info("Base de données initialisée.")


def enregistrer_offre(
    categorie,
    titre,
    description="",
    lien="",
    telegram_message_id=None
):

    with db_lock:

        conn = db()

        cursor = conn.execute("""
            INSERT INTO offres (
                categorie,
                titre,
                description,
                lien,
                telegram_message_id,
                date_creation
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            categorie,
            titre,
            description,
            lien,
            telegram_message_id,
            datetime.now().isoformat()
        ))

        offre_id = cursor.lastrowid

        conn.commit()
        conn.close()

    return offre_id


def rechercher_offres(
    categorie=None,
    recherche=None,
    limite=10
):

    conn = db()

    if categorie:

        resultats = conn.execute("""
            SELECT *
            FROM offres
            WHERE categorie = ?
            ORDER BY id DESC
            LIMIT ?
        """, (
            categorie,
            limite
        )).fetchall()

   
