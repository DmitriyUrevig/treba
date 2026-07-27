# ============================================================
# БОТ ДЛЯ ПРИЁМА ЗАПИСОК В ПРАВОСЛАВНЫЙ ХРАМ (MaX)
# БЕЗ AIOGRAM - используем requests и API MaX
# ============================================================

import os
import json
import logging
from datetime import datetime
import requests
from flask import Flask, request, jsonify

# ---- БИБЛИОТЕКИ ДЛЯ GOOGLE TABLES ----
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ============================================================
# 1. НАСТРОЙКИ
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")  # Токен от BotFather в MaX
SHEET_ID = os.getenv("SHEET_ID")  # ID Google таблицы
GROUP_ID = os.getenv("GROUP_ID")  # ID группы (строка)
PAYMENT_LINK = "https://qr.nspk.ru/AS1A001JEEQNNOUF8DJ9KT01C22A9HCA?type=01&bank=100000000026&crc=22BF"
CREDS_FILE = "creds.json"

# URL API MaX (используйте актуальные данные из документации MaX)
MAX_API_URL = "https://api.max.ru/v1"  # Пример, уточните в документации MaX

logging.basicConfig(level=logging.INFO)

# Создаём Flask приложение для вебхуков
app = Flask(__name__)

# Хранилище состояний пользователей (в реальности используйте Redis или БД)
user_states = {}
user_data = {}

# ============================================================
# 2. ПОДКЛЮЧЕНИЕ К GOOGLE TABLES
# ============================================================

def get_google_sheet():
    """Подключаемся к Google Sheets"""
    scope = ["https://spreadsheets.google.com/feeds", 
             "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    return sheet

def save_to_google(names_list, note_type):
    """Сохраняет имена в Google таблицу"""
    try:
        sheet = get_google_sheet()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        names_str = ", ".join(names_list)
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
        
        # Отправка через API MaX в группу
        url = f"{MAX_API_URL}/messages.send"
        payload = {
            "chat_id": GROUP_ID,
            "text": msg
        }
        headers = {"Authorization": f"Bearer {BOT_TOKEN}"}
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            logging.info(f"✅ Отправлено в группу: {msg}")
            return True
        else:
            logging.error(f"❌ Ошибка отправки в группу: {response.text}")
            return False
    except Exception as e:
        logging.error(f"❌ Ошибка отправки в группу: {e}")
        return False

# ============================================================
# 3. ФУНКЦИИ ДЛЯ ОТПРАВКИ СООБЩЕНИЙ В MaX
# ============================================================

def send_message(chat_id, text, keyboard=None, photo=None):
    """Универсальная функция отправки сообщения"""
    url = f"{MAX_API_URL}/messages.send"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    
    if keyboard:
        payload["reply_markup"] = json.dumps(keyboard)
    
    if photo:
        payload["photo"] = photo
    
    headers = {"Authorization": f"Bearer {BOT_TOKEN}"}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        return response.status_code == 200
    except Exception as e:
        logging.error(f"Ошибка отправки: {e}")
        return False

def edit_message(chat_id, message_id, text, keyboard=None):
    """Редактирует существующее сообщение"""
    url = f"{MAX_API_URL}/messages.edit"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text
    }
    
    if keyboard:
        payload["reply_markup"] = json.dumps(keyboard)
    
    headers = {"Authorization": f"Bearer {BOT_TOKEN}"}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        return response.status_code == 200
    except Exception as e:
        logging.error(f"Ошибка редактирования: {e}")
        return False

# ============================================================
# 4. КЛАВИАТУРЫ (в формате MaX)
# ============================================================

def get_main_keyboard():
    """Главное меню с двумя кнопками"""
    return {
        "inline_keyboard": [
            [
                {"text": "🕯️ Записка о ЗДРАВИИ", "callback_data": "type_health"},
                {"text": "☦️ Записка о УПОКОЕНИИ", "callback_data": "type_repose"}
            ]
        ]
    }

def get_edit_send_keyboard():
    """Кнопки редактировать/отправить"""
    return {
        "inline_keyboard": [
            [
                {"text": "✏️ Редактировать", "callback_data": "edit_names"},
                {"text": "✅ Отправить", "callback_data": "send_names"}
            ]
        ]
    }

def get_donate_keyboard():
    """Кнопка оплаты и подтверждения"""
    return {
        "inline_keyboard": [
            [{"text": "💳 Пожертвовать от 150 руб", "url": PAYMENT_LINK}],
            [{"text": "✅ Я пожертвовал", "callback_data": "donated"}]
        ]
    }

def get_final_keyboard():
    """Финальное меню"""
    return {
        "inline_keyboard": [
            [{"text": "🔄 Заказать другие требы", "callback_data": "new_order"}],
            [{"text": "❌ Закрыть приложение", "callback_data": "close_app"}]
        ]
    }

# ============================================================
# 5. ОБРАБОТЧИКИ ВЕБХУКА
# ============================================================

@app.route('/webhook', methods=['POST'])
def webhook():
    """Основной обработчик всех сообщений от MaX"""
    try:
        data = request.get_json()
        logging.info(f"Получены данные: {data}")
        
        # Проверяем, что это сообщение от пользователя
        if 'message' in data:
            message = data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            message_id = message['message_id']
            
            # Обработка команды /start
            if text == '/start':
                return handle_start(chat_id, message_id)
            
            # Обработка текстовых сообщений (ввод имён)
            user_state = user_states.get(chat_id, '')
            if user_state == 'entering_names':
                return handle_names_input(chat_id, message_id, text)
            
        # Обработка callback-запросов (нажатие на кнопки)
        elif 'callback_query' in data:
            callback = data['callback_query']
            chat_id = callback['message']['chat']['id']
            message_id = callback['message']['message_id']
            callback_data = callback['data']
            
            return handle_callback(chat_id, message_id, callback_data)
        
        return jsonify({"status": "ok"})
    
    except Exception as e:
        logging.error(f"Ошибка в вебхуке: {e}")
        return jsonify({"status": "error"}), 500

