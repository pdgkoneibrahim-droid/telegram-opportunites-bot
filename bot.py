import os
import asyncio
from telegram import Bot

CHANNEL_ID = "@canalRM24"
BOT_TOKEN = os.getenv("BOT_TOKEN")


async def publier(texte):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN n'est pas configuré.")

    bot = Bot(token=BOT_TOKEN)

    await bot.send_message(
        chat_id=CHANNEL_ID,
        text=texte,
        disable_web_page_preview=False
    )


async def main():
    message = """🌍 OPPORTUNITÉS INTERNATIONALES

💼 OFFRES D'EMPLOI
🧑‍💻 OFFRES DE STAGE
🎓 BOURSES INTERNATIONALES

📢 Retrouvez régulièrement sur notre canal des opportunités
d'emploi, de stage et d'études à l'international.

🔗 Canal officiel :
@canalRM24
"""

    try:
        await publier(message)
        print("✅ Publication envoyée dans @canalRM24")

    except Exception as erreur:
        print(f"❌ Erreur : {erreur}")


if __name__ == "__main__":
    asyncio.run(main())
