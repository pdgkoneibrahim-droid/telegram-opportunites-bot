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
    page=1,
    remunerated=False
):
    if not ADZUNA_APP_ID:
        logger.warning(
            "ADZUNA_APP_ID manquant."
        )
        return []

    if not ADZUNA_APP_KEY:
        logger.warning(
            "ADZUNA_APP_KEY manquant."
        )
        return []

    country = (
        country or "ca"
    ).lower().strip()

    if country not in COUNTRIES:
        country = "ca"

    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": 20,
        "content-type": "application/json",
    }

    search_keyword = (
        keyword or ""
    ).strip()

    if remunerated:
        if search_keyword:
            search_keyword = (
                f"{search_keyword} paid internship"
            )
        else:
            search_keyword = "paid internship"

    if search_keyword:
        params["what"] = search_keyword

    url = (
        "https://api.adzuna.com/v1/api/jobs/"
        f"{country}/search/{page}"
    )

    try:
        response = requests.get(
            url,
            params=params,
            timeout=20,
            headers={
                "Accept": "application/json",
                "User-Agent":
                    "OpportunitesInternationales/2.0",
            },
        )

        response.raise_for_status()

        data = response.json()

        return data.get(
            "results",
            []
        )

    except Exception as error:
        logger.exception(
            "Erreur Adzuna: %s",
            error
        )
        return []


