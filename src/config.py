import os
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.critical("Не найден токен Telegram бота!")
    raise ValueError("Не найден токен Telegram бота!")

TELEGRAM_CHANNEL_ID_STR = os.getenv("TELEGRAM_CHANNEL_ID")
TELEGRAM_CHANNEL_ID = None
if TELEGRAM_CHANNEL_ID_STR:
    try:
        TELEGRAM_CHANNEL_ID = int(TELEGRAM_CHANNEL_ID_STR)
    except ValueError:
        logger.error(f"Неверный формат TELEGRAM_CHANNEL_ID: {TELEGRAM_CHANNEL_ID_STR}. Ожидалось число.")
        raise ValueError("Неверный формат TELEGRAM_CHANNEL_ID")
else:
    logger.warning("Не найден ID канала Telegram (TELEGRAM_CHANNEL_ID). Постинг в канал не будет работать.")

ADMIN_USER_ID_STR = os.getenv("ADMIN_USER_ID")
ADMIN_USER_ID = None
if ADMIN_USER_ID_STR:
    try:
        ADMIN_USER_ID = int(ADMIN_USER_ID_STR)
    except ValueError:
        logger.error(f"Неверный формат ADMIN_USER_ID: {ADMIN_USER_ID_STR}.")
        raise ValueError("Неверный формат ADMIN_USER_ID")
else:
    logger.critical("Не найден ID администратора (ADMIN_USER_ID).")
    raise ValueError("Не найден ID администратора!")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
     logger.warning("Не найден API ключ Google Gemini (GEMINI_API_KEY). Функции генерации AI не будут работать.")

CHANNEL_PERSONA = os.getenv("CHANNEL_PERSONA")
if not CHANNEL_PERSONA:
    logger.warning("Не найдена персона канала (CHANNEL_PERSONA). Будет использована персона по умолчанию.")
    CHANNEL_PERSONA = "Ты - полезный AI ассистент."

PROXY_URL = os.getenv("PROXY_URL")

logger.info("Конфигурация загружена.")
logger.info(f"Admin User ID: {ADMIN_USER_ID}")
logger.info(f"Target Channel ID: {TELEGRAM_CHANNEL_ID}")
logger.info(f"Channel Persona loaded (first 50 chars): {CHANNEL_PERSONA[:50]}...")
logger.info(f"Google Gemini API Key loaded: {'Yes' if GEMINI_API_KEY else 'No'}")
if PROXY_URL:
    logger.info(f"Proxy URL configured via PROXY_URL")
else:
    logger.info("Proxy URL (PROXY_URL) is not set. Proxy will not be explicitly configured.")