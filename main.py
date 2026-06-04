from dotenv import load_dotenv

load_dotenv()

from telegram import Update

from app import telegram_app


def main():
    telegram_app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()