def enregistrer_offres(
    offres,
    country,
    categorie
):
    connection = db()
    nombre = 0
    nouveaux_ids = []

    for offre in offres:

        source_id = str(
            offre.get("id", "")
        ).strip()

        if not source_id:
            continue

        company = (
            offre.get("company")
            or {}
        )

        location = (
            offre.get("location")
            or {}
        )

        category = (
            offre.get("category")
            or {}
        )

        titre = str(
            offre.get("title", "")
            or ""
        ).strip()

        description = str(
            offre.get("description", "")
            or ""
        ).strip()

        entreprise = (
            company.get("display_name")
            or "Entreprise non précisée"
        )

        localisation = (
            location.get("display_name")
            or ""
        )

        salaire_min = offre.get(
            "salary_min"
        )

        salaire_max = offre.get(
            "salary_max"
        )

        lien = (
            offre.get("redirect_url")
            or ""
        )

        date_publication = (
            offre.get("created")
            or ""
        )

        texte = (
            f"{titre} "
            f"{description} "
            f"{category.get('label', '')}"
        )

        categorie_finale = detect_category(
            titre,
            texte,
            categorie,
            salaire_min,
            salaire_max
        )

        try:
            cursor = connection.execute("""
                INSERT INTO offres (
                    source_id,
                    titre,
                    entreprise,
                    description,
                    pays,
                    localisation,
                    categorie,
                    salaire_min,
                    salaire_max,
                    devise,
                    lien,
                    date_publication,
                    source,
                    telegram_message_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                source_id,
                titre,
                entreprise,
                description,
                COUNTRIES.get(
                    country,
                    country.upper()
                ),
                localisation,
                categorie_finale,
                salaire_min,
                salaire_max,
                "",
                lien,
                date_publication,
                "Adzuna",
                None,
            ))

            nombre += 1

            nouveaux_ids.append(
                cursor.lastrowid
            )

        except sqlite3.IntegrityError:
            pass

    connection.commit()
    connection.close()

    return nombre, nouveaux_ids


# ============================================================
# FORMATAGE DES OFFRES TELEGRAM
# ============================================================

def format_offer_for_telegram(offre):
    titre = escape(
        str(offre["titre"] or "")
    )

    entreprise = escape(
        str(
            offre["entreprise"]
            or "Entreprise non précisée"
        )
    )

    pays = escape(
        str(
            offre["pays"]
            or "Non précisé"
        )
    )

    localisation = escape(
        str(
            offre["localisation"]
            or ""
        )
    )

    categorie = escape(
        str(
            offre["categorie"]
            or "Emploi"
        )
    )

    description = str(
        offre["description"]
        or ""
    ).strip()

    if len(description) > 900:
        description = (
            description[:900]
            + "..."
        )

    description = escape(
        description
    )

    lien = str(
        offre["lien"]
        or ""
    ).strip()

    salaire = format_salary(
        offre["salaire_min"],
        offre["salaire_max"],
        offre["devise"]
    )

    texte = (
        "🌍 <b>OPPORTUNITÉ INTERNATIONALE</b>\n\n"
        f"📂 <b>{categorie}</b>\n"
        f"📌 <b>{titre}</b>\n"
        f"🏢 <b>{entreprise}</b>\n"
        f"🌍 <b>Pays :</b> {pays}\n"
    )

    if localisation:
        texte += (
            f"📍 <b>Lieu :</b> "
            f"{localisation}\n"
        )

    if salaire:
        texte += (
            f"💰 <b>Salaire :</b> "
            f"{escape(salaire)}\n"
        )

    if description:
        texte += (
            f"\n📝 {description}\n"
        )

    if lien:
        texte += (
            f"\n🔗 <a href=\"{escape(lien)}\">"
            "👉 Voir l'offre / Candidater"
            "</a>\n"
        )

    texte += (
        "\n📢 <b>RESEAU MONDIAL</b>\n"
        "🌐 Opportunités : emplois • stages • bourses"
    )

    return texte


# ============================================================
# PUBLICATION TELEGRAM
# ============================================================

async def publier_offre(
    bot,
    offre_id
):
    connection = db()

    offre = connection.execute("""
        SELECT *
        FROM offres
        WHERE id = ?
    """, (
        offre_id,
    )).fetchone()

    connection.close()

    if offre is None:
        return False

    if offre["telegram_message_id"]:
        return True

    try:
        message = await bot.send_message(
            chat_id=CHANNEL_ID,
            text=format_offer_for_telegram(
                offre
            ),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
        )

        connection = db()

        connection.execute("""
            UPDATE offres
            SET telegram_message_id = ?
            WHERE id = ?
        """, (
            message.message_id,
            offre_id,
        ))

        connection.commit()
        connection.close()

        logger.info(
            "Offre %s publiée dans %s.",
            offre_id,
            CHANNEL_ID
        )

        return True

    except Exception as error:
        logger.exception(
            "Impossible de publier l'offre %s: %s",
            offre_id,
            error
        )

        return False


async def publier_nouvelles_offres(bot):
    connection = db()

    offres = connection.execute("""
        SELECT id
        FROM offres
        WHERE telegram_message_id IS NULL
        ORDER BY id ASC
        LIMIT 5
    """).fetchall()

    connection.close()

    if not offres:
        logger.info(
            "Aucune nouvelle offre à publier."
        )
        return 0

    nombre = 0

    for offre in offres:
        success = await publier_offre(
            bot,
            offre["id"]
        )

        if success:
            nombre += 1

        await asyncio.sleep(2)

    return nombre


# ============================================================
# CRÉATION MANUELLE D'UNE OFFRE
# ============================================================

def creer_offre_manuelle(
    categorie,
    titre,
    description,
    lien
):
    categorie_finale = normalize_category(
        categorie
    )

    source_id = (
        "manual_"
        + uuid4().hex
    )

    connection = db()

    cursor = connection.execute("""
        INSERT INTO offres (
            source_id,
            titre,
            entreprise,
            description,
            pays,
            localisation,
            categorie,
            salaire_min,
            salaire_max,
            devise,
            lien,
            date_publication,
            source,
            telegram_message_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        source_id,
        titre,
        "RESEAU MONDIAL",
        description,
        "",
        "",
        categorie_finale,
        None,
        None,
        "",
        lien,
        "",
        "Manuel",
        None,
    ))

    offre_id = cursor.lastrowid

    connection.commit()
    connection.close()

    return offre_id


# ============================================================
# ADMIN TELEGRAM
# ============================================================

def telegram_admin_required(
    update: Update
):
    if not ADMIN_TELEGRAM_ID:
        return False

    user = update.effective_user

    if user is None:
        return False

    return str(
        user.id
    ) == ADMIN_TELEGRAM_ID


