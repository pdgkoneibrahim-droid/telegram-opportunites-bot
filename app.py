import os
import sqlite3
import threading
import logging
import html
from functools import wraps

import requests

from flask import (
    Flask,
    request,
    redirect,
    url_for,
    render_template_string,
    session,
)

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.constants import ParseMode

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

app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "change-this-secret-key"
)

BOT_TOKEN = os.environ.get(
    "BOT_TOKEN",
    ""
).strip()

CHANNEL_ID = os.environ.get(
    "CHANNEL_ID",
    "@canalRM24"
).strip()


# ============================================================
# ADMIN TELEGRAM
# ============================================================

ADMIN_TELEGRAM_ID = os.environ.get(
    "ADMIN_TELEGRAM_ID",
    "5056571209"
).strip()

ADMIN_ID = 5056571209


# ============================================================
# ADZUNA
# ============================================================

ADZUNA_APP_ID = os.environ.get(
    "ADZUNA_APP_ID",
    ""
).strip()

ADZUNA_APP_KEY = os.environ.get(
    "ADZUNA_APP_KEY",
    ""
).strip()


# ============================================================
# ADMIN WEB
# ============================================================

ADMIN_KEY = os.environ.get(
    "ADMIN_KEY",
    ""
).strip()


# ============================================================
# DATABASE
# ============================================================

