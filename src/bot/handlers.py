import logging
import io
import asyncio
import tempfile
from typing import Dict, List, Optional
from aiogram import Router, types, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.utils.markdown import hcode, hbold, hpre
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

from src.config import ADMIN_USER_ID, TELEGRAM_CHANNEL_ID
from src.ai.generator import generate_text

admin_router = Router()
logger = logging.getLogger(__name__)

media_group_cache: Dict[str, List[types.Message]] = {}
processing_media_groups: set[str] = set()
MEDIA_GROUP_DELAY_S = 1.5

BOT_MAX_DOWNLOAD_SIZE = 20 * 1024 * 1024 

admin_router.message.filter(F.from_user.id == ADMIN_USER_ID)

@admin_router.message(CommandStart())
async def handle_start(message: types.Message):
    user_id = message.from_user.id
    logger.info(f"Получена команда /start от администратора {user_id}")
    cmd_text = hcode("/gen_text <ваш запрос>")
    cmd_photo = "Отправь фото (или альбом) с общей подписью-запросом"
    cmd_video = "Отправь видео с подписью-запросом"
    cmd_gif = "Отправь GIF с подписью-запросом"

    start_message = (
        f"Привет, Администратор! ID={user_id}\n"
        f"Я готов к работе.\n\n"
        f"<b>Команды:</b>\n"
        f"1. {cmd_text} - генерация текстового поста.\n"
        f"2. {cmd_photo} - генерация текста по фото/альбому и подписи.\n"
        f"3. {cmd_video} - генерация текста по видео и подписи.\n"
        f"4. {cmd_gif} - генерация текста по GIF и подписи.\n\n"
        f"(Публикация: сначала медиа, потом текст).\n"
        f"(Файлы > {round(BOT_MAX_DOWNLOAD_SIZE / (1024*1024))}МБ не анализируются, текст генерируется по подписи)."
    )
    try:
        await message.answer(start_message)
    except Exception as e:
        logger.error(f"Ошибка в handle_start при отправке ответа: {e}", exc_info=True)
        try:
            await message.answer("Произошла ошибка при формировании приветственного сообщения. Проверьте логи.")
        except Exception as inner_e:
             logger.error(f"Не удалось отправить даже простое сообщение в handle_start: {inner_e}")

@admin_router.message(Command(commands=["gen_text"]))
async def handle_generate_text_command(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    command_args = message.text.split(maxsplit=1)
    if len(command_args) < 2 or not command_args[1].strip():
        await message.answer(f"Пожалуйста, укажи текст запроса после команды.\n"
                             f"Пример: {hcode('/gen_text Расскажи о погоде')}")
        return

    prompt = command_args[1].strip()
    logger.info(f"Администратор {user_id} запросил /gen_text: '{prompt[:100]}...'")

    if not TELEGRAM_CHANNEL_ID:
        await message.answer("❌ Ошибка: ID канала для публикации не настроен в конфигурации.")
        logger.error("Попытка /gen_text без TELEGRAM_CHANNEL_ID.")
        return

    processing_message = await message.answer("⏳ Генерирую текст по вашему запросу...")
    generated_content = await generate_text(prompt=prompt, images_bytes=None, media_path=None, media_mime_type=None)

    if generated_content and not generated_content.startswith("(Ошибка:") and not generated_content.startswith("(Произошла ошибка"):
        logger.info("Текст успешно сгенерирован (/gen_text). Публикация в канал...")
        await processing_message.edit_text("✅ Текст сгенерирован! Публикую в канал...")
        try:
            await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=generated_content)
            logger.info(f"Текстовый пост (/gen_text) успешно отправлен в канал {TELEGRAM_CHANNEL_ID}")
            await processing_message.edit_text(f"✅ Текстовый пост на тему '{hbold(prompt[:50])}...' успешно опубликован!")
        except TelegramAPIError as e:
            logger.error(f"Ошибка API Telegram при отправке текстового поста (/gen_text): {e}", exc_info=True)
            await processing_message.edit_text(f"❌ Ошибка при публикации поста. Сгенерированный текст:\n\n{hpre(generated_content[:1500])}")
        except Exception as e:
            logger.error(f"Неизвестная ошибка при отправке текстового поста (/gen_text): {e}", exc_info=True)
            await processing_message.edit_text(f"❌ Неизвестная ошибка при публикации. Сгенерированный текст:\n\n{hpre(generated_content[:1500])}")
    elif generated_content:
         logger.error(f"Не удалось сгенерировать текст (/gen_text, ошибка AI): '{generated_content}' для промпта: '{prompt[:100]}...'")
         await processing_message.edit_text(f"❌ Не удалось сгенерировать текст.\n{hpre(generated_content)}")
    else:
        logger.error(f"Не удалось сгенерировать текст (/gen_text, AI вернул None) для промпта: '{prompt[:100]}...'")
        await processing_message.edit_text("❌ Не удалось сгенерировать текст (ошибка AI).")

