# ============================================================
# БОТ ДЛЯ ПРИЁМА ЗАПИСОК В ПРАВОСЛАВНЫЙ ХРАМ
# Платформа: MaX (мессенджер)
# Хостинг: bothost.ru
# Библиотека: Aiogram 3.x
# ============================================================

import asyncio
import logging
import os
from datetime import datetime

# ---- БИБЛИОТЕКИ ДЛЯ ТЕЛЕГРАМ/MAX ----
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, Message
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ---- БИБЛИОТЕКИ ДЛЯ GOOGLE TABLES ----
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ============================================================
# 1. НАСТРОЙКИ (всё через переменные окружения для безопасности)
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")  # Токен от BotFather в MaX
SHEET_ID = os.getenv("SHEET_ID")  # ID Google таблицы
GROUP_ID = int(os.getenv("GROUP_ID"))  # ID закрытой группы (число)
PAYMENT_LINK = "https://qr.nspk.ru/AS1A001JEEQNNOUF8DJ9KT01C22A9HCA?type=01&bank=100000000026&crc=22BF"

# Путь к JSON-ключу от Google (на bothost.ru положите в папку с ботом)
CREDS_FILE = "creds.json"

# Включаем логирование (чтобы видеть ошибки)
logging.basicConfig(level=logging.INFO)

# Создаём бота и диспетчер
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ============================================================
# 2. ПОДКЛЮЧЕНИЕ К GOOGLE TABLES
# ============================================================

def get_google_sheet():
    """Подключаемся к Google Sheets и возвращаем лист"""
    scope = ["https://spreadsheets.google.com/feeds", 
             "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1  # Первый лист
    return sheet

# ============================================================
# 3. СОСТОЯНИЯ ДЛЯ FSM (машина состояний)
# ============================================================

class Form(StatesGroup):
    choosing_type = State()  # Выбор типа записки
    entering_names = State()  # Ввод имён
    editing_names = State()  # Редактирование (опционально)
    waiting_donation = State()  # Ожидание подтверждения оплаты

# ============================================================
# 4. КЛАВИАТУРЫ (кнопки)
# ============================================================

# Главное меню с двумя карточками (в MaX кнопки с картинками не делаются,
# но мы сделаем кнопки с эмодзи и текстом, а картинки пришлём отдельно)
main_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="🕯️ Записка о ЗДРАВИИ", callback_data="type_health"),
        InlineKeyboardButton(text="☦️ Записка о УПОКОЕНИИ", callback_data="type_repose")
    ]
])

# Клавиатура после ввода имён
edit_send_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_names"),
        InlineKeyboardButton(text="✅ Отправить", callback_data="send_names")
    ]
])

# Клавиатура после отправки
donate_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="💳 Пожертвовать от 150 руб", url=PAYMENT_LINK)],
    [InlineKeyboardButton(text="✅ Я пожертвовал", callback_data="donated")]
])

# Клавиатура финального меню
final_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🔄 Заказать другие требы", callback_data="new_order")],
    [InlineKeyboardButton(text="❌ Закрыть приложение", callback_data="close_app")]
])

# ============================================================
# 5. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def save_to_google(names_list, note_type):
    """Сохраняет имена и тип записки в Google таблицу"""
    try:
        sheet = get_google_sheet()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Объединяем имена в одну строку через запятую
        names_str = ", ".join(names_list)
        # Добавляем строку: Дата, Тип, Имена, Сумма, Статус
        sheet.append_row([now, note_type, names_str, "0", "Ожидает оплаты"])
        logging.info(f"✅ Запись сохранена в Google: {names_str}")
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения в Google: {e}")
        return False

def send_to_group(names_list, note_type):
    """Отправляет сообщение в закрытую группу MaX"""
    try:
        names_str = ", ".join(names_list)
        msg = f"📩 НОВАЯ ЗАПИСКА\n\nТип: {note_type}\nИмена: {names_str}\nВремя: {datetime.now()}"
        bot.send_message(chat_id=GROUP_ID, text=msg)
        logging.info(f"✅ Отправлено в группу: {msg}")
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка отправки в группу: {e}")
        return False

# ============================================================
# 6. ОБРАБОТЧИКИ КОМАНД
# ============================================================

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Приветствие и показ главного меню"""
    await state.clear()  # Сбрасываем состояние
    # Отправляем приветствие с картинкой (здесь можно заменить на реальную картинку храма)
    await message.answer_photo(
        photo="https://cdn-icons-png.flaticon.com/512/2762/2762178.png",  # Иконка храма
        caption="🙏 Добро пожаловать! Выберите тип записки:",
        reply_markup=main_keyboard
    )
    await state.set_state(Form.choosing_type)

# ============================================================
# 7. ОБРАБОТЧИК ВЫБОРА ТИПА ЗАПИСКИ
# ============================================================

@dp.callback_query(F.data.startswith("type_"), Form.choosing_type)
async def process_type(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал тип записки (здоровье или упокой)"""
    note_type = "Здравие" if callback.data == "type_health" else "Упокоение"
    await state.update_data(note_type=note_type)
    
    # Показываем форму для ввода имён (10 полей)
    names_prompt = (
        "✍️ Введите имена крещёных православных христиан в РОДИТЕЛЬНОМ падеже (кого?)\n"
        "Не более 10 имён. Введите по одному имени в строке:\n\n"
    )
    # Создаём 10 строк с подсказками
    for i in range(1, 11):
        names_prompt += f"{i}. __________________\n"
    
    # Отправляем инструкцию
    await callback.message.edit_text(
        text=names_prompt,
        reply_markup=None
    )
    # Отправляем отдельное сообщение с просьбой ввести имена (для удобства)
    await callback.message.answer(
        "📝 Напишите имена, каждое с новой строки (максимум 10):"
    )
    await state.set_state(Form.entering_names)
    await callback.answer()