DB_FILE = os.environ.get(
    "DB_FILE",
    "opportunites.db"
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# ============================================================
# PAYS
# ============================================================

COUNTRIES = {
    "af": "Afghanistan",
    "al": "Albanie",
    "dz": "Algérie",
    "ad": "Andorre",
    "ao": "Angola",
    "ag": "Antigua-et-Barbuda",
    "ar": "Argentine",
    "am": "Arménie",
    "au": "Australie",
    "at": "Autriche",
    "az": "Azerbaïdjan",
    "bs": "Bahamas",
    "bh": "Bahreïn",
    "bd": "Bangladesh",
    "bb": "Barbade",
    "by": "Biélorussie",
    "be": "Belgique",
    "bz": "Belize",
    "bj": "Bénin",
    "bt": "Bhoutan",
    "bo": "Bolivie",
    "ba": "Bosnie-Herzégovine",
    "bw": "Botswana",
    "br": "Brésil",
    "bn": "Brunei",
    "bg": "Bulgarie",
    "bf": "Burkina Faso",
    "bi": "Burundi",
    "cv": "Cap-Vert",
    "kh": "Cambodge",
    "cm": "Cameroun",
    "ca": "Canada",
    "cf": "République centrafricaine",
    "td": "Tchad",
    "cl": "Chili",
    "cn": "Chine",
    "co": "Colombie",
    "km": "Comores",
    "cg": "Congo",
    "cd": "République démocratique du Congo",
    "cr": "Costa Rica",
    "hr": "Croatie",
    "cu": "Cuba",
    "cy": "Chypre",
    "cz": "Tchéquie",
    "dk": "Danemark",
    "dj": "Djibouti",
    "dm": "Dominique",
    "do": "République dominicaine",
    "ec": "Équateur",
    "eg": "Égypte",
    "sv": "Salvador",
    "gq": "Guinée équatoriale",
    "er": "Érythrée",
    "ee": "Estonie",
    "sz": "Eswatini",
    "et": "Éthiopie",
    "fj": "Fidji",
    "fi": "Finlande",
    "fr": "France",
    "ga": "Gabon",
    "gm": "Gambie",
    "ge": "Géorgie",
    "de": "Allemagne",
    "gh": "Ghana",
    "gr": "Grèce",
    "gd": "Grenade",
    "gt": "Guatemala",
    "gn": "Guinée",
    "gw": "Guinée-Bissau",
    "gy": "Guyana",
    "ht": "Haïti",
    "hn": "Honduras",
    "hu": "Hongrie",
    "is": "Islande",
    "in": "Inde",
    "id": "Indonésie",
    "ir": "Iran",
    "iq": "Irak",
    "ie": "Irlande",
    "il": "Israël",
    "it": "Italie",
    "jm": "Jamaïque",
    "jp": "Japon",
    "jo": "Jordanie",
    "kz": "Kazakhstan",
    "ke": "Kenya",
    "ki": "Kiribati",
    "kp": "Corée du Nord",
    "kr": "Corée du Sud",
    "kw": "Koweït",
    "kg": "Kirghizistan",
    "la": "Laos",
    "lv": "Lettonie",
    "lb": "Liban",
    "ls": "Lesotho",
    "lr": "Libéria",
    "ly": "Libye",
    "li": "Liechtenstein",
    "lt": "Lituanie",
    "lu": "Luxembourg",
    "mg": "Madagascar",
    "mw": "Malawi",
    "my": "Malaisie",
    "mv": "Maldives",
    "ml": "Mali",
    "mt": "Malte",
    "mh": "Îles Marshall",
    "mr": "Mauritanie",
    "mu": "Maurice",
    "mx": "Mexique",
    "fm": "Micronésie",
    "md": "Moldavie",
    "mc": "Monaco",
    "mn": "Mongolie",
    "me": "Monténégro",
    "ma": "Maroc",
    "mz": "Mozambique",
    "mm": "Myanmar",
    "na": "Namibie",
    "nr": "Nauru",
    "np": "Népal",
    "nl": "Pays-Bas",
    "nz": "Nouvelle-Zélande",
    "ni": "Nicaragua",
    "ne": "Niger",
    "ng": "Nigeria",
    "mk": "Macédoine du Nord",
    "no": "Norvège",
    "om": "Oman",
    "pk": "Pakistan",
    "pw": "Palaos",
    "pa": "Panama",
    "pg": "Papouasie-Nouvelle-Guinée",
    "py": "Paraguay",
    "pe": "Pérou",
    "ph": "Philippines",
    "pl": "Pologne",
    "pt": "Portugal",
    "qa": "Qatar",
    "ro": "Roumanie",
    "ru": "Russie",
    "rw": "Rwanda",
    "kn": "Saint-Christophe-et-Niévès",
    "lc": "Sainte-Lucie",
    "vc": "Saint-Vincent-et-les-Grenadines",
    "ws": "Samoa",
    "sm": "Saint-Marin",
    "st": "Sao Tomé-et-Principe",
    "sa": "Arabie saoudite",
    "sn": "Sénégal",
    "rs": "Serbie",
    "sc": "Seychelles",
    "sl": "Sierra Leone",
    "sg": "Singapour",
    "sk": "Slovaquie",
    "si": "Slovénie",
    "sb": "Îles Salomon",
    "so": "Somalie",
    "za": "Afrique du Sud",
    "ss": "Soudan du Sud",
    "es": "Espagne",
    "lk": "Sri Lanka",
    "sd": "Soudan",
    "sr": "Suriname",
    "se": "Suède",
    "ch": "Suisse",
    "sy": "Syrie",
    "tj": "Tadjikistan",
    "tz": "Tanzanie",
    "th": "Thaïlande",
    "tl": "Timor oriental",
    "tg": "Togo",
    "to": "Tonga",
    "tt": "Trinité-et-Tobago",
    "tn": "Tunisie",
    "tr": "Turquie",
    "tm": "Turkménistan",
    "tv": "Tuvalu",
    "ug": "Ouganda",
    "ua": "Ukraine",
    "ae": "Émirats arabes unis",
    "gb": "Royaume-Uni",
    "us": "États-Unis",
    "uy": "Uruguay",
    "uz": "Ouzbékistan",
    "vu": "Vanuatu",
    "va": "Vatican",
    "ve": "Venezuela",
    "vn": "Vietnam",
    "ye": "Yémen",
    "zm": "Zambie",
    "zw": "Zimbabwe",
}


# ============================================================
# CATÉGORIES
# ============================================================

CATEGORIES = {
    "emploi": "Emploi",
    "bourse": "Bourse",
    "stage_remunere": "Stage rémunéré",
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
            source TEXT DEFAULT 'Adzuna'
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS telegram_offres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categorie TEXT NOT NULL,
            titre TEXT NOT NULL,
            description TEXT,
            lien TEXT,
            telegram_message_id INTEGER,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS utilisateurs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT UNIQUE,
            username TEXT,
            first_name TEXT,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # NOUVELLE TABLE :
    # utilisateurs intéressés par une catégorie/recherche
    # --------------------------------------------------------

    connection.execute("""
        CREATE TABLE IF NOT EXISTS demandes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT NOT NULL,
            categorie TEXT,
            recherche TEXT,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(telegram_id, categorie)
        )
    """)

    connection.commit()
    connection.close()


init_db()


# ============================================================
# ADMIN WEB
# ============================================================

def admin_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not session.get("admin"):
            return redirect(
                url_for("admin_login")
            )

        return function(*args, **kwargs)

    return wrapper


# ============================================================
# ADMIN TELEGRAM
# ============================================================

def is_telegram_admin(update: Update) -> bool:

    if not update.effective_user:
        return False

    try:

        user_id = int(
            update.effective_user.id
        )

        configured_id = int(
            ADMIN_TELEGRAM_ID
        )

        return (
            user_id == ADMIN_ID
            or user_id == configured_id
        )

    except (ValueError, TypeError):

        return False


async def telegram_admin_required(
    update: Update
) -> bool:

    if is_telegram_admin(update):
        return True

    if update.message:

        await update.message.reply_text(
            "❌ Cette commande est réservée "
            "à l'administrateur."
        )

    return False


# ============================================================
# UTILISATEURS
# ============================================================

def enregistrer_utilisateur(user):

    if not user:
        return

    connection = db()

    connection.execute("""
        INSERT OR IGNORE INTO utilisateurs (
            telegram_id,
            username,
            first_name
        )
        VALUES (?, ?, ?)
    """, (
        str(user.id),
        user.username or "",
        user.first_name or "",
    ))

    connection.execute("""
        UPDATE utilisateurs
        SET username = ?,
            first_name = ?
        WHERE telegram_id = ?
    """, (
        user.username or "",
        user.first_name or "",
        str(user.id),
    ))

    connection.commit()
    connection.close()


# ============================================================
# DEMANDES
# ============================================================

def enregistrer_demande(
    telegram_id,
    categorie=None,
    recherche=""
):

    connection = db()

    # SQLite ne permet pas toujours une bonne gestion
    # de NULL dans une contrainte UNIQUE.
    # On utilise une catégorie vide pour la demande générale.

    categorie_db = (
        categorie
        or ""
    ).strip().lower()

    connection.execute("""
        INSERT INTO demandes (
            telegram_id,
            categorie,
            recherche
        )
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_id, categorie)
        DO UPDATE SET
            recherche = excluded.recherche,
            date_creation = CURRENT_TIMESTAMP
    """, (
        str(telegram_id),
        categorie_db,
        recherche or "",
    ))

    connection.commit()
    connection.close()


def obtenir_demandes_categorie(categorie):

    categorie = (
        categorie
        or ""
    ).strip().lower()

    connection = db()

    rows = connection.execute("""
        SELECT DISTINCT telegram_id
        FROM demandes
        WHERE lower(categorie) = ?
    """, (
        categorie,
    )).fetchall()

    connection.close()

    return rows


# ============================================================
# ADZUNA
# ============================================================

def is_paid_internship(
    text,
    salary_min=None,
    salary_max=None
):

    text = (
        text
        or ""
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


def rechercher_adzuna(
    country,
    keyword="",
    page=1,
    remunerated=False
):

    if not ADZUNA_APP_ID:
        return []

    if not ADZUNA_APP_KEY:
        return []

    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": 20,
        "content-type": "application/json",
    }

    if keyword
