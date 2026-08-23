import os
import sqlite3
import threading
import logging
import re
import asyncio

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIGURATION
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "5056571209"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@canalRM24").strip()
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = os.getenv("DB_PATH", "opportunites.db")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN manquant dans Render > Environment."
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "BOT TELEGRAM ACTIF"


@app.route("/health")
def health():
    return "OK"


def run_flask():
    app.run(
        host="0.0.0.0",
        port=PORT
    )


# =========================================================
# DATABASE
# =========================================================

lock = threading.Lock()


def connection():
    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    with lock:

        conn = connection()

        conn.execute("""
            CREATE TABLE IF NOT EXISTS offres (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                categorie TEXT NOT NULL,
                titre TEXT NOT NULL,
                description TEXT,
                lien TEXT,
                message_id INTEGER,
                created_at TEXT NOT NULL
            )
        """)

        conn.commit()
        conn.close()


def save_offer(
    categorie,
    titre,
    description,
    lien,
    message_id=None
):

    with lock:

        conn = connection()

        cursor = conn.execute("""
            INSERT INTO offres
            (categorie, titre, description, lien,
             message_id, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
        """, (
            categorie,
            titre,
            description,
            lien,
            message_id
        ))

        offer_id = cursor.lastrowid

        conn.commit()
        conn.close()

        return offer_id


def get_offers(
    categorie=None,
    keyword=None,
    limit=10
):

    conn = connection()

    if categorie:

        rows = conn.execute("""
            SELECT *
            FROM offres
            WHERE categorie = ?
            ORDER BY id DESC
            LIMIT ?
        """, (
            categorie,
            limit
        )).fetchall()

    elif keyword:

        words = [
            x.lower()
            for x in keyword.split()
            if len(x) >= 2
        ]

        conditions = []
        values = []

        for word in words:

            conditions.append(
                "(LOWER(titre) LIKE ? "
                "OR LOWER(description) LIKE ?)"
            )

            values.extend([
                f"%{word}%",
                f"%{word}%"
            ])

        if not conditions:
            conn.close()
            return []

        sql = f"""
            SELECT *
            FROM offres
            WHERE {" OR ".join(conditions)}
            ORDER BY id DESC
            LIMIT ?
        """

        values.append(limit)

        rows = conn.execute(
            sql,
            values
        ).fetchall()

    else:

        rows = []

    conn.close()

    return rows


# =========================================================
# CATEGORY
# =========================================================

def category(text):

    text = text.lower()

    if any(x in text for x in [
        "bourse",
        "scholarship",
        "fellowship",
        "bourse d'étude",
        "bourse d'études"
    ]):
        return "BOURSE"

    if any(x in text for x in [
        "stage",
        "stagiaire",
        "internship",
        "intern"
    ]):
        return "STAGE"

    if any(x in text for x in [
        "emploi",
        "job",
        "recrutement",
        "recrute",
        "hiring",
        "poste",
        "embauche",
        "career"
    ]):
        return "EMPLOI"

    return None


def extract_link(text):

    match = re.search(
        r"https?://[^\s]+",
        text or ""
    )

    if not match:
        return ""

    return match.group(0).rstrip(
        ".,);]}"
    )


def channel_link():

    if CHANNEL_ID.startswith("@"):
        return (
            "https://t.me/"
            + CHANNEL_ID[1:]
        )

    return CHANNEL_ID


# =========================================================
# MENU
# =========================================================

def menu():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💼 EMPLOI",
                callback_data="EMPLOI"
            ),
            InlineKeyboardButton(
                "🎓 STAGE",
                callback_data="STAGE"
            )
        ],
        [
            InlineKeyboardButton(
                "🎓 BOURSE",
                callback_data="BOURSE"
            )
        ],
        [
            InlineKeyboardButton(
                "📢 VOIR LE CANAL",
                url=channel_link()
            )
        ]
    ])


# =========================================================
# START
# =========================================================

