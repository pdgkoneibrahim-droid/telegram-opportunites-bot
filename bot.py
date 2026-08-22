import os
import sqlite3
import logging
from datetime import datetime, timezone

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    PreCheckoutQueryHandler,
    filters,
)

# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@canalRM24")

# Ton identifiant Telegram administrateur
ADMIN_ID = 5056571209

# Prix mensuel Premium en Telegram Stars
PREMIUM_STARS = int(os.getenv("PREMIUM_STARS", "100"))

DATABASE = "opportunites.db"

# États du formulaire administrateur
CATEGORY, TITLE, DESCRIPTION, LINK, PREMIUM = range(5)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# BASE DE DONNÉES
# ============================================================

def db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    connection = db()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            link TEXT NOT NULL,
            premium INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            premium_until TEXT
        )
    """)

    connection.commit()
    connection.close()


# ============================================================
# UTILISATEURS PREMIUM
# ============================================================

def set_premium(user_id, expiration):
    connection = db()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO users (user_id, premium_until)
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET premium_until = excluded.premium_until
    """, (user_id, expiration))

    connection.commit()
    connection.close()


def is_premium(user_id):
    connection = db()
    cursor = connection.cursor()

    cursor.execute(
        "SELECT premium_until FROM users WHERE user_id = ?",
        (user_id,)
    )

    row = cursor.fetchone()
    connection.close()

    if not row or not row["premium_until"]:
        return False

    try:
        expiration = datetime.fromisoformat(row["premium_until"])
        return expiration > datetime.now(timezone.utc)
    except Exception:
        return False


