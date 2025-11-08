import logging
import sys
import os
import asyncio

# --- ИМПОРТЫ ДЛЯ AIOGRAM 3.X ---
from aiogram import Bot, Dispatcher, types, F # Добавлен F для фильтров
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage 
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import ChatNotFound, MessageNotModified # Изменен путь к исключениям

# --- 0. Импорт dotenv для локальной разработки ---
try:
    from dotenv import load_dotenv
    # Загружаем переменные из файла .env в текущей директории
    load_dotenv() 
except ImportError:
    pass 

# --- 1. Настройка логгирования ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 2. Конфигурация (Чтение из переменных окружения) ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
LOG_GROUP_ID_STR = os.getenv('LOG_GROUP_ID') 

if not BOT_TOKEN:
    logger.error("Ошибка: Переменная окружения BOT_TOKEN не установлена.")
    sys.exit(1)

if not LOG_GROUP_ID_STR:
    logger.error("Ошибка: Переменная окружения LOG_GROUP_ID не установлена.")
    sys.exit(1)

try:
    # Важно: для супергрупп ID должен быть отрицательным (например, -100XXXXXXXXX)
    LOG_GROUP_ID = int(LOG_GROUP_ID_STR)
except ValueError:
    logger.error(f"Ошибка: LOG_GROUP_ID ('{LOG_GROUP_ID_STR}') не является корректным числом.")
    sys.exit(1)

# --- 3. Инициализация бота, диспетчера и FSM Storage ---
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
# В aiogram 3.x диспетчер инициализируется без объекта bot, он передается в start_polling
dp = Dispatcher(storage=storage) 

# --- 4. Хранилище для маппинга сообщений и FSM States ---
# Ключ: ID сообщения в лог-группе, Значение: ID пользователя, который его отправил
MESSAGE_MAP = {} 

class SupportStates(StatesGroup):
    waiting_for_support_message = State()

class OrderStates(StatesGroup):
    waiting_for_purchase_item = State()

class ReviewStates(StatesGroup):
    waiting_for_review_type = State() 
    waiting_for_review_text = State()

# --- 5. Клавиатуры ---

def get_main_menu_keyboard():
    """Возвращает клавиатуру главного меню (row_width=1)."""
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton(text="🛒 ЗАКАЗЫ", callback_data="start_order"), 
        types.InlineKeyboardButton(text="💬 Техподдержка", callback_data="start_support"),
        types.InlineKeyboardButton(text="⭐ ОТЗЫВЫ", callback_data="start_review")
    )
    return keyboard

def get_cancel_keyboard():
    """Возвращает клавиатуру с кнопкой 'Отмена / В главное меню' (row_width=1)."""
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(text="❌ Отмена / В главное меню", callback_data="cancel_to_menu")
    )
    return keyboard

def get_review_type_keyboard():
    """Возвращает клавиатуру выбора типа отзыва (row_width=2)."""
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton(text="👍 Положительный", callback_data="review_type_positive"),
        types.InlineKeyboardButton(text="👎 Отрицательный", callback_data="review_type_negative"),
        types.InlineKeyboardButton(text="❌ Отмена / В главное меню", callback_data="cancel_to_menu")
    )
    return keyboard

def get_support_reply_keyboard(user_id):
    """Возвращает кнопку 'Ответить' для лог-группы."""
    keyboard = types.InlineKeyboardMarkup()
    # Кнопка для напоминания админу, как отвечать (см. handler process_reply_button)
    keyboard.add(types.InlineKeyboardButton(text="Ответить", callback_data=f"reply_{user_id}"))
    return keyboard

# --- 6. Универсальный хендлер для отмены ---