async def start(update, context):

    await update.message.reply_text(
        "🤖 *Bienvenue !*\n\n"
        "Je peux rechercher des :\n\n"
        "💼 Emplois\n"
        "🎓 Stages\n"
        "🎓 Bourses\n\n"
        "Écrivez simplement ce que vous recherchez.\n\n"
        "Exemples :\n"
        "💼 Je cherche un emploi\n"
        "🎓 Je cherche un stage\n"
        "🎓 Je cherche une bourse\n"
        "💼 Emploi informatique\n"
        "🎓 Stage laboratoire\n"
        "🎓 Bourse Canada",
        parse_mode="Markdown",
        reply_markup=menu()
    )


# =========================================================
# SHOW OFFERS
# =========================================================

async def show_category(update, context):

    query = update.callback_query

    await query.answer()

    cat = query.data

    offers = get_offers(
        categorie=cat,
        limit=10
    )

    if not offers:

        await query.message.reply_text(
            f"🔎 Aucune offre {cat} disponible actuellement.\n\n"
            "📢 Consultez le canal pour les nouvelles offres.",
            reply_markup=menu()
        )

        return

    for offer in offers:

        text = (
            f"📂 *{offer['categorie']}*\n\n"
            f"📌 *{offer['titre']}*\n\n"
            f"{offer['description'][:700]}\n\n"
            "👇 Cliquez ci-dessous pour candidater."
        )

        buttons = []

        if offer["lien"]:

            buttons.append(
                InlineKeyboardButton(
                    "👉 CANDIDATER",
                    url=offer["lien"]
                )
            )

        buttons.append(
            InlineKeyboardButton(
                "📢 CANAL",
                url=channel_link()
            )
        )

        await query.message.reply_text(
            text,
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                buttons
            ])
        )


# =========================================================
# USER SEARCH
# =========================================================

async def search(update, context):

    text = update.message.text.strip()

    cat = category(text)

    if cat:

        offers = get_offers(
            categorie=cat,
            limit=10
        )

    else:

        cleaned = re.sub(
            r"\b(je|cherche|recherche|une|un|des|de|du|la|le|les|pour|dans)\b",
            " ",
            text,
            flags=re.IGNORECASE
        )

        offers = get_offers(
            keyword=cleaned,
            limit=10
        )

    if not offers:

        await update.message.reply_text(
            "🔎 Je n'ai pas encore trouvé cette offre "
            "dans ma base.\n\n"
            "Essayez :\n"
            "💼 emploi\n"
            "🎓 stage\n"
            "🎓 bourse\n\n"
            "📢 Voir toutes les offres :",
            reply_markup=menu()
        )

        return

    await update.message.reply_text(
        f"🔎 *{len(offers)} offre(s) trouvée(s)*",
        parse_mode="Markdown"
    )

    for offer in offers:

        buttons = []

        if offer["lien"]:

            buttons.append(
                InlineKeyboardButton(
                    "👉 VOIR / CANDIDATER",
                    url=offer["lien"]
                )
            )

        buttons.append(
            InlineKeyboardButton(
                "📢 CANAL",
                url=channel_link()
            )
        )

        await update.message.reply_text(
            f"📂 *{offer['categorie']}*\n\n"
            f"📌 *{offer['titre']}*\n\n"
            f"{offer['description'][:700]}",
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                buttons
            ])
        )


# =========================================================
# ADD OFFER
# =========================================================