# ============================================================
# MENU PRINCIPAL
# ============================================================

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("💼 Emploi", callback_data="cat_emploi"),
            InlineKeyboardButton("🧑‍💻 Stage", callback_data="cat_stage"),
        ],
        [
            InlineKeyboardButton("🎓 Bourse", callback_data="cat_bourse"),
        ],
        [
            InlineKeyboardButton("⭐ Premium", callback_data="premium"),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    text = (
        f"👋 Bonjour {user.first_name} !\n\n"
        "🌍 Bienvenue sur le bot Opportunités Internationales.\n\n"
        "Tu peux consulter gratuitement nos offres :\n\n"
        "💼 Emploi\n"
        "🧑‍💻 Stage\n"
        "🎓 Bourse internationale\n\n"
        "Les offres sont gratuites à consulter.\n"
        "⭐ Certaines offres nécessitent Premium pour accéder "
        "au lien de candidature.\n\n"
        "Choisis une catégorie :"
    )

    await update.message.reply_text(
        text,
        reply_markup=main_menu()
    )


# ============================================================
# AFFICHAGE DES OFFRES
# ============================================================

async def show_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category = query.data.replace("cat_", "")

    connection = db()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT * FROM offers
        WHERE category = ?
        ORDER BY id DESC
    """, (category,))

    offers = cursor.fetchall()
    connection.close()

    category_names = {
        "emploi": "💼 EMPLOI",
        "stage": "🧑‍💻 STAGE",
        "bourse": "🎓 BOURSES INTERNATIONALES",
    }

    if not offers:
        await query.message.reply_text(
            f"{category_names[category]}\n\n"
            "Aucune offre disponible pour le moment.",
            reply_markup=main_menu()
        )
        return

    await query.message.reply_text(
        f"{category_names[category]}\n\n"
        f"📢 {len(offers)} offre(s) disponible(s)."
    )

    for offer in offers:
        text = (
            f"{category_names[category]}\n\n"
            f"📌 <b>{offer['title']}</b>\n\n"
            f"{offer['description']}\n\n"
        )

        buttons = []

        if offer["premium"] == 1:
            if is_premium(query.from_user.id):
                buttons.append([
                    InlineKeyboardButton(
                        "🔗 Candidater",
                        url=offer["link"]
                    )
                ])
            else:
                buttons.append([
                    InlineKeyboardButton(
                        "⭐ Débloquer la candidature",
                        callback_data="premium"
                    )
                ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    "🔗 Candidater",
                    url=offer["link"]
                )
            ])

        await query.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )


# ============================================================
# PREMIUM
# ============================================================

async def premium_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if is_premium(user_id):
        await query.message.reply_text(
            "⭐ Tu es déjà membre Premium.\n\n"
            "Tu peux accéder aux liens de candidature "
            "des offres Premium."
        )
        return

    text = (
        "⭐ <b>ABONNEMENT PREMIUM</b>\n\n"
        "Avec Premium, tu peux accéder aux liens de candidature "
        "réservés aux membres.\n\n"
        f"💳 Prix : <b>{PREMIUM_STARS} Stars / mois</b>\n"
        "🔄 Renouvellement mensuel automatique\n"
        "📅 Période : 30 jours\n\n"
        "Les offres restent gratuites à consulter."
    )

    keyboard = [
        [
            InlineKeyboardButton(
                f"⭐ S'abonner — {PREMIUM_STARS} Stars",
                callback_data="subscribe"
            )
        ]
    ]

    await query.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    prices = [
        LabeledPrice(
            label="Abonnement Premium mensuel",
            amount=PREMIUM_STARS
        )
    ]

    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title="⭐ Premium Opportunités",
        description=(
            "Accès Premium aux liens de candidature "
            "des offres réservées."
        ),
        payload=f"premium_monthly_{query.from_user.id}",
        provider_token="",
        currency="XTR",
        prices=prices,
        subscription_period=30 * 24 * 60 * 60,
    )


# ============================================================
# PAIEMENT
# ============================================================

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query

    await query.answer(ok=True)


async def successful_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    payment = update.message.successful_payment

    expiration = payment.subscription_expiration_date

    if expiration:
        expiration_iso = expiration.astimezone(
            timezone.utc
        ).isoformat()
    else:
        expiration_iso = (
            datetime.now(timezone.utc)
        ).replace(
            day=datetime.now(timezone.utc).day
        ).isoformat()

    set_premium(
        update.effective_user.id,
        expiration_iso
    )

    await update.message.reply_text(
        "🎉 <b>Paiement confirmé !</b>\n\n"
        "⭐ Ton abonnement Premium est maintenant actif.\n\n"
        "Tu peux retourner au menu et consulter les offres "
        "pour accéder aux liens de candidature.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# ============================================================
# ADMINISTRATION
# ============================================================

def is_admin(user_id):
    return user_id == ADMIN_ID


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ Accès réservé à l'administrateur."
        )
        return

    keyboard = [
        [
            InlineKeyboardButton(
                "➕ Ajouter une offre",
                callback_data="admin_add"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Voir les offres",
                callback_data="admin_list"
            )
        ],
    ]

    await update.message.reply_text(
        "🔐 <b>Panneau administrateur</b>\n\n"
        "Choisis une action :",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_add_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return ConversationHandler.END

    keyboard = [
        [
            InlineKeyboardButton(
                "💼 Emploi",
                callback_data="add_emploi"
            )
        ],
        [
            InlineKeyboardButton(
                "🧑‍💻 Stage",
                callback_data="add_stage"
            )
        ],
        [
            InlineKeyboardButton(
                "🎓 Bourse",
                callback_data="add_bourse"
            )
        ],
    ]

    await query.message.reply_text(
        "Choisis la catégorie de l'offre :",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return CATEGORY


async def admin_category(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return ConversationHandler.END

    category = query.data.replace("add_", "")

    context.user_data["offer_category"] = category

    await query.message.reply_text(
        "📌 Envoie maintenant le <b>titre de l'offre</b>.",
        parse_mode="HTML"
    )

    return TITLE


async def admin_title(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["offer_title"] = update.message.text.strip()

    await update.message.reply_text(
        "📝 Envoie maintenant la <b>description complète</b> "
        "de l'offre.",
        parse_mode="HTML"
    )

    return DESCRIPTION


async def admin_description(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["offer_description"] = update.message.text.strip()

    await update.message.reply_text(
        "🔗 Envoie maintenant le <b>lien de candidature</b>.\n\n"
        "Exemple : https://exemple.com/candidature",
        parse_mode="HTML"
    )

    return LINK


async def admin_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    link = update.message.text.strip()

    if not (
        link.startswith("http://")
        or link.startswith("https://")
    ):
        await update.message.reply_text(
            "❌ Le lien doit commencer par http:// ou https://\n\n"
            "Envoie le lien de candidature à nouveau."
        )
        return LINK

    context.user_data["offer_link"] = link

    keyboard = [
        [
            InlineKeyboardButton(
                "⭐ Premium",
                callback_data="offer_premium"
            )
        ],
        [
            InlineKeyboardButton(
                "🆓 Gratuit",
                callback_data="offer_free"
            )
        ],
    ]

    await update.message.reply_text(
        "🔐 Qui peut accéder au lien de candidature ?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return PREMIUM


async def admin_premium(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return ConversationHandler.END

    premium = 1 if query.data == "offer_premium" else 0

    category = context.user_data["offer_category"]
    title = context.user_data["offer_title"]
    description = context.user_data["offer_description"]
    link = context.user_data["offer_link"]

    now = datetime.now(timezone.utc).isoformat()

    connection = db()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO offers (
            category,
            title,
            description,
            link,
            premium,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        category,
        title,
        description,
        link,
        premium,
        now
    ))

    offer_id = cursor.lastrowid

    connection.commit()
    connection.close()

    # Publication dans le canal
    category_names = {
        "emploi": "💼 OFFRE D'EMPLOI",
        "stage": "🧑‍💻 OFFRE DE STAGE",
        "bourse": "🎓 BOURSE INTERNATIONALE",
    }

    access = (
        "⭐ Lien de candidature réservé aux membres Premium."
        if premium
        else
        "🆓 Candidature gratuite."
    )

    publication = (
        f"{category_names[category]}\n\n"
        f"📌 <b>{title}</b>\n\n"
        f"{description}\n\n"
        f"{access}\n\n"
        "🤖 Consultez cette opportunité avec notre bot."
    )

    keyboard = []

    if not premium:
        keyboard.append([
            InlineKeyboardButton(
                "🔗 Candidater",
                url=link
            )
        ])
    else:
        keyboard.append([
            InlineKeyboardButton(
                "🤖 Ouvrir le bot",
                url="https://t.me/Pdgki_bot"
            )
        ])

    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=publication,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=False
        )

        await query.message.reply_text(
            f"✅ Offre #{offer_id} enregistrée et publiée dans "
            f"{CHANNEL_ID}."
        )

    except Exception as error:
        logger.exception(error)

        await query.message.reply_text(
            "⚠️ L'offre a été enregistrée, mais je n'ai pas pu "
            "la publier dans le canal.\n\n"
            "Vérifie que le bot est administrateur du canal."
        )

    context.user_data.clear()

    return ConversationHandler.END


async def admin_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    connection = db()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, category, title, premium
        FROM offers
        ORDER BY id DESC
        LIMIT 30
    """)

    offers = cursor.fetchall()
    connection.close()

    if not offers:
        await query.message.reply_text(
            "📭 Aucune offre enregistrée."
        )
        return

    text = "📋 <b>OFFRES ENREGISTRÉES</b>\n\n"

    for offer in offers:
        access = "⭐ Premium" if offer["premium"] else "🆓 Gratuit"

        text += (
            f"#{offer['id']} — {offer['category'].upper()}\n"
            f"📌 {offer['title']}\n"
            f"🔐 {access}\n\n"
        )

    await query.message.reply_text(
        text,
        parse_mode="HTML"
    )


