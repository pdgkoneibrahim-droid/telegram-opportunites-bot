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
    LabeledPrice,
)

from telegram.constants import ParseMode

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
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

CANDIDATURE_STARS = 100


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# VÉRIFICATION CONFIGURATION
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN absent dans les variables d'environnement."
    )


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
        logger.exception("Erreur Flask")


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
                telegram_message_id INTEGER,
                date_creation TEXT NOT NULL
            )
            """
        )

        conn.commit()
        conn.close()

    logger.info("Base SQLite prête.")


def ajouter_offre(
    categorie,
    titre,
    description="",
    lien="",
    telegram_message_id=None,
):

    with db_lock:

        conn = get_db()

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
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        offre_id = cursor.lastrowid

        conn.commit()
        conn.close()

        return offre_id


def offre_par_id(offre_id):

    with db_lock:

        conn = get_db()

        resultat = conn.execute(
            """
            SELECT *
            FROM offres
            WHERE id = ?
            LIMIT 1
            """,
            (offre_id,),
        ).fetchone()

        conn.close()

        return resultat


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
                OR LOWER(description) LIKE ?
                OR LOWER(categorie) LIKE ?
            )
            """
        )

        valeur = f"%{mot}%"

        valeurs.extend(
            [
                valeur,
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

    valeurs.append(limite)

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

def admin(update):

    user = update.effective_user

    return (
        user is not None
        and user.id == ADMIN_ID
    )


def safe_text(
    value,
    maximum=3500,
):

    value = str(value or "")

    return value[:maximum]


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


# ============================================================
# LIENS
# ============================================================

def bot_link(start_parameter=None):

    base = (
        f"https://t.me/{BOT_USERNAME}"
    )

    if start_parameter:
        return (
            f"{base}?start={start_parameter}"
        )

    return base


def channel_link():

    if not CHANNEL_USERNAME:
        return ""

    return (
        f"https://t.me/{CHANNEL_USERNAME}"
    )


def clean_link(value):

    value = str(value or "").strip()

    if not value:
        return ""

    if re.match(
        r"^https?://@",
        value,
        re.IGNORECASE,
    ):
        return ""

    if value.startswith("t.me/"):
        value = "https://" + value

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


def detect_category(text):

    text = str(text or "").lower()

    if any(
        mot in text
        for mot in (
            "bourse",
            "bourses",
            "scholarship",
            "fellowship",
            "bourse d'étude",
            "bourse d'études",
        )
    ):
        return "BOURSE"

    if any(
        mot in text
        for mot in (
            "stage",
            "stages",
            "stagiaire",
            "internship",
            "intern",
        )
    ):
        return "STAGE"

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
            "poste",
            "postes",
            "embauche",
        )
    ):
        return "EMPLOI"

    return None


# ============================================================
# MESSAGE ASSISTANT
# ============================================================

def assistant_message():

    return (
        "🤖 <b>RÉSEAU MONDIAL — ASSISTANT OPPORTUNITÉS</b>\n\n"
        "Bienvenue !\n\n"
        "Je peux rechercher les opportunités "
        "publiées dans notre base :\n\n"
        "💼 <b>Emploi</b>\n"
        "🎓 <b>Stage</b>\n"
        "🎓 <b>Bourse</b>\n\n"
        "🌍 International et local selon les offres disponibles.\n\n"
        "Écrivez simplement ce que vous recherchez.\n\n"
        "<b>Opportunités disponibles :</b>\n"
        "💼 Emplois\n"
        "🎓 Bourses d'études\n"
        "💰 Stages rémunérés"
    )


# ============================================================
# MENU
# ============================================================