async def add_offer(update, context):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ Commande réservée à l'administrateur."
        )

        return

    data = update.message.text

    data = data.replace(
        "/ajouter",
        "",
        1
    ).strip()

    parts = [
        x.strip()
        for x in data.split("|")
    ]

    if len(parts) < 4:

        await update.message.reply_text(
            "❌ Format :\n\n"
            "/ajouter EMPLOI | Titre | Description | Lien"
        )

        return

    cat = parts[0].upper()
    title = parts[1]
    description = parts[2]
    link = parts[3]

    if cat not in [
        "EMPLOI",
        "STAGE",
        "BOURSE"
    ]:

        await update.message.reply_text(
            "❌ Utilisez EMPLOI, STAGE ou BOURSE."
        )

        return

    # -----------------------------------------------------
    # PUBLICATION IMMEDIATE
    # -----------------------------------------------------

    post = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=(
            "📢 *NOUVELLE OPPORTUNITÉ*\n\n"
            f"📂 *{cat}*\n\n"
            f"📌 *{title}*\n\n"
            f"{description}\n\n"
            "👇 *Candidature :*\n"
            f"{link}\n\n"
            "🤖 Retrouvez d'autres opportunités "
            "sur notre canal."
        ),
        parse_mode="Markdown"
    )

    offer_id = save_offer(
        cat,
        title,
        description,
        link,
        post.message_id
    )

    publication = (
        f"{channel_link()}/{post.message_id}"
    )

    await update.message.reply_text(
        "✅ *OFFRE PUBLIÉE !*\n\n"
        f"📂 {cat}\n"
        f"📌 {title}\n\n"
        f"🆔 Offre : {offer_id}\n\n"
        f"🔗 Publication :\n{publication}",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )


# =========================================================
# TEST CHANNEL
# =========================================================

async def test_channel(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    try:

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                "🧪 *TEST RÉUSSI !*\n\n"
                "🤖 Le bot peut publier dans ce canal."
            ),
            parse_mode="Markdown"
        )

        await update.message.reply_text(
            "✅ Test réussi : message envoyé dans le canal."
        )

    except Exception as e:

        logger.exception(e)

        await update.message.reply_text(
            "❌ Impossible de publier dans le canal.\n\n"
            f"{str(e)[:1000]}"
        )


# =========================================================
# HOURLY MESSAGE
# =========================================================

async def hourly(context):

    try:

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                "🤖 *BOT OPPORTUNITÉS*\n\n"
                "Vous recherchez un :\n\n"
                "💼 emploi\n"
                "🎓 stage\n"
                "🎓 bourse\n\n"
                "👉 Ouvrez le bot et écrivez "
                "directement votre recherche."
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🤖 OUVRIR LE BOT",
                        url="https://t.me/Pdgki_bot"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📢 VOIR LES OFFRES",
                        url=channel_link()
                    )
                ]
            ])
        )

        logger.info(
            "Publication horaire réussie."
        )

    except Exception as e:

        logger.exception(
            "Erreur publication horaire"
        )


# =========================================================
# STATS
# =========================================================

async def stats(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    conn = connection()

    total = conn.execute(
        "SELECT COUNT(*) FROM offres"
    ).fetchone()[0]

    emploi = conn.execute(
        "SELECT COUNT(*) FROM offres "
        "WHERE categorie='EMPLOI'"
    ).fetchone()[0]

    stage = conn.execute(
        "SELECT COUNT(*) FROM offres "
        "WHERE categorie='STAGE'"
    ).fetchone()[0]

    bourse = conn.execute(
        "SELECT COUNT(*) FROM offres "
        "WHERE categorie='BOURSE'"
    ).fetchone()[0]

    conn.close()

    await update.message.reply_text(
        f"📊 *STATISTIQUES*\n\n"
        f"📚 Total : {total}\n"
        f"💼 Emplois : {emploi}\n"
        f"🎓 Stages : {stage}\n"
        f"🎓 Bourses : {bourse}",
        parse_mode="Markdown"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    logger.info("Initialisation de la base...")

    init_db()

    logger.info("Démarrage de Flask...")

    flask = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask.start()

    logger.info("Construction du bot Telegram...")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "ajouter",
            add_offer
        )
    )

    application.add_handler(
        CommandHandler(
            "testcanal",
            test_channel
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            show_category,
            pattern="^(EMPLOI|STAGE|BOURSE)$"
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            search
        )
    )

    # =====================================================
    # PUBLICATION CHAQUE HEURE
    # =====================================================

    if application.job_queue:

        application.job_queue.run_repeating(
            hourly,
            interval=3600,
            first=3600
        )

        logger.info(
            "Publication automatique : OK"
        )

    else:

        logger.error(
            "JobQueue indisponible."
        )

    logger.info(
        "Démarrage Telegram..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        logger.exception(
            "ERREUR FATALE DU BOT : %s",
            error
        )

        # L'erreur sera visible dans les logs Render.
        raise
