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
# CONFIGURATION EXISTANTE
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
# FLASK POUR RENDER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot Opportunités Telegram actif."


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
        """, (categorie, limite)).fetchall()

    elif recherche:
        terme = f"%{recherche}%"

        resultats = conn.execute("""
            SELECT *
            FROM offres
            WHERE titre LIKE ?
               OR description LIKE ?
            ORDER BY id DESC
            LIMIT ?
        """, (terme, terme, limite)).fetchall()

    else:
        resultats = []

    conn.close()

    return resultats


# ============================================================
# CATÉGORISATION AUTOMATIQUE
# ============================================================

def detecter_categorie(texte):
    texte = texte.lower()

    emploi = [
        "emploi",
        "offre d'emploi",
        "offre emploi",
        "recrutement",
        "recrute",
        "recrutement",
        "job",
        "jobs",
        "poste vacant",
        "poste",
        "embauche",
        "hiring",
        "career",
    ]

    stage = [
        "stage",
        "stagiaire",
        "stages",
        "internship",
        "intern",
        "internat",
    ]

    bourse = [
        "bourse",
        "bourse d'étude",
        "bourse d'études",
        "scholarship",
        "scholarships",
        "fellowship",
        "financement des études",
        "études financées",
    ]

    if any(mot in texte for mot in stage):
        return "STAGE"

    if any(mot in texte for mot in bourse):
        return "BOURSE"

    if any(mot in texte for mot in emploi):
        return "EMPLOI"

    return None


# ============================================================
# EXTRACTION DU LIEN
# ============================================================

def extraire_lien(texte):
    if not texte:
        return ""

    match = re.search(
        r"https?://[^\s]+",
        texte
    )

    if match:
        return match.group(0).rstrip(".,);]")

    return ""


# ============================================================
# MENU
# ============================================================

def menu_principal():

    keyboard = [
        [
            InlineKeyboardButton(
                "💼 EMPLOI",
                callback_data="EMPLOI"
            ),
            InlineKeyboardButton(
                "🎓 STAGE",
                callback_data="STAGE"
            ),
        ],
        [
            InlineKeyboardButton(
                "🎓 BOURSE",
                callback_data="BOURSE"
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 Voir le canal",
                url=(
                    "https://t.me/"
                    + CHANNEL_ID.replace("@", "")
                )
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# /START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    texte = (
        "👋 *Bienvenue sur le Bot Opportunités !*\n\n"
        "Je peux vous aider à trouver des opportunités "
        "dans plusieurs catégories :\n\n"
        "💼 *EMPLOI*\n"
        "🎓 *STAGE*\n"
        "🎓 *BOURSE*\n\n"
        "Choisissez une catégorie ou écrivez directement "
        "ce que vous recherchez.\n\n"
        "Exemples :\n"
        "• Je cherche un emploi\n"
        "• Je cherche un stage\n"
        "• Je cherche une bourse au Canada\n"
        "• Stage laboratoire\n"
        "• Emploi comptable"
    )

    await update.message.reply_text(
        texte,
        parse_mode="Markdown",
        reply_markup=menu_principal()
    )


# ============================================================
# BOUTONS CATÉGORIES
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
            f"🔎 Aucune offre *{categorie}* n'est "
            "actuellement enregistrée.\n\n"
            "📢 Les nouvelles opportunités sont publiées "
            "sur notre canal.",
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
            description = offre["description"][:300]
            message += f"{description}\n"

        if offre["lien"]:
            message += (
                f"👉 [Voir l'offre et candidater]"
                f"({offre['lien']})\n"
            )

        message += "\n"

    message += (
        "📢 *Toutes les opportunités :*\n"
        f"https://t.me/{CHANNEL_ID.replace('@', '')}"
    )

    await query.message.reply_text(
        message,
        parse_mode="Markdown",
        disable_web_page_preview=True
    )


# ============================================================
# RECHERCHE UTILISATEUR
# ============================================================

async def rechercher(update: Update, context: ContextTypes.DEFAULT_TYPE):

    texte = update.message.text.strip()

    if not texte:
        return

    categorie = detecter_categorie(texte)

    # --------------------------------------------------------
    # Recherche par catégorie
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
                        f"👉 [Candidater / Voir l'offre]"
                        f"({offre['lien']})\n"
                    )

                message += "\n"

            message += (
                "📢 Retrouvez toutes les offres sur notre canal :\n"
                f"https://t.me/{CHANNEL_ID.replace('@', '')}"
            )

            await update.message.reply_text(
                message,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )

            return

    # --------------------------------------------------------
    # Recherche par mots
    # --------------------------------------------------------

    mots = texte

    # Retire quelques mots génériques
    mots = re.sub(
        r"\b(je|cherche|recherche|une|un|des|de|du|la|le|les|pour|dans)\b",
        " ",
        mots,
        flags=re.IGNORECASE
    )

    mots = " ".join(mots.split())

    offres = rechercher_offres(
        recherche=mots,
        limite=10
    )

    if offres:

        message = "🔎 *Opportunités trouvées :*\n\n"

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

        message += (
            "📢 Plus d'opportunités :\n"
            f"https://t.me/{CHANNEL_ID.replace('@', '')}"
        )

        await update.message.reply_text(
            message,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

        return

    # --------------------------------------------------------
    # Aucune correspondance
    # --------------------------------------------------------

    await update.message.reply_text(
        "🔎 Je n'ai pas trouvé d'offre correspondant "
        "exactement à votre recherche.\n\n"
        "Essayez par exemple :\n\n"
        "💼 *emploi*\n"
        "🎓 *stage*\n"
        "🎓 *bourse*\n"
        "💼 *emploi informatique*\n"
        "🎓 *stage laboratoire*\n"
        "🎓 *bourse Canada*\n\n"
        "📢 Consultez aussi notre canal pour les nouvelles offres.",
        parse_mode="Markdown",
        reply_markup=menu_principal()
    )


# ============================================================
# AJOUT D'UNE OFFRE PAR L'ADMINISTRATEUR
# ============================================================

async def ajouter(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ Cette commande est réservée à l'administrateur."
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
            "/ajouter EMPLOI | Titre | Description | Lien\n\n"
            "ou :\n"
            "/ajouter STAGE | Titre | Description | Lien\n\n"
            "ou :\n"
            "/ajouter BOURSE | Titre | Description | Lien"
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
            "❌ Catégorie inconnue.\n\n"
            "Utilisez seulement :\n"
            "EMPLOI\n"
            "STAGE\n"
            "BOURSE"
        )

        return

    ajouter_offre(
        categorie=categorie,
        titre=titre,
        description=description,
        lien=lien
    )

    await update.message.reply_text(
        "✅ *Offre enregistrée avec succès !*\n\n"
        f"📂 Catégorie : *{categorie}*\n"
        f"📌 Titre : *{titre}*\n\n"
        "Les utilisateurs pourront maintenant "
        "la retrouver avec le bot.",
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

    categorie = detecter_categorie(texte)

    if not categorie:
        logger.info(
            "Publication sans catégorie détectée."
        )
        return

    lien_candidature = extraire_lien(texte)

    username = post.chat.username

    lien_publication = ""

    if username:
        lien_publication = (
            f"https://t.me/"
            f"{username}/"
            f"{post.message_id}"
        )

    # Si un lien externe existe, on le garde.
    # Sinon, on utilise le lien vers la publication Telegram.
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
# STATISTIQUES ADMIN
# ============================================================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    conn = db()

    total = conn.execute(
        "SELECT COUNT(*) AS total FROM offres"
    ).fetchone()["total"]

    emplois = conn.execute(
        "SELECT COUNT(*) AS total FROM offres WHERE categorie='EMPLOI'"
    ).fetchone()["total"]

    stages = conn.execute(
        "SELECT COUNT(*) AS total FROM offres WHERE categorie='STAGE'"
    ).fetchone()["total"]

    bourses = conn.execute(
        "SELECT COUNT(*) AS total FROM offres WHERE categorie='BOURSE'"
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
# AIDE ADMIN
# ============================================================

async def aide(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id == ADMIN_ID:

        await update.message.reply_text(
            "🛠️ *COMMANDES ADMINISTRATEUR*\n\n"
            "/ajouter EMPLOI | Titre | Description | Lien\n\n"
            "/ajouter STAGE | Titre | Description | Lien\n\n"
            "/ajouter BOURSE | Titre | Description | Lien\n\n"
            "/stats\n\n"
            "📢 Les nouvelles publications du canal sont "
            "également analysées automatiquement.",
            parse_mode="Markdown"
        )

    else:

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
# DÉMARRAGE DU BOT
# ============================================================

def main():

    init_db()

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commandes
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("aide", aide)
    )

    application.add_handler(
        CommandHandler("ajouter", ajouter)
    )

    application.add_handler(
        CommandHandler("stats", stats)
    )

    # Boutons
    application.add_handler(
        CallbackQueryHandler(
            categorie_callback,
            pattern="^(EMPLOI|STAGE|BOURSE)$"
        )
    )

    # Publications du canal
    application.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST,
            publication_canal
        )
    )

    # Messages utilisateurs
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            rechercher
        )
    )

    logger.info(
        "🚀 Bot Opportunités démarré."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