def main_menu():

    boutons = [
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
                "🤖 DEMANDER UNE OFFRE",
                url=bot_link("demande"),
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
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message is None:
        return

    if (
        context.args
        and context.args[0].lower() == "demande"
    ):

        await update.message.reply_text(
            assistant_message(),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )

        return

    await update.message.reply_text(
        assistant_message(),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


async def aide(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await start(
        update,
        context,
    )


# ============================================================
# AFFICHAGE OFFRE
# ============================================================

async def send_offer(
    message,
    offer,
):

    categorie = html_safe(
        offer["categorie"],
        50,
    )

    titre = html_safe(
        offer["titre"],
        700,
    )

    description = html_safe(
        offer["description"],
        2500,
    )

    offre_id = int(
        offer["id"]
    )

    texte = (
        f"📂 <b>{categorie}</b>\n\n"
        f"📌 <b>{titre}</b>\n\n"
        f"{description}\n\n"
        "👇 <b>Pour plus d'informations :</b>"
    )

    boutons = [
        InlineKeyboardButton(
            "👉 CANDIDATER • 100 ⭐",
            callback_data=f"CANDIDATER:{offre_id}",
        ),
        InlineKeyboardButton(
            "🤖 DEMANDER UNE OFFRE",
            url=bot_link("demande"),
        ),
    ]

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
            [boutons]
        ),
    )


# ============================================================
# CANDIDATURE — 100 STARS
# ============================================================

async def candidature_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    try:

        offre_id = int(
            query.data.split(
                ":",
                1,
            )[1]
        )

    except (
        ValueError,
        IndexError,
    ):

        await query.message.reply_text(
            "⚠️ Cette candidature est invalide."
        )

        return

    offre = offre_par_id(
        offre_id
    )

    if not offre:

        await query.message.reply_text(
            "⚠️ Cette opportunité n'est plus disponible."
        )

        return

    lien = clean_link(
        offre["lien"]
    )

    if not lien:

        await query.message.reply_text(
            "⚠️ Aucun lien de candidature "
            "n'est disponible pour cette offre."
        )

        return

    titre = html_safe(
        offre["titre"],
        700,
    )

    try:

        await context.bot.send_invoice(
            chat_id=query.from_user.id,
            title="Accès à la candidature",
            description=(
                f"Accès au lien de candidature : "
                f"{offre['titre']}"
            )[:255],
            payload=f"candidature:{offre_id}",
            provider_token="",
            currency="XTR",
            prices=[
                LabeledPrice(
                    "Accès candidature",
                    CANDIDATURE_STARS,
                )
            ],
        )

    except Exception:

        logger.exception(
            "Création facture candidature"
        )

        await query.message.reply_text(
            "⚠️ Impossible de créer le paiement "
            "pour le moment. Veuillez réessayer."
        )


# ============================================================
# PRÉ-CHECKOUT
# ============================================================

async def precheckout_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.pre_checkout_query

    payload = query.invoice_payload

    if not payload.startswith(
        "candidature:"
    ):

        await query.answer(
            ok=False,
            error_message="Commande non reconnue.",
        )

        return

    try:

        offre_id = int(
            payload.split(
                ":",
                1,
            )[1]
        )

    except (
        ValueError,
        IndexError,
    ):

        await query.answer(
            ok=False,
            error_message=(
                "Référence de candidature invalide."
            ),
        )

        return

    offre = offre_par_id(
        offre_id
    )

    if not offre:

        await query.answer(
            ok=False,
            error_message=(
                "Cette opportunité n'est plus disponible."
            ),
        )

        return

    if query.currency != "XTR":

        await query.answer(
            ok=False,
            error_message=(
                "Le paiement doit être effectué "
                "en Telegram Stars."
            ),
        )

        return

    if query.total_amount != CANDIDATURE_STARS:

        await query.answer(
            ok=False,
            error_message=(
                "Le montant de la commande est incorrect."
            ),
        )

        return

    await query.answer(
        ok=True
    )


# ============================================================
# PAIEMENT CONFIRMÉ
# ============================================================

async def successful_payment_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message is None:
        return

    payment = update.message.successful_payment

    if payment is None:
        return

    payload = payment.invoice_payload

    if not payload.startswith(
        "candidature:"
    ):
        return

    try:

        offre_id = int(
            payload.split(
                ":",
                1,
            )[1]
        )

    except (
        ValueError,
        IndexError,
    ):

        await update.message.reply_text(
            "⚠️ Paiement reçu, mais la référence "
            "de candidature est invalide."
        )

        return

    offre = offre_par_id(
        offre_id
    )

    if not offre:

        await update.message.reply_text(
            "✅ <b>Paiement confirmé.</b>\n\n"
            "⚠️ Cette offre n'est malheureusement "
            "plus disponible.",
            parse_mode=ParseMode.HTML,
        )

        return

    lien = clean_link(
        offre["lien"]
    )

    if not lien:

        await update.message.reply_text(
            "✅ <b>Paiement confirmé.</b>\n\n"
            "⚠️ Aucun lien de candidature "
            "n'est actuellement disponible.",
            parse_mode=ParseMode.HTML,
        )

        return

    titre = html_safe(
        offre["titre"],
        700,
    )

    lien_html = html_safe(
        lien,
        1500,
    )

    await update.message.reply_text(
        "✅ <b>PAIEMENT CONFIRMÉ</b>\n\n"
        f"📌 <b>{titre}</b>\n\n"
        "Votre accès est maintenant activé.\n\n"
        "🔗 <b>LIEN OFFICIEL DE CANDIDATURE :</b>\n"
        f"{lien_html}\n\n"
        "⚠️ Vérifiez toujours les informations "
        "sur le site officiel avant de transmettre "
        "vos documents.",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    logger.info(
        "Paiement candidature confirmé | "
        "user=%s | offre=%s | stars=%s",
        update.effective_user.id,
        offre_id,
        payment.total_amount,
    )


# ============================================================
# CATÉGORIE
# ============================================================

async def category_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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
        f"🔎 {len(resultats)} opportunité(s) "
        f"{categorie} trouvée(s)."
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
# RECHERCHE
# ============================================================

async def user_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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
            f"🤖 <b>ASSISTANT RÉSEAU MONDIAL</b>\n\n"
            f"🔎 {len(resultats)} opportunité(s) "
            "correspondant à votre demande :",
            parse_mode=ParseMode.HTML,
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
        "🤖 <b>ASSISTANT RÉSEAU MONDIAL</b>\n\n"
        "Je n'ai trouvé aucune opportunité "
        "correspondant à votre demande parmi "
        "les offres actuellement publiées.\n\n"
        "Vous pouvez essayer une autre recherche "
        "ou consulter le canal.",
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

    if update.message is None:
        return

    if not admin(update):

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
                "/ajouter STAGE | Titre | "
                "Description | Lien"
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

        if categorie not in (
            "EMPLOI",
            "STAGE",
            "BOURSE",
        ):

            await update.message.reply_text(
                "ℹ️ Choisissez :\n\n"
                "💼 EMPLOI\n"
                "🎓 STAGE\n"
                "🎓 BOURSE"
            )

            return

        if not titre:

            await update.message.reply_text(
                "ℹ️ Ajoutez le titre de l'offre."
            )

            return

        if not description:

            description = (
                "Consultez les informations "
                "disponibles pour cette opportunité."
            )

        offre_id = ajouter_offre(
            categorie=categorie,
            titre=titre,
            description=description,
            lien=lien,
            telegram_message_id=None,
        )

        categorie_html = html_safe(
            categorie,
            50,
        )

        titre_html = html_safe(
            titre,
            700,
        )

        description_html = html_safe(
            description,
            2500,
        )

        canal_text = (
            "📢 <b>NOUVELLE OPPORTUNITÉ</b>\n\n"
            f"📂 <b>{categorie_html}</b>\n\n"
            f"📌 <b>{titre_html}</b>\n\n"
            f"{description_html}\n\n"
            "👇 <b>Pour plus d'informations :</b>"
        )

        boutons = [
            InlineKeyboardButton(
                "👉 CANDIDATER • 100 ⭐",
                callback_data=f"CANDIDATER:{offre_id}",
            ),
            InlineKeyboardButton(
                "🤖 DEMANDER UNE OFFRE",
                url=bot_link("demande"),
            ),
        ]

        canal = channel_link()

        if canal:

            boutons.append(
                InlineKeyboardButton(
                    "📢 VOIR LE CANAL",
                    url=canal,
                )
            )

        publication = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=canal_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup(
                [boutons]
            ),
        )

        with db_lock:

            conn = get_db()

            conn.execute(
                """
                UPDATE offres
                SET telegram_message_id = ?
                WHERE id = ?
                """,
                (
                    publication.message_id,
                    offre_id,
                ),
            )

            conn.commit()
            conn.close()

        await update.message.reply_text(
            "✅ <b>OFFRE PUBLIÉE</b>\n\n"
            f"📂 {categorie_html}\n"
            f"📌 {titre_html}\n"
            f"🆔 Référence : <b>{offre_id}</b>\n\n"
            "📢 Elle est maintenant disponible "
            "dans le canal et dans la recherche "
            "du bot.",
            parse_mode=ParseMode.HTML,
        )

    except Exception:

        logger.exception(
            "Commande /ajouter"
        )

        await update.message.reply_text(
            "⚠️ Le service est momentanément "
            "indisponible pour cette opération.\n\n"
            "Vérifiez que le bot est administrateur "
            "du canal."
        )


# ============================================================
# TEST CANAL
# ============================================================

async def testcanal(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message is None:
        return

    if not admin(update):

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
                            url=bot_link("demande"),
                        )
                    ]
                ]
            ),
        )

        await update.message.reply_text(
            "✅ Test effectué : le message "
            "a été envoyé dans le canal."
        )

    except Exception:

        logger.exception(
            "Test canal"
        )

        await update.message.reply_text(
            "⚠️ Le bot ne peut pas publier "
            "dans le canal actuellement."
        )


