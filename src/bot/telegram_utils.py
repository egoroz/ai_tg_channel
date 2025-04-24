import logging
from aiogram import Bot
from aiogram.types import InputFile, URLInputFile
from aiogram.exceptions import TelegramAPIError

from src.config import TELEGRAM_CHANNEL_ID

logger = logging.getLogger(__name__)

async def post_to_channel(
    bot: Bot,
    text: str | None = None,
    photo: str | InputFile | None = None,
    video: str | InputFile | None = None
    ) -> bool:
    """
    Отправляет сообщение с текстом и/или медиа в заданный канал.

    Args:
        bot: Экземпляр aiogram Bot.
        text: Текст сообщения (может быть caption для медиа).
        photo: URL или InputFile изображения.
        video: URL или InputFile видео.

    Returns:
        True если успешно, False в случае ошибки.
    """
    if not TELEGRAM_CHANNEL_ID:
        logger.error("Не указан ID канала (TELEGRAM_CHANNEL_ID). Постинг невозможен.")
        return False

    if not text and not photo and not video:
        logger.warning("Попытка отправить пустой пост в канал.")
        return False

    try:
        target_chat_id = TELEGRAM_CHANNEL_ID
        if photo:
            if isinstance(photo, str):
                logger.info(f"Отправка фото (URL) в канал {target_chat_id} с текстом (caption): {text[:50] if text else 'Нет'}...")
                await bot.send_photo(chat_id=target_chat_id, photo=URLInputFile(photo), caption=text)
            else:
                logger.info(f"Отправка фото (InputFile) в канал {target_chat_id} с текстом (caption): {text[:50] if text else 'Нет'}...")
                await bot.send_photo(chat_id=target_chat_id, photo=photo, caption=text)

        elif video:
             if isinstance(video, str):
                logger.info(f"Отправка видео (URL) в канал {target_chat_id} с текстом (caption): {text[:50] if text else 'Нет'}...")
                await bot.send_video(chat_id=target_chat_id, video=URLInputFile(video), caption=text)
             else:
                logger.info(f"Отправка видео (InputFile) в канал {target_chat_id} с текстом (caption): {text[:50] if text else 'Нет'}...")
                await bot.send_video(chat_id=target_chat_id, video=video, caption=text)

        elif text:
            logger.info(f"Отправка текста в канал {target_chat_id}: {text[:100]}...")
            await bot.send_message(chat_id=target_chat_id, text=text)

        logger.info(f"Пост успешно отправлен в канал {target_chat_id}")
        return True

    except TelegramAPIError as e:
        logger.error(f"Ошибка API Telegram при отправке поста в канал {TELEGRAM_CHANNEL_ID}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при отправке поста в канал: {e}", exc_info=True)
        return False