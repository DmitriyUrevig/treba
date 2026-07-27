#!/usr/bin/env python3
# ============================================================
# БОТ ДЛЯ ПРИЁМА ЦЕРКОВНЫХ ЗАПИСОК (ОДНИМ ФАЙЛОМ)
# Платформа: MaX (мессенджер)
# Структура: вдохновлена официальным примером max-bot-example-todolist
# ============================================================

import os
import json
import logging
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any

# ---- СТОРОННИЕ БИБЛИОТЕКИ ----
import requests
from flask import Flask, request, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ============================================================
# 1. КОНФИГУРАЦИЯ (из переменных окружения)
# ============================================================

# --- ОБЯЗАТЕЛЬНЫЕ ПЕРЕМЕННЫЕ ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_ОТ_BOTFATHER")  # Токен бота в MaX
SHEET_ID = os.getenv("SHEET_ID", "ID_ВАШЕЙ_GOOGLE_ТАБЛИЦЫ")  # ID таблицы
GROUP_ID = os.getenv("GROUP_ID", "ID_ЗАКРЫТОЙ_ГРУППЫ")  # ID группы для уведомлений
CREDS_FILE = os.getenv("CREDS_FILE", "creds.json")  # Путь к JSON-ключу Google

# --- ОПЦИОНАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
PAYMENT_LINK = os.getenv("PAYMENT_LINK", "https://qr.nspk.ru/AS1A001JEEQNNOUF8DJ9KT01C22A9HCA?type=01&bank=100000000026&crc=22BF")
MAX_API_URL = os.getenv("MAX_API_URL", "https://api.max.ru/v1")  # Уточните в документации MaX
PORT = int(os.getenv("PORT", 5000))

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================
# 2. ДОМЕННЫЕ МОДЕЛИ (domain/models.py)
# ============================================================

class NoteType(Enum):
    """Тип записки"""
    HEALTH = "Здравие"
    REPOSE = "Упокоение"

class NoteStatus(Enum):
    """Статус записки"""
    PENDING = "Ожидает оплаты"
    PAID = "Оплачено"
    SENT = "Отправлено в храм"

@dataclass
class Note:
    """Модель записки"""
    chat_id: str
    names: List[str]
    note_type: NoteType
    status: NoteStatus = NoteStatus.PENDING
    created_at: Optional[str] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@dataclass
class UserState:
    """Состояние пользователя"""
    chat_id: str
    current_state: str  # choosing_type, entering_names, editing, waiting_payment
    data: Dict[str, Any]  # Временные данные

# ============================================================
# 3. КЛИЕНТ ДЛЯ API MAX (clients/max_client.py)
# ============================================================

class MaxClient:
    """Клиент для общения с API MaX"""
    
    def __init__(self, token: str, api_url: str = MAX_API_URL):
        self.token = token
        self.api_url = api_url
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def _request(self, method: str, endpoint: str, payload: Dict) -> bool:
        """Базовый метод для запросов к API"""
        url = f"{self.api_url}/{endpoint}"
        try:
            response = requests.post(
                url, 
                json=payload, 
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                logger.info(f"✅ Успешный запрос к {endpoint}")
                return True
            else:
                logger.error(f"❌ Ошибка {response.status_code}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Исключение при запросе к {endpoint}: {e}")
            return False
    
    def send_message(self, chat_id: str, text: str, keyboard: Dict = None, photo: str = None) -> bool:
        """Отправка сообщения"""
        payload = {
            "chat_id": chat_id,
            "text": text
        }
        if keyboard:
            payload["reply_markup"] = json.dumps(keyboard)
        if photo:
            payload["photo"] = photo
        
        return self._request("POST", "messages.send", payload)
    
    def edit_message(self, chat_id: str, message_id: str, text: str, keyboard: Dict = None) -> bool:
        """Редактирование сообщения"""
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text
        }
        if keyboard:
            payload["reply_markup"] = json.dumps(keyboard)
        
        return self._request("POST", "messages.edit", payload)
    
    def answer_callback(self, callback_id: str, text: str = "") -> bool:
        """Ответ на callback-запрос (для уведомления о нажатии кнопки)"""
        payload = {
            "callback_query_id": callback_id,
            "text": text
        }
        return self._request("POST", "callback.answer", payload)

# ============================================================
# 4. РЕПОЗИТОРИЙ ДЛЯ GOOGLE TABLES (repository/note_repo.py)
# ============================================================