# ============================================================
# PUBLIER LE BOUTON DU BOT
# ============================================================

async def publier_bot(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message is None:
        return

    if not admin(update):

        await update.message.reply_text(
            "⛔ Accès réservé à l'administrateur."
        )

        return

    texte = (
        "🤖 <b>BESOIN D'UNE OPPORTUNITÉ ?</b>\n\n"
        "💼 Emploi\n"
        "🎓 Stage\n"
        "🎓 Bourse\n\n"
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
                            url=bot_link("demande"),
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
            "⚠️ Le message n'a pas pu être publié."
        )


# ============================================================
# PUBLICATION AUTOMATIQUE
# ============================================================

async def hourly_post(
    context: ContextTypes.DEFAULT_TYPE,
):

    texte = (
        "🤖 <b>BOT OPPORTUNITÉS</b>\n\n"
        "Vous recherchez :\n\n"
        "💼 Emploi\n"
        "🎓 Stage\n"
        "🎓 Bourse\n\n"
        "Cliquez ci-dessous pour rechercher "
        "une opportunité."
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
                            url=bot_link("demande"),
                        )
                    ]
                ]
            ),
        )

        logger.info(
            "Publication automatique effectuée."
        )

    except Exception:

        logger.exception(
            "Publication automatique"
        )


