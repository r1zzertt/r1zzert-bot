import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import requests
import time
import logging
import sqlite3
from datetime import datetime
import threading
from flask import Flask, request
import random

# ==================== НАСТРОЙКИ ====================
TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME', '@r1zzert')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
PORT = int(os.environ.get('PORT', 10000))

if not TOKEN or not GROQ_API_KEY:
    print("❌ Ошибка: не все переменные окружения заданы!")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ==================== БАЗА ДАННЫХ ====================
def init_database():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            mode TEXT DEFAULT 'assistant',
            messages_count INTEGER DEFAULT 0,
            images_count INTEGER DEFAULT 0,
            joined_date TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_database()

def get_user_mode(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT mode FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 'assistant'

def set_user_mode(user_id, mode):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users (user_id, mode, joined_date) VALUES (?, ?, ?)',
                  (user_id, mode, datetime.now()))
    conn.commit()
    conn.close()

def update_stats(user_id, stat_type):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    if stat_type == 'message':
        cursor.execute('UPDATE users SET messages_count = messages_count + 1 WHERE user_id = ?', (user_id,))
    elif stat_type == 'image':
        cursor.execute('UPDATE users SET images_count = images_count + 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
def check_subscription(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

# ==================== РАБОТА С ИИ ====================
def ask_groq(question, system_prompt):
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        data = {
            "model": "llama-3.3-70b-versatile",  # НОВАЯ РАБОЧАЯ МОДЕЛЬ
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            "temperature": 0.7,
            "max_tokens": 1024
        }
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            logger.error(f"Groq ошибка {response.status_code}: {response.text}")
            return "😕 Ошибка Groq"
    except Exception as e:
        logger.error(f"Ошибка при запросе к Groq: {e}")
        return "😕 Ошибка связи с ИИ"

# ==================== ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ ====================
def generate_image(prompt):
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        data = {
            "model": "llama-3.3-70b-versatile",  # ТОЖЕ НОВАЯ МОДЕЛЬ
            "messages": [
                {"role": "user", "content": f"Опиши подробно это изображение: {prompt}"}
            ],
            "max_tokens": 500
        }
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        return None
    except:
        return None

# ==================== РЕЖИМЫ ====================
MODES = {
    "assistant": {"name": "🤵 Обычный помощник", "prompt": "Ты полезный ассистент. Отвечай кратко и по делу."},
    "developer": {"name": "💻 Разработчик", "prompt": "Ты эксперт по программированию. Помогай с кодом."},
    "writer": {"name": "✍️ Писатель", "prompt": "Ты профессиональный писатель. Помогай с текстами."},
    "creative": {"name": "🎨 Креативщик", "prompt": "Ты креативный директор. Генерируй идеи."}
}

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("💬 Чат", "🎭 Режимы", "🎨 Фото", "📊 Статистика", "❓ Помощь")
    return markup

def get_modes_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    for mode_id, mode_info in MODES.items():
        markup.add(InlineKeyboardButton(mode_info['name'], callback_data=f"mode_{mode_id}"))
    return markup

# ==================== ВЕБХУК ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return 'OK', 200
    except Exception as e:
        logger.error(f"Ошибка вебхука: {e}")
        return 'ERROR', 500

@app.route('/')
def home():
    return "🤖 @r1zzert_bot работает!"

@app.route('/health')
def health():
    return "OK", 200

# ==================== ЖИВЫЕ ОТВЕТЫ ====================
def get_chat_welcome():
    return random.choice([
        "💬 **Давай поболтаем!** Спрашивай что хочешь!",
        "💬 **Я слушаю тебя!** Расскажи, что у тебя нового!",
        "💬 **Погнали общаться!** О чём поговорим?"
    ])

def get_photo_welcome():
    return random.choice([
        "🎨 **Опиши что хочешь увидеть!**",
        "🎨 **Включи воображение!** Что должно быть на картинке?",
        "🎨 **Генератор описаний запущен!** Что создаём?"
    ])

def get_help_message():
    return f"""
❓ **Помощь**

💬 Чат — общайся на любые темы
🎭 Режимы — меняй стиль общения
🎨 Фото — опиши картинку
📊 Статистика — твоя активность

🔐 Канал: {CHANNEL_USERNAME}
"""

# ==================== КОМАНДЫ ====================
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "друг"
    
    if not check_subscription(user_id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=f"https://t.me/{CHANNEL_USERNAME[1:]}"))
        markup.add(InlineKeyboardButton("✅ Я ПОДПИСАЛСЯ", callback_data="check_sub"))
        bot.send_message(
            message.chat.id,
            f"👋 Привет, {user_name}!\n🔒 Подпишись на {CHANNEL_USERNAME}",
            reply_markup=markup
        )
        return
    
    set_user_mode(user_id, 'assistant')
    bot.send_message(message.chat.id, f"👋 **С возвращением!**", reply_markup=get_main_keyboard())

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    
    if call.data == "check_sub":
        if check_subscription(user_id):
            bot.edit_message_text("✅ Подписка подтверждена!", call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "Добро пожаловать!", reply_markup=get_main_keyboard())
        else:
            bot.answer_callback_query(call.id, "❌ Не подписан!", show_alert=True)
    
    elif call.data.startswith("mode_"):
        mode_id = call.data.replace("mode_", "")
        if mode_id in MODES:
            set_user_mode(user_id, mode_id)
            bot.answer_callback_query(call.id, f"Режим: {MODES[mode_id]['name']}")
            bot.send_message(call.message.chat.id, f"✅ Режим изменён на {MODES[mode_id]['name']}", reply_markup=get_main_keyboard())

# ==================== ТЕКСТОВЫЕ СООБЩЕНИЯ ====================
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id
    text = message.text
    
    if not check_subscription(user_id):
        bot.send_message(message.chat.id, "❌ Сначала подпишись!")
        return
    
    if text == "💬 Чат":
        bot.send_message(message.chat.id, get_chat_welcome())
    
    elif text == "🎭 Режимы":
        bot.send_message(message.chat.id, "🎭 Выбери режим:", reply_markup=get_modes_keyboard())
    
    elif text == "🎨 Фото":
        bot.send_message(message.chat.id, get_photo_welcome())
        bot.register_next_step_handler(
            bot.send_message(message.chat.id, "✏️ **Напиши промпт:**"),
            process_image
        )
    
    elif text == "📊 Статистика":
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute('SELECT messages_count, images_count, joined_date FROM users WHERE user_id = ?', (user_id,))
        stats = cursor.fetchone()
        conn.close()
        if stats:
            joined = datetime.fromisoformat(stats[2]).strftime('%d.%m.%Y')
            bot.send_message(message.chat.id, f"📊 Статистика:\n💬 {stats[0]}\n🎨 {stats[1]}\n📅 {joined}")
        else:
            bot.send_message(message.chat.id, "📊 Статистика пуста")
    
    elif text == "❓ Помощь":
        bot.send_message(message.chat.id, get_help_message())
    
    else:
        bot.send_chat_action(message.chat.id, 'typing')
        answer = ask_groq(text, MODES[get_user_mode(user_id)]['prompt'])
        if answer:
            update_stats(user_id, 'message')
            bot.send_message(message.chat.id, f"{MODES[get_user_mode(user_id)]['name']}\n\n{answer}")
        else:
            bot.send_message(message.chat.id, "😕 Ошибка")

def process_image(message):
    result = generate_image(message.text)
    if result:
        update_stats(message.from_user.id, 'image')
        bot.send_message(message.chat.id, f"🎨 {result}")
    else:
        bot.send_message(message.chat.id, "😕 Не удалось создать описание")

# ==================== ЗАПУСК ====================
if __name__ == '__main__':
    logger.info("🚀 Запуск...")
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"https://r1zzert-bot.onrender.com/webhook")
    logger.info("✅ Вебхук установлен")
    app.run(host='0.0.0.0', port=PORT)