@admin_router.message(F.photo, F.from_user.id == ADMIN_USER_ID)
async def handle_photo_message(message: types.Message, bot: Bot):
    """ Обрабатывает одиночные фото с подписью и медиагруппы (альбомы) фото. """
    if message.media_group_id:
        group_id = str(message.media_group_id)
        media_group_cache.setdefault(group_id, []).append(message)
        logger.debug(f"Добавлено фото в кэш группы {group_id}. Размер: {len(media_group_cache[group_id])}")
        if group_id not in processing_media_groups:
            processing_media_groups.add(group_id)
            asyncio.create_task(schedule_media_group_processing(group_id, bot))
            logger.info(f"Запланирована обработка медиагруппы {group_id} через {MEDIA_GROUP_DELAY_S} сек.")
    else:
        logger.info(f"Получено одиночное фото от админа {message.from_user.id}")
        if not message.caption:
            await message.reply("Это одиночное фото. Чтобы я его обработал, нужна подпись-запрос.")
            return
        prompt = message.caption.strip()
        file_id = message.photo[-1].file_id
        await process_single_photo(message, bot, prompt, file_id)

async def schedule_media_group_processing(group_id: str, bot: Bot):
    """ Ждет и запускает обработку медиагруппы фото. """
    await asyncio.sleep(MEDIA_GROUP_DELAY_S)
    logger.info(f"Время ожидания для группы {group_id} истекло. Запуск обработки.")
    try:
        await _process_media_group(group_id, bot)
    except Exception as e:
         logger.error(f"Критическая ошибка при обработке медиагруппы {group_id}: {e}", exc_info=True)
         if group_id in media_group_cache and media_group_cache[group_id]:
             first_message = media_group_cache[group_id][0]
             try: await first_message.reply(f"❌ Критическая ошибка обработки альбома {group_id}.")
             except: pass
    finally:
        media_group_cache.pop(group_id, None)
        processing_media_groups.discard(group_id)
        logger.info(f"Очищен кэш и статус обработки для группы {group_id}")

async def _process_media_group(group_id: str, bot: Bot):
    """ Обрабатывает собранную медиагруппу фото. """
    messages = media_group_cache.get(group_id, [])
    if not messages: return
    first_message = messages[0]
    prompt: Optional[str] = None
    for msg in messages:
        if msg.caption: prompt = msg.caption.strip(); break
    if not prompt: await first_message.reply("❌ В этом альбоме фото не найдена подпись-запрос."); return

    logger.info(f"Обработка медиагруппы {group_id} ({len(messages)} фото), запрос: '{prompt[:100]}...'")
    if not TELEGRAM_CHANNEL_ID: await first_message.reply("❌ ID канала не настроен."); return

    processing_message = await first_message.reply("⏳ Получил альбом. Скачиваю фото для анализа...")
    images_bytes_list: List[bytes] = []
    file_ids_list: List[str] = []
    download_errors = 0

    for i, msg in enumerate(messages):
        if msg.photo:
            file_id = msg.photo[-1].file_id
            file_ids_list.append(file_id)
            logger.debug(f"Скачивание фото #{i+1} (id={file_id}) гр. {group_id}")
            try:
                f_info = await bot.get_file(file_id)
                if f_info.file_size > BOT_MAX_DOWNLOAD_SIZE:
                    logger.warning(f"Фото #{i+1} гр. {group_id} ({f_info.file_size}b) > лимита. Пропуск.")
                    download_errors += 1; continue
                dl: io.BytesIO = await bot.download_file(f_info.file_path)
                images_bytes_list.append(dl.read()); dl.close()
            except Exception as e: download_errors += 1; logger.error(f"Ошибка скач. фото #{i+1} гр. {group_id}: {e}")

    if download_errors > 0: logger.warning(f"Ошибок скачивания в гр. {group_id}: {download_errors}.")
    if not images_bytes_list: await processing_message.edit_text("❌ Не удалось скачать фото из альбома."); return

    await processing_message.edit_text(f"⏳ Фото ({len(images_bytes_list)} шт.) обработаны. Генерирую текст поста...")
    generated_text = await generate_text(prompt=prompt, images_bytes=images_bytes_list, media_path=None, media_mime_type=None)

    if generated_text and not generated_text.startswith("(Ошибка:") and not generated_text.startswith("(Произошла ошибка"):
        logger.info(f"Текст сгенерирован для гр. {group_id}. Публикация...")
        await processing_message.edit_text(f"✅ Текст сгенерирован! Публикую в канал...")
        try:
            media_group_to_send = [types.InputMediaPhoto(media=fid) for fid in file_ids_list]
            if len(media_group_to_send) == 1:
                 await bot.send_photo(chat_id=TELEGRAM_CHANNEL_ID, photo=file_ids_list[0])
                 logger.info(f"Одиночное фото из гр. {group_id} отправлено.")
            elif len(media_group_to_send) > 1:
                 await bot.send_media_group(chat_id=TELEGRAM_CHANNEL_ID, media=media_group_to_send)
                 logger.info(f"Медиагруппа {group_id} ({len(file_ids_list)} фото) отправлена.")
            else:
                logger.warning(f"Нет фото для отправки в группе {group_id} после фильтрации.")
                await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=f"(Альбом не отправлен из-за размера фото)\n\n{generated_text}")
                await processing_message.edit_text(f"⚠️ Фото в альбоме слишком большие. Опубликован только текст.")
                return

            await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=generated_text)
            logger.info(f"Текст поста для гр. {group_id} отправлен после медиа.")
            await processing_message.edit_text(f"✅ Пост (альбом фото + текст) на тему '{hbold(prompt[:50])}...' успешно опубликован!")
        except Exception as e:
            logger.error(f"Ошибка отправки гр. {group_id}: {e}", exc_info=True)
            await processing_message.edit_text(f"❌ Ошибка публикации. Текст:\n\n{hpre(generated_text[:1500])}")
    elif generated_text:
        await processing_message.edit_text(f"❌ Не удалось сгенерировать текст для альбома.\n{hpre(generated_text)}")
    else:
        await processing_message.edit_text("❌ Не удалось сгенерировать текст для альбома (ошибка AI).")


