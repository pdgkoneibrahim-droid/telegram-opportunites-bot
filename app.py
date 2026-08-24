import os
import sqlite3
import asyncio
import threading
import logging
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

DB_FILE = "opportunites.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


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
}

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

    connection.commit()
    connection.close()


init_db()


# ============================================================
# UTILITAIRES ADMIN WEB
# ============================================================

def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):

        if not session.get("admin"):
            return redirect(url_for("admin_login"))

        return function(*args, **kwargs)

    return wrapper


# ============================================================
# UTILITAIRES ADMIN TELEGRAM
# ============================================================

def is_telegram_admin(update: Update) -> bool:

    if not update.effective_user:
        return False

    if not ADMIN_TELEGRAM_ID:
        return False

    try:
        return (
            str(update.effective_user.id)
            == str(ADMIN_TELEGRAM_ID)
        )

    except Exception:
        return False


async def telegram_admin_required(
    update: Update
) -> bool:

    if is_telegram_admin(update):
        return True

    if update.message:

        await update.message.reply_text(
            "❌ Commande réservée à l'administrateur."
        )

    return False


# ============================================================
# ENREGISTREMENT UTILISATEURS TELEGRAM
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
# ADZUNA
# ============================================================

def is_paid_internship(
    text,
    salary_min=None,
    salary_max=None
):

    text = (text or "").lower()

    if salary_min is not None or salary_max is not None:
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

    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []

    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": 20,
        "content-type": "application/json",
    }

    if keyword:
        params["what"] = keyword

    if remunerated:

        params["what"] = (
            f"{keyword} paid internship"
            if keyword
            else "paid internship"
        )

    url = (
        "https://api.adzuna.com/v1/api/jobs/"
        f"{country}/search/{page}"
    )

    response = requests.get(
        url,
        params=params,
        timeout=20,
        headers={
            "Accept": "application/json",
            "User-Agent": (
                "OpportunitesInternationales/1.0"
            ),
        },
    )

    response.raise_for_status()

    return response.json().get(
        "results",
        []
    )


