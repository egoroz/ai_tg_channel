import logging
import google.generativeai as genai
import io
from PIL import Image
from typing import List, Optional
from google.api_core import exceptions as google_api_exceptions

from src.config import GEMINI_API_KEY, CHANNEL_PERSONA, PROXY_URL

logger = logging.getLogger(__name__)

model = None
if GEMINI_API_KEY:
    try:
        proxy_config = None
        if PROXY_URL:
            proxy_config = PROXY_URL
            logger.info(f"Configuring Google Gemini to use proxy: {proxy_config}")
        else:
            logger.info("Proxy URL not set, configuring Google Gemini without explicit proxy.")

        genai.configure(api_key=GEMINI_API_KEY)

        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        logger.info(f"Модель Google Gemini '{model.model_name}' инициализирована (с поддержкой Vision/Video/GIF).")
       
    except Exception as e:
        logger.error(f"Ошибка инициализации Google Generative AI: {e}", exc_info=True)
        model = None
else:
    logger.warning("API ключ Google Gemini не предоставлен. Генерация текста будет недоступна.")


async def generate_text(
    prompt: str,
    images_bytes: Optional[List[bytes]] = None,
    media_path: Optional[str] = None,
    media_mime_type: Optional[str] = None     
    ) -> str | None:
    """
    Генерирует текст с помощью Gemini API, опционально используя
    изображения (байты) или медиафайл (видео/GIF по пути через File API).
    """
    if not model:
        logger.error("Модель Gemini не инициализирована."); return "(Ошибка: Модель Gemini не инициализирована)"

    content_parts = []
    uploaded_file = None
    images_log_count = 0
    media_log_status = "No"

    full_text_prompt = f"{CHANNEL_PERSONA}\n\nЗадача: {prompt}"
    content_parts.append(full_text_prompt)
    
    if images_bytes and not (media_path and media_mime_type):
        media_log_status = "Skipped (has images)"
        valid_images_count = 0
        for i, img_bytes in enumerate(images_bytes):
            try: img = Image.open(io.BytesIO(img_bytes)); content_parts.append(img); valid_images_count += 1
            except: logger.error(f"Ошибка обработки изображения #{i+1}", exc_info=True)
        images_log_count = valid_images_count
        if images_log_count > 0: logger.info(f"Добавлено {images_log_count} изображений.")
        else: logger.warning("Не удалось добавить изображения.")

    elif media_path and media_mime_type:
        images_log_count = 0
        logger.info(f"Попытка загрузить медиафайл: {media_path} ({media_mime_type}) через File API...")
        try:
            uploaded_file = genai.upload_file(path=media_path, mime_type=media_mime_type, display_name="user_media_upload")
            media_log_status = f"Uploaded ({uploaded_file.name}, type: {media_mime_type})"
            logger.info(f"Медиафайл успешно загружен. Name: {uploaded_file.name}, URI: {uploaded_file.uri}")
            content_parts.append(uploaded_file)
            logger.info("Объект загруженного медиафайла добавлен в запрос к Gemini.")

        except ConnectionRefusedError as cre:
            media_log_status = "Error (Conn Refused)"
            logger.error(f"Connection Refused при загрузке медиафайла: {cre}. Проверьте доступность и настройки прокси {PROXY_URL}.", exc_info=True)
            return f"(Ошибка: Отказ в соединении при загрузке медиа. Проверьте прокси/сеть: {cre})"
        except google_api_exceptions.GoogleAPIError as e:
            media_log_status = "Error (Google API)"; logger.error(f"Ошибка Google API при загрузке медиафайла: {e}", exc_info=True)
            if uploaded_file:
                try: genai.delete_file(uploaded_file.name); logger.info(f"Удален файл {uploaded_file.name} после ошибки Google API.")
                except Exception as del_e: logger.error(f"Ошибка удаления файла {uploaded_file.name}: {del_e}")
            return f"(Ошибка Google API при загрузке медиа: {e})"
        except FileNotFoundError:
             media_log_status = "Error (Not Found)"; logger.error(f"Медиафайл не найден по пути: {media_path}")
             return f"(Ошибка: Медиафайл не найден - {media_path})"
        except Exception as e:
            media_log_status = "Error (Unknown Upload)"; logger.error(f"Неизвестная ошибка при загрузке медиафайла: {e}", exc_info=True)
            if uploaded_file:
                try: genai.delete_file(uploaded_file.name); logger.info(f"Удален файл {uploaded_file.name} после неизвестной ошибки.")
                except Exception as del_e: logger.error(f"Ошибка удаления файла {uploaded_file.name}: {del_e}")
            return f"(Ошибка при загрузке медиафайла: {e})"

    logger.info(f"Запрос к Gemini API: model={model.model_name}, images={images_log_count}, media_file={media_log_status}, prompt='{prompt[:100]}...'")
    generated_text_result: Optional[str] = None
    try:
        response = model.generate_content(content_parts)
        if not response.parts:
             if response.prompt_feedback.block_reason:
                 block_reason = response.prompt_feedback.block_reason; logger.error(f"Ответ заблокирован: {block_reason}")
                 safety = hasattr(response, 'candidates') and response.candidates and response.candidates[0].finish_reason == "SAFETY"
                 generated_text_result = "Ограничения безопасности." if safety else f"(Ошибка: Блокировка - {block_reason})"
             else: logger.error("Пустой ответ от Gemini."); generated_text_result = "(Ошибка: пустой ответ Gemini)"
        else: generated_text = response.text.strip(); logger.info(f"Ответ Gemini: {len(generated_text)} симв."); generated_text_result = generated_text if generated_text else None
    except ConnectionRefusedError as cre:
        logger.error(f"Connection Refused при вызове generate_content: {cre}. Проверьте доступность и настройки прокси {PROXY_URL}.", exc_info=True)
        generated_text_result = f"(Ошибка: Отказ в соединении при генерации. Проверьте прокси/сеть: {cre})"
    except Exception as e:
        logger.error(f"Ошибка вызова Gemini API: {e}", exc_info=True)
        generated_text_result = f"(Ошибка вызова Gemini API: {e})"

    finally:
        if uploaded_file:
            try: logger.info(f"Удаление загруженного файла: {uploaded_file.name}"); genai.delete_file(uploaded_file.name); logger.info(f"Файл {uploaded_file.name} удален.")
            except Exception as e: logger.error(f"Ошибка удаления файла {uploaded_file.name}: {e}", exc_info=True)

    return generated_text_result