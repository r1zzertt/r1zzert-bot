import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import requests
import time
import logging
from flask import Flask
import threading
import sqlite3
from datetime import datetime, timedelta
import hashlib

# ==================== НАСТРОЙКИ ====================
TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
KLING_API_KEY = os.environ.get('KLING_API_KEY', '')
KLING_SECRET_KEY = os.environ.get('KLING_SECRET_KEY', '')

# Проверка что всё есть
if not TOKEN or not CHANNEL_USERNAME or not GROQ_API_KEY:
    print("❌ Ошибка: не все переменные окружения заданы!")
    print("Нужны: BOT_TOKEN, CHANNEL_USERNAME, GROQ_API_KEY")

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask приложение для health checks
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 @r1zzert_bot MEGA AI is running!"

@app.route('/health')
def health():
    return "OK", 200

# Инициализация бота
bot = telebot.TeleBot(TOKEN)

# ==================== БАЗА ДАННЫХ ====================
def init_database():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            mode TEXT DEFAULT 'assistant',
            joined_date TIMESTAMP,
            last_activity TIMESTAMP,
            messages_count INTEGER DEFAULT 0,
            images_generated INTEGER DEFAULT 0,
            videos_generated INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS message_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            response TEXT,
            mode TEXT,
            timestamp TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            prompt TEXT,
            status TEXT DEFAULT 'pending',
            task_id TEXT,
            video_url TEXT,
            created_at TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

