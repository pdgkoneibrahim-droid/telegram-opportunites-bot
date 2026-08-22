import os
import asyncio
from telegram import Bot

# Canal Telegram
CHANNEL_ID = "@canalRM24"

# Le token sera ajouté plus tard dans GitHub Secrets
BOT_TOKEN = os.getenv("BOT_TOKEN")


async def publier_message(texte):
    bot = Bot(token=BOT_TOKEN)
    await bot.send_message(
        chat_id=CHANNEL_ID,
        text=texte,
        disable_web_page_preview=False
    )


async def main():
    if not BOT_TOKEN:
        print("❌ Le token BOT_TOKEN n'est pas configuré.")
        return

    bot = Bot(token=BOT_TOKEN)

    try:
        informations = await bot.get_me()
        print(f"✅ Bot connecté : @{informations.username}")

        await publier_message(
            """🌍 OPPORTUNITÉS INTERNATIONALES

💼 OFFRES D'EMPLOI
🧑‍💻 OFFRES DE STAGE
🎓 BOURSES D'ÉTUDES
🌎 OPPORTUNITÉS INTERNATIONALES

📢 Restez abonnés à notre canal pour découvrir régulièrement de nouvelles opportunités.

🔗 Canal : @canalRM24"""
        )

        print("✅ Publication envoyée avec succès.")

    except Exception as erreur:
        print(f"❌ Erreur : {erreur}")


if __name__ == "__main__":
    asyncio.run(main())
