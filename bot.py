import os
import re
import sqlite3
import threading
import logging
from datetime import datetime, timezone

from flask import Flask

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

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_ID = int(
    os.getenv("ADMIN_ID", "5056571209").strip()
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
).strip()

BOT_USERNAME = os.getenv(
    "BOT_USERNAME",
    "Pdgki_bot"
).strip().lstrip("@")

CHANNEL_USERNAME = os.getenv(
    "CHANNEL_USERNAME",
    "canalRM24"
).strip().lstrip("@")


# ============================================================
# VÉRIFICATION
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN absent dans les variables d'environnement."
    )


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# FLASK POUR RENDER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():

    return "BOT OPPORTUNITÉS ACTIF"


@app.route("/health")
def health():

    return "OK"


def run_flask():

    try:

        app.run(
            host="0.0.0.0",
            port=PORT,
            threaded=True,
        )

    except Exception:

        logger.exception(
            "Erreur Flask"
        )


# ============================================================
# BASE DE DONNÉES
# ============================================================

db_lock = threading.RLock()


def get_db():

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False,
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    with db_lock:

        conn = get_db()

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS offres (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                categorie TEXT NOT NULL,

                titre TEXT NOT NULL,

                description TEXT DEFAULT '',

                lien TEXT DEFAULT '',

                telegram_message_id INTEGER UNIQUE,

                date_creation TEXT NOT NULL
            )
            """
        )

        conn.commit()

        conn.close()

    logger.info(
        "Base SQLite prête."
    )


def ajouter_offre(
    categorie,
    titre,
    description="",
    lien="",
    telegram_message_id=None,
):

    with db_lock:

        conn = get_db()

        # ----------------------------------------------------
        # SI LA PUBLICATION EXISTE DÉJÀ
        # ----------------------------------------------------

        if telegram_message_id is not None:

            existante = conn.execute(
                """
                SELECT id
                FROM offres
                WHERE telegram_message_id = ?
                """,
                (
                    telegram_message_id,
                ),
            ).fetchone()

            if existante:

                conn.execute(
                    """
                    UPDATE offres

                    SET categorie = ?,
                        titre = ?,
                        description = ?,
                        lien = ?

                    WHERE telegram_message_id = ?
                    """,
                    (
                        categorie,
                        titre,
                        description,
                        lien,
                        telegram_message_id,
                    ),
                )

                conn.commit()

                offre_id = existante["id"]

                conn.close()

                return offre_id

        # ----------------------------------------------------
        # NOUVELLE OFFRE
        # ----------------------------------------------------

        cursor = conn.execute(
            """
            INSERT INTO offres
            (
                categorie,
                titre,
                description,
                lien,
                telegram_message_id,
                date_creation
            )

            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                categorie,
                titre,
                description,
                lien,
                telegram_message_id,
                datetime.now(
                    timezone.utc
                ).isoformat(),
            ),
        )

        offre_id = cursor.lastrowid

        conn.commit()

        conn.close()

        return offre_id


def offres_categorie(
    categorie,
    limite=10,
):

    with db_lock:

        conn = get_db()

        resultats = conn.execute(
            """
            SELECT *

            FROM offres

            WHERE categorie = ?

            ORDER BY id DESC

            LIMIT ?
            """,
            (
                categorie,
                limite,
            ),
        ).fetchall()

        conn.close()

        return resultats


def offres_recherche(
    texte,
    limite=10,
):

    mots = re.findall(
        r"[A-Za-zÀ-ÿ0-9]+",
        texte.lower(),
    )

    mots = [
        mot
        for mot in mots
        if len(mot) >= 3
    ]

    if not mots:

        return []

    conditions = []

    valeurs = []

    for mot in mots:

        conditions.append(
            """
            (
                LOWER(titre) LIKE ?

                OR

                LOWER(description) LIKE ?
            )
            """
        )

        valeur = f"%{mot}%"

        valeurs.extend(
            [
                valeur,
                valeur,
            ]
        )

    sql = f"""
        SELECT *

        FROM offres

        WHERE {" OR ".join(conditions)}

        ORDER BY id DESC

        LIMIT ?
    """

    valeurs.append(
        limite
    )

    with db_lock:

        conn = get_db()

        resultats = conn.execute(
            sql,
            valeurs,
        ).fetchall()

        conn.close()

        return resultats


# ============================================================
# UTILITAIRES
# ============================================================