def get_user(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute('''
            INSERT INTO users (user_id, joined_date, last_activity, mode)
            VALUES (?, ?, ?, ?)
        ''', (user_id, datetime.now(), datetime.now(), 'assistant'))
        conn.commit()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
    
    conn.close()
    return user

def update_user_activity(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET last_activity = ? WHERE user_id = ?', 
                  (datetime.now(), user_id))
    conn.commit()
    conn.close()

def save_message(user_id, message, response, mode):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO message_history (user_id, message, response, mode, timestamp)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, message[:500], response[:500] if response else None, mode, datetime.now()))
    cursor.execute('UPDATE users SET messages_count = messages_count + 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

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
    cursor.execute('UPDATE users SET mode = ? WHERE user_id = ?', (mode, user_id))
    conn.commit()
    conn.close()

def increment_image_count(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET images_generated = images_generated + 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def increment_video_count(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET videos_generated = videos_generated + 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def add_to_video_queue(user_id, prompt):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO video_queue (user_id, prompt, status, created_at)
        VALUES (?, ?, ?, ?)
    ''', (user_id, prompt[:200], 'pending', datetime.now()))
    queue_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return queue_id

def update_video_queue(queue_id, status, task_id=None, video_url=None):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    if status == 'completed':
        cursor.execute('''
            UPDATE video_queue 
            SET status = ?, task_id = ?, video_url = ?, completed_at = ? 
            WHERE id = ?
        ''', (status, task_id, video_url, datetime.now(), queue_id))
    else:
        cursor.execute('UPDATE video_queue SET status = ?, task_id = ? WHERE id = ?', 
                      (status, task_id, queue_id))
    
    conn.commit()
    conn.close()

def get_queue_position(queue_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM video_queue 
        WHERE status = 'pending' AND created_at < (
            SELECT created_at FROM video_queue WHERE id = ?
        )
    ''', (queue_id,))
    position = cursor.fetchone()[0] + 1
    
    cursor.execute("SELECT COUNT(*) FROM video_queue WHERE status = 'pending'")
    total = cursor.fetchone()[0]
    
    conn.close()
    return position, total

def get_user_stats(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT messages_count, images_generated, videos_generated, joined_date
        FROM users WHERE user_id = ?
    ''', (user_id,))
    stats = cursor.fetchone()
    
    cursor.execute('''
        SELECT COUNT(*) FROM message_history 
        WHERE user_id = ? AND timestamp > ?
    ''', (user_id, datetime.now() - timedelta(days=1)))
    today_messages = cursor.fetchone()[0]
    
    conn.close()
    
    if stats:
        return {
            'total_messages': stats[0],
            'total_images': stats[1],
            'total_videos': stats[2],
            'joined_date': stats[3],
            'today_messages': today_messages
        }
    return None

# Инициализируем БД
init_database()

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
def check_subscription(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

# ==================== РАБОТА С ИИ ====================
def ask_groq(question, system_prompt=None):
    if not system_prompt:
        system_prompt = "Ты полезный ассистент. Отвечай кратко и по делу."
    
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
            "temperature": 0.7,
            "max_tokens": 1000
        }
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            logger.error(f"Ошибка Groq: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Ошибка при запросе к Groq: {e}")
        return None

# ==================== ГЕНЕРАЦИЯ ВИДЕО ====================
def generate_kling_video(prompt):
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
            "aspect_ratio": "9:16",
            "cfg_scale": 0.5,
            "mode": "std"
        }
        
        response = requests.post(
            "https://api.kling.ai/v1/videos/generations",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0 and 'data' in result:
                task_id = result['data']['task_id']
                return check_kling_task(task_id)
        return None
    except Exception as e:
        logger.error(f"Ошибка генерации видео: {e}")
        return None

def check_kling_task(task_id, max_attempts=30):
    headers = {
        "Authorization": f"Bearer {KLING_API_KEY}"
    }
    
    for attempt in range(max_attempts):
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
                    else:
                        time.sleep(5)
        except Exception as e:
            logger.error(f"Ошибка при проверке задачи: {e}")
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
                {"role": "user", "content": f"Опиши подробно, как должно выглядеть изображение: {prompt}"}
            ]
        }
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        if response.status_code == 200:
            description = response.json()['choices'][0]['message']['content']
            return f"🖼️ Вот описание того, что ты просил:\n\n{description}"
        return None
    except Exception as e:
        logger.error(f"Ошибка генерации изображения: {e}")
        return None

# ==================== РЕЖИМЫ РАБОТЫ ====================
MODES = {
    "assistant": {
        "name": "🤵 Обычный помощник",
        "system_prompt": "Ты дружелюбный ассистент. Помогаешь с любыми вопросами, даёшь полезные советы. Отвечай кратко и по делу."
    },
    "developer": {
        "name": "💻 Помощник разработчика",
        "system_prompt": "Ты эксперт по программированию. Помогаешь писать код, объясняешь сложные концепции. Отвечай на русском с примерами кода."
    },
    "writer": {
        "name": "✍️ Редактор текстов",
        "system_prompt": "Ты профессиональный редактор. Помогаешь писать посты, статьи, описания. Делаешь тексты красивыми и убедительными."
    },
    "teacher": {
        "name": "👨‍🏫 Учитель",
        "system_prompt": "Ты терпеливый учитель. Объясняешь сложные вещи простыми словами, приводишь примеры."
    },
    "creative": {
        "name": "🎨 Креативный директор",
        "system_prompt": "Ты креативный директор. Помогаешь с идеями для контента, названиями, слоганами. Мыслишь нестандартно."
    },
    "video_pro": {
        "name": "🎬 Видеорежиссёр",
        "system_prompt": "Ты эксперт по созданию видео. Помогаешь придумывать сюжеты, описываешь как должно выглядеть видео."
    }
}

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("💬 Чат"),
        KeyboardButton("🎭 Режимы"),
        KeyboardButton("🎨 Создать фото"),
        KeyboardButton("🎬 Создать видео"),
        KeyboardButton("📊 Статистика"),
        KeyboardButton("❓ Помощь"),
        KeyboardButton("📜 История"),
        KeyboardButton("🎥 Видео-режиссёр")
    )
    return markup

def get_modes_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for mode_id, mode_info in MODES.items():
        buttons.append(InlineKeyboardButton(mode_info['name'], callback_data=f"mode_{mode_id}"))
    markup.add(*buttons)
    return markup

def get_video_presets_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌅 Закат на пляже", callback_data="video_preset_sunset"),
        InlineKeyboardButton("🏙️ Ночной город", callback_data="video_preset_city"),
        InlineKeyboardButton("🚀 Космос", callback_data="video_preset_space"),
        InlineKeyboardButton("🌊 Океан", callback_data="video_preset_ocean"),
        InlineKeyboardButton("🎮 Игровой клип", callback_data="video_preset_game"),
        InlineKeyboardButton("🛒 Обзор товара", callback_data="video_preset_product"),
        InlineKeyboardButton("🎬 Свой промпт", callback_data="video_preset_custom")
    )
    return markup

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "друг"
    
    logger.info(f"Пользователь {user_id} запустил бота")
    get_user(user_id)
    update_user_activity(user_id)
    
    if not check_subscription(user_id):
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=f"https://t.me/{CHANNEL_USERNAME[1:]}"),
            InlineKeyboardButton("✅ Я ПОДПИСАЛСЯ", callback_data="check_sub")
        )
        bot.send_message(
            message.chat.id,
            f"👋 Привет, {user_name}!\n\n"
            f"🔒 Доступ к боту — только для подписчиков канала {CHANNEL_USERNAME}\n\n"
            f"Подпишись и нажми кнопку:",
            reply_markup=markup
        )
        return
    
    bot.send_message(
        message.chat.id,
        f"👋 Привет, {user_name}! Добро пожаловать в @r1zzert_bot MEGA AI!\n\n"
        f"🔥 Что я умею:\n"
        f"🎬 Генерация видео — создавай видео по тексту\n"
        f"💬 Умный чат — отвечаю на любые вопросы\n"
        f"🎭 Режимы — меняю личность и стиль\n"
        f"📜 История — помню все диалоги\n"
        f"📊 Статистика — твоя активность\n\n"
        f"Текущий режим: {MODES[get_user_mode(user_id)]['name']}\n"
        f"Используй кнопки ниже 👇",
        reply_markup=get_main_keyboard()
    )

@bot.message_handler(commands=['menu'])
def menu_command(message):
    if not check_subscription(message.from_user.id):
        return
    update_user_activity(message.from_user.id)
    bot.send_message(message.chat.id, "📱 Главное меню", reply_markup=get_main_keyboard())

@bot.message_handler(commands=['mode'])
def mode_command(message):
    if not check_subscription(message.from_user.id):
        return
    update_user_activity(message.from_user.id)
    bot.send_message(
        message.chat.id,
        "🎭 Выбери режим работы:\n\nКаждый режим меняет личность и стиль ответов бота.",
        reply_markup=get_modes_keyboard()
    )

@bot.message_handler(commands=['image'])
def image_command(message):
    if not check_subscription(message.from_user.id):
        return
    update_user_activity(message.from_user.id)
    msg = bot.send_message(
        message.chat.id,
        "🎨 Опиши, что ты хочешь увидеть.\nНапример: Киберпанк город на закате, неоновые огни"
    )
    bot.register_next_step_handler(msg, process_image_generation)

def process_image_generation(message):
    if not check_subscription(message.from_user.id):
        return
    
    user_id = message.from_user.id
    prompt = message.text
    
    bot.send_chat_action(message.chat.id, 'upload_photo')
    bot.send_message(message.chat.id, "🎨 Генерирую описание изображения...")
    
    result = generate_image(prompt)
    
    if result:
        bot.send_message(message.chat.id, result)
        increment_image_count(user_id)
    else:
        bot.send_message(message.chat.id, "😕 Не удалось сгенерировать изображение. Попробуй позже.")

@bot.message_handler(commands=['video'])
def video_command(message):
    if not check_subscription(message.from_user.id):
        return
    update_user_activity(message.from_user.id)
    
    bot.send_message(
        message.chat.id,
        "🎬 Создание видео\n\nВыбери готовый сценарий или введи свой промпт:",
        reply_markup=get_video_presets_keyboard()
    )

def process_video_generation(message):
    if not check_subscription(message.from_user.id):
        return
    
    user_id = message.from_user.id
    prompt = message.text
    
    queue_id = add_to_video_queue(user_id, prompt)
    position, total = get_queue_position(queue_id)
    
    bot.send_message(
        message.chat.id,
        f"🎬 Твой запрос добавлен в очередь!\n"
        f"Позиция в очереди: {position}/{total}\n"
        f"Примерное время ожидания: {position} минута\n\n"
        f"Я уведомлю тебя, когда видео будет готово."
    )
    
    def generate_video_thread():
        video_url = generate_kling_video(prompt)
        
        if video_url:
            update_video_queue(queue_id, 'completed', video_url=video_url)
            increment_video_count(user_id)
            
            try:
                bot.send_video(
                    user_id,
                    video_url,
                    caption=f"🎬 Видео готово!\n\nПромпт: {prompt}"
                )
                bot.send_message(
                    user_id,
                    f"✅ Видео успешно сгенерировано!"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки видео: {e}")
                bot.send_message(
                    user_id,
                    f"❌ Ошибка при отправке видео.\n"
                    f"Но ты можешь скачать его по ссылке: {video_url}"
                )
        else:
            update_video_queue(queue_id, 'failed')
            bot.send_message(
                user_id,
                "❌ Не удалось сгенерировать видео. Попробуй позже или измени промпт."
            )
    
    thread = threading.Thread(target=generate_video_thread)
    thread.daemon = True
    thread.start()

@bot.message_handler(commands=['stats'])
def stats_command(message):
    if not check_subscription(message.from_user.id):
        return
    
    user_id = message.from_user.id
    stats = get_user_stats(user_id)
    
    if stats:
        joined = datetime.fromisoformat(str(stats['joined_date'])).strftime('%d.%m.%Y')
        stats_text = f"""
📊 Твоя статистика

📅 В боте с: {joined}
💬 Всего сообщений: {stats['total_messages']}
📈 Сообщений сегодня: {stats['today_messages']}
🎨 Сгенерировано изображений: {stats['total_images']}
🎬 Сгенерировано видео: {stats['total_videos']}

Текущий режим: {MODES[get_user_mode(user_id)]['name']}
        """
        bot.send_message(message.chat.id, stats_text)
    else:
        bot.send_message(message.chat.id, "📊 Статистика пока пуста")

@bot.message_handler(commands=['history'])
def history_command(message):
    if not check_subscription(message.from_user.id):
        return
    
    user_id = message.from_user.id
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT message, response, timestamp, mode FROM message_history 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 10
    ''', (user_id,))
    
    history = cursor.fetchall()
    conn.close()
    
    if history:
        history_text = "📜 Последние 10 диалогов:\n\n"
        for i, (msg, resp, ts, mode) in enumerate(history, 1):
            ts_formatted = datetime.fromisoformat(ts).strftime('%H:%M %d.%m')
            history_text += f"{i}. {ts_formatted} ({MODES.get(mode, {}).get('name', mode)})\n"
            history_text += f"   Ты: {msg[:50]}...\n"
            history_text += f"   Бот: {resp[:50]}...\n\n"
        
        if len(history_text) > 4000:
            parts = [history_text[i:i+4000] for i in range(0, len(history_text), 4000)]
            for part in parts:
                bot.send_message(message.chat.id, part)
        else:
            bot.send_message(message.chat.id, history_text)
    else:
        bot.send_message(message.chat.id, "📜 История диалогов пока пуста")

@bot.message_handler(commands=['help'])
def help_command(message):
    if not check_subscription(message.from_user.id):
        return
    
    update_user_activity(message.from_user.id)
    
    help_text = f"""
❓ Помощь по боту @r1zzert_bot MEGA AI

🤖 ОСНОВНЫЕ ФУНКЦИИ:

💬 Чат — просто общайся со мной
🎭 Режимы — выбери мою личность
🎨 Создать фото — сгенерируй изображение по тексту
🎬 Создать видео — создай видео по тексту
📊 Статистика — посмотри свою активность
📜 История — просмотри последние диалоги

🎥 ВИДЕО-ГЕНЕРАЦИЯ:
• Выбери готовый пресет или введи свой промпт
• Видео создаётся 1-2 минуты
• Ты получишь уведомление о готовности
• Формат 9:16 (вертикальный) — для TikTok/Reels

🔐 ПОДПИСКА:
• Бот работает только для подписчиков канала {CHANNEL_USERNAME}
• После подписки нажми кнопку "✅ Я ПОДПИСАЛСЯ"

📝 ПРИМЕРЫ ПРОМПТОВ ДЛЯ ВИДЕО:
• Закат над океаном, камера медленно поднимается
• Ночной город, идёт дождь, неоновые огни
• Космический корабль взлетает с планеты

Приятного использования! 🚀
    """
    bot.send_message(message.chat.id, help_text, reply_markup=get_main_keyboard())

# ==================== ОБРАБОТЧИКИ КНОПОК ====================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    
    if call.data == "check_sub":
        if check_subscription(user_id):
            user_name = call.from_user.first_name or "друг"
            
            bot.edit_message_text(
                f"✅ Подписка подтверждена! Добро пожаловать, {user_name}!",
                call.message.chat.id,
                call.message.message_id
            )
            
            bot.send_message(
                call.message.chat.id,
                f"👋 Добро пожаловать в @r1zzert_bot MEGA AI!\n\n"
                f"🔥 Что я умею:\n"
                f"🎬 Генерация видео — создавай видео по тексту\n"
                f"💬 Умный чат — отвечаю на любые вопросы\n"
                f"🎭 Режимы — меняю личность и стиль\n"
                f"📜 История — помню все диалоги\n"
                f"📊 Статистика — твоя активность\n\n"
                f"Текущий режим: {MODES[get_user_mode(user_id)]['name']}\n"
                f"Используй кнопки ниже 👇",
                reply_markup=get_main_keyboard()
            )
        else:
            bot.answer_callback_query(
                call.id,
                text="❌ Ты не подписан на канал! Сначала подпишись.",
                show_alert=True
            )
    
    elif call.data.startswith("mode_"):
        mode_id = call.data.replace("mode_", "")
        if mode_id in MODES:
            set_user_mode(user_id, mode_id)
            bot.answer_callback_query(call.id, text=f"Режим изменён на {MODES[mode_id]['name']}")
            bot.send_message(
                call.message.chat.id,
                f"✅ Режим изменён на {MODES[mode_id]['name']}\n\nТеперь я буду отвечать в этом стиле.",
                reply_markup=get_main_keyboard()
            )
    
    elif call.data.startswith("video_preset_"):
        preset = call.data.replace("video_preset_", "")
        
        presets = {
            "sunset": "Закат над океаном, волны набегают на берег, камера медленно поднимается, небо оранжево-розовое, 4K",
            "city": "Ночной мегаполис, идёт дождь, неоновые огни отражаются в лужах, камера движется по улице",
            "space": "Космический корабль пролетает мимо красивой туманности, звёзды, планеты, эпичная сцена",
            "ocean": "Подводный мир, коралловый риф, разноцветные рыбки, солнечные лучи проникают сквозь воду",
            "game": "Игровой персонаж в фэнтези мире, магия, эпичная битва, динамичный экшен",
            "product": "Товар красиво вращается на белом фоне, 3D-анимация, профессиональная съёмка"
        }
        
        if preset == "custom":
            msg = bot.send_message(
                call.message.chat.id,
                "🎬 Опиши, какое видео ты хочешь создать.\nБудь креативным!"
            )
            bot.register_next_step_handler(msg, process_video_generation)
        elif preset in presets:
            bot.send_message(call.message.chat.id, f"🎬 Выбран пресет: {presets[preset][:50]}...")
            process_video_generation(type('obj', (object,), {
                'from_user': call.from_user,
                'chat': call.message.chat,
                'text': presets[preset],
                'message_id': call.message.message_id
            }))

# ==================== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ====================
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id
    
    if not check_subscription(user_id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=f"https://t.me/{CHANNEL_USERNAME[1:]}"))
        bot.send_message(
            message.chat.id,
            "❌ Сначала подпишись на канал!",
            reply_markup=markup
        )
        return
    
    update_user_activity(user_id)
    text = message.text
    
    if text == "💬 Чат":
        bot.send_message(
            message.chat.id,
            f"💬 Просто напиши мне что-нибудь, и я отвечу!\n\n"
            f"Текущий режим: {MODES[get_user_mode(user_id)]['name']}\n"
            f"Изменить режим можно через меню или /mode"
        )
    
    elif text == "🎭 Режимы":
        mode_command(message)
    
    elif text == "🎨 Создать фото":
        image_command(message)
    
    elif text == "🎬 Создать видео":
        video_command(message)
    
    elif text == "📊 Статистика":
        stats_command(message)
    
    elif text == "📜 История":
        history_command(message)
    
    elif text == "🎥 Видео-режиссёр":
        set_user_mode(user_id, 'video_pro')
        bot.send_message(
            message.chat.id,
            "🎬 Теперь я твой Видеорежиссёр!\n\n"
            "Расскажи, какое видео ты хочешь создать, и я помогу придумать сценарий.\n\n"
            "Потом просто нажми 🎬 Создать видео и используй мой промпт!"
        )
    
    elif text == "❓ Помощь":
        help_command(message)
    
    else:
        bot.send_chat_action(message.chat.id, 'typing')
        
        mode = get_user_mode(user_id)
        system_prompt = MODES[mode]['system_prompt']
        answer = ask_groq(text, system_prompt)
        
        if answer:
            save_message(user_id, text, answer, mode)
            response = f"Режим: {MODES[mode]['name']}\n\n{answer}"
            
            if len(response) > 4000:
                parts = [response[i:i+4000] for i in range(0, len(response), 4000)]
                for part in parts:
                    bot.send_message(message.chat.id, part)
            else:
                bot.send_message(message.chat.id, response)
        else:
            bot.send_message(
                message.chat.id,
                "😕 Извини, не могу ответить сейчас. Попробуй позже или задай другой вопрос."
            )

# ==================== ЗАПУСК БОТА ====================
def run_bot():
    logger.info("🚀 MEGA AI Бот запускается...")
    
    try:
        bot.remove_webhook()
        logger.info("✅ Вебхук удалён")
    except:
        pass
    
    time.sleep(2)
    
    try:
        bot.stop_polling()
        logger.info("✅ Старый polling остановлен")
    except:
        pass
    
    time.sleep(2)
    
    while True:
        try:
            logger.info("🔄 Запускаю polling...")
            bot.infinity_polling(timeout=30, long_polling_timeout=20, skip_pending=True)
        except Exception as e:
            logger.error(f"Ошибка в polling: {e}")
            
            if "409" in str(e):
                logger.warning("⚠️ Конфликт 409, пробую перезапуск...")
                try:
                    bot.stop_polling()
                    time.sleep(5)
                except:
                    pass
            else:
                time.sleep(3)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("🌐 Flask сервер запускается на порту " + os.environ.get('PORT', '10000'))
    
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