async def process_single_photo(message: types.Message, bot: Bot, prompt: str, file_id: str):
    """ Обрабатывает одиночное фото с подписью. """
    logger.info(f"Обработка одиночного фото {file_id}, запрос: '{prompt[:100]}...'")
    if not TELEGRAM_CHANNEL_ID: await message.reply("❌ ID канала не настроен."); return

    processing_message = await message.reply("⏳ Получил фото. Скачиваю и обрабатываю для анализа...")
    image_bytes_to_send = None
    photo_was_analyzed = False

    try:
        file_info = await bot.get_file(file_id)
        if file_info.file_size > BOT_MAX_DOWNLOAD_SIZE:
             logger.warning(f"Одиночное фото {file_id} ({file_info.file_size}b) > лимита.")
             await processing_message.edit_text("⚠️ Фото слишком большое, генерирую только по тексту...")
        else:
             dl: io.BytesIO = await bot.download_file(file_info.file_path)
             image_bytes_to_send = dl.read(); dl.close()
             photo_was_analyzed = True
             logger.info(f"Фото {file_id} скачано.")
             await processing_message.edit_text("⏳ Фото обработано. Генерирую текст поста...")
    except Exception as e:
        logger.error(f"Ошибка подготовки фото {file_id}: {e}", exc_info=True)
        await processing_message.edit_text("❌ Ошибка скачивания фото. Генерация по тексту.")

    generated_text = await generate_text(
        prompt=prompt,
        images_bytes=[image_bytes_to_send] if image_bytes_to_send else None,
        media_path=None, media_mime_type=None
        )

    if generated_text and not generated_text.startswith("(Ошибка:") and not generated_text.startswith("(Произошла ошибка"):
        status_text = "с учетом фото" if photo_was_analyzed else "только по тексту"
        logger.info(f"Текст поста ({status_text}) сгенерирован для фото {file_id}. Публикация...")
        await processing_message.edit_text(f"✅ Текст поста ({status_text}) сгенерирован! Публикую...")
        try:
            await bot.send_photo(chat_id=TELEGRAM_CHANNEL_ID, photo=file_id)
            await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=generated_text)
            await processing_message.edit_text(f"✅ Пост (фото + текст {status_text}) опубликован!")
        except Exception as e:
            logger.error(f"Ошибка отправки фото {file_id}: {e}", exc_info=True)
            await processing_message.edit_text(f"❌ Ошибка публикации. Текст:\n\n{hpre(generated_text[:1500])}")
    elif generated_text:
        await processing_message.edit_text(f"❌ Ошибка AI: {hpre(generated_text)}")
    else:
        await processing_message.edit_text("❌ Не удалось сгенерировать текст (ошибка AI).")

