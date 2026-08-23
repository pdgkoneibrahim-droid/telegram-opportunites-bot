import os
import re
import html
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

ADMIN_ID_RAW = os.getenv("ADMIN_ID", "5056571209").strip()

CHANNEL_ID = os.getenv(
    "CHANNEL_ID",
    "@canalRM24"
).strip()

PORT_RAW = os.getenv(
    "PORT",
    "10000"
).strip()

DB_PATH = os.getenv(
    "DB_PATH",
    "opportunites.db"
).strip()

BOT_USERNAME = os.getenv(
    "BOT_USERNAME",
    "Pdgki_bot"
).strip().lstrip("@")

# ------------------------------------------------------------
# Validation configuration
# ------------------------------------------------------------

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN manquant. "
        "Ajoute BOT_TOKEN dans Render > Environment."
    )

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    raise RuntimeError(
        "ADMIN_ID invalide. Il doit être un nombre Telegram."
    )

try:
    PORT = int(PORT_RAW)
except ValueError:
    PORT = 10000


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# FLASK / RENDER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "🤖 Bot Opportunités actif.", 200


@app.route("/health")
def health():
    return "OK", 200


def run_flask():
    try:
        app.run(
            host="0.0.0.0",
            port=PORT,
            threaded=True,
            use_reloader=False,
        )
    except Exception:
        logger.exception("Erreur Flask")


# ============================================================
# BASE DE DONNÉES
# ============================================================