# ============================================================
# COMMANDES TELEGRAM
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = (
        "🌍 <b>RESEAU MONDIAL</b>\n\n"
        "Bienvenue sur le bot des opportunités "
        "internationales.\n\n"
        "💼 /emploi — offres d'emploi\n"
        "💰 /stage — stages rémunérés\n"
        "🎓 /bourse — bourses\n"
        "🔎 /recherche mot-clé — rechercher\n\n"
        "Exemple :\n"
        "<code>/recherche informatique</code>\n\n"
        "Pour l'administration :\n"
        "<code>/ajouter</code>\n"
        "<code>/testcanal</code>"
    )

    await update.message.reply_text(
        message,
        parse_mode=ParseMode.HTML
    )


async def id_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    await update.message.reply_text(
        f"🆔 Votre Telegram ID : {user.id}"
    )


async def testcanal_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not telegram_admin_required(
        update
    ):
        await update.message.reply_text(
            "❌ Commande réservée à l'administrateur."
        )
        return

    try:
        sent = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                "✅ <b>TEST REUSSI</b>\n\n"
                "Le bot peut publier dans le canal "
                "RESEAU MONDIAL.\n\n"
                f"📢 Canal : {escape(CHANNEL_ID)}"
            ),
            parse_mode=ParseMode.HTML
        )

        await update.message.reply_text(
            "✅ Test réussi : le bot peut publier "
            f"dans le canal.\n\n"
            f"Message ID : {sent.message_id}"
        )

    except Exception as error:
        logger.exception(
            "Erreur test canal: %s",
            error
        )

        await update.message.reply_text(
            "❌ Le bot n'a pas réussi à publier "
            "dans le canal.\n\n"
            f"Erreur : {str(error)[:500]}"
        )


async def ajouter_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not telegram_admin_required(
        update
    ):
        await update.message.reply_text(
            "❌ Commande réservée à l'administrateur."
        )
        return

    text = (
        update.message.text
        or ""
    ).strip()

    parts = text.split(
        "|",
        3
    )

    if len(parts) != 4:
        await update.message.reply_text(
            "❌ Format incorrect.\n\n"
            "Utilisez :\n"
            "/ajouter CATEGORIE | TITRE | "
            "DESCRIPTION | LIEN\n\n"
            "Exemple :\n"
            "/ajouter STAGE | Stage informatique | "
            "Stage rémunéré en Belgique | "
            "https://exemple.com"
        )
        return

    categorie = parts[0].replace(
        "/ajouter",
        "",
        1
    ).strip()

    titre = parts[1].strip()
    description = parts[2].strip()
    lien = parts[3].strip()

    if not titre:
        await update.message.reply_text(
            "❌ Le titre est obligatoire."
        )
        return

    if not description:
        await update.message.reply_text(
            "❌ La description est obligatoire."
        )
        return

    if not lien.startswith(
        ("http://", "https://")
    ):
        await update.message.reply_text(
            "❌ Le lien doit commencer par "
            "http:// ou https://"
        )
        return

    try:
        offre_id = creer_offre_manuelle(
            categorie,
            titre,
            description,
            lien
        )

        success = await publier_offre(
            context.bot,
            offre_id
        )

        if success:
            await update.message.reply_text(
                "✅ <b>OFFRE PUBLIÉE</b>\n\n"
                f"📂 {escape(normalize_category(categorie))}\n"
                f"📌 {escape(titre)}\n"
                f"🆔 Référence : {offre_id}\n\n"
                "📢 Elle est maintenant disponible "
                "dans le canal et dans la recherche "
                "du bot.",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                "⚠️ L'offre a été enregistrée, "
                "mais sa publication dans le canal "
                "a échoué.\n\n"
                f"Référence : {offre_id}"
            )

    except Exception as error:
        logger.exception(
            "Erreur /ajouter: %s",
            error
        )

        await update.message.reply_text(
            "❌ Erreur lors de l'ajout de l'offre.\n\n"
            f"{str(error)[:500]}"
        )


