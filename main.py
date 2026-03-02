import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import requests
import time
import logging
import sqlite3
from datetime import datetime, timedelta
import hashlib
import threading
from flask import Flask, request

# ==================== НАСТРОЙКИ ====================
TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
KLING_API_KEY = os.environ.get('KLING_API_KEY', '')
KLING_SECRET_KEY = os.environ.get('KLING_SECRET_KEY', '')
PORT = int(os.environ.get('PORT', 10000))

if not TOKEN or not CHANNEL_USERNAME or not GROQ_API_KEY:
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
            videos_count INTEGER DEFAULT 0,
            joined_date TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            prompt TEXT,
            status TEXT DEFAULT 'pending',
            video_url TEXT,
            created_at TIMESTAMP
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
    elif stat_type == 'video':
        cursor.execute('UPDATE users SET videos_count = videos_count + 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_stats(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT messages_count, images_count, videos_count, joined_date FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result

def add_to_queue(user_id, prompt):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO video_queue (user_id, prompt, created_at) VALUES (?, ?, ?)',
                  (user_id, prompt, datetime.now()))
    queue_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return queue_id

def update_queue(queue_id, video_url):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE video_queue SET status = ?, video_url = ? WHERE id = ?',
                  ('completed', video_url, queue_id))
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
            "Content-Type": "application/json"
        }
        data = {
            "model": "llama3-70b-8192",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            "temperature": 0.7
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

# ==================== ГЕНЕРАЦИЯ ВИДЕО ====================
def generate_video(prompt):
    try:
        if not KLING_API_KEY or not KLING_SECRET_KEY:
            return None
        
        timestamp = int(time.time())
        sign_string = f"{KLING_API_KEY}{timestamp}{KLING_SECRET_KEY}"
        sign = hashlib.md5(sign_string.encode()).hexdigest()
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {KLING_API_KEY}",
            "X-Timestamp": str(timestamp),
            "X-Sign": sign
        }
        
        data = {
            "prompt": prompt,
            "duration": 5,
            "aspect_ratio": "9:16"
        }
        
        response = requests.post(
            "https://api.kling.ai/v1/videos/generations",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0:
                task_id = result['data']['task_id']
                return check_video_task(task_id)
        return None
    except:
        return None

def check_video_task(task_id, max_attempts=20):
    headers = {"Authorization": f"Bearer {KLING_API_KEY}"}
    
    for _ in range(max_attempts):
        try:
            response = requests.get(
                f"https://api.kling.ai/v1/videos/generations/{task_id}",
                headers=headers,
                timeout=30
            )
            if response.status_code == 200:
                result = response.json()
                if result.get('code') == 0:
                    status = result['data']['status']
                    if status == 'succeed':
                        return result['data']['videos'][0]['url']
                    elif status == 'failed':
                        return None
            time.sleep(5)
        except:
            time.sleep(5)
    return None

# ==================== ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ ====================
def generate_image(prompt):
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "llama-3.2-11b-vision-preview",
            "messages": [
                {"role": "user", "content": f"Опиши подробно это изображение: {prompt}"}
            ]
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
    "assistant": {
        "name": "🤵 Обычный помощник",
        "prompt": "Ты полезный ассистент. Отвечай кратко и по делу."
    },
    "developer": {
        "name": "💻 Разработчик",
        "prompt": "Ты эксперт по программированию. Помогай с кодом."
    },
    "writer": {
        "name": "✍️ Писатель",
        "prompt": "Ты профессиональный писатель. Помогай с текстами."
    },
    "creative": {
        "name": "🎨 Креативщик",
        "prompt": "Ты креативный директор. Генерируй идеи."
    }
}

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("💬 Чат"),
        KeyboardButton("🎭 Режимы"),
        KeyboardButton("🎨 Фото"),
        KeyboardButton("🎬 Видео"),
        KeyboardButton("📊 Статистика"),
        KeyboardButton("❓ Помощь")
    )
    return markup

def get_modes_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    for mode_id, mode_info in MODES.items():
        markup.add(InlineKeyboardButton(mode_info['name'], callback_data=f"mode_{mode_id}"))
    return markup

def get_video_presets():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌅 Закат", callback_data="video_sunset"),
        InlineKeyboardButton("🏙️ Ночной город", callback_data="video_city"),
        InlineKeyboardButton("🚀 Космос", callback_data="video_space"),
        InlineKeyboardButton("🎮 Игры", callback_data="video_game"),
        InlineKeyboardButton("✏️ Свой текст", callback_data="video_custom")
    )
    return markup

# ==================== ВЕБХУК ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return 'OK', 200

@app.route('/')
def home():
    return "🤖 @r1zzert_bot MEGA AI is running!"