def is_admin(update):

    user = update.effective_user

    return (
        user is not None
        and user.id == ADMIN_ID
    )


def safe_text(
    value,
    maximum=3500,
):

    return str(
        value or ""
    )[:maximum]


def html_safe(
    value,
    maximum=3500,
):

    value = safe_text(
        value,
        maximum,
    )

    return (
        value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def bot_link():

    return (
        f"https://t.me/{BOT_USERNAME}"
    )


def channel_link():

    if not CHANNEL_USERNAME:

        return ""

    return (
        f"https://t.me/{CHANNEL_USERNAME}"
    )


def clean_link(value):

    value = str(
        value or ""
    ).strip()

    if not value:

        return ""

    if re.match(
        r"^https?://@",
        value,
        re.IGNORECASE,
    ):

        return ""

    if value.startswith(
        "t.me/"
    ):

        value = (
            "https://" + value
        )

    if value.startswith("@"):

        username = value[1:].strip()

        if re.fullmatch(
            r"[A-Za-z0-9_]{5,32}",
            username,
        ):

            return (
                f"https://t.me/{username}"
            )

        return ""

    if re.match(
        r"^https?://[^\s]+$",
        value,
        re.IGNORECASE,
    ):

        return value

    return ""


# ============================================================
# DÉTECTION DES CATÉGORIES
# ============================================================

def detect_category(text):

    text = str(
        text or ""
    ).lower()

    # --------------------------------------------------------
    # BOURSES
    # --------------------------------------------------------

    if any(
        mot in text
        for mot in (
            "bourse",
            "bourses",
            "scholarship",
            "scholarships",
            "fellowship",
            "fellowships",
            "bourse d'étude",
            "bourse d'études",
            "bourse universitaire",
            "études",
            "study",
        )
    ):

        return "BOURSE"

    # --------------------------------------------------------
    # STAGES RÉMUNÉRÉS
    # --------------------------------------------------------

    if any(
        mot in text
        for mot in (
            "stage rémunéré",
            "stage remunere",
            "stages rémunérés",
            "paid internship",
            "paid internships",
            "paid intern",
            "stipend",
            "stipendié",
            "stipend",
            "rémunéré",
            "remunere",
        )
    ):

        return "STAGE RÉMUNÉRÉ"

    # --------------------------------------------------------
    # EMPLOIS
    # --------------------------------------------------------

    if any(
        mot in text
        for mot in (
            "emploi",
            "emplois",
            "job",
            "jobs",
            "recrutement",
            "recrute",
            "hiring",
            "career",
            "careers",
            "poste",
            "postes",
            "embauche",
            "recruitment",
            "vacancy",
            "vacancies",
        )
    ):

        return "EMPLOI"

    # --------------------------------------------------------
    # STAGE
    # --------------------------------------------------------

    if any(
        mot in text
        for mot in (
            "stage",
            "stages",
            "stagiaire",
            "internship",
            "internships",
            "intern",
            "trainee",
            "traineeship",
        )
    ):

        return "STAGE RÉMUNÉRÉ"

    return None


# ============================================================
# MENU PRINCIPAL
# ============================================================

def main_menu():

    boutons = [

        [
            InlineKeyboardButton(
                "💼 EMPLOI",
                callback_data="EMPLOI",
            ),

            InlineKeyboardButton(
                "🎓 BOURSE",
                callback_data="BOURSE",
            ),
        ],

        [
            InlineKeyboardButton(
                "💰 STAGES RÉMUNÉRÉS",
                callback_data="STAGE",
            )
        ],

        [
            InlineKeyboardButton(
                "🤖 DEMANDER UNE OFFRE",
                url=bot_link(),
            )
        ],
    ]

    canal = channel_link()

    if canal:

        boutons.append(
            [
                InlineKeyboardButton(
                    "📢 VOIR LE CANAL",
                    url=canal,
                )
            ]
        )

    return InlineKeyboardMarkup(
        boutons
    )


# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message is None:

        return

    texte = (
        "<b>🤖 RÉSEAU MONDIAL — ASSISTANT OPPORTUNITÉS</b>\n\n"

        "Bienvenue !\n\n"

        "Je peux rechercher les opportunités "
        "publiées dans notre base :\n\n"

        "💼 <b>Emploi</b>\n"
        "🎓 <b>Bourse</b>\n"
        "💰 <b>Stages rémunérés</b>\n\n"

        "🌍 International et local selon les offres disponibles.\n\n"

        "Écrivez simplement ce que vous recherchez."
    )

    await update.message.reply_text(
        texte,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


async def aide(
    update,
    context,
):

    await start(
        update,
        context,
    )


# ============================================================
# AFFICHER UNE OFFRE
# ============================================================

async def send_offer(
    message,
    offer,
):

    categorie = html_safe(
        offer["categorie"],
        80,
    )

    titre = html_safe(
        offer["titre"],
        700,
    )

    description = html_safe(
        offer["description"],
        2500,
    )

    lien = clean_link(
        offer["lien"]
    )

    texte = (
        f"📂 <b>{categorie}</b>\n\n"

        f"📌 <b>{titre}</b>\n\n"

        f"{description}\n\n"

        "👇 <b>Pour plus d'informations :</b>"
    )

    boutons = []

    if lien:

        boutons.append(
            InlineKeyboardButton(
                "👉 CANDIDATER",
                url=lien,
            )
        )

    boutons.append(
        InlineKeyboardButton(
            "🤖 DEMANDER UNE OFFRE",
            url=bot_link(),
        )
    )

    canal = channel_link()

    if canal:

        boutons.append(
            InlineKeyboardButton(
                "📢 VOIR LE CANAL",
                url=canal,
            )
        )

    await message.reply_text(
        texte,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            [
                boutons
            ]
        ),
    )


# ============================================================
# BOUTONS CATÉGORIES
# ============================================================

async def category_callback(
    update,
    context,
):

    query = update.callback_query

    await query.answer()

    categorie = query.data

    resultats = offres_categorie(
        categorie,
        10,
    )

    if not resultats:

        await query.message.reply_text(
            f"🔎 Aucune offre {categorie} "
            "n'est actuellement enregistrée.",
            reply_markup=main_menu(),
        )

        return

    await query.message.reply_text(
        f"🔎 {len(resultats)} "
        f"opportunité(s) {categorie} trouvée(s)."
    )

    for offre in resultats:

        try:

            await send_offer(
                query.message,
                offre,
            )

        except Exception:

            logger.exception(
                "Affichage offre"
            )


# ============================================================
# RECHERCHE UTILISATEUR
# ============================================================

async def user_search(
    update,
    context,
):

    if update.message is None:

        return

    texte = (
        update.message.text or ""
    ).strip()

    if not texte:

        return

    categorie = detect_category(
        texte
    )

    if categorie:

        resultats = offres_categorie(
            categorie,
            10,
        )

    else:

        resultats = offres_recherche(
            texte,
            10,
        )

    if resultats:

        await update.message.reply_text(
            f"🔎 {len(resultats)} "
            "opportunité(s) trouvée(s)."
        )

        for offre in resultats:

            try:

                await send_offer(
                    update.message,
                    offre,
                )

            except Exception:

                logger.exception(
                    "Affichage recherche"
                )

        return

    await update.message.reply_text(
        "🔎 Aucune opportunité correspondant "
        "à votre recherche n'est actuellement "
        "enregistrée.\n\n"

        "Essayez par exemple :\n\n"

        "💼 emploi informatique\n"
        "🎓 bourse Canada\n"
        "💰 stage rémunéré informatique",
        reply_markup=main_menu(),
    )


# ============================================================
# AJOUTER UNE OFFRE MANUELLEMENT
# ============================================================

async def ajouter(
    update,
    context,
):

    if update.message is None:

        return

    if not is_admin(update):

        await update.message.reply_text(
            "⛔ Cette commande est réservée "
            "à l'administrateur."
        )

        return

    try:

        contenu = (
            update.message.text or ""
        )

        contenu = re.sub(
            r"^/ajouter(?:@\w+)?",
            "",
            contenu,
            count=1,
            flags=re.IGNORECASE,
        ).strip()

        parties = [
            partie.strip()
            for partie in contenu.split("|")
        ]

        if len(parties) < 3:

            await update.message.reply_text(
                "ℹ️ Utilisez :\n\n"

                "/ajouter EMPLOI | Titre | "
                "Description | Lien\n\n"

                "Catégories :\n"
                "EMPLOI\n"
                "BOURSE\n"
                "STAGE RÉMUNÉRÉ"
            )

            return

        categorie = (
            parties[0]
            .upper()
            .strip()
        )

        titre = parties[1].strip()

        description = parties[2].strip()

        lien = ""

        if len(parties) >= 4:

            lien = clean_link(
                parties[3]
            )

        if categorie == "STAGE":

            categorie = "STAGE RÉMUNÉRÉ"

        if categorie not in (
            "EMPLOI",
            "BOURSE",
            "STAGE RÉMUNÉRÉ",
        ):

            await update.message.reply_text(
                "⛔ Catégorie invalide."
            )

            return

        if not titre:

            await update.message.reply_text(
                "⛔ Le titre est obligatoire."
            )

            return

        if not description:

            description = (
                "Informations disponibles "
                "pour cette opportunité."
            )

        offre_id = ajouter_offre(
            categorie=categorie,
            titre=titre,
            description=description,
            lien=lien,
        )

        await update.message.reply_text(
            "✅ <b>OFFRE ENREGISTRÉE</b>\n\n"

            f"📂 {html_safe(categorie)}\n"
            f"📌 {html_safe(titre)}\n"
            f"🆔 Référence : <b>{offre_id}</b>",
            parse_mode=ParseMode.HTML,
        )

    except Exception:

        logger.exception(
            "Commande /ajouter"
        )

        await update.message.reply_text(
            "⚠️ Impossible d'enregistrer l'offre."
        )


# ============================================================
# SYNCHRONISATION AUTOMATIQUE DU CANAL
# ============================================================

async def canal_post_automatique(
    update,
    context,
):

    post = (
        update.channel_post
        or update.edited_channel_post
    )

    if post is None:

        return

    # --------------------------------------------------------
    # VÉRIFICATION DU CANAL
    # --------------------------------------------------------

    username = (
        post.chat.username or ""
    ).lower()

    configured_username = (
        CHANNEL_USERNAME or ""
    ).lower()

    canal_correct = (
        username == configured_username
        or str(post.chat.id) == str(CHANNEL_ID)
    )

    if not canal_correct:

        logger.warning(
            "Publication ignorée : mauvais canal."
        )

        return

    # --------------------------------------------------------
    # RÉCUPÉRER LE TEXTE
    # --------------------------------------------------------

    texte = (
        post.text
        or post.caption
        or ""
    ).strip()

    if not texte:

        logger.info(
            "Publication sans texte ignorée."
        )

        return

    # --------------------------------------------------------
    # DÉTECTION CATÉGORIE
    # --------------------------------------------------------

    categorie = detect_category(
        texte
    )

    # Si aucune catégorie évidente,
    # classement par défaut en EMPLOI.

    if categorie is None:

        categorie = "EMPLOI"

    # --------------------------------------------------------
    # TITRE
    # --------------------------------------------------------

    lignes = [
        ligne.strip()
        for ligne in texte.splitlines()
        if ligne.strip()
    ]

    if lignes:

        titre = lignes[0][:700]

    else:

        titre = "Nouvelle opportunité"

    # --------------------------------------------------------
    # DESCRIPTION
    # --------------------------------------------------------

    description = texte[:3500]

    # --------------------------------------------------------
    # EXTRACTION DU LIEN
    # --------------------------------------------------------

    liens = re.findall(
        r"https?://[^\s<>]+",
        texte,
        flags=re.IGNORECASE,
    )

    lien = ""

    if liens:

        lien = clean_link(
            liens[0].rstrip(
                ".,;)"
            )
        )

    # --------------------------------------------------------
    # ENREGISTREMENT / MISE À JOUR
    # --------------------------------------------------------

    offre_id = ajouter_offre(
        categorie=categorie,
        titre=titre,
        description=description,
        lien=lien,
        telegram_message_id=post.message_id,
    )

    logger.info(
        "✅ CANAL → SITE | "
        "offre=%s | "
        "catégorie=%s | "
        "message=%s",
        offre_id,
        categorie,
        post.message_id,
    )


# ============================================================
# TEST DU CANAL
# ============================================================

async def testcanal(
    update,
    context,
):

    if update.message is None:

        return

    if not is_admin(update):

        await update.message.reply_text(
            "⛔ Accès réservé à l'administrateur."
        )

        return

    try:

        await context.bot.send_message(
            chat_id=CHANNEL_ID,

            text=(
                "✅ <b>TEST DU CANAL</b>\n\n"
                "🤖 Le bot est connecté au canal."
            ),

            parse_mode=ParseMode.HTML,

            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🤖 DEMANDER UNE OFFRE",
                            url=bot_link(),
                        )
                    ]
                ]
            ),
        )

        await update.message.reply_text(
            "✅ Test réussi : le bot peut "
            "publier dans le canal."
        )

    except Exception:

        logger.exception(
            "Test canal"
        )

        await update.message.reply_text(
            "⚠️ Impossible de publier dans le canal.\n\n"
            "Vérifie que le bot est administrateur."
        )


