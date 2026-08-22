import os
import asyncio
from telegram import Bot

CHANNEL_ID = "@canalRM24"
BOT_TOKEN = os.getenv("BOT_TOKEN")


async def publier_opportunite(titre, categorie, description, lien):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN n'est pas configuré.")

    bot = Bot(token=BOT_TOKEN)

    message = f"""🌍 OPPORTUNITÉ INTERNATIONALE

{categorie}

📌 {titre}

📝 {description}

🔗 Candidature :
{lien}

📢 Abonne-toi à @canalRM24 pour recevoir les prochaines opportunités.
"""

    await bot.send_message(
        chat_id=CHANNEL_ID,
        text=message,
        disable_web_page_preview=False
    )


async def main():
    try:
        bot = Bot(BOT_TOKEN)

        me = await bot.get_me()
        print(f"✅ Bot connecté : @{me.username}")

        await publier_opportunite(
            titre="Exemple d'offre à remplacer",
            categorie="💼 EMPLOI",
            description="Cette publication est un test du système de publication automatique.",
            lien="https://example.com"
        )

        print("✅ Publication de test réussie.")

    except Exception as erreur:
        print(f"❌ Erreur : {erreur}")


if __name__ == "__main__":
    asyncio.run(main())