db_lock = threading.Lock()


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

        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS offres (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    categorie TEXT NOT NULL,
                    titre TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    lien TEXT DEFAULT '',
                    telegram_message_id INTEGER,
                    date_creation TEXT NOT NULL
                )
            """)

            conn.commit()

        finally:
            conn.close()

    logger.info("Base de données initialisée.")


def ajouter_offre(
    categorie,
    titre,
    description="",
    lien="",
    telegram_message_id=None,
):
    with db_lock:
        conn = get_db()

        try:
            cursor = conn.execute(
                """
                INSERT INTO offres (
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
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

            offre_id = cursor.lastrowid

            conn.commit()

            return offre_id

        finally:
            conn.close()


def offres_categorie(categorie, limite=10):
    conn = get_db()

    try:
        return conn.execute(
            """
            SELECT *
            FROM offres
            WHERE categorie = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                categorie,
                int(limite),
            ),
        ).fetchall()

    finally:
        conn.close()


def offres_recherche(texte, limite=10):
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
                OR LOWER(description) LIKE ?
            )
            """
        )

        valeur = f"%{mot}%"

        valeurs.extend([
            valeur,
            valeur,
        ])

    sql = f"""
        SELECT *
        FROM offres
        WHERE {" OR ".join(conditions)}
        ORDER BY id DESC
        LIMIT ?
    """

    valeurs.append(int(limite))

    conn = get_db()

    try:
        return conn.execute(
            sql,
            valeurs,
        ).fetchall()

    finally:
        conn.close()


# ============================================================
# UTILITAIRES
# ============================================================

def is_admin(update: Update):
    user = update.effective_user

    return (
        user is not None
        and user.id == ADMIN_ID
    )


def safe_text(value, maximum=3500):
    value = str(value or "")

    return value[:maximum]


def escape_html(value, maximum=3500):
    value = safe_text(
        value,
        maximum,
    )

    return html.escape(
        value,
        quote=False,
    )


def bot_link():
    return f"https://t.me/{BOT_USERNAME}"


def channel_link():
    if CHANNEL_ID.startswith("@"):
        username = CHANNEL_ID[1:]

        if username:
            return f"https://t.me/{username}"

    return ""


def extract_link(text):
    if not text:
        return ""

    match = re.search(
        r"https?://[^\s<>]+",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return ""

    return match.group(0).rstrip(
        ".,);]}>'\""
    )


def valid_url(url):
    return bool(
        url
        and url.startswith(
            (
                "http://",
                "https://",
            )
        )
    )


def detect_category(text):
    text = text.lower()

    if any(
        word in text
        for word in [
            "bourse",
            "bourses",
            "scholarship",
            "fellowship",
            "bourse d'étude",
            "bourse d'études",
        ]
    ):
        return "BOURSE"

    if any(
        word in text
        for word in [
            "stage",
            "stages",
            "stagiaire",
            "internship",
            "intern",
        ]
    ):
        return "STAGE"

    if any(
        word in text
        for word in [
            "emploi",
            "emplois",
            "job",
            "jobs",
            "recrutement",
            "recrute",
            "hiring",
            "career",
            "poste",
            "postes",
            "embauche",
        ]
    ):
        return "EMPLOI"

    return None


# ============================================================
# MENU
# ============================================================

def main_menu():

    buttons = [
        [
            InlineKeyboardButton(
                "💼 EMPLOI",
                callback_data="EMPLOI",
            ),
            InlineKeyboardButton(
                "🎓 STAGE",
                callback_data="STAGE",
            ),
        ],
        [
            InlineKeyboardButton(
                "🎓 BOURSE",
                callback_data="BOURSE",
            ),
        ],
        [
            InlineKeyboardButton(
                "🤖 CONTACTER LE BOT",
                url=bot_link(),
            ),
        ],
    ]

    link = channel_link()

    if link:
        buttons.append([
            InlineKeyboardButton(
                "📢 VOIR LE CANAL",
                url=link,
            )
        ])

    return InlineKeyboardMarkup(buttons)


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    text = (
        "<b>🤖 BIENVENUE SUR LE BOT OPPORTUNITÉS</b>\n\n"

        "Je peux rechercher pour vous :\n\n"

        "💼 <b>Emploi</b>\n"
        "🎓 <b>Stage</b>\n"
        "🎓 <b>Bourse</b>\n\n"

        "✍️ Écrivez directement ce que vous recherchez.\n\n"

        "<b>Exemples :</b>\n"
        "💼 Je cherche un emploi\n"
        "💼 Emploi informatique\n"
        "🎓 Je cherche un stage\n"
        "🎓 Stage laboratoire\n"
        "🎓 Je cherche une bourse\n"
        "🎓 Bourse Canada"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


async def aide(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await start(update, context)


# ============================================================
# AFFICHER UNE OFFRE
# ============================================================

async def send_offer(message, offer):

    categorie = escape_html(
        offer["categorie"],
        50,
    )

    titre = escape_html(
        offer["titre"],
        500,
    )

    description = escape_html(
        offer["description"],
        1500,
    )

    lien = str(
        offer["lien"] or ""
    ).strip()

    text = (
        f"📂 <b>{categorie}</b>\n\n"
        f"📌 <b>{titre}</b>\n\n"
    )

    if description:
        text += f"{description}\n\n"

    text += (
        "👇 <b>Pour candidater :</b>"
    )

    buttons = []

    if valid_url(lien):

        buttons.append(
            InlineKeyboardButton(
                "👉 VOIR / CANDIDATER",
                url=lien,
            )
        )

    buttons.append(
        InlineKeyboardButton(
            "🤖 DEMANDER UNE AUTRE OFFRE",
            url=bot_link(),
        )
    )

    link = channel_link()

    if link:

        buttons.append(
            InlineKeyboardButton(
                "📢 VOIR LE CANAL",
                url=link,
            )
        )

    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            [buttons]
        ),
    )


# ============================================================
# BOUTONS CATÉGORIES
# ============================================================

async def category_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    categorie = query.data

    if categorie not in [
        "EMPLOI",
        "STAGE",
        "BOURSE",
    ]:
        return

    results = offres_categorie(
        categorie,
        10,
    )

    if not results:

        await query.message.reply_text(
            (
                f"🔎 Aucune offre "
                f"<b>{categorie}</b> "
                "n'est actuellement disponible.\n\n"
                "📢 Revenez plus tard ou "
                "consultez le canal."
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )

        return

    await query.message.reply_text(
        (
            f"🔎 <b>{len(results)} "
            f"offre(s) {categorie}</b> "
            "trouvée(s)."
        ),
        parse_mode=ParseMode.HTML,
    )

    for offer in results:

        try:
            await send_offer(
                query.message,
                offer,
            )

        except Exception:
            logger.exception(
                "Erreur affichage offre ID %s",
                offer["id"],
            )


# ============================================================
# RECHERCHE UTILISATEUR
# ============================================================

async def user_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    text = (
        update.message.text or ""
    ).strip()

    if not text:
        return

    categorie = detect_category(text)

    if categorie:

        results = offres_categorie(
            categorie,
            10,
        )

    else:

        results = offres_recherche(
            text,
            10,
        )

    if results:

        await update.message.reply_text(
            (
                f"🔎 <b>{len(results)} "
                "opportunité(s) trouvée(s).</b>"
            ),
            parse_mode=ParseMode.HTML,
        )

        for offer in results:

            try:

                await send_offer(
                    update.message,
                    offer,
                )

            except Exception:

                logger.exception(
                    "Erreur affichage offre ID %s",
                    offer["id"],
                )

        return

    await update.message.reply_text(
        (
            "🔎 <b>Aucune offre trouvée.</b>\n\n"

            "Essayez par exemple :\n\n"

            "💼 emploi informatique\n"
            "🎓 stage laboratoire\n"
            "🎓 bourse Canada\n"
            "💼 emploi Abidjan\n\n"

            "📢 De nouvelles opportunités sont "
            "publiées régulièrement dans notre canal."
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


# ============================================================
# AJOUTER UNE OFFRE
# ============================================================

async def ajouter(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(update):

        await update.message.reply_text(
            "⛔ Commande réservée à l'administrateur."
        )

        return

    contenu = update.message.text or ""

    contenu = re.sub(
        r"^/ajouter(?:@\w+)?",
        "",
        contenu,
        count=1,
        flags=re.IGNORECASE,
    ).strip()

    parties = [
        p.strip()
        for p in contenu.split("|")
    ]

    if len(parties) < 4:

        await update.message.reply_text(
            (
                "❌ Format incorrect.\n\n"

                "<code>/ajouter EMPLOI | "
                "Titre | Description | Lien</code>\n\n"

                "<code>/ajouter STAGE | "
                "Titre | Description | Lien</code>\n\n"

                "<code>/ajouter BOURSE | "
                "Titre | Description | Lien</code>"
            ),
            parse_mode=ParseMode.HTML,
        )

        return

    categorie = parties[0].upper().strip()

    titre = parties[1].strip()

    description = parties[2].strip()

    lien = parties[3].strip()

    if categorie not in [
        "EMPLOI",
        "STAGE",
        "BOURSE",
    ]:

        await update.message.reply_text(
            "❌ Catégorie invalide : EMPLOI, STAGE ou BOURSE."
        )

        return

    if not titre:

        await update.message.reply_text(
            "❌ Le titre est obligatoire."
        )

        return

    if lien and not valid_url(lien):

        await update.message.reply_text(
            "❌ Le lien doit commencer par http:// ou https://"
        )

        return

    # --------------------------------------------------------
    # Texte destiné au canal
    # --------------------------------------------------------

    canal_text = (
        "📢 <b>NOUVELLE OPPORTUNITÉ</b>\n\n"
        f"📂 <b>{escape_html(categorie, 50)}</b>\n\n"
        f"📌 <b>{escape_html(titre, 500)}</b>\n\n"
    )

    if description:

        canal_text += (
            f"{escape_html(description, 2500)}\n\n"
        )

    canal_text += (
        "👇 <b>Pour candidater :</b>"
    )

    buttons = []

    if valid_url(lien):

        buttons.append(
            InlineKeyboardButton(
                "👉 CANDIDATER",
                url=lien,
            )
        )

    buttons.append(
        InlineKeyboardButton(
            "🤖 DEMANDER UNE OFFRE",
            url=bot_link(),
        )
    )

    try:

        publication = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=canal_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup(
                [buttons]
            ),
        )

        offre_id = ajouter_offre(
            categorie=categorie,
            titre=titre,
            description=description,
            lien=lien,
            telegram_message_id=publication.message_id,
        )

        await update.message.reply_text(
            (
                "✅ <b>OFFRE ENREGISTRÉE ET PUBLIÉE</b>\n\n"
                f"📂 {escape_html(categorie, 50)}\n"
                f"📌 {escape_html(titre, 500)}\n"
                f"🆔 ID : <b>{offre_id}</b>"
            ),
            parse_mode=ParseMode.HTML,
        )

    except Exception as error:

        logger.exception(
            "Erreur publication offre"
        )

        await update.message.reply_text(
            (
                "❌ <b>PUBLICATION IMPOSSIBLE</b>\n\n"
                f"<code>{escape_html(error, 1500)}</code>\n\n"
                "Vérifie que le bot est administrateur "
                "du canal et possède le droit de publier."
            ),
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# TEST CANAL
# ============================================================

async def testcanal(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(update):

        await update.message.reply_text(
            "⛔ Accès refusé."
        )

        return

    try:

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                "✅ <b>TEST RÉUSSI</b>\n\n"
                "🤖 Le bot peut publier dans ce canal."
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🤖 CONTACTER LE BOT",
                        url=bot_link(),
                    )
                ]
            ]),
        )

        await update.message.reply_text(
            "✅ Test réussi : message envoyé dans le canal."
        )

    except Exception as error:

        logger.exception(
            "Erreur test canal"
        )

        await update.message.reply_text(
            (
                "❌ <b>ÉCHEC DU TEST</b>\n\n"
                f"<code>{escape_html(error, 1500)}</code>\n\n"
                "Vérifie CHANNEL_ID et les droits "
                "administrateur du bot."
            ),
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# PUBLIER LE BOUTON DU BOT
# ============================================================

async def publier_bot(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(update):

        await update.message.reply_text(
            "⛔ Accès refusé."
        )

        return

    text = (
        "🤖 <b>BESOIN D'UNE OPPORTUNITÉ ?</b>\n\n"

        "Vous cherchez :\n"
        "💼 un emploi\n"
        "🎓 un stage\n"
        "🎓 une bourse\n\n"

        "Cliquez sur le bouton ci-dessous "
        "et écrivez directement votre recherche."
    )

    try:

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🤖 DEMANDER UNE OFFRE",
                        url=bot_link(),
                    )
                ]
            ]),
        )

        await update.message.reply_text(
            "✅ Bouton du bot publié dans le canal."
        )

    except Exception as error:

        logger.exception(
            "Erreur publication bouton"
        )

        await update.message.reply_text(
            (
                "❌ <b>PUBLICATION IMPOSSIBLE</b>\n\n"
                f"<code>{escape_html(error, 1500)}</code>"
            ),
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# PUBLICATION AUTOMATIQUE
# ============================================================

async def hourly_post(
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "🤖 <b>BOT OPPORTUNITÉS</b>\n\n"

        "Vous recherchez une opportunité ?\n\n"

        "💼 Emploi\n"
        "🎓 Stage\n"
        "🎓 Bourse\n\n"

        "Cliquez ci-dessous pour demander "
        "directement une offre au bot."
    )

    try:

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🤖 DEMANDER UNE OFFRE",
                        url=bot_link(),
                    )
                ]
            ]),
        )

        logger.info(
            "Publication automatique réussie."
        )

    except Exception as error:

        logger.exception(
            "Publication automatique échouée"
        )