# ============================================================
# PUBLICATION DU BOUTON BOT
# ============================================================

async def publier_bot(
    update,
    context,
):

    if update.message is None:

        return

    if not is_admin(update):

        await update.message.reply_text(
            "⛔ Accès réservé à l'administrateur."
        )

        return

    texte = (
        "🤖 <b>BESOIN D'UNE OPPORTUNITÉ ?</b>\n\n"

        "💼 Emploi\n"
        "🎓 Bourse\n"
        "💰 Stage rémunéré\n\n"

        "Cliquez ci-dessous et indiquez "
        "ce que vous recherchez."
    )

    try:

        await context.bot.send_message(
            chat_id=CHANNEL_ID,

            text=texte,

            parse_mode=ParseMode.HTML,

            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🤖 DEMANDER UNE OFFRE",
                            url=bot_link(),
                        )
                    ]
                ]
            ),
        )

        await update.message.reply_text(
            "✅ Publication effectuée dans le canal."
        )

    except Exception:

        logger.exception(
            "Publication bouton bot"
        )

        await update.message.reply_text(
            "⚠️ Publication impossible."
        )


# ============================================================
# STATISTIQUES
# ============================================================

async def stats(
    update,
    context,
):

    if update.message is None:

        return

    if not is_admin(update):

        await update.message.reply_text(
            "⛔ Accès réservé à l'administrateur."
        )

        return

    with db_lock:

        conn = get_db()

        total = conn.execute(
            "SELECT COUNT(*) FROM offres"
        ).fetchone()[0]

        emplois = conn.execute(
            """
            SELECT COUNT(*)
            FROM offres
            WHERE categorie = 'EMPLOI'
            """
        ).fetchone()[0]

        bourses = conn.execute(
            """
            SELECT COUNT(*)
            FROM offres
            WHERE categorie = 'BOURSE'
            """
        ).fetchone()[0]

        stages = conn.execute(
            """
            SELECT COUNT(*)
            FROM offres
            WHERE categorie = 'STAGE RÉMUNÉRÉ'
            """
        ).fetchone()[0]

        conn.close()

    await update.message.reply_text(
        "📊 <b>STATISTIQUES</b>\n\n"

        f"📚 Total : <b>{total}</b>\n"

        f"💼 Emplois : <b>{emplois}</b>\n"

        f"🎓 Bourses : <b>{bourses}</b>\n"

        f"💰 Stages rémunérés : <b>{stages}</b>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# ERREUR GLOBALE
# ============================================================

async def error_handler(
    update,
    context,
):

    logger.error(
        "Erreur Telegram : %s",
        context.error,
    )


# ============================================================
# DÉMARRAGE
# ============================================================

def main():

    # Base de données
    init_db()

    # Serveur Render
    threading.Thread(
        target=run_flask,
        daemon=True,
    ).start()

    # Application Telegram
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # COMMANDES
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "aide",
            aide,
        )
    )

    application.add_handler(
        CommandHandler(
            "ajouter",
            ajouter,
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats,
        )
    )

    application.add_handler(
        CommandHandler(
            "testcanal",
            testcanal,
        )
    )

    application.add_handler(
        CommandHandler(
            "canal",
            publier_bot,
        )
    )

    # --------------------------------------------------------
    # BOUTONS
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            category_callback,
            pattern=r"^(EMPLOI|BOURSE|STAGE)$",
        )
    )

    # --------------------------------------------------------
    # SYNCHRONISATION AUTOMATIQUE DU CANAL
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST,
            canal_post_automatique,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.UpdateType.EDITED_CHANNEL_POST,
            canal_post_automatique,
        )
    )

    # --------------------------------------------------------
    # RECHERCHE DES UTILISATEURS
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            user_search,
        )
    )

    # --------------------------------------------------------
    # GESTION DES ERREURS
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "=========================================="
    )

    logger.info(
        "🤖 BOT OPPORTUNITÉS DÉMARRÉ"
    )

    logger.info(
        "📢 Canal : @%s",
        CHANNEL_USERNAME,
    )

    logger.info(
        "🔄 Synchronisation automatique activée"
    )

    logger.info(
        "=========================================="
    )

    # --------------------------------------------------------
    # POLLING
    # --------------------------------------------------------

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":

    main()