async def rechercher_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    text = (
        update.message.text
        or ""
    ).strip()

    keyword = text[
        len("/recherche"):
    ].strip()

    if not keyword:
        await update.message.reply_text(
            "🔎 Utilisation :\n"
            "/recherche informatique\n\n"
            "ou\n"
            "/recherche infirmier Canada"
        )
        return

    offres_api = []

    for country in (
        "ca",
        "gb",
        "fr"
    ):
        result = rechercher_adzuna(
            country=country,
            keyword=keyword,
            page=1,
            remunerated=False
        )

        offres_api.extend(
            [
                (
                    result,
                    country
                )
                for result in result
            ]
        )

        if len(offres_api) >= 10:
            break

    total = 0

    for result, country in offres_api[:10]:
        count, ids = enregistrer_offres(
            [result],
            country,
            "Emploi"
        )

        total += count

    connection = db()

    rows = connection.execute("""
        SELECT *
        FROM offres
        WHERE (
            lower(titre) LIKE ?
            OR lower(description) LIKE ?
        )
        ORDER BY id DESC
        LIMIT 5
    """, (
        f"%{keyword.lower()}%",
        f"%{keyword.lower()}%",
    )).fetchall()

    connection.close()

    if not rows:
        await update.message.reply_text(
            "🔎 Aucune offre trouvée pour : "
            f"{keyword}"
        )
        return

    await update.message.reply_text(
        f"🔎 <b>Résultats pour :</b> "
        f"{escape(keyword)}\n\n"
        f"📊 {len(rows)} résultat(s)",
        parse_mode=ParseMode.HTML
    )

    for row in rows:
        try:
            await update.message.reply_text(
                format_offer_for_telegram(
                    row
                ),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False
            )
        except Exception as error:
            logger.exception(
                "Erreur envoi résultat recherche: %s",
                error
            )

        await asyncio.sleep(1)


async def categorie_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    categorie
):
    connection = db()

    rows = connection.execute("""
        SELECT *
        FROM offres
        WHERE categorie = ?
        ORDER BY id DESC
        LIMIT 5
    """, (
        categorie,
    )).fetchall()

    connection.close()

    if not rows:
        await update.message.reply_text(
            f"🔎 Aucune offre disponible "
            f"dans la catégorie : {categorie}."
        )
        return

    await update.message.reply_text(
        f"📂 <b>{escape(categorie)}</b>\n\n"
        f"{len(rows)} offre(s) trouvée(s).",
        parse_mode=ParseMode.HTML
    )

    for row in rows:
        await update.message.reply_text(
            format_offer_for_telegram(row),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False
        )

        await asyncio.sleep(1)


async def emploi_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await categorie_command(
        update,
        context,
        "Emploi"
    )


async def stage_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await categorie_command(
        update,
        context,
        "Stage rémunéré"
    )


async def bourse_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await categorie_command(
        update,
        context,
        "Bourse"
    )


