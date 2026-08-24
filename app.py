import os
import sqlite3
import asyncio
import threading
import logging
from functools import wraps
from html import escape
from uuid import uuid4

import requests
from flask import (
    Flask,
    request,
    redirect,
    url_for,
    render_template_string,
    session,
)

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ============================================================
# CONFIGURATION
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "change-this-secret-key"
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

CHANNEL_ID = os.environ.get(
    "CHANNEL_ID",
    "@canalRM24"
).strip()

ADMIN_TELEGRAM_ID = os.environ.get(
    "ADMIN_TELEGRAM_ID",
    ""
).strip()

ADZUNA_APP_ID = os.environ.get(
    "ADZUNA_APP_ID",
    ""
).strip()

ADZUNA_APP_KEY = os.environ.get(
    "ADZUNA_APP_KEY",
    ""
).strip()

ADMIN_KEY = os.environ.get(
    "ADMIN_KEY",
    ""
).strip()

DB_FILE = os.environ.get(
    "DB_FILE",
    "opportunites.db"
)

AUTO_POST_MINUTES = int(
    os.environ.get(
        "AUTO_POST_MINUTES",
        "60"
    )
)

AUTO_COUNTRIES = [
    x.strip().lower()
    for x in os.environ.get(
        "AUTO_COUNTRIES",
        "ca,gb,fr"
    ).split(",")
    if x.strip()
]

AUTO_JOB_KEYWORDS = os.environ.get(
    "AUTO_JOB_KEYWORDS",
    "jobs"
).strip()


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format=(
        "%(asctime)s - %(name)s - "
        "%(levelname)s - %(message)s"
    ),
    level=logging.INFO,
)

logger = logging.getLogger(
    "opportunites-internationales"
)


# ============================================================
# PAYS
# ============================================================

COUNTRIES = {
    "fr": "France",
    "gb": "Royaume-Uni",
    "ca": "Canada",
    "us": "États-Unis",
    "de": "Allemagne",
    "au": "Australie",
    "be": "Belgique",
    "ch": "Suisse",
    "it": "Italie",
    "es": "Espagne",
    "nl": "Pays-Bas",
    "ie": "Irlande",
    "at": "Autriche",
    "pl": "Pologne",
    "za": "Afrique du Sud",
    "in": "Inde",
    "br": "Brésil",
    "mx": "Mexique",
    "pt": "Portugal",
    "se": "Suède",
    "no": "Norvège",
    "dk": "Danemark",
    "fi": "Finlande",
    "nz": "Nouvelle-Zélande",
    "sg": "Singapour",
    "ae": "Émirats arabes unis",
}


# ============================================================
# CATÉGORIES
# ============================================================

CATEGORIES = {
    "emploi": "Emploi",
    "job": "Emploi",
    "jobs": "Emploi",
    "bourse": "Bourse",
    "bourses": "Bourse",
    "stage": "Stage rémunéré",
    "stage_remunere": "Stage rémunéré",
    "stage rémunéré": "Stage rémunéré",
}


# ============================================================
# BASE DE DONNÉES
# ============================================================

def db():
    connection = sqlite3.connect(
        DB_FILE,
        timeout=30,
        check_same_thread=False
    )

    connection.row_factory = sqlite3.Row

    try:
        connection.execute(
            "PRAGMA journal_mode=WAL"
        )
        connection.execute(
            "PRAGMA busy_timeout=30000"
        )
    except Exception:
        pass

    return connection


def init_db():
    connection = db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS offres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT UNIQUE,
            titre TEXT NOT NULL,
            entreprise TEXT,
            description TEXT,
            pays TEXT,
            localisation TEXT,
            categorie TEXT,
            salaire_min REAL,
            salaire_max REAL,
            devise TEXT,
            lien TEXT,
            date_publication TEXT,
            source TEXT DEFAULT 'Adzuna',
            telegram_message_id INTEGER
        )
    """)

    # --------------------------------------------------------
    # Migration de l'ancienne base
    # --------------------------------------------------------

    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(offres)"
        ).fetchall()
    }

    if "telegram_message_id" not in columns:
        connection.execute("""
            ALTER TABLE offres
            ADD COLUMN telegram_message_id INTEGER
        """)

    if "source" not in columns:
        connection.execute("""
            ALTER TABLE offres
            ADD COLUMN source TEXT DEFAULT 'Adzuna'
        """)

    if "date_publication" not in columns:
        connection.execute("""
            ALTER TABLE offres
            ADD COLUMN date_publication TEXT
        """)

    if "devise" not in columns:
        connection.execute("""
            ALTER TABLE offres
            ADD COLUMN devise TEXT
        """)

    connection.commit()
    connection.close()


init_db()


# ============================================================
# UTILITAIRES
# ============================================================

def normalize_category(value):
    value = (
        value or ""
    ).strip().lower()

    return CATEGORIES.get(
        value,
        "Emploi"
    )


def is_paid_internship(
    text,
    salary_min=None,
    salary_max=None
):
    text = (
        text or ""
    ).lower()

    if salary_min is not None:
        return True

    if salary_max is not None:
        return True

    words = (
        "paid internship",
        "paid intern",
        "paid placement",
        "stipend",
        "salary",
        "salaried",
        "paid trainee",
        "rémunéré",
        "remunere",
        "rémunération",
        "remuneration",
        "payé",
        "paye",
    )

    return any(
        word in text
        for word in words
    )


def detect_category(
    titre,
    description,
    requested_category,
    salary_min=None,
    salary_max=None
):
    text = (
        f"{titre or ''} "
        f"{description or ''}"
    ).lower()

    if (
        requested_category == "Stage rémunéré"
        and any(
            word in text
            for word in (
                "stage",
                "intern",
                "internship",
                "trainee",
                "placement"
            )
        )
    ):
        return "Stage rémunéré"

    if is_paid_internship(
        text,
        salary_min,
        salary_max
    ):
        if any(
            word in text
            for word in (
                "stage",
                "intern",
                "internship",
                "trainee",
                "placement"
            )
        ):
            return "Stage rémunéré"

    return requested_category


def format_salary(
    salary_min,
    salary_max,
    devise=""
):
    if (
        salary_min is None
        and salary_max is None
    ):
        return ""

    if salary_min is not None:
        minimum = str(salary_min)
    else:
        minimum = ""

    if salary_max is not None:
        maximum = str(salary_max)
    else:
        maximum = ""

    if minimum and maximum:
        result = f"{minimum} - {maximum}"
    elif minimum:
        result = minimum
    else:
        result = maximum

    if devise:
        result += f" {devise}"

    return result


# ============================================================
# ADZUNA
# ============================================================

def rechercher_adzuna(
    country,
    keyword="",
    page