class NoteRepository:
    """Работа с Google Sheets как хранилищем записок"""
    
    def __init__(self, sheet_id: str, creds_file: str):
        self.sheet_id = sheet_id
        self.creds_file = creds_file
        self._init_sheet()
    
    def _init_sheet(self):
        """Инициализация подключения к Google Sheets"""
        try:
            scope = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                self.creds_file, 
                scope
            )
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(self.sheet_id).sheet1
            logger.info("✅ Подключение к Google Sheets установлено")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Google Sheets: {e}")
            raise
    
    def save(self, note: Note) -> bool:
        """Сохраняет записку в таблицу"""
        try:
            names_str = ", ".join(note.names)
            row = [
                note.created_at,
                note.note_type.value,
                names_str,
                "0",  # Сумма пожертвования (будет обновлена позже)
                note.status.value
            ]
            self.sheet.append_row(row)
            logger.info(f"✅ Записка сохранена: {names_str}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения в Google: {e}")
            return False
    
    def update_status(self, chat_id: str, status: NoteStatus) -> bool:
        """Обновляет статус последней записки пользователя (можно расширить)"""
        # В реальном проекте здесь бы был поиск по chat_id
        # Для простоты пропускаем
        return True

# ============================================================
# 5. ОСНОВНОЙ СЕРВИС БОТА (services/bot_service.py)
# ============================================================