# ============================================================
# 6. ОБРАБОТКА КОМАНД И СООБЩЕНИЙ
# ============================================================

def handle_start(chat_id, message_id):
    """Обработка команды /start"""
    user_states[chat_id] = 'choosing_type'
    user_data[chat_id] = {}
    
    # Отправляем приветствие с картинкой
    send_message(
        chat_id,
        "🙏 Добро пожаловать! Выберите тип записки:",
        keyboard=get_main_keyboard(),
        photo="https://cdn-icons-png.flaticon.com/512/2762/2762178.png"
    )
    return jsonify({"status": "ok"})

def handle_names_input(chat_id, message_id, text):
    """Обработка ввода имён"""
    # Разбиваем на строки и убираем пустые
    names = [name.strip() for name in text.split("\n") if name.strip()]
    
    if len(names) == 0:
        send_message(chat_id, "❌ Вы не ввели ни одного имени. Попробуйте снова:")
        return jsonify({"status": "ok"})
    
    if len(names) > 10:
        send_message(chat_id, "❌ Слишком много имён (максимум 10). Введите ещё раз:")
        return jsonify({"status": "ok"})
    
    # Сохраняем имена
    user_data[chat_id]['names'] = names
    
    # Показываем введённые имена
    names_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(names)])
    send_message(
        chat_id,
        f"✅ Вы ввели {len(names)} имён:\n\n{names_list}\n\nПроверьте и нажмите 'Отправить' или 'Редактировать'.",
        keyboard=get_edit_send_keyboard()
    )
    user_states[chat_id] = 'editing_names'
    return jsonify({"status": "ok"})

def handle_callback(chat_id, message_id, callback_data):
    """Обработка нажатий на кнопки"""
    
    # Выбор типа записки
    if callback_data in ['type_health', 'type_repose']:
        note_type = "Здравие" if callback_data == "type_health" else "Упокоение"
        user_data[chat_id]['note_type'] = note_type
        user_states[chat_id] = 'entering_names'
        
        # Форма для ввода имён
        names_prompt = (
            "✍️ Введите имена крещёных православных христиан в РОДИТЕЛЬНОМ падеже (кого?)\n"
            "Не более 10 имён. Введите по одному имени в строке:\n\n"
        )
        for i in range(1, 11):
            names_prompt += f"{i}. __________________\n"
        
        edit_message(chat_id, message_id, names_prompt)
        send_message(chat_id, "📝 Напишите имена, каждое с новой строки (максимум 10):")
        return jsonify({"status": "ok"})
    
    # Редактирование имён
    elif callback_data == 'edit_names':
        send_message(chat_id, "✏️ Введите имена заново (каждое с новой строки, максимум 10):")
        user_states[chat_id] = 'entering_names'
        return jsonify({"status": "ok"})
    
    # Отправка имён
    elif callback_data == 'send_names':
        names = user_data.get(chat_id, {}).get('names', [])
        note_type = user_data.get(chat_id, {}).get('note_type', 'Не указан')
        
        if not names:
            send_message(chat_id, "❌ Ошибка: нет имён. Начните заново.")
            user_states[chat_id] = ''
            return jsonify({"status": "ok"})
        
        # Сохраняем в Google
        google_ok = save_to_google(names, note_type)
        
        # Отправляем в группу
        group_ok = send_to_group(names, note_type)
        
        if not google_ok or not group_ok:
            send_message(chat_id, "⚠️ Ошибка при сохранении, но вы можете продолжить.")
        
        # Показываем кнопку оплаты
        edit_message(
            chat_id,
            message_id,
            "🙏 Ваши имена приняты.\n\nДля завершения сделайте добровольное пожертвование (от 150 руб).\nПосле оплаты нажмите 'Я пожертвовал'.",
            keyboard=get_donate_keyboard()
        )
        user_states[chat_id] = 'waiting_donation'
        return jsonify({"status": "ok"})
    
    # Подтверждение оплаты
    elif callback_data == 'donated':
        edit_message(
            chat_id,
            message_id,
            "✅ Ваша записка отправлена в храм!\n\nСпасибо за ваше пожертвование и молитвы! 🙏",
            keyboard=get_final_keyboard()
        )
        user_states[chat_id] = ''
        return jsonify({"status": "ok"})
    
    # Новый заказ
    elif callback_data == 'new_order':
        user_states[chat_id] = 'choosing_type'
        user_data[chat_id] = {}
        edit_message(
            chat_id,
            message_id,
            "🙏 Выберите тип записки:",
            keyboard=get_main_keyboard()
        )
        return jsonify({"status": "ok"})
    
    # Закрыть приложение
    elif callback_data == 'close_app':
        send_message(chat_id, "👋 До свидания! Приходите ещё.")
        user_states[chat_id] = ''
        user_data[chat_id] = {}
        return jsonify({"status": "ok"})
    
    return jsonify({"status": "ok"})

# ============================================================
# 7. ЗАПУСК (для bothost.ru)
# ============================================================

if __name__ == '__main__':
    # Получаем порт из переменных окружения (bothost.ru даёт свой)
    port = int(os.environ.get('PORT', 5000))
    
    # Запускаем Flask сервер
    app.run(host='0.0.0.0', port=port, debug=False)