def enregistrer_offres(
    offres,
    country,
    categorie
):

    connection = db()

    nombre = 0

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
            titre
            + " "
            + description
            + " "
            + str(
                category.get(
                    "label",
                    ""
                )
                or ""
            )
        ).lower()

        categorie_finale = categorie

        if (
            categorie == "Stage rémunéré"
            or is_paid_internship(
                texte,
                salaire_min,
                salaire_max
            )
        ):

            if any(
                word in texte
                for word in (
                    "internship",
                    "intern",
                    "trainee",
                    "stage",
                    "placement",
                    "rémun",
                    "remuner",
                    "paid",
                )
            ):
                categorie_finale = (
                    "Stage rémunéré"
                )

        try:

            connection.execute("""
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
                    source
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?
                )
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
            ))

            nombre += 1

        except sqlite3.IntegrityError:
            pass

    connection.commit()
    connection.close()

    return nombre


# ============================================================
# MENU TELEGRAM
# ============================================================

def menu_keyboard():

    keyboard = [

        [
            InlineKeyboardButton(
                "💼 EMPLOI",
                callback_data="cat_emploi"
            ),
            InlineKeyboardButton(
                "🎓 STAGE",
                callback_data="cat_stage"
            ),
        ],

        [
            InlineKeyboardButton(
                "🎓 BOURSE",
                callback_data="cat_bourse"
            ),
        ],

        [
            InlineKeyboardButton(
                "🤖 DEMANDER UNE OFFRE",
                callback_data="demander_offre"
            ),
        ],

        [
            InlineKeyboardButton(
                "📢 VOIR LE CANAL",
                url="https://t.me/canalRM24"
            ),
        ],
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


MENU_TEXT = """
🌍 <b>RESEAU MONDIAL</b>

💼 <b>EMPLOI</b>
🎓 <b>STAGE</b>
🎓 <b>BOURSE</b>

🤖 <b>DEMANDER UNE OFFRE</b>

📢 Retrouvez toutes les opportunités
dans notre canal Telegram.

👇 Choisissez une option :
"""


async def envoyer_menu(
    bot,
    chat_id
):

    try:

        await bot.send_message(
            chat_id=chat_id,
            text=MENU_TEXT,
            parse_mode=ParseMode.HTML,
            reply_markup=menu_keyboard(),
            disable_web_page_preview=True,
        )

        return True

    except Exception as error:

        logger.exception(
            "Erreur envoi menu : %s",
            error
        )

        return False


# ============================================================
# PUBLICATION MENU CANAL
# ============================================================

async def publier_menu_canal(
    bot
):

    try:

        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=MENU_TEXT,
            parse_mode=ParseMode.HTML,
            reply_markup=menu_keyboard(),
            disable_web_page_preview=True,
        )

        logger.info(
            "Menu publié dans %s",
            CHANNEL_ID
        )

        return True

    except Exception as error:

        logger.exception(
            "Erreur publication menu canal : %s",
            error
        )

        return False


async def menu_toutes_les_2_heures(
    context: ContextTypes.DEFAULT_TYPE
):

    logger.info(
        "Publication automatique du menu..."
    )

    await publier_menu_canal(
        context.bot
    )


# ============================================================
# /START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_user:
        return

    enregistrer_utilisateur(
        update.effective_user
    )

    await envoyer_menu(
        context.bot,
        update.effective_chat.id
    )


# ============================================================
# /MENU
# ============================================================

async def menu_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_chat:
        return

    await envoyer_menu(
        context.bot,
        update.effective_chat.id
    )


# ============================================================
# /ID
# ============================================================

async def id_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_user:
        return

    await update.message.reply_text(
        "🆔 Votre Telegram ID :\n\n"
        f"{update.effective_user.id}"
    )


# ============================================================
# /TESTCANAL
# ============================================================

async def testcanal_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await telegram_admin_required(
        update
    ):
        return

    try:

        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                "🧪 <b>TEST RÉUSSI</b>\n\n"
                "Le bot peut publier dans "
                "le canal <b>@canalRM24</b>."
            ),
            parse_mode=ParseMode.HTML,
        )

        await update.message.reply_text(
            "✅ Test réussi : le bot peut "
            "publier dans le canal."
        )

        logger.info(
            "Test canal réussi : message %s",
            message.message_id
        )

    except Exception as error:

        logger.exception(
            "Erreur test canal : %s",
            error
        )

        await update.message.reply_text(
            "❌ Échec de publication dans "
            "le canal.\n\n"
            f"Erreur : {str(error)[:700]}"
        )


# ============================================================
# /AJOUTER
# ============================================================

async def ajouter_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await telegram_admin_required(
        update
    ):
        return

    texte = (
        update.message.text
        or ""
    ).strip()

    contenu = texte[
        len("/ajouter"):
    ].strip()

    morceaux = [
        morceau.strip()
        for morceau in contenu.split("|")
    ]

    if len(morceaux) < 4:

        await update.message.reply_text(
            "❌ Format incorrect.\n\n"
            "Utilise :\n"
            "/ajouter CATEGORIE | TITRE | "
            "DESCRIPTION | LIEN\n\n"
            "Exemple :\n"
            "/ajouter STAGE | "
            "Bourse Oxford | "
            "Entièrement financée au Royaume-Uni | "
            "https://example.com"
        )

        return

    categorie = morceaux[0]
    titre = morceaux[1]
    description = morceaux[2]
    lien = morceaux[3]

    if not titre:

        await update.message.reply_text(
            "❌ Le titre est obligatoire."
        )

        return

    connection = db()

    cursor = connection.execute("""
        INSERT INTO telegram_offres (
            categorie,
            titre,
            description,
            lien
        )
        VALUES (?, ?, ?, ?)
    """, (
        categorie,
        titre,
        description,
        lien,
    ))

    offre_id = cursor.lastrowid

    connection.commit()
    connection.close()

    texte_canal = (
        "🌍 <b>RESEAU MONDIAL</b>\n\n"
        f"📂 <b>{categorie.upper()}</b>\n\n"
        f"📌 <b>{titre}</b>\n\n"
        f"{description}\n\n"
        f"🔗 {lien}\n\n"
        f"🆔 Référence : {offre_id}"
    )

    try:

        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=texte_canal,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
        )

        connection = db()

        connection.execute("""
            UPDATE telegram_offres
            SET telegram_message_id = ?
            WHERE id = ?
        """, (
            message.message_id,
            offre_id,
        ))

        connection.commit()
        connection.close()

        await update.message.reply_text(
            "✅ <b>OFFRE PUBLIÉE</b>\n\n"
            f"📂 {categorie}\n"
            f"📌 {titre}\n"
            f"🆔 Référence : {offre_id}\n\n"
            "📢 Elle est maintenant disponible "
            "dans le canal et dans la recherche "
            "du bot.",
            parse_mode=ParseMode.HTML,
        )

    except Exception as error:

        logger.exception(
            "Erreur publication offre : %s",
            error
        )

        await update.message.reply_text(
            "⚠️ Offre enregistrée, mais la "
            "publication dans le canal a échoué.\n\n"
            f"Erreur : {str(error)[:700]}"
        )


# ============================================================
# ENVOI DIRECT DES MESSAGES ADMIN AU CANAL
# ============================================================

async def publier_message_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not is_telegram_admin(update):

        # Les autres utilisateurs peuvent
        # utiliser le bot pour rechercher.
        await rechercher_demande(
            update,
            context
        )

        return

    texte = (
        update.message.text
        or ""
    ).strip()

    if not texte:
        return

    try:

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=texte,
            disable_web_page_preview=False,
        )

        await update.message.reply_text(
            "✅ Message publié dans le canal."
        )

        logger.info(
            "Message admin publié dans le canal."
        )

    except Exception as error:

        logger.exception(
            "Erreur publication message admin : %s",
            error
        )

        await update.message.reply_text(
            "❌ Impossible de publier le message.\n\n"
            f"Erreur : {str(error)[:700]}"
        )


# ============================================================
# RECHERCHE DES OFFRES TELEGRAM
# ============================================================

def rechercher_offres_telegram(
    recherche,
    categorie=None,
    limite=10
):

    recherche = (
        recherche
        or ""
    ).strip().lower()

    connection = db()

    if categorie:

        rows = connection.execute("""
            SELECT *
            FROM telegram_offres
            WHERE lower(categorie) LIKE ?
              AND (
                    lower(titre) LIKE ?
                    OR lower(description) LIKE ?
                  )
            ORDER BY id DESC
            LIMIT ?
        """, (
            f"%{categorie.lower()}%",
            f"%{recherche}%",
            f"%{recherche}%",
            limite,
        )).fetchall()

    else:

        rows = connection.execute("""
            SELECT *
            FROM telegram_offres
            WHERE lower(titre) LIKE ?
               OR lower(description) LIKE ?
               OR lower(categorie) LIKE ?
            ORDER BY id DESC
            LIMIT ?
        """, (
            f"%{recherche}%",
            f"%{recherche}%",
            f"%{recherche}%",
            limite,
        )).fetchall()

    connection.close()

    return rows


async def envoyer_offres_telegram(
    update,
    offres,
    titre="🔎 OFFRES DISPONIBLES"
):

    if not offres:

        await update.message.reply_text(
            "😔 Aucune offre correspondante "
            "n'a été trouvée pour le moment.\n\n"
            "📢 Consulte également notre canal :\n"
            "https://t.me/canalRM24"
        )

        return

    texte = f"{titre}\n\n"

    for offre in offres:

        texte += (
            f"📌 <b>{offre['titre']}</b>\n"
            f"📂 {offre['categorie']}\n"
        )

        if offre["description"]:
            texte += (
                f"📝 {offre['description'][:500]}\n"
            )

        if offre["lien"]:
            texte += (
                f"🔗 {offre['lien']}\n"
            )

        texte += (
            f"🆔 Référence : {offre['id']}\n"
            "━━━━━━━━━━━━━━\n"
        )

    await update.message.reply_text(
        texte,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=False,
    )


# ============================================================
# DEMANDE D'OFFRE
# ============================================================

async def demander_offre_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    context.user_data[
        "attente_recherche"
    ] = True

    await query.message.reply_text(
        "🤖 <b>DEMANDER UNE OFFRE</b>\n\n"
        "Écris ce que tu recherches.\n\n"
        "Exemples :\n"
        "• ingénieur informatique\n"
        "• stage en Belgique\n"
        "• bourse au Canada\n"
        "• emploi en France\n"
        "• stage rémunéré\n\n"
        "🔎 Le bot recherchera les offres "
        "correspondantes.",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# CALLBACK CATÉGORIES
# ============================================================

async def categorie_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    data = query.data

    if data == "cat_emploi":

        categorie = "emploi"
        titre = "💼 EMPLOIS DISPONIBLES"

    elif data == "cat_stage":

        categorie = "stage"
        titre = "🎓 STAGES DISPONIBLES"

    elif data == "cat_bourse":

        categorie = "bourse"
        titre = "🎓 BOURSES DISPONIBLES"

    else:
        return

    offres = rechercher_offres_telegram(
        "",
        categorie=categorie,
        limite=10
    )

    if not offres:

        await query.message.reply_text(
            f"{titre}\n\n"
            "😔 Aucune offre n'est encore "
            "enregistrée dans cette catégorie.\n\n"
            "📢 Consulte le canal :\n"
            "https://t.me/canalRM24"
        )

        return

    texte = (
        f"<b>{titre}</b>\n\n"
    )

    for offre in offres:

        texte += (
            f"📌 <b>{offre['titre']}</b>\n"
            f"📝 {offre['description'][:400]}\n"
        )

        if offre["lien"]:

            texte += (
                f"🔗 {offre['lien']}\n"
            )

        texte += (
            f"🆔 Référence : {offre['id']}\n"
            "━━━━━━━━━━━━━━\n"
        )

    await query.message.reply_text(
        texte,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=False,
    )


# ============================================================
# RECHERCHE UTILISATEUR
# ============================================================

async def rechercher_demande(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    texte = (
        update.message.text
        or ""
    ).strip()

    if not texte:
        return

    enregistrer_utilisateur(
        update.effective_user
    )

    offres = rechercher_offres_telegram(
        texte,
        limite=10
    )

    if offres:

        await envoyer_offres_telegram(
            update,
            offres
        )

        return

    # Recherche Adzuna si aucune offre locale
    if ADZUNA_APP_ID and ADZUNA_APP_KEY:

        try:

            offres_api = rechercher_adzuna(
                country="ca",
                keyword=texte,
                page=1,
                remunerated=False,
            )

            if offres_api:

                enregistrer_offres(
                    offres_api,
                    "ca",
                    "Emploi"
                )

                await update.message.reply_text(
                    "🔎 J'ai trouvé des offres "
                    "correspondantes sur notre "
                    "source internationale.\n\n"
                    "🌐 Consulte le site :\n"
                    "https://telegram-opportunites-bot."
                    "onrender.com"
                )

                return

        except Exception as error:

            logger.warning(
                "Recherche Adzuna utilisateur : %s",
                error
            )

    await update.message.reply_text(
        "🔎 Je n'ai pas trouvé d'offre "
        "correspondante pour le moment.\n\n"
        "Essaie avec d'autres mots-clés.\n\n"
        "Exemple :\n"
        "💼 ingénieur\n"
        "🎓 bourse Canada\n"
        "🎓 stage Belgique\n\n"
        "📢 Canal : https://t.me/canalRM24"
    )


# ============================================================
# /STATS
# ============================================================

async def stats_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await telegram_admin_required(
        update
    ):
        return

    connection = db()

    offres = connection.execute(
        "SELECT COUNT(*) AS total FROM telegram_offres"
    ).fetchone()["total"]

    utilisateurs = connection.execute(
        "SELECT COUNT(*) AS total FROM utilisateurs"
    ).fetchone()["total"]

    connection.close()

    await update.message.reply_text(
        "📊 <b>STATISTIQUES</b>\n\n"
        f"📌 Offres : {offres}\n"
        f"👥 Utilisateurs : {utilisateurs}",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# GESTION ERREURS TELEGRAM
# ============================================================

async def telegram_error_handler(
    update,
    context
):

    logger.exception(
        "Erreur Telegram : %s",
        context.error
    )


# ============================================================
# DÉMARRAGE DU BOT
# ============================================================

telegram_application = None
telegram_thread = None


def lancer_bot_telegram():

    global telegram_application

    if not BOT_TOKEN:

        logger.warning(
            "BOT_TOKEN absent. "
            "Le bot Telegram ne sera pas lancé."
        )

        return

    try:

        telegram_application = (
            Application
            .builder()
            .token(BOT_TOKEN)
            .build()
        )

        # ----------------------------------------------------
        # COMMANDES
        # ----------------------------------------------------

        telegram_application.add_handler(
            CommandHandler(
                "start",
                start_command
            )
        )

        telegram_application.add_handler(
            CommandHandler(
                "menu",
                menu_command
            )
        )

        telegram_application.add_handler(
            CommandHandler(
                "id",
                id_command
            )
        )

        telegram_application.add_handler(
            CommandHandler(
                "testcanal",
                testcanal_command
            )
        )

        telegram_application.add_handler(
            CommandHandler(
                "ajouter",
                ajouter_command
            )
        )

        telegram_application.add_handler(
            CommandHandler(
                "stats",
                stats_command
            )
        )

        # ----------------------------------------------------
        # BOUTONS
        # ----------------------------------------------------

        telegram_application.add_handler(
            CallbackQueryHandler(
                demander_offre_callback,
                pattern="^demander_offre$"
            )
        )

        telegram_application.add_handler(
            CallbackQueryHandler(
                categorie_callback,
                pattern="^cat_"
            )
        )

        # ----------------------------------------------------
        # MESSAGES TEXTE
        # ----------------------------------------------------

        telegram_application.add_handler(
            MessageHandler(
                filters.TEXT
                & ~filters.COMMAND,
                message_texte_handler
            )
        )

        telegram_application.add_error_handler(
            telegram_error_handler
        )

        # ----------------------------------------------------
        # MENU AUTOMATIQUE TOUTES LES 2 HEURES
        # ----------------------------------------------------

        if telegram_application.job_queue:

            telegram_application.job_queue.run_repeating(
                menu_toutes_les_2_heures,
                interval=7200,
                first=30,
                name="menu_2_heures",
            )

            logger.info(
                "Publication automatique "
                "toutes les 2 heures activée."
            )

        else:

            logger.error(
                "JobQueue indisponible. "
                "Vérifie python-telegram-bot[job-queue]."
            )

        logger.info(
            "Démarrage du bot Telegram..."
        )

        telegram_application.run_polling(
            drop_pending_updates=True,
            stop_signals=None,
            close_loop=False,
        )

    except Exception as error:

        logger.exception(
            "ERREUR DÉMARRAGE BOT TELEGRAM : %s",
            error
        )


def demarrer_bot_en_arriere_plan():

    global telegram_thread

    if not BOT_TOKEN:
        return

    if (
        telegram_thread
        and telegram_thread.is_alive()
    ):
        return

    telegram_thread = threading.Thread(
        target=lancer_bot_telegram,
        daemon=True,
        name="telegram-bot-thread"
    )

    telegram_thread.start()

    logger.info(
        "Thread Telegram lancé."
    )


# ============================================================
# HANDLER TEXTE CENTRAL
# ============================================================

async def message_texte_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    texte = (
        update.message.text
        or ""
    ).strip()

    if not texte:
        return

    # --------------------------------------------------------
    # ADMIN
    # Tout message texte de l'admin est publié directement
    # dans le canal.
    # --------------------------------------------------------

    if is_telegram_admin(update):

        await publier_message_admin(
            update,
            context
        )

        return

    # --------------------------------------------------------
    # UTILISATEUR
    # Recherche d'une offre
    # --------------------------------------------------------

    await rechercher_demande(
        update,
        context
    )


# ============================================================
# SITE WEB - ACCUEIL
# ============================================================

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
            categorie == "stage_remunere"
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

            logger.warning(
                "Erreur Adzuna : %s",
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
            (
                'Emploi',
                'Bourse',
                'Bourses',
                'Stage rémunéré'
            )
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


# ============================================================
# ADMIN WEB
# ============================================================

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

        if ADMIN_KEY and key == ADMIN_KEY:

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


# ============================================================
# HTML DU SITE
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

<a class="admin" href="/admin/login">
⚙️ Administration
</a>

<h1>
🌍 Opportunités internationales
</h1>

<p>
💼 Emplois • 🎓 Bourses • 💰 Stages rémunérés
</p>

<p>
Trouvez des opportunités internationales
et locales selon les offres disponibles.
</p>

<p>
📢
<a href="https://t.me/canalRM24"
target="_blank">
Rejoindre notre canal Telegram
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
{% if code == country %}selected{% endif %}
>
{{ name }}
</option>

{% endfor %}

</select>

<select name="categorie">

<option value="emploi"
{% if categorie == "emploi" %}selected{% endif %}
>
💼 Emplois
</option>

<option value="bourse"
{% if categorie == "bourse" %}selected{% endif %}
>
🎓 Bourses
</option>

<option value="stage_remunere"
{% if categorie == "stage_remunere" %}selected{% endif %}
>
💰 Stages rémunérés
</option>

<option value="tous"
{% if categorie == "tous" %}selected{% endif %}
>
Toutes les catégories
</option>

</select>

<button name="search" value="1">
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
🏢
<b>{{ offre["entreprise"] }}</b>
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

{% if offre["salaire_min"] or offre["salaire_max"] %}

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
🔎 Aucune offre enregistrée pour cette recherche.
</h2>

<p>
Effectuez une recherche pour récupérer
les offres disponibles.
</p>

</div>

{% endif %}

</div>

</body>

</html>
"""


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
{{ offres|length }} offres affichées.
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

<a href="/admin/modifier/{{ offre["id"] }}">
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

<option value="Emploi"
{% if offre["categorie"] == "Emploi" %}
selected
{% endif %}
>
💼 Emploi
</option>

<option value="Bourse"
{% if offre["categorie"] == "Bourse" %}
selected
{% endif %}
>
🎓 Bourse
</option>

<option value="Stage rémunéré"
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
# LANCEMENT FLASK + BOT
# ============================================================

demarrer_bot_en_arriere_plan()


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