class BotService:
    """Основная бизнес-логика бота"""
    
    def __init__(self, max_client: MaxClient, note_repo: NoteRepository, group_id: str):
        self.client = max_client
        self.repo = note_repo
        self.group_id = group_id
        
        # Хранилище состояний пользователей (в реальном проекте - Redis)
        self.user_states: Dict[str, UserState] = {}
        
        # Клавиатуры (как в примере max-bot-example-todolist)
        self._init_keyboards()
    
    def _init_keyboards(self):
        """Инициализация всех клавиатур"""
        self.main_keyboard = {
            "inline_keyboard": [
                [{"text": "🕯️ О ЗДРАВИИ", "callback_data": "type_health"}],
                [{"text": "☦️ О УПОКОЕНИИ", "callback_data": "type_repose"}]
            ]
        }
        
        self.edit_keyboard = {
            "inline_keyboard": [
                [{"text": "✏️ Редактировать", "callback_data": "edit"}],
                [{"text": "✅ Отправить", "callback_data": "send"}]
            ]
        }
        
        self.donate_keyboard = {
            "inline_keyboard": [
                [{"text": "💳 Пожертвовать от 150 руб", "url": PAYMENT_LINK}],
                [{"text": "✅ Я пожертвовал", "callback_data": "donated"}]
            ]
        }
        
        self.final_keyboard = {
            "inline_keyboard": [
                [{"text": "🔄 Другие требы", "callback_data": "new_order"}],
                [{"text": "❌ Закрыть приложение", "callback_data": "close"}]
            ]
        }
    
    def _get_state(self, chat_id: str) -> UserState:
        """Получить состояние пользователя, создать если нет"""
        if chat_id not in self.user_states:
            self.user_states[chat_id] = UserState(
                chat_id=chat_id,
                current_state="idle",
                data={}
            )
        return self.user_states[chat_id]
    
    def _set_state(self, chat_id: str, state: str, data: Dict = None):
        """Установить состояние пользователя"""
        user_state = self._get_state(chat_id)
        user_state.current_state = state
        if data is not None:
            user_state.data.update(data)
    
    # ---- ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ ----
    
    def handle_start(self, chat_id: str, msg_id: str, callback_id: str = None):
        """Обработка команды /start"""
        self._set_state(chat_id, "choosing_type", {"message_id": msg_id})
        self.client.send_message(
            chat_id,
            "🙏 Добро пожаловать в бот для подачи записок!\n\n"
            "Выберите тип записки:",
            keyboard=self.main_keyboard,
            photo="https://cdn-icons-png.flaticon.com/512/2762/2762178.png"
        )
        if callback_id:
            self.client.answer_callback(callback_id)
    
    def handle_text(self, chat_id: str, text: str):
        """Обработка текстовых сообщений"""
        state = self._get_state(chat_id)
        
        if state.current_state == "entering_names":
            self._process_names(chat_id, text)
        else:
            self.client.send_message(
                chat_id,
                "Используйте кнопки для навигации. /start - начать заново"
            )
    
    def handle_callback(self, chat_id: str, callback_data: str, callback_id: str, msg_id: str):
        """Обработка нажатий на кнопки"""
        state = self._get_state(chat_id)
        
        # ---- ВЫБОР ТИПА ЗАПИСКИ ----
        if callback_data in ["type_health", "type_repose"]:
            note_type = NoteType.HEALTH if callback_data == "type_health" else NoteType.REPOSE
            self._set_state(chat_id, "entering_names", {
                "note_type": note_type,
                "message_id": msg_id
            })
            self.client.send_message(
                chat_id,
                "📝 Введите до 10 имён крещёных православных христиан.\n"
                "Каждое имя с новой строки (в родительном падеже, кого?):"
            )
            self.client.answer_callback(callback_id)
            return
        
        # ---- РЕДАКТИРОВАНИЕ ----
        if callback_data == "edit":
            self._set_state(chat_id, "entering_names", {"message_id": msg_id})
            self.client.send_message(
                chat_id,
                "✏️ Введите имена заново (каждое с новой строки, максимум 10):"
            )
            self.client.answer_callback(callback_id)
            return
        
        # ---- ОТПРАВКА ----
        if callback_data == "send":
            self._send_note(chat_id, msg_id)
            self.client.answer_callback(callback_id)
            return
        
        # ---- ПОДТВЕРЖДЕНИЕ ОПЛАТЫ ----
        if callback_data == "donated":
            self._confirm_donation(chat_id, msg_id)
            self.client.answer_callback(callback_id)
            return
        
        # ---- НОВЫЙ ЗАКАЗ ----
        if callback_data == "new_order":
            self._set_state(chat_id, "choosing_type", {"message_id": msg_id})
            self.client.edit_message(
                chat_id,
                msg_id,
                "🙏 Выберите тип записки:",
                keyboard=self.main_keyboard
            )
            self.client.answer_callback(callback_id)
            return
        
        # ---- ЗАКРЫТЬ ----
        if callback_data == "close":
            self.client.send_message(
                chat_id,
                "👋 До свидания! Приходите ещё.\n\n"
                "Чтобы начать заново, нажмите /start"
            )
            self._set_state(chat_id, "idle", {})
            self.client.answer_callback(callback_id)
            return
        
        # ---- НЕИЗВЕСТНЫЙ CALLBACK ----
        self.client.answer_callback(callback_id, "Неизвестная команда")
    
    # ---- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ----
    
    def _process_names(self, chat_id: str, text: str):
        """Обработка ввода имён"""
        # Разбиваем по строкам и убираем пустые
        names = [name.strip() for name in text.split("\n") if name.strip()]
        
        # Проверки
        if not names:
            self.client.send_message(chat_id, "❌ Вы не ввели ни одного имени. Попробуйте снова:")
            return
        
        if len(names) > 10:
            self.client.send_message(
                chat_id,
                f"❌ Слишком много имён (введено {len(names)}, максимум 10). Попробуйте снова:"
            )
            return
        
        # Сохраняем имена
        state = self._get_state(chat_id)
        state.data["names"] = names
        
        # Показываем введённые имена
        names_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(names)])
        self.client.send_message(
            chat_id,
            f"✅ Вы ввели {len(names)} имён:\n\n{names_list}\n\n"
            "Проверьте и нажмите 'Отправить' или 'Редактировать'.",
            keyboard=self.edit_keyboard
        )
        self._set_state(chat_id, "editing")
    
    def _send_note(self, chat_id: str, msg_id: str):
        """Сохранение записки и отправка в группу"""
        state = self._get_state(chat_id)
        names = state.data.get("names", [])
        note_type = state.data.get("note_type")
        
        if not names or not note_type:
            self.client.send_message(
                chat_id,
                "❌ Ошибка: нет имён или типа записки. Начните заново /start"
            )
            return
        
        # Создаём записку
        note = Note(
            chat_id=chat_id,
            names=names,
            note_type=note_type
        )
        
        # Сохраняем в Google
        if self.repo.save(note):
            # Отправляем в закрытую группу
            self._notify_group(note)
            
            # Показываем кнопку оплаты
            self.client.edit_message(
                chat_id,
                msg_id,
                "🙏 Ваши имена приняты.\n\n"
                "Для завершения сделайте добровольное пожертвование (от 150 руб).\n"
                "После оплаты нажмите 'Я пожертвовал'.",
                keyboard=self.donate_keyboard
            )
            self._set_state(chat_id, "waiting_payment")
        else:
            self.client.send_message(
                chat_id,
                "⚠️ Произошла ошибка при сохранении. Попробуйте позже или /start заново."
            )
    
    def _notify_group(self, note: Note):
        """Отправка уведомления в закрытую группу"""
        names_str = ", ".join(note.names)
        msg = (
            f"📩 НОВАЯ ЗАПИСКА\n\n"
            f"Тип: {note.note_type.value}\n"
            f"Имена: {names_str}\n"
            f"Время: {note.created_at}\n"
            f"Статус: {note.status.value}"
        )
        self.client.send_message(self.group_id, msg)
        logger.info(f"✅ Уведомление отправлено в группу {self.group_id}")
    
    def _confirm_donation(self, chat_id: str, msg_id: str):
        """Подтверждение пожертвования"""
        self.client.edit_message(
            chat_id,
            msg_id,
            "✅ Ваша записка отправлена в храм!\n\n"
            "Спасибо за ваше пожертвование и молитвы! 🙏",
            keyboard=self.final_keyboard
        )
        self._set_state(chat_id, "idle")