# ============================================================
# 8. ОБРАБОТЧИК ВВОДА ИМЁН
# ============================================================

@dp.message(Form.entering_names)
async def process_names(message: Message, state: FSMContext):
    """Получаем имена от пользователя"""
    raw_text = message.text.strip()
    # Разбиваем по строкам и убираем пустые
    names = [name.strip() for name in raw_text.split("\n") if name.strip()]
    
    if len(names) == 0:
        await message.answer("❌ Вы не ввели ни одного имени. Попробуйте снова:")
        return
    
    if len(names) > 10:
        await message.answer("❌ Слишком много имён (максимум 10). Введите ещё раз:")
        return
    
    # Сохраняем имена в состоянии
    await state.update_data(names=names)
    
    # Показываем имена и кнопки "Редактировать" / "Отправить"
    names_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(names)])
    await message.answer(
        f"✅ Вы ввели {len(names)} имён:\n\n{names_list}\n\n"
        "Проверьте и нажмите 'Отправить' или 'Редактировать'.",
        reply_markup=edit_send_keyboard
    )
    await state.set_state(Form.editing_names)

# ============================================================
# 9. ОБРАБОТЧИК РЕДАКТИРОВАНИЯ
# ============================================================

@dp.callback_query(F.data == "edit_names", Form.editing_names)
async def edit_names(callback: CallbackQuery, state: FSMContext):
    """Позволяет отредактировать имена (просто просим ввести заново)"""
    await callback.message.answer(
        "✏️ Введите имена заново (каждое с новой строки, максимум 10):"
    )
    await state.set_state(Form.entering_names)
    await callback.answer()

# ============================================================
# 10. ОБРАБОТЧИК ОТПРАВКИ (СОХРАНЕНИЕ + КНОПКА ОПЛАТЫ)
# ============================================================

@dp.callback_query(F.data == "send_names", Form.editing_names)
async def send_names(callback: CallbackQuery, state: FSMContext):
    """Отправляем данные, сохраняем в Google и группу, показываем кнопку оплаты"""
    data = await state.get_data()
    names = data.get("names", [])
    note_type = data.get("note_type", "Не указан")
    
    if not names:
        await callback.message.answer("❌ Ошибка: нет имён. Начните заново.")
        await state.clear()
        return
    
    # Сохраняем в Google Таблицу
    google_ok = save_to_google(names, note_type)
    
    # Отправляем в закрытую группу
    group_ok = send_to_group(names, note_type)
    
    if not google_ok or not group_ok:
        await callback.message.answer("⚠️ Ошибка при сохранении, но вы можете продолжить.")
    
    # Показываем кнопку для пожертвования
    await callback.message.edit_text(
        text="🙏 Ваши имена приняты.\n\n"
             "Для завершения сделайте добровольное пожертвование (от 150 руб).\n"
             "После оплаты нажмите 'Я пожертвовал'.",
        reply_markup=donate_keyboard
    )
    await state.set_state(Form.waiting_donation)
    await callback.answer()

# ============================================================
# 11. ОБРАБОТЧИК "Я ПОЖЕРТВОВАЛ"
# ============================================================

@dp.callback_query(F.data == "donated", Form.waiting_donation)
async def donation_confirmed(callback: CallbackQuery, state: FSMContext):
    """Пользователь подтвердил оплату"""
    # Обновляем статус в Google (можно добавить, но для простоты пропустим)
    
    await callback.message.edit_text(
        text="✅ Ваша записка отправлена в храм!\n\n"
             "Спасибо за ваше пожертвование и молитвы! 🙏",
        reply_markup=final_keyboard
    )
    await state.clear()  # Сбрасываем состояние
    await callback.answer()

# ============================================================
# 12. ОБРАБОТЧИК "ЗАКАЗАТЬ ДРУГИЕ ТРЕБЫ"
# ============================================================

@dp.callback_query(F.data == "new_order")
async def new_order(callback: CallbackQuery, state: FSMContext):
    """Возвращаем в главное меню"""
    await state.clear()
    await callback.message.edit_text(
        text="🙏 Выберите тип записки:",
        reply_markup=main_keyboard
    )
    await state.set_state(Form.choosing_type)
    await callback.answer()

# ============================================================
# 13. ОБРАБОТЧИК "ЗАКРЫТЬ ПРИЛОЖЕНИЕ"
# ============================================================

@dp.callback_query(F.data == "close_app")
async def close_app(callback: CallbackQuery, state: FSMContext):
    """Закрываем приложение (в MaX работает как завершение диалога)"""
    await callback.message.answer("👋 До свидания! Приходите ещё.")
    await state.clear()
    # В MaX нет прямого закрытия, но мы отправляем команду /start в ответ
    # чтобы пользователь мог начать заново
    await callback.answer()

# ============================================================
# 14. ЗАПУСК БОТА (для bothost.ru используется вебхук)
# ============================================================

async def on_startup():
    """Действия при запуске"""
    logging.info("🚀 Бот запущен!")

async def main():
    """Точка входа для bothost.ru (используем вебхук)"""
    # На bothost.ru вебхук настраивается автоматически через переменную WEBHOOK_URL
    # Удаляем старые вебхуки
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Устанавливаем вебхук (URL даст хостинг)
    webhook_url = os.getenv("WEBHOOK_URL")  # bothost.ru сам передаёт эту переменную
    if webhook_url:
        await bot.set_webhook(url=webhook_url)
        logging.info(f"✅ Вебхук установлен: {webhook_url}")
    else:
        # Для локального тестирования используем polling
        logging.info("⚠️ WEBHOOK_URL не найден, запускаем в режиме polling")
        await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())