async def texte_recherche(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message:
        return

    text = (
        update.message.text
        or ""
    ).strip()

    if len(text) < 3:
        return

    lower = text.lower()

    keywords = (
        "emploi",
        "job",
        "travail",
        "stage",
        "bourse",
        "cherche",
        "recherche",
    )

    if not any(
        word in lower
        for word in keywords
    ):
        return

    await update.message.reply_text(
        "🔎 Je recherche les opportunités "
        "correspondantes...\n\n"
        "Utilisez aussi :\n"
        "/recherche mot-clé"
    )


# ============================================================
# PUBLICATION AUTOMATIQUE
# ============================================================

async def auto_publication_job(
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        bot = context.application.bot

        # ----------------------------------------------------
        # 1. Publier les offres déjà présentes en base
        # ----------------------------------------------------

        await publier_nouvelles_offres(
            bot
        )

        # ----------------------------------------------------
        # 2. Récupérer automatiquement de nouvelles offres
        # ----------------------------------------------------

        if (
            ADZUNA_APP_ID
            and ADZUNA_APP_KEY
        ):
            for country in AUTO_COUNTRIES:

                offres = rechercher_adzuna(
                    country=country,
                    keyword=AUTO_JOB_KEYWORDS,
                    page=1,
                    remunerated=False
                )

                if offres:
                    enregistrer_offres(
                        offres,
                        country,
                        "Emploi"
                    )

            # Publier les nouvelles offres
            await publier_nouvelles_offres(
                bot
            )

    except Exception as error:
        logger.exception(
            "Erreur publication automatique: %s",
            error
        )


# ============================================================
# DÉMARRAGE DU BOT TELEGRAM
# ============================================================

telegram_thread = None
telegram_loop_started = False


async def telegram_main():
    if not BOT_TOKEN:
        logger.error(
            "BOT_TOKEN n'est pas configuré. "
            "Le bot Telegram ne peut pas démarrer."
        )
        return

    logger.info(
        "Démarrage du bot Telegram..."
    )

    telegram_app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # Commandes
    # --------------------------------------------------------

    telegram_app.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "id",
            id_command
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "ajouter",
            ajouter_command
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "testcanal",
            testcanal_command
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "recherche",
            rechercher_command
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "emploi",
            emploi_command
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "stage",
            stage_command
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "bourse",
            bourse_command
        )
    )

    # --------------------------------------------------------
    # Recherche par texte
    # --------------------------------------------------------

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            texte_recherche
        )
    )

    # --------------------------------------------------------
    # Initialisation
    # --------------------------------------------------------

    await telegram_app.initialize()

    await telegram_app.start()

    if telegram_app.updater is None:
        raise RuntimeError(
            "Updater Telegram indisponible."
        )

    await telegram_app.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

    logger.info(
        "BOT TELEGRAM DEMARRE AVEC SUCCES."
    )

    logger.info(
        "Canal cible : %s",
        CHANNEL_ID
    )

    # --------------------------------------------------------
    # Job automatique
    # --------------------------------------------------------

    if telegram_app.job_queue:

        telegram_app.job_queue.run_repeating(
            auto_publication_job,
            interval=(
                AUTO_POST_MINUTES * 60
            ),
            first=30,
            name="publication_automatique"
        )

        logger.info(
            "Publication automatique activée "
            "toutes les %s minutes.",
            AUTO_POST_MINUTES
        )

    else:
        logger.error(
            "JobQueue indisponible. "
            "Vérifiez python-telegram-bot[job-queue]."
        )

    # --------------------------------------------------------
    # Garder le bot vivant
    # --------------------------------------------------------

    stop_event = asyncio.Event()

    try:
        await stop_event.wait()

    finally:
        logger.info(
            "Arrêt du bot Telegram..."
        )

        if telegram_app.updater:
            await telegram_app.updater.stop()

        await telegram_app.stop()
        await telegram_app.shutdown()


def run_telegram_thread():
    global telegram_loop_started

    if telegram_loop_started:
        return

    telegram_loop_started = True

    try:
        asyncio.run(
            telegram_main()
        )
    except Exception as error:
        logger.exception(
            "Le bot Telegram s'est arrêté : %s",
            error
        )


def start_telegram_bot():
    global telegram_thread

    if not BOT_TOKEN:
        logger.error(
            "BOT_TOKEN manquant. "
            "Bot Telegram non lancé."
        )
        return

    if telegram_thread is not None:
        return

    telegram_thread = threading.Thread(
        target=run_telegram_thread,
        name="telegram-bot",
        daemon=True
    )

    telegram_thread.start()

    logger.info(
        "Thread Telegram lancé."
    )


# ============================================================
# FLASK - ADMIN
# ============================================================

def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):

        if not session.get("admin"):
            return redirect(
                url_for("admin_login")
            )

        return function(
            *args,
            **kwargs
        )

    return wrapper


@app.route("/")
def accueil():

    keyword = request.args.get(
        "keyword",
        ""
    ).strip()

    country = request.args.get(
        "country",
        "ca"
    ).strip()

    categorie = request.args.get(
        "categorie",
        "emploi"
    ).strip()

    offres = []

    recherche = (
        request.args.get("search")
        or keyword
    )

    if recherche:

        remunerated = (
            categorie
            == "stage_remunere"
        )

        try:

            offres_api = rechercher_adzuna(
                country=country,
                keyword=keyword,
                page=1,
                remunerated=remunerated,
            )

            categorie_api = CATEGORIES.get(
                categorie,
                "Emploi"
            )

            enregistrer_offres(
                offres_api,
                country,
                categorie_api
            )

        except Exception as error:
            logger.exception(
                "Erreur Adzuna accueil: %s",
                error
            )

    connection = db()

    if categorie == "emploi":

        query = """
            SELECT *
            FROM offres
            WHERE categorie = 'Emploi'
               OR categorie IS NULL
            ORDER BY id DESC
            LIMIT 100
        """

    elif categorie == "bourse":

        query = """
            SELECT *
            FROM offres
            WHERE lower(categorie) IN
            ('bourse', 'bourses')
            ORDER BY id DESC
            LIMIT 100
        """

    elif categorie == "stage_remunere":

        query = """
            SELECT *
            FROM offres
            WHERE categorie = 'Stage rémunéré'
            ORDER BY id DESC
            LIMIT 100
        """

    else:

        query = """
            SELECT *
            FROM offres
            WHERE categorie IN
            ('Emploi',
             'Bourse',
             'Bourses',
             'Stage rémunéré')
            ORDER BY id DESC
            LIMIT 100
        """

    offres = connection.execute(
        query
    ).fetchall()

    connection.close()

    return render_template_string(
        HTML_HOME,
        offres=offres,
        keyword=keyword,
        country=country,
        categorie=categorie,
        countries=COUNTRIES,
    )


