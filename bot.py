import os
import sqlite3
import threading
import logging
import re
from datetime import datetime

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

# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "5056571209"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@canalRM24").strip()
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = os.getenv("DB_PATH", "opportunites.db")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN est absent. Ajoute-le dans Render > Environment."
    )

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# ============================================================
# FLASK - RENDER
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


def ajouter_offre(
    categorie,
    titre,
    description="",
    lien="",
    telegram_message_id=None
):

    with db_lock:

        conn = db()

        conn.execute("""
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

        conn.commit()
        conn.close()


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

    elif recherche:

        terme = f"%{recherche}%"

        resultats = conn.execute("""
            SELECT *
            FROM offres
            WHERE titre LIKE ?
               OR description LIKE ?
            ORDER BY id DESC
            LIMIT ?
        """, (
            terme,
            terme,
            limite
        )).fetchall()

    else:

        resultats = []

    conn.close()

    return resultats


# ============================================================
# DÉTECTION AUTOMATIQUE DES CATÉGORIES
# ============================================================

def detecter_categorie(texte):

    texte = texte.lower()

    mots_stage = [
        "stage",
        "stagiaire",
        "stages",
        "internship",
        "intern"
    ]

    mots_bourse = [
        "bourse",
        "bourse d'étude",
        "bourse d'études",
        "scholarship",
        "scholarships",
        "fellowship",
        "études financées"
    ]

    mots_emploi = [
        "emploi",
        "offre d'emploi",
        "offre emploi",
        "recrutement",
        "recrute",
        "job",
        "jobs",
        "poste vacant",
        "poste",
        "embauche",
        "hiring",
        "career"
    ]

    if any(mot in texte for mot in mots_stage):
        return "STAGE"

    if any(mot in texte for mot in mots_bourse):
        return "BOURSE"

    if any(mot in texte for mot in mots_emploi):
        return "EMPLOI"

    return None


# ============================================================
# EXTRAIRE UN LIEN
# ============================================================

def extraire_lien(texte):

    if not texte:
        return ""

    match = re.search(
        r"https?://[^\s]+",
        texte
    )

    if match:

        return match.group(0).rstrip(
            ".,);]"
        )

    return ""


# ============================================================
# MENU PRINCIPAL
# ============================================================

def menu_principal():

    canal = CHANNEL_ID.replace("@", "")

    keyboard = [

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
                "📢 Voir le canal",
                url=f"https://t.me/{canal}"
            )
        ]
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = (
        "👋 *Bienvenue sur le Bot Opportunités !*\n\n"

        "Je peux vous aider à trouver des opportunités :\n\n"

        "💼 *EMPLOI*\n"
        "🎓 *STAGE*\n"
        "🎓 *BOURSE*\n\n"

        "Vous pouvez écrire directement "
        "ce que vous recherchez.\n\n"

        "Exemples :\n"
        "💼 Je cherche un emploi\n"
        "🎓 Je cherche un stage\n"
        "🎓 Je cherche une bourse\n"
        "💼 Emploi informatique\n"
        "🎓 Stage laboratoire"
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown",
        reply_markup=menu_principal()
    )


# ============================================================
# BOUTONS DES CATÉGORIES
# ============================================================

async def categorie_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    categorie = query.data

    offres = rechercher_offres(
        categorie=categorie,
        limite=10
    )

    if not offres:

        await query.message.reply_text(
            f"🔎 Aucune offre *{categorie}* "
            "n'est actuellement disponible.\n\n"

            "📢 Consultez notre canal pour "
            "les nouvelles opportunités.",
            parse_mode="Markdown",
            reply_markup=menu_principal()
        )

        return

    message = (
        f"📋 *DERNIÈRES OFFRES {categorie}*\n\n"
    )

    for offre in offres:

        message += (
            f"🔹 *{offre['titre']}*\n"
        )

        if offre["description"]:

            description = (
                offre["description"][:300]
            )

            message += (
                f"{description}\n"
            )

        if offre["lien"]:

            message += (
                f"👉 [Voir l'offre et candidater]"
                f"({offre['lien']})\n"
            )

        message += "\n"

    canal = CHANNEL_ID.replace("@", "")

    message += (
        "📢 *Toutes les opportunités :*\n"
        f"https://t.me/{canal}"
    )

    await query.message.reply_text(
        message,
        parse_mode="Markdown",
        disable_web_page_preview=True
    )


# ============================================================
# RECHERCHE UTILISATEUR
# ============================================================

async def rechercher(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    texte = update.message.text.strip()

    if not texte:
        return

    categorie = detecter_categorie(
        texte
    )

    # --------------------------------------------------------
    # RECHERCHE PAR CATÉGORIE
    # --------------------------------------------------------

    if categorie:

        offres = rechercher_offres(
            categorie=categorie,
            limite=10
        )

        if offres:

            message = (
                f"🔎 *Offres {categorie} trouvées :*\n\n"
            )

            for offre in offres:

                message += (
                    f"📌 *{offre['titre']}*\n"
                )

                if offre["description"]:

                    message += (
                        f"{offre['description'][:250]}\n"
                    )

                if offre["lien"]:

                    message += (
                        f"👉 [Voir l'offre]"
                        f"({offre['lien']})\n"
                    )

                message += "\n"

            canal = CHANNEL_ID.replace("@", "")

            message += (
                "📢 *Toutes les offres :*\n"
                f"https://t.me/{canal}"
            )

            await update.message.reply_text(
                message,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )

            return

    # --------------------------------------------------------
    # RECHERCHE PAR MOTS-CLÉS
    # --------------------------------------------------------

    mots = re.sub(
        r"\b(je|cherche|recherche|une|un|des|de|du|"
        r"la|le|les|pour|dans)\b",
        " ",
        texte,
        flags=re.IGNORECASE
    )

    mots = " ".join(
        mots.split()
    )

    offres = rechercher_offres(
        recherche=mots,
        limite=10
    )

    if offres:

        message = (
            "🔎 *Opportunités trouvées :*\n\n"
        )

        for offre in offres:

            message += (
                f"📂 *{offre['categorie']}*\n"
                f"📌 *{offre['titre']}*\n"
            )

            if offre["lien"]:

                message += (
                    f"👉 [Voir l'offre]"
                    f"({offre['lien']})\n"
                )

            message += "\n"

        canal = CHANNEL_ID.replace("@", "")

        message += (
            "📢 Plus d'opportunités :\n"
            f"https://t.me/{canal}"
        )

        await update.message.reply_text(
            message,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

        return

    # --------------------------------------------------------
    # AUCUNE OFFRE
    # --------------------------------------------------------

    await update.message.reply_text(
        "🔎 Je n'ai pas trouvé d'offre "
        "correspondant exactement à votre recherche.\n\n"

        "Essayez par exemple :\n\n"

        "💼 *emploi*\n"
        "🎓 *stage*\n"
        "🎓 *bourse*\n"
        "💼 *emploi informatique*\n"
        "🎓 *stage laboratoire*\n"
        "🎓 *bourse Canada*\n\n"

        "📢 Consultez notre canal pour "
        "les nouvelles opportunités.",
        parse_mode="Markdown",
        reply_markup=menu_principal()
    )


# ============================================================
# AJOUT MANUEL D'UNE OFFRE
# ============================================================

async def ajouter(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ Cette commande est réservée "
            "à l'administrateur."
        )

        return

    contenu = update.message.text

    contenu = contenu.replace(
        "/ajouter",
        "",
        1
    ).strip()

    parties = [
        partie.strip()
        for partie in contenu.split("|")
    ]

    if len(parties) < 4:

        await update.message.reply_text(
            "❌ Format incorrect.\n\n"

            "Utilisez :\n\n"

            "/ajouter EMPLOI | Titre | "
            "Description | Lien\n\n"

            "/ajouter STAGE | Titre | "
            "Description | Lien\n\n"

            "/ajouter BOURSE | Titre | "
            "Description | Lien"
        )

        return

    categorie = parties[0].upper()
    titre = parties[1]
    description = parties[2]
    lien = parties[3]

    if categorie not in [
        "EMPLOI",
        "STAGE",
        "BOURSE"
    ]:

        await update.message.reply_text(
            "❌ Catégorie incorrecte.\n\n"
            "Utilisez : EMPLOI, STAGE ou BOURSE."
        )

        return

    ajouter_offre(
        categorie=categorie,
        titre=titre,
        description=description,
        lien=lien
    )

    await update.message.reply_text(
        "✅ *Offre enregistrée !*\n\n"

        f"📂 Catégorie : *{categorie}*\n"
        f"📌 Titre : *{titre}*\n\n"

        "Le bot pourra maintenant "
        "la proposer aux utilisateurs.",
        parse_mode="Markdown"
    )


# ============================================================
# PUBLICATIONS DU CANAL
# ============================================================

async def publication_canal(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    post = update.channel_post

    if not post:
        return

    texte = (
        post.text
        or post.caption
        or ""
    ).strip()

    if not texte:
        return

    categorie = detecter_categorie(
        texte
    )

    if not categorie:

        logger.info(
            "Publication sans catégorie détectée."
        )

        return

    lien_candidature = extraire_lien(
        texte
    )

    username = post.chat.username

    lien_publication = ""

    if username:

        lien_publication = (
            f"https://t.me/"
            f"{username}/"
            f"{post.message_id}"
        )

    lien = (
        lien_candidature
        if lien_candidature
        else lien_publication
    )

    lignes = [
        ligne.strip()
        for ligne in texte.splitlines()
        if ligne.strip()
    ]

    titre = (
        lignes[0][:200]
        if lignes
        else f"Nouvelle offre {categorie}"
    )

    ajouter_offre(
        categorie=categorie,
        titre=titre,
        description=texte,
        lien=lien,
        telegram_message_id=post.message_id
    )

    logger.info(
        f"Publication enregistrée : "
        f"{categorie} - {titre}"
    )


# ============================================================
# PUBLICATION AUTOMATIQUE CHAQUE HEURE
# ============================================================

async def publication_horaire(
    context: ContextTypes.DEFAULT_TYPE
):

    message = (
        "🤖 *COMMENT UTILISER LE BOT ?*\n\n"

        "Vous pouvez écrire directement "
        "ce que vous recherchez.\n\n"

        "Exemples :\n"

        "💼 Je cherche un emploi\n"
        "🎓 Je cherche un stage\n"
        "🎓 Je cherche une bourse\n"
        "💼 Emploi informatique\n"
        "🎓 Stage laboratoire\n\n"

        "📢 *Retrouvez toutes nos opportunités "
        "sur notre canal.*"
    )

    try:

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="Markdown"
        )

        logger.info(
            "✅ Message automatique publié "
            "sur le canal."
        )

    except Exception as e:

        logger.error(
            f"❌ Erreur publication automatique : {e}"
        )


# ============================================================
# STATISTIQUES
# ============================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    conn = db()

    total = conn.execute(
        "SELECT COUNT(*) AS total FROM offres"
    ).fetchone()["total"]

    emplois = conn.execute(
        "SELECT COUNT(*) AS total FROM offres "
        "WHERE categorie='EMPLOI'"
    ).fetchone()["total"]

    stages = conn.execute(
        "SELECT COUNT(*) AS total FROM offres "
        "WHERE categorie='STAGE'"
    ).fetchone()["total"]

    bourses = conn.execute(
        "SELECT COUNT(*) AS total FROM offres "
        "WHERE categorie='BOURSE'"
    ).fetchone()["total"]

    conn.close()

    await update.message.reply_text(
        "📊 *STATISTIQUES DU BOT*\n\n"

        f"📚 Total : *{total}*\n"
        f"💼 Emplois : *{emplois}*\n"
        f"🎓 Stages : *{stages}*\n"
        f"🎓 Bourses : *{bourses}*",
        parse_mode="Markdown"
    )


# ============================================================
# AIDE
# ============================================================

async def aide(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🤖 *Comment utiliser le bot ?*\n\n"

        "Vous pouvez écrire ce que vous recherchez.\n\n"

        "Exemples :\n"

        "💼 Je cherche un emploi\n"
        "🎓 Je cherche un stage\n"
        "🎓 Je cherche une bourse\n"
        "💼 Emploi informatique\n"
        "🎓 Stage laboratoire",
        parse_mode="Markdown",
        reply_markup=menu_principal()
    )


# ============================================================
# FLASK EN ARRIÈRE-PLAN
# ============================================================

def run_flask():

    app.run(
        host="0.0.0.0",
        port=PORT
    )


# ============================================================
# DÉMARRAGE
# ============================================================

def main():

    init_db()

    # Flask pour maintenir Render actif
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

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
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "aide",
            aide
        )
    )

    application.add_handler(
        CommandHandler(
            "ajouter",
            ajouter
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    # --------------------------------------------------------
    # BOUTONS
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            categorie_callback,
            pattern="^(EMPLOI|STAGE|BOURSE)$"
        )
    )

    # --------------------------------------------------------
    # PUBLICATIONS DU CANAL
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST,
            publication_canal
        )
    )

    # --------------------------------------------------------
    # MESSAGES UTILISATEURS
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            rechercher
        )
    )

    # --------------------------------------------------------
    # PUBLICATION AUTOMATIQUE
    # --------------------------------------------------------
    #
    # 3600 secondes = 1 heure
    #
    # Le premier message sera envoyé après 1 heure.
    # --------------------------------------------------------

    if application.job_queue:

        application.job_queue.run_repeating(
            publication_horaire,
            interval=3600,
            first=3600
        )

        logger.info(
            "⏰ Publication automatique activée : "
            "toutes les 1 heure."
        )

    else:

        logger.error(
            "JobQueue indisponible. "
            "Installe python-telegram-bot[job-queue]."
        )

    logger.info(
        "🚀 Bot Opportunités démarré."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":
    main()