@admin_router.message(F.video, F.caption, F.from_user.id == ADMIN_USER_ID)
async def handle_video_with_caption(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    prompt = message.caption.strip()
    video = message.video
    if not (video and video.file_id and video.mime_type):
        await message.reply("❌ Ошибка инфо о видео."); return

    file_id = video.file_id
    mime_type = video.mime_type
    logger.info(f"Админ {user_id} ВИДЕО {file_id} ({mime_type}), запрос: '{prompt[:100]}...'")
    if not TELEGRAM_CHANNEL_ID: await message.reply("❌ ID канала?"); return

    processing_message = await message.reply("⏳ Получил видео. Проверяю размер...")
    temp_video_path: Optional[str] = None
    generated_text: Optional[str] = None
    video_was_analyzed = False

    try:
        file_info = None
        try:
            file_info = await bot.get_file(file_id)
            logger.info(f"Размер видео {file_id}: {file_info.file_size} байт.")
        except TelegramBadRequest as e:
            if "file is too big" in str(e):
                 logger.warning(f"Видео {file_id} >20MB (get_file).")
                 await processing_message.edit_text(f"⚠️ Видео >20MB, анализ невозможен.\n⏳ Генерация по тексту...")
                 generated_text = await generate_text(prompt=prompt, media_path=None, media_mime_type=None)
            else: raise e
        else:
            if file_info.file_size > BOT_MAX_DOWNLOAD_SIZE:
                logger.warning(f"Видео {file_id} ({file_info.file_size}b) > лимита.")
                await processing_message.edit_text(f"⚠️ Видео >~{round(BOT_MAX_DOWNLOAD_SIZE/(1024*1024))}MB, анализ невозможен.\n⏳ Генерация по тексту...")
                generated_text = await generate_text(prompt=prompt, media_path=None, media_mime_type=None)
            else:
                await processing_message.edit_text("⏳ Скачиваю видео...")
                with tempfile.NamedTemporaryFile(suffix=f"_{file_id}.tmp", delete=True) as temp_file:
                    temp_video_path = temp_file.name
                    logger.info(f"Скачиваю видео {file_id} в {temp_video_path}")
                    await bot.download_file(file_info.file_path, destination=temp_file)
                    logger.info(f"Видео {file_id} скачано ({file_info.file_size} байт).")
                    await processing_message.edit_text(f"⏳ Видео скачано (~{round(file_info.file_size/1024/1024)}MB). Анализ...")
                    generated_text = await generate_text(prompt=prompt, media_path=temp_video_path, media_mime_type=mime_type)
                    video_was_analyzed = True
                logger.info(f"Временный файл для {file_id} удален.")
                temp_video_path = None

    except TelegramAPIError as e:
        logger.error(f"Ошибка TG API (видео {file_id}): {e}", exc_info=True)
        await processing_message.edit_text("❌ Ошибка Telegram при обработке видео.")
        return
    except Exception as e:
        logger.error(f"Ошибка подготовки видео {file_id}: {e}", exc_info=True)
        await processing_message.edit_text("❌ Ошибка подготовки видео.")
        return

    if generated_text and not generated_text.startswith("(Ошибка:") and not generated_text.startswith("(Произошла ошибка"):
        status_text = "с учетом видео" if video_was_analyzed else "только по тексту"
        logger.info(f"Текст ({status_text}) сген. для видео {file_id}. Публикация...")
        await processing_message.edit_text(f"✅ Текст ({status_text}) сгенерирован! Публикую...")
        try:
            await bot.send_video(chat_id=TELEGRAM_CHANNEL_ID, video=file_id)
            await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=generated_text)
            await processing_message.edit_text(f"✅ Пост (видео + текст {status_text}) опубликован!")
        except Exception as e:
            logger.error(f"Ошибка отправки видео/текста {file_id}: {e}", exc_info=True)
            await processing_message.edit_text(f"❌ Ошибка публикации. Текст:\n\n{hpre(generated_text[:1500])}")
    elif generated_text:
        await processing_message.edit_text(f"❌ Ошибка AI/FileAPI: {hpre(generated_text)}")
    else:
        await processing_message.edit_text("❌ Ошибка AI.")