@app.route(
    "/admin/login",
    methods=["GET", "POST"]
)
def admin_login():

    message = ""

    if request.method == "POST":

        key = request.form.get(
            "key",
            ""
        ).strip()

        if (
            ADMIN_KEY
            and key == ADMIN_KEY
        ):

            session["admin"] = True

            return redirect(
                url_for("admin")
            )

        message = (
            "Clé administrateur incorrecte."
        )

    return render_template_string(
        HTML_LOGIN,
        message=message
    )


@app.route("/admin/logout")
def admin_logout():

    session.clear()

    return redirect(
        url_for("accueil")
    )


@app.route("/admin")
@admin_required
def admin():

    connection = db()

    offres = connection.execute("""
        SELECT *
        FROM offres
        ORDER BY id DESC
        LIMIT 200
    """).fetchall()

    connection.close()

    return render_template_string(
        HTML_ADMIN,
        offres=offres
    )


@app.route(
    "/admin/supprimer/<int:offre_id>",
    methods=["POST"]
)
@admin_required
def supprimer(offre_id):

    connection = db()

    connection.execute(
        "DELETE FROM offres WHERE id = ?",
        (offre_id,)
    )

    connection.commit()
    connection.close()

    return redirect(
        url_for("admin")
    )


@app.route(
    "/admin/modifier/<int:offre_id>",
    methods=["GET", "POST"]
)
@admin_required
def modifier(offre_id):

    connection = db()

    offre = connection.execute("""
        SELECT *
        FROM offres
        WHERE id = ?
    """, (
        offre_id,
    )).fetchone()

    if offre is None:

        connection.close()

        return redirect(
            url_for("admin")
        )

    if request.method == "POST":

        connection.execute("""
            UPDATE offres
            SET titre = ?,
                entreprise = ?,
                description = ?,
                pays = ?,
                localisation = ?,
                categorie = ?,
                lien = ?
            WHERE id = ?
        """, (
            request.form.get(
                "titre",
                ""
            ).strip(),

            request.form.get(
                "entreprise",
                ""
            ).strip(),

            request.form.get(
                "description",
                ""
            ).strip(),

            request.form.get(
                "pays",
                ""
            ).strip(),

            request.form.get(
                "localisation",
                ""
            ).strip(),

            request.form.get(
                "categorie",
                "Emploi"
            ).strip(),

            request.form.get(
                "lien",
                ""
            ).strip(),

            offre_id,
        ))

        connection.commit()
        connection.close()

        return redirect(
            url_for("admin")
        )

    connection.close()

    return render_template_string(
        HTML_EDIT,
        offre=offre
    )


@app.route("/health")
def health():
    return "OK", 200


@app.route("/telegram-status")
def telegram_status():

    if not BOT_TOKEN:
        return {
            "telegram": "disabled",
            "reason": "BOT_TOKEN manquant"
        }, 503

    if telegram_thread is None:
        return {
            "telegram": "not_started"
        }, 503

    if telegram_thread.is_alive():
        return {
            "telegram": "running",
            "channel": CHANNEL_ID
        }, 200

    return {
        "telegram": "stopped",
        "channel": CHANNEL_ID
    }, 503


# ============================================================
# PAGE D'ACCUEIL
# ============================================================