@app.route('/health')
def health():
    return "OK", 200

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
            f"👋 Привет, {user_name}!\n🔒 Подпишись на канал {CHANNEL_USERNAME}",
            reply_markup=markup
        )
        return
    
    set_user_mode(user_id, 'assistant')
    bot.send_message(
        message.chat.id,
        f"👋 Добро пожаловать в MEGA AI!\n\n"
        f"🤖 Я умею:\n"
        f"• Отвечать на вопросы\n"
        f"• Генерировать видео\n"
        f"• Создавать описания фото\n"
        f"• Менять режимы\n\n"
        f"Текущий режим: {MODES['assistant']['name']}",
        reply_markup=get_main_keyboard()
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    
    if call.data == "check_sub":
        if check_subscription(user_id):
            bot.edit_message_text(
                "✅ Подписка подтверждена!",
                call.message.chat.id,
                call.message.message_id
            )
            bot.send_message(
                call.message.chat.id,
                "Добро пожаловать!",
                reply_markup=get_main_keyboard()
            )
        else:
            bot.answer_callback_query(call.id, "❌ Не подписан!", show_alert=True)
    
    elif call.data.startswith("mode_"):
        mode_id = call.data.replace("mode_", "")
        if mode_id in MODES:
            set_user_mode(user_id, mode_id)
            bot.answer_callback_query(call.id, f"Режим: {MODES[mode_id]['name']}")
            bot.send_message(
                call.message.chat.id,
                f"✅ Режим изменён на {MODES[mode_id]['name']}",
                reply_markup=get_main_keyboard()
            )
    
    elif call.data.startswith("video_"):
        presets = {
            "sunset": "Закат над океаном, волны, небо оранжевое",
            "city": "Ночной город, неон, дождь, киберпанк",
            "space": "Космический корабль в туманности",
            "game": "Игровой персонаж в фэнтези мире",
            "custom": "custom"
        }
        
        preset_key = call.data.replace("video_", "")
        if preset_key == "custom":
            msg = bot.send_message(call.message.chat.id, "✏️ Опиши видео:")
            bot.register_next_step_handler(msg, process_video)
        else:
            process_video_text(call.message, presets[preset_key])

def process_video_text(message, prompt):
    user_id = message.from_user.id
    queue_id = add_to_queue(user_id, prompt)
    
    bot.send_message(
        message.chat.id,
        f"🎬 Видео добавлено в очередь!\n"
        f"Время ожидания: 1-2 минуты"
    )
    
    def generate():
        video_url = generate_video(prompt)
        if video_url:
            update_queue(queue_id, video_url)
            update_stats(user_id, 'video')
            try:
                bot.send_video(
                    user_id,
                    video_url,
                    caption=f"🎬 Видео готово!\n\nПромпт: {prompt}"
                )
            except:
                bot.send_message(
                    user_id,
                    f"❌ Ошибка отправки.\nСсылка: {video_url}"
                )
        else:
            bot.send_message(user_id, "❌ Не удалось создать видео")
    
    thread = threading.Thread(target=generate)
    thread.daemon = True
    thread.start()

def process_video(message):
    process_video_text(message, message.text)

# ==================== ТЕКСТОВЫЕ СООБЩЕНИЯ ====================
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id
    text = message.text
    
    if not check_subscription(user_id):
        bot.send_message(message.chat.id, "❌ Сначала подпишись!")
        return
    
    if text == "💬 Чат":
        bot.send_message(message.chat.id, "💬 Напиши что-нибудь...")
    
    elif text == "🎭 Режимы":
        bot.send_message(
            message.chat.id,
            "🎭 Выбери режим:",
            reply_markup=get_modes_keyboard()
        )
    
    elif text == "🎨 Фото":
        msg = bot.send_message(
            message.chat.id,
            "🎨 Опиши что хочешь увидеть:"
        )
        bot.register_next_step_handler(msg, process_image)
    
    elif text == "🎬 Видео":
        bot.send_message(
            message.chat.id,
            "🎬 Выбери сценарий:",
            reply_markup=get_video_presets()
        )
    
    elif text == "📊 Статистика":
        stats = get_stats(user_id)
        if stats:
            msgs, imgs, vids, joined = stats
            joined_str = datetime.fromisoformat(joined).strftime('%d.%m.%Y')
            bot.send_message(
                message.chat.id,
                f"📊 Статистика:\n\n"
                f"💬 Сообщений: {msgs}\n"
                f"🎨 Фото: {imgs}\n"
                f"🎬 Видео: {vids}\n"
                f"📅 В боте с: {joined_str}"
            )
        else:
            bot.send_message(message.chat.id, "📊 Статистика пуста")
    
    elif text == "❓ Помощь":
        bot.send_message(
            message.chat.id,
            f"❓ Помощь:\n\n"
            f"💬 Чат - просто общайся\n"
            f"🎭 Режимы - выбери стиль\n"
            f"🎨 Фото - опиши картинку\n"
            f"🎬 Видео - создай видео\n"
            f"📊 Статистика - твоя активность\n\n"
            f"Канал: {CHANNEL_USERNAME}"
        )
    
    else:
        bot.send_chat_action(message.chat.id, 'typing')
        mode = get_user_mode(user_id)
        answer = ask_groq(text, MODES[mode]['prompt'])
        if answer:
            update_stats(user_id, 'message')
            bot.send_message(message.chat.id, answer)
        else:
            bot.send_message(message.chat.id, "😕 Ошибка, попробуй позже")

def process_image(message):
    user_id = message.from_user.id
    prompt = message.text
    
    bot.send_chat_action(message.chat.id, 'upload_photo')
    result = generate_image(prompt)
    
    if result:
        update_stats(user_id, 'image')
        bot.send_message(message.chat.id, f"🎨 Описание:\n\n{result}")
    else:
        bot.send_message(message.chat.id, "😕 Не удалось создать описание")

# ==================== ЗАПУСК ====================
if __name__ == '__main__':
    logger.info("🚀 MEGA AI запускается с вебхуками...")
    
    # Устанавливаем вебхук
    webhook_url = f"https://r1zzert-bot.onrender.com/webhook"
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=webhook_url)
    logger.info(f"✅ Вебхук установлен на {webhook_url}")
    
    # Запускаем Flask
    app.run(host='0.0.0.0', port=PORT)