# В aiogram 3.x используем F.data вместо лямбда-функций в декораторах для фильтрации
@dp.callback_query(F.data == 'cancel_to_menu') 
async def process_cancel_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Сбрасывает FSM-состояние и возвращает в главное меню."""
    await bot.answer_callback_query(callback_query.id, text="Отменено.")
    await state.clear() # В aiogram 3.x используем .clear() вместо .finish()
    
    # Пытаемся удалить сообщение, если оно было отредактировано (например, при выборе отзыва)
    try:
        await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
    except Exception:
        pass # Игнорируем ошибку, если сообщение уже удалено или не может быть удалено
        
    await bot.send_message(
        callback_query.from_user.id,
        "Действие отменено. Вы вернулись в главное меню.",
        reply_markup=get_main_menu_keyboard()
    )

# --- 7. Хендлеры для пользователя (Главное меню) ---

# В aiogram 3.x используем dp.message вместо dp.message_handler, и F.command
@dp.message(F.command('start') | F.command('menu')) 
async def start_command(message: types.Message, state: FSMContext):
    await state.clear() # В aiogram 3.x используем .clear()
    await message.reply(
        "Добро пожаловать! Выберите нужный раздел:",
        reply_markup=get_main_menu_keyboard()
    )

# --- 8. Хендлеры для ЗАКАЗОВ (FSM) ---

@dp.callback_query(F.data == 'start_order') 
async def process_start_order_callback(callback_query: types.CallbackQuery, state: FSMContext): # Добавляем state: FSMContext
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        "Отлично! Что бы вы хотели приобрести?",
        reply_markup=get_cancel_keyboard() 
    )
    await state.set_state(OrderStates.waiting_for_purchase_item) # Используем .set_state()

@dp.message(OrderStates.waiting_for_purchase_item, F.content_type == types.ContentType.TEXT) # F.content_type
async def handle_purchase_item(message: types.Message, state: FSMContext):
    logger.info(f"Получен заказ от {message.from_user.id}: {message.text}")
    await message.reply(
        "Спасибо за ваш заказ! Мы скоро свяжемся с вами для уточнения деталей.",
        reply_markup=get_main_menu_keyboard()
    )
    await state.clear() # В aiogram 3.x используем .clear()

@dp.message(OrderStates.waiting_for_purchase_item) # Ловим все, что не TEXT
async def handle_invalid_order_input(message: types.Message):
    await message.reply("Пожалуйста, опишите ваш заказ текстом.", reply_markup=get_cancel_keyboard())


# --- 9. Хендлеры для Техподдержки (FSM) ---

@dp.callback_query(F.data == 'start_support') 
async def process_start_support_callback(callback_query: types.CallbackQuery, state: FSMContext): # Добавляем state: FSMContext
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        "Напишите ваше сообщение для оператора, или отправьте фото/документ. Как только вы его отправите, мы передадим его в техподдержку.",
        reply_markup=get_cancel_keyboard() 
    )
    await state.set_state(SupportStates.waiting_for_support_message) # Используем .set_state()

@dp.message(SupportStates.waiting_for_support_message, F.content_type != types.ContentType.UNKNOWN) # F.content_type
async def handle_user_support_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear() # В aiogram 3.x используем .clear()
    
    log_header = (
        f"❓ **НОВЫЙ ЗАПРОС В ТЕХПОДДЕРЖКУ**\n"
        f"От: {message.from_user.full_name} (@{message.from_user.username or 'нет'})\n"
        f"ID: `{user_id}`\n"
    )
    
    try:
        if message.content_type == types.ContentType.TEXT:
            log_text = log_header + f"\nТекст:\n{message.text}"
            log_message = await bot.send_message(
                chat_id=LOG_GROUP_ID, 
                text=log_text, 
                reply_markup=get_support_reply_keyboard(user_id),
                parse_mode=types.ParseMode.MARKDOWN
            )
        else:
            # Отправляем заголовок отдельно
            await bot.send_message(
                chat_id=LOG_GROUP_ID, 
                text=log_header, 
                parse_mode=types.ParseMode.MARKDOWN
            )
            
            # Копируем медиафайл
            log_message = await bot.copy_message(
                chat_id=LOG_GROUP_ID,
                from_chat_id=user_id,
                message_id=message.message_id,
                reply_markup=get_support_reply_keyboard(user_id)
            )
            
            # Если есть подпись, она будет скопирована вместе с медиа
            # Дополнительное сообщение о подписи, как в оригинале, не нужно, если copy_message работает корректно
                
        MESSAGE_MAP[log_message.message_id] = user_id
        logger.info(f"Запрос от {user_id} залогирован под ID сообщения {log_message.message_id}")
        
    except Exception as e:
        logger.exception(f"Ошибка при отправке запроса в группу логов:")
        await message.answer(
            "Произошла ошибка при регистрации вашего запроса. Попробуйте позже.", 
            reply_markup=get_main_menu_keyboard()
        )
        return

    await message.reply(
        "Ваш запрос принят. Ожидайте ответа оператора.",
        reply_markup=get_main_menu_keyboard()
    )


# --- 10. Хендлеры для ОТЗЫВОВ (FSM) ---

@dp.callback_query(F.data == 'start_review') 
async def process_start_review_callback(callback_query: types.CallbackQuery, state: FSMContext): # Добавляем state: FSMContext
    """Шаг 1: Предлагаем выбрать тип отзыва."""
    await bot.answer_callback_query(callback_query.id)
    
    await bot.send_message(
        callback_query.from_user.id,
        "Выберите, пожалуйста, тип отзыва:",
        reply_markup=get_review_type_keyboard()
    )
    await state.set_state(ReviewStates.waiting_for_review_type) # Используем .set_state()

@dp.callback_query(ReviewStates.waiting_for_review_type, F.data.startswith('review_type_')) 
async def process_review_type_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """Шаг 2: Получаем тип отзыва и просим ввести текст."""
    await bot.answer_callback_query(callback_query.id)
    
    review_type = callback_query.data.split('_')[-1] 
    
    await state.update_data(review_type=review_type)
    
    if review_type == 'positive':
        prompt = "Спасибо! Напишите, что вам больше всего понравилось в нашей работе."
    else:
        prompt = "Нам очень жаль! Пожалуйста, опишите, что пошло не так, чтобы мы могли исправиться."
        
    # Редактируем сообщение, удаляя кнопки выбора типа и добавляя кнопку отмены
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=prompt,
        reply_markup=get_cancel_keyboard() 
    )
    
    await state.set_state(ReviewStates.waiting_for_review_text) # Используем .set_state()

@dp.message(ReviewStates.waiting_for_review_text, F.content_type == types.ContentType.TEXT)
async def handle_user_review(message: types.Message, state: FSMContext):
    """Шаг 3: Обрабатывает полученный отзыв и отправляет его в лог-группу."""
    user_id = message.from_user.id
    review_text = message.text
    
    data = await state.get_data()
    review_type = data.get('review_type', 'неизвестный')
    
    await state.clear() # В aiogram 3.x используем .clear()
    
    if review_type == 'positive':
        log_title = "✅ ПОЛОЖИТЕЛЬНЫЙ ОТЗЫВ"
        reply_text = "Ваш положительный отзыв успешно принят! Спасибо за вашу обратную связь."
    else:
        log_title = "❌ ОТРИЦАТЕЛЬНЫЙ ОТЗЫВ"
        reply_text = "Ваш отрицательный отзыв принят. Мы обязательно изучим вашу проблему и свяжемся с вами, если потребуется уточнение."

    log_text = (
        f"⭐ **{log_title}**\n"
        f"От: {message.from_user.full_name} (@{message.from_user.username or 'нет'})\n"
        f"ID: `{user_id}`\n\n"
        f"Текст отзыва:\n{review_text}"
    )
    
    try:
        await bot.send_message(
            chat_id=LOG_GROUP_ID, 
            text=log_text, 
            parse_mode=types.ParseMode.MARKDOWN
        )
        logger.info(f"Отзыв ({review_type}) от {user_id} успешно отправлен.")
        
    except Exception as e:
        logger.exception(f"Ошибка при отправке отзыва в группу логов:")
        
    await message.reply(
        reply_text,
        reply_markup=get_main_menu_keyboard()
    )

@dp.message(ReviewStates.waiting_for_review_text) # Ловим все, что не TEXT
async def handle_invalid_review_input(message: types.Message):
    await message.reply("Пожалуйста, напишите ваш отзыв текстом.", reply_markup=get_cancel_keyboard())
    
# --- 11. Хендлеры для группы логгирования (Администратор) ---

@dp.callback_query(F.data.startswith('reply_'))
async def process_reply_button(callback_query: types.CallbackQuery):
    """
    Обрабатывает нажатие кнопки "Ответить" в лог-группе, информируя админа.
    """
    await bot.answer_callback_query(callback_query.id, text="Используйте функцию 'Ответить' (Reply) на сообщение пользователя.")
    
    # Отправляем напоминание администратору
    await bot.send_message(
        chat_id=callback_query.from_user.id,
        text="Чтобы ответить пользователю, используйте функцию 'Ответить' (Reply) прямо на сообщение пользователя в группе с логами. Бот автоматически перешлет ваш ответ."
    )

# В aiogram 3.x для обработки сообщений в конкретном чате используем F.chat.id
@dp.message(F.chat.id == LOG_GROUP_ID)
async def handle_admin_reply(message: types.Message):
    # Проверяем, является ли это ответом на сообщение, которое мы залогировали
    if message.reply_to_message:
        replied_message_id = message.reply_to_message.message_id
        
        if replied_message_id in MESSAGE_MAP:
            target_user_id = MESSAGE_MAP[replied_message_id]
            
            # Удаляем ID исходного сообщения из маппинга, чтобы избежать утечки памяти
            # и повторных ответов на старые запросы
            del MESSAGE_MAP[replied_message_id] 
            
            response_text = f"📢 **Ответ технической поддержки:**"
            
            try:
                # 1. Отправляем заголовок
                await bot.send_message(
                    chat_id=target_user_id, 
                    text=response_text,
                    parse_mode=types.ParseMode.MARKDOWN
                )
                
                # 2. Копируем сообщение администратора (текст, фото, документ и т.д.)
                sent_message = await bot.copy_message(
                    chat_id=target_user_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id
                )
                
                # 3. Подтверждаем отправку администратору
                await message.reply(f"✅ Ответ успешно отправлен пользователю `{target_user_id}`.")
                
            except ChatNotFound:
                 logger.error(f"Не удалось отправить ответ пользователю {target_user_id}: Чат не найден.")
                 await message.reply(f"❌ Ошибка: Не удалось отправить ответ пользователю `{target_user_id}`. Чат не найден (возможно, пользователь заблокировал бота).")
            except Exception as e:
                logger.exception(f"Не удалось отправить ответ пользователю {target_user_id}:")
                await message.reply(f"❌ Ошибка: Не удалось отправить ответ пользователю `{target_user_id}`. Причина: {e}")
        
        else:
            logger.info(f"Получено сообщение в лог-группе, не являющееся ответом на активный запрос. ID: {replied_message_id}")


# --- 12. Общий хендлер для Callback Query (Улучшение UX) ---
@dp.callback_query() # Общий хендлер без фильтра
async def handle_all_callbacks(callback_query: types.CallbackQuery):
    """Обрабатывает все колбэки, которые не были обработаны другими хендлерами."""
    try:
        # Если колбэк не был обработан, значит, он, скорее всего, устарел
        await bot.answer_callback_query(callback_query.id, text="Действие устарело или не поддерживается.", show_alert=True)
    except MessageNotModified:
        pass 
    except Exception as e:
        logger.error(f"Ошибка при обработке общего callback: {e}")


# --- 13. Проверка доступа к лог-группе ---

async def check_group_access():
    logger.info(f"Проверка доступа к лог-группе с ID: {LOG_GROUP_ID}")
    
    if not isinstance(LOG_GROUP_ID, int):
        logger.error("LOG_GROUP_ID не является числом.")
        return False

    try:
        await bot.get_me()
        logger.info("Токен бота успешно проверен.")
        
        await bot.send_message(
            chat_id=LOG_GROUP_ID, 
            text="✅ Бот успешно запущен и имеет доступ к этой группе для логирования запросов."
        )
        logger.info("Успешно отправлено тестовое сообщение в лог-группу.")
        return True
        
    except ChatNotFound:
        logger.error(f"❌ Критическая ошибка: Чат с ID {LOG_GROUP_ID} не найден. Убедитесь, что ID корректен (для супергрупп это -100...).")
        return False
    except Exception as e:
        logger.exception(f"❌ Критическая ошибка при проверке доступа к лог-группе:")
        logger.error("Убедитесь, что бот добавлен в группу и имеет права администратора на отправку сообщений.")
        return False


# --- 14. Запуск бота ---
async def main():
    logger.info("Начинаем запуск бота...")
    
    # Проверка доступа к группе логирования
    if not await check_group_access():
        logger.error("Запуск бота отменен из-за критической ошибки конфигурации.")
        sys.exit(1)
        
    logger.info("Запуск диспетчера...")
    # В aiogram 3.x bot передается в start_polling
    await dp.start_polling(bot, skip_updates=True) 

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")
    except Exception as e:
        logger.exception("Произошла ошибка при запуске бота:")