HTML_HOME = """
<!doctype html>
<html lang="fr">

<head>

<meta charset="utf-8">

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>Opportunités internationales</title>

<style>

body {
    font-family: Arial, sans-serif;
    background: #f4f6f8;
    margin: 0;
    padding: 20px;
}

.container {
    max-width: 1100px;
    margin: auto;
}

header,
.search,
.card {
    background: white;
    border-radius: 15px;
}

header {
    padding: 25px;
    margin-bottom: 20px;
}

.search {
    padding: 20px;
    margin-bottom: 20px;
}

input,
select,
button {
    padding: 12px;
    margin: 5px;
    border-radius: 8px;
    border: 1px solid #ccc;
}

button {
    cursor: pointer;
}

.card {
    padding: 20px;
    margin: 15px 0;
}

.admin {
    float: right;
}

a {
    text-decoration: none;
}

</style>

</head>

<body>

<div class="container">

<header>

<a class="admin"
href="/admin/login">
⚙️ Administration
</a>

<h1>
🌍 Opportunités internationales
</h1>

<p>
💼 Emplois • 🎓 Bourses •
💰 Stages rémunérés
</p>

<p>
Trouvez des opportunités
internationales et locales.
</p>

<p>
📢 Telegram :
<a
href="https://t.me/canalRM24"
target="_blank"
>
RESEAU MONDIAL
</a>
</p>

</header>

<section class="search">

<form method="get">

<input
name="keyword"
value="{{ keyword }}"
placeholder="Exemple : informatique, ingénieur..."
>

<select name="country">

{% for code, name in countries.items() %}

<option
value="{{ code }}"
{% if code == country %}
selected
{% endif %}
>
{{ name }}
</option>

{% endfor %}

</select>

<select name="categorie">

<option
value="emploi"
{% if categorie == "emploi" %}
selected
{% endif %}
>
💼 Emplois
</option>

<option
value="bourse"
{% if categorie == "bourse" %}
selected
{% endif %}
>
🎓 Bourses
</option>

<option
value="stage_remunere"
{% if categorie == "stage_remunere" %}
selected
{% endif %}
>
💰 Stages rémunérés
</option>

<option
value="tous"
{% if categorie == "tous" %}
selected
{% endif %}
>
Toutes les catégories
</option>

</select>

<button
name="search"
value="1"
>
🔎 Rechercher
</button>

</form>

</section>

{% if offres %}

{% for offre in offres %}

<article class="card">

<h2>
{{ offre["titre"] }}
</h2>

<p>
🏢 <b>
{{ offre["entreprise"] }}
</b>
</p>

<p>
🌍 {{ offre["pays"] }}

{% if offre["localisation"] %}

— {{ offre["localisation"] }}

{% endif %}

</p>

<p>
📂 {{ offre["categorie"] }}
</p>

{% if offre["salaire_min"]
or offre["salaire_max"] %}

<p>
💰 Salaire :
{{ offre["salaire_min"] or "" }}
-
{{ offre["salaire_max"] or "" }}
</p>

{% endif %}

<p>
{{ offre["description"] }}
</p>

{% if offre["lien"] %}

<p>

<a
href="{{ offre["lien"] }}"
target="_blank"
rel="noopener noreferrer"
>
👉 Voir l'offre / Candidater
</a>

</p>

{% endif %}

</article>

{% endfor %}

{% else %}

<div class="card">

<h2>
🔎 Aucune offre enregistrée
pour cette recherche.
</h2>

<p>
Effectuez une recherche pour
récupérer les offres disponibles.
</p>

</div>

{% endif %}

</div>

</body>

</html>
"""


# ============================================================
# LOGIN ADMIN
# ============================================================

HTML_LOGIN = """
<!doctype html>
<html lang="fr">

<head>

<meta charset="utf-8">

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>Administration</title>

<style>

body {
    font-family: Arial;
    background: #f4f6f8;
    padding: 30px;
}

.box {
    max-width: 450px;
    margin: auto;
    background: white;
    padding: 25px;
    border-radius: 15px;
}

input,
button {
    width: 100%;
    box-sizing: border-box;
    padding: 12px;
    margin: 8px 0;
}

</style>

</head>

<body>

<div class="box">

<h1>
⚙️ Administration
</h1>

<form method="post">

<input
type="password"
name="key"
placeholder="Clé administrateur"
required
>

<button>
🔐 Se connecter
</button>

</form>

{% if message %}

<p>
{{ message }}
</p>

{% endif %}

</div>

</body>

</html>
"""