# ============================================================
# STATS
# ============================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(update):

        await update.message.reply_text(
            "⛔ Accès réservé à l'administrateur."
        )

        return

    conn = get_db()

    try:

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

        stages = conn.execute(
            """
            SELECT COUNT(*)
            FROM offres
            WHERE categorie = 'STAGE'
            """
        ).fetchone()[0]

        bourses = conn.execute(
            """
            SELECT COUNT(*)
            FROM offres
            WHERE categorie = 'BOURSE'
            """
        ).fetchone()[0]

    finally:

        conn.close()

    await update.message.reply_text(
        (
            "📊 <b>STATISTIQUES DU BOT</b>\n\n"
            f"📚 Total : <b>{total}</b>\n"
            f"💼 Emplois : <b>{emplois}</b>\n"
            f"🎓 Stages : <b>{stages}</b>\n"
            f"🎓 Bourses : <b>{bourses}</b>"
        ),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# ERREUR GLOBALE
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "Erreur Telegram : %s",
        context.error,
        exc_info=context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    # --------------------------------------------------------
    # Initialisation
    # --------------------------------------------------------

    init_db()

    # --------------------------------------------------------
    # Serveur Flask pour Render
    # --------------------------------------------------------

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
    )

    flask_thread.start()

    # --------------------------------------------------------
    # Application Telegram
    # --------------------------------------------------------

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # Commandes
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
    # Boutons catégories
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            category_callback,
            pattern=r"^(EMPLOI|STAGE|BOURSE)$",
        )
    )

    # --------------------------------------------------------
    # Messages utilisateurs
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            user_search,
        )
    )

    # --------------------------------------------------------
    # Publication automatique
    # --------------------------------------------------------

    if application.job_queue is not None:

        application.job_queue.run_repeating(
            hourly_post,
            interval=3600,
            first=3600,
        )

        logger.info(
            "⏰ Publication automatique activée : toutes les heures."
        )

    else:

        logger.error(
            "❌ JobQueue indisponible. "
            "Installe python-telegram-bot[job-queue]."
        )

    # --------------------------------------------------------
    # Gestion des erreurs
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "🤖 Bot Opportunités démarrage..."
    )

    # --------------------------------------------------------
    # Démarrage Telegram
    # --------------------------------------------------------

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":
    main()