# ============================================================
# ANNULATION
# ============================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ Opération annulée."
    )

    return ConversationHandler.END


# ============================================================
# ERREURS
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    logger.exception(
        "Exception pendant le traitement d'une mise à jour:",
        exc_info=context.error
    )


# ============================================================
# DÉMARRAGE
# ============================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN n'est pas configuré dans Render."
        )

    init_database()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commandes utilisateurs
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CallbackQueryHandler(
            show_category,
            pattern=r"^cat_(emploi|stage|bourse)$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            premium_menu,
            pattern=r"^premium$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            subscribe,
            pattern=r"^subscribe$"
        )
    )

    # Paiements
    application.add_handler(
        PreCheckoutQueryHandler(precheckout)
    )

    application.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment
        )
    )

    # Administration
    application.add_handler(
        CommandHandler("admin", admin)
    )

    conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                admin_add_start,
                pattern=r"^admin_add$"
            )
        ],
        states={
            CATEGORY: [
                CallbackQueryHandler(
                    admin_category,
                    pattern=r"^add_(emploi|stage|bourse)$"
                )
            ],
            TITLE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_title
                )
            ],
            DESCRIPTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_description
                )
            ],
            LINK: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_link
                )
            ],
            PREMIUM: [
                CallbackQueryHandler(
                    admin_premium,
                    pattern=r"^offer_(premium|free)$"
                )
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel)
        ],
        per_user=True,
        per_chat=True,
    )

    application.add_handler(conversation)

    application.add_handler(
        CallbackQueryHandler(
            admin_list,
            pattern=r"^admin_list$"
        )
    )

    application.add_error_handler(error_handler)

    logger.info("🤖 Bot démarré...")

    # Le bot reste actif et écoute les utilisateurs
    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