# ============================================================
# ADMIN
# ============================================================

HTML_ADMIN = """
<!doctype html>
<html lang="fr">

<head>

<meta charset="utf-8">

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>Administration</title>

<style>

body {
    font-family: Arial;
    background: #f4f6f8;
    padding: 20px;
}

.container {
    max-width: 1200px;
    margin: auto;
}

.card {
    background: white;
    padding: 20px;
    margin: 15px 0;
    border-radius: 15px;
}

button,
a {
    padding: 10px;
    margin: 5px;
}

.delete {
    color: #b00020;
}

</style>

</head>

<body>

<div class="container">

<p>

<a href="/">
🌍 Voir le site
</a>

|

<a href="/admin/logout">
Déconnexion
</a>

</p>

<h1>
⚙️ Administration
</h1>

<p>
{{ offres|length }}
offres affichées.
</p>

{% for offre in offres %}

<div class="card">

<h2>
{{ offre["titre"] }}
</h2>

<p>
🏢 {{ offre["entreprise"] }}
</p>

<p>
🌍 {{ offre["pays"] }}
</p>

<p>
📂 {{ offre["categorie"] }}
</p>

{% if offre["telegram_message_id"] %}

<p>
📢 Publiée dans Telegram
</p>

{% else %}

<p>
⏳ Pas encore publiée dans Telegram
</p>

{% endif %}

{% if offre["lien"] %}

<p>

🔗

<a
href="{{ offre["lien"] }}"
target="_blank"
>
Lien de candidature
</a>

</p>

{% endif %}

<a
href="/admin/modifier/{{ offre["id"] }}"
>
✏️ Modifier
</a>

<form
method="post"
action="/admin/supprimer/{{ offre["id"] }}"
style="display:inline"
>

<button
class="delete"
type="submit"
>
🗑️ Supprimer
</button>

</form>

</div>

{% endfor %}

</div>

</body>

</html>
"""


# ============================================================
# MODIFICATION
# ============================================================

HTML_EDIT = """
<!doctype html>
<html lang="fr">

<head>

<meta charset="utf-8">

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>Modifier une offre</title>

<style>

body {
    font-family: Arial;
    background: #f4f6f8;
    padding: 20px;
}

.box {
    max-width: 800px;
    margin: auto;
    background: white;
    padding: 25px;
    border-radius: 15px;
}

input,
textarea,
select,
button {
    width: 100%;
    box-sizing: border-box;
    padding: 12px;
    margin: 8px 0;
}

textarea {
    min-height: 200px;
}

</style>

</head>

<body>

<div class="box">

<h1>
✏️ Modifier l'offre
</h1>

<form method="post">

<label>
Titre
</label>

<input
name="titre"
value="{{ offre["titre"] }}"
required
>

<label>
Entreprise
</label>

<input
name="entreprise"
value="{{ offre["entreprise"] or "" }}"
>

<label>
Pays
</label>

<input
name="pays"
value="{{ offre["pays"] or "" }}"
>

<label>
Localisation
</label>

<input
name="localisation"
value="{{ offre["localisation"] or "" }}"
>

<label>
Catégorie
</label>

<select name="categorie">

<option
value="Emploi"
{% if offre["categorie"] == "Emploi" %}
selected
{% endif %}
>
💼 Emploi
</option>

<option
value="Bourse"
{% if offre["categorie"] == "Bourse" %}
selected
{% endif %}
>
🎓 Bourse
</option>

<option
value="Stage rémunéré"
{% if offre["categorie"] == "Stage rémunéré" %}
selected
{% endif %}
>
💰 Stage rémunéré
</option>

</select>

<label>
Description
</label>

<textarea
name="description"
>{{ offre["description"] or "" }}</textarea>

<label>
Lien de candidature
</label>

<input
name="lien"
value="{{ offre["lien"] or "" }}"
>

<button>
💾 Enregistrer
</button>

</form>

<a href="/admin">
⬅️ Retour
</a>

</div>

</body>

</html>
"""


# ============================================================
# DÉMARRAGE FLASK
# ============================================================

# IMPORTANT :
# Gunicorn importe "app:app".
# Le bot est donc démarré automatiquement
# lorsque le module est chargé.

start_telegram_bot()


if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
)