# ============================================================
# STATISTIQUES
# ============================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message is None:
        return

    if not admin(update):

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

        conn.close()

    await update.message.reply_text(
        "📊 <b>STATISTIQUES</b>\n\n"
        f"📚 Total : <b>{total}</b>\n"
        f"💼 Emplois : <b>{emplois}</b>\n"
        f"🎓 Stages : <b>{stages}</b>\n"
        f"🎓 Bourses : <b>{bourses}</b>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# ERREUR GLOBALE
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.exception(
        "Erreur Telegram : %s",
        context.error,
    )


# ============================================================
# DÉMARRAGE
# ============================================================

def main():

    init_db()

    threading.Thread(
        target=run_flask,
        daemon=True,
    ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

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

    application.add_handler(
        CallbackQueryHandler(
            candidature_callback,
            pattern=r"^CANDIDATER:\d+$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            category_callback,
            pattern=r"^(EMPLOI|STAGE|BOURSE)$",
        )
    )

    application.add_handler(
        PreCheckoutQueryHandler(
            precheckout_callback
        )
    )

    application.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment_callback,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            user_search,
        )
    )

    if application.job_queue:

        application.job_queue.run_repeating(
            hourly_post,
            interval=3600,
            first=3600,
        )

        logger.info(
            "Publication automatique activée."
        )

    else:

        logger.warning(
            "JobQueue absente : publication automatique désactivée."
        )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "BOT OPPORTUNITÉS DÉMARRÉ."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":
    main()