@admin_router.message(F.animation, F.caption, F.from_user.id == ADMIN_USER_ID)
async def handle_animation_with_caption(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    prompt = message.caption.strip()
    animation = message.animation
    if not (animation and animation.file_id and animation.mime_type):
        await message.reply("❌ Ошибка инфо о GIF."); return

    file_id = animation.file_id
    mime_type = animation.mime_type
    logger.info(f"Админ {user_id} GIF {file_id} ({mime_type}), запрос: '{prompt[:100]}...'")
    if not TELEGRAM_CHANNEL_ID: await message.reply("❌ ID канала?"); return

    processing_message = await message.reply("⏳ Получил GIF. Проверяю размер...")
    temp_gif_path: Optional[str] = None
    generated_text: Optional[str] = None
    gif_was_analyzed = False

    try:
        file_info = None
        try:
            file_info = await bot.get_file(file_id)
            logger.info(f"Размер GIF {file_id}: {file_info.file_size} байт.")
        except TelegramBadRequest as e:
            if "file is too big" in str(e):
                 logger.warning(f"GIF {file_id} >20MB (get_file).");
                 await processing_message.edit_text(f"⚠️ GIF >20MB, анализ невозможен.\n⏳ Генерация по тексту...")
                 generated_text = await generate_text(prompt=prompt, media_path=None, media_mime_type=None)
            else: raise e
        else:
            if file_info.file_size > BOT_MAX_DOWNLOAD_SIZE:
                logger.warning(f"GIF {file_id} ({file_info.file_size}b) > лимита.")
                await processing_message.edit_text(f"⚠️ GIF >~{round(BOT_MAX_DOWNLOAD_SIZE/(1024*1024))}MB, анализ невозможен.\n⏳ Генерация по тексту...")
                generated_text = await generate_text(prompt=prompt, media_path=None, media_mime_type=None)
            else:
                await processing_message.edit_text("⏳ Скачиваю GIF...")
                with tempfile.NamedTemporaryFile(suffix=f"_{file_id}.gif", delete=True) as temp_file:
                    temp_gif_path = temp_file.name; logger.info(f"Скачиваю GIF {file_id} в {temp_gif_path}")
                    await bot.download_file(file_info.file_path, destination=temp_file)
                    logger.info(f"GIF {file_id} скачан ({file_info.file_size} байт).")
                    await processing_message.edit_text(f"⏳ GIF скачан (~{round(file_info.file_size/1024/1024)}MB). Анализ...")
                    generated_text = await generate_text(prompt=prompt, media_path=temp_gif_path, media_mime_type=mime_type)
                    gif_was_analyzed = True
                logger.info(f"Временный файл для GIF {file_id} удален.")
                temp_gif_path = None

    except TelegramAPIError as e:
        logger.error(f"Ошибка TG API (GIF {file_id}): {e}", exc_info=True); await processing_message.edit_text("❌ Ошибка Telegram при обработке GIF."); return
    except Exception as e:
        logger.error(f"Ошибка подготовки GIF {file_id}: {e}", exc_info=True); await processing_message.edit_text("❌ Ошибка подготовки GIF."); return

    if generated_text and not generated_text.startswith("(Ошибка:") and not generated_text.startswith("(Произошла ошибка"):
        status_text = "с учетом GIF" if gif_was_analyzed else "только по тексту"
        logger.info(f"Текст ({status_text}) сген. для GIF {file_id}. Публикация...")
        await processing_message.edit_text(f"✅ Текст ({status_text}) сгенерирован! Публикую...")
        try:
            await bot.send_animation(chat_id=TELEGRAM_CHANNEL_ID, animation=file_id)
            await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=generated_text)
            await processing_message.edit_text(f"✅ Пост (GIF + текст {status_text}) опубликован!")
        except Exception as e:
            logger.error(f"Ошибка отправки GIF/текста {file_id}: {e}", exc_info=True)
            await processing_message.edit_text(f"❌ Ошибка публикации. Текст:\n\n{hpre(generated_text[:1500])}")
    elif generated_text:
        await processing_message.edit_text(f"❌ Ошибка AI/FileAPI: {hpre(generated_text)}")
    else:
        await processing_message.edit_text("❌ Ошибка AI.")

@admin_router.message()
async def handle_admin_other_message(message: types.Message):
    user_id = message.from_user.id
    if (message.photo or message.video or message.animation) and not message.caption:
         media_type = message.content_type
         logger.info(f"Получено медиа ({media_type}) от админа {user_id} БЕЗ подписи.")
         await message.reply(f"Я вижу {media_type}, но нужна подпись-запрос, чтобы я его обработал.")
         return

    logger.info(f"Получено неопознанное сообщение от админа {user_id}. Тип: {message.content_type}.")
    await message.reply("Я получил твое сообщение, но не знаю, что с ним делать.\n"
                        f"Используй команду {hcode('/gen_text <...>')} или отправь фото/альбом/видео/GIF с подписью-запросом.")