# ============================================================
# 6. ВЕБ-СЕРВЕР И МАРШРУТЫ (router/webhook.py)
# ============================================================

# Создаём Flask-приложение
app = Flask(__name__)

# Инициализация компонентов (как фабрика в примере)
def init_components():
    """Инициализация всех компонентов (аналог fx.go)"""
    max_client = MaxClient(BOT_TOKEN)
    note_repo = NoteRepository(SHEET_ID, CREDS_FILE)
    bot_service = BotService(max_client, note_repo, GROUP_ID)
    return bot_service

# Глобальный сервис (инициализируется при первом запросе)
bot_service = None

@app.before_request
def before_request():
    """Инициализация перед первым запросом"""
    global bot_service
    if bot_service is None:
        bot_service = init_components()
        logger.info("✅ Компоненты бота инициализированы")

# ---- ОСНОВНОЙ ВЕБХУК ----
@app.route('/webhook', methods=['POST'])
def webhook():
    """Основной обработчик вебхуков от MaX"""
    try:
        data = request.get_json()
        logger.info(f"📨 Получен вебхук: {json.dumps(data, indent=2)}")
        
        # ---- ОБРАБОТКА СООБЩЕНИЙ ----
        if 'message' in data:
            message = data['message']
            chat_id = str(message['chat']['id'])
            text = message.get('text', '')
            msg_id = str(message['message_id'])
            
            # Команда /start
            if text == '/start':
                bot_service.handle_start(chat_id, msg_id, None)
            # Текстовое сообщение
            elif text:
                bot_service.handle_text(chat_id, text)
            else:
                logger.warning(f"Пустое сообщение от {chat_id}")
        
        # ---- ОБРАБОТКА НАЖАТИЙ НА КНОПКИ ----
        elif 'callback_query' in data:
            callback = data['callback_query']
            chat_id = str(callback['message']['chat']['id'])
            msg_id = str(callback['message']['message_id'])
            callback_data = callback['data']
            callback_id = callback['id']
            
            bot_service.handle_callback(chat_id, callback_data, callback_id, msg_id)
        
        else:
            logger.warning(f"Неизвестный тип события: {data}")
        
        return jsonify({"status": "ok"})
    
    except Exception as e:
        logger.error(f"❌ Ошибка в вебхуке: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

# ---- ДОПОЛНИТЕЛЬНЫЙ МАРШРУТ ДЛЯ ПРОВЕРКИ ----
@app.route('/health', methods=['GET'])
def health():
    """Проверка работоспособности (как в примере)"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/info', methods=['GET'])
def info():
    """Информация о боте (как в примере)"""
    return jsonify({
        "name": "Church Notes Bot",
        "version": "1.0.0",
        "description": "Бот для приёма записок в православный храм",
        "type": "MaX Bot"
    })

# ============================================================
# 7. ТОЧКА ВХОДА (как cmd/todolist)
# ============================================================

if __name__ == '__main__':
    logger.info("🚀 Запуск бота для церковных записок...")
    logger.info(f"📱 Версия: 1.0.0")
    logger.info(f"🔌 Порт: {PORT}")
    
    # Проверка наличия обязательных переменных
    if BOT_TOKEN in ["ВАШ_ТОКЕН_ОТ_BOTFATHER", ""]:
        logger.error("❌ Не задан BOT_TOKEN! Установите переменную окружения.")
        logger.info("💡 Пример: export BOT_TOKEN=ваш_токен")
        exit(1)
    
    if SHEET_ID in ["ID_ВАШЕЙ_GOOGLE_ТАБЛИЦЫ", ""]:
        logger.warning("⚠️ Не задан SHEET_ID. Сохранение в Google работать не будет.")
    
    if GROUP_ID in ["ID_ЗАКРЫТОЙ_ГРУППЫ", ""]:
        logger.warning("⚠️ Не задан GROUP_ID. Уведомления в группу работать не будут.")
    
    # Инициализация компонентов
    try:
        bot_service = init_components()
        logger.info("✅ Все компоненты успешно инициализированы")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации: {e}")
        exit(1)
    
    # Запуск сервера
    logger.info(f"🌐 Сервер запущен на порту {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
