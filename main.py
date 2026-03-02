import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import requests
import time
import logging
import sqlite3
from datetime import datetime, timedelta
import threading
from flask import Flask, request
import random
import urllib.parse

# ==================== НАСТРОЙКИ ====================
TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME', '@r1zzert')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
PORT = int(os.environ.get('PORT', 10000))

# 👑 СПИСОК АДМИНОВ (добавь свои ID)
ADMIN_IDS = [1783230843]  # Замени на свой ID! Узнать можно у @userinfobot

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
            images_generated INTEGER DEFAULT 0,
            memes_created INTEGER DEFAULT 0,
            voice_messages INTEGER DEFAULT 0,
            crystals INTEGER DEFAULT 50,
            joined_date TIMESTAMP,
            last_active TIMESTAMP,
            last_daily TIMESTAMP,
            clicks INTEGER DEFAULT 0,
            roulette_wins INTEGER DEFAULT 0,
            challenges_completed INTEGER DEFAULT 0,
            username TEXT,
            first_name TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            game_type TEXT,
            score INTEGER,
            played_at TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE UNIQUE,
            title TEXT,
            description TEXT,
            reward INTEGER DEFAULT 10
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS completed_challenges (
            user_id INTEGER,
            challenge_id INTEGER,
            completed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (challenge_id) REFERENCES challenges (id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            reason TEXT,
            created_at TIMESTAMP
        )
    ''')
    
    conn.commit()
    
    # Добавляем ежедневные челленджи если их нет
    cursor.execute('SELECT COUNT(*) FROM challenges')
    if cursor.fetchone()[0] == 0:
        challenges = [
            ("Напиши стих", "Сочини стихотворение на любую тему", 15),
            ("Создай мем", "Сделай мем с любым текстом", 20),
            ("Выиграй в рулетку", "Угадай число в рулетке", 10),
            ("Сделай 10 кликов", "Потыкай кнопку в кликере", 10),
            ("Поговори с психологом", "Напиши что тебя беспокоит", 15)
        ]
        for title, desc, reward in challenges:
            cursor.execute('''
                INSERT INTO challenges (date, title, description, reward)
                VALUES (?, ?, ?, ?)
            ''', (datetime.now().date(), title, desc, reward))
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_database()

def get_user(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute('''
            INSERT INTO users (user_id, joined_date, last_active, last_daily)
            VALUES (?, ?, ?, ?)
        ''', (user_id, datetime.now(), datetime.now(), datetime.now() - timedelta(days=1)))
        conn.commit()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
    
    conn.close()
    return user

def get_user_mode(user_id):
    user = get_user(user_id)
    return user[1] if user else 'assistant'

def set_user_mode(user_id, mode):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET mode = ?, last_active = ? WHERE user_id = ?',
                  (mode, datetime.now(), user_id))
    conn.commit()
    conn.close()

def update_stats(user_id, stat_type, amount=1):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET last_active = ? WHERE user_id = ?', (datetime.now(), user_id))
    
    if stat_type == 'message':
        cursor.execute('UPDATE users SET messages_count = messages_count + ? WHERE user_id = ?', (amount, user_id))
    elif stat_type == 'image':
        cursor.execute('UPDATE users SET images_generated = images_generated + ? WHERE user_id = ?', (amount, user_id))
    elif stat_type == 'meme':
        cursor.execute('UPDATE users SET memes_created = memes_created + ? WHERE user_id = ?', (amount, user_id))
    elif stat_type == 'voice':
        cursor.execute('UPDATE users SET voice_messages = voice_messages + ? WHERE user_id = ?', (amount, user_id))
    elif stat_type == 'click':
        cursor.execute('UPDATE users SET clicks = clicks + ? WHERE user_id = ?', (amount, user_id))
    elif stat_type == 'roulette_win':
        cursor.execute('UPDATE users SET roulette_wins = roulette_wins + ? WHERE user_id = ?', (amount, user_id))
    elif stat_type == 'challenge':
        cursor.execute('UPDATE users SET challenges_completed = challenges_completed + ? WHERE user_id = ?', (amount, user_id))
    
    conn.commit()
    conn.close()

def add_crystals(user_id, amount, reason):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET crystals = crystals + ? WHERE user_id = ?', (amount, user_id))
    cursor.execute('''
        INSERT INTO transactions (user_id, amount, reason, created_at)
        VALUES (?, ?, ?, ?)
    ''', (user_id, amount, reason, datetime.now()))
    conn.commit()
    conn.close()

def spend_crystals(user_id, amount, reason):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT crystals FROM users WHERE user_id = ?', (user_id,))
    current = cursor.fetchone()[0]
    
    if current >= amount:
        cursor.execute('UPDATE users SET crystals = crystals - ? WHERE user_id = ?', (amount, user_id))
        cursor.execute('''
            INSERT INTO transactions (user_id, amount, reason, created_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, -amount, reason, datetime.now()))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def get_crystals(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT crystals FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def get_daily_bonus(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT last_daily FROM users WHERE user_id = ?', (user_id,))
    last_daily = cursor.fetchone()[0]
    last = datetime.fromisoformat(last_daily)
    
    if datetime.now().date() > last.date():
        cursor.execute('UPDATE users SET crystals = crystals + 20, last_daily = ? WHERE user_id = ?',
                      (datetime.now(), user_id))
        cursor.execute('''
            INSERT INTO transactions (user_id, amount, reason, created_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, 20, "Ежедневный бонус", datetime.now()))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def get_todays_challenge():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, title, description, reward FROM challenges 
        WHERE date = ? ORDER BY RANDOM() LIMIT 1
    ''', (datetime.now().date(),))
    challenge = cursor.fetchone()
    conn.close()
    return challenge

def check_challenge_completed(user_id, challenge_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM completed_challenges 
        WHERE user_id = ? AND challenge_id = ?
    ''', (user_id, challenge_id))
    completed = cursor.fetchone()
    conn.close()
    return completed is not None

def complete_challenge(user_id, challenge_id, reward):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO completed_challenges (user_id, challenge_id, completed_at)
        VALUES (?, ?, ?)
    ''', (user_id, challenge_id, datetime.now()))
    cursor.execute('UPDATE users SET crystals = crystals + ? WHERE user_id = ?', (reward, user_id))
    cursor.execute('UPDATE users SET challenges_completed = challenges_completed + 1 WHERE user_id = ?', (user_id,))
    cursor.execute('''
        INSERT INTO transactions (user_id, amount, reason, created_at)
        VALUES (?, ?, ?, ?)
    ''', (user_id, reward, "Выполнен челлендж", datetime.now()))
    conn.commit()
    conn.close()

def get_leaderboard():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, clicks, roulette_wins, crystals, challenges_completed 
        FROM users ORDER BY crystals DESC LIMIT 10
    ''')
    leaders = cursor.fetchall()
    conn.close()
    return leaders

def get_all_users():
    """Получить список всех пользователей для рассылки"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    users = cursor.fetchall()
    conn.close()
    return [user[0] for user in users]

def get_total_users_count():
    """Получить общее количество пользователей"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_user_info(user_id):
    """Получить полную информацию о пользователе"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

# ==================== ПРОВЕРКА ПРАВ ====================
def is_admin(user_id):
    """Проверка, является ли пользователь админом"""
    return user_id in ADMIN_IDS

def admin_only(func):
    """Декоратор для админских команд"""
    def wrapper(message, *args, **kwargs):
        if not is_admin(message.from_user.id):
            bot.reply_to(message, "⛔ Эта команда только для администраторов.")
            return
        return func(message, *args, **kwargs)
    return wrapper

# ==================== АДМИНСКИЕ КОМАНДЫ ====================
@bot.message_handler(commands=['admin'])
@admin_only
def admin_panel(message):
    """Главное меню админки"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
        InlineKeyboardButton("👥 Пользователи", callback_data="admin_users"),
        InlineKeyboardButton("💎 Начислить кристаллы", callback_data="admin_add_crystals"),
        InlineKeyboardButton("🎁 Выдать бонус всем", callback_data="admin_bonus_all"),
        InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
        InlineKeyboardButton("🔍 Найти пользователя", callback_data="admin_find_user"),
        InlineKeyboardButton("📋 Логи транзакций", callback_data="admin_transactions")
    )
    bot.send_message(
        message.chat.id,
        "👑 **Панель администратора**\n\nВыбери действие:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['stats'])
@admin_only
def admin_stats_command(message):
    """Быстрая статистика"""
    total_users = get_total_users_count()
    bot.send_message(
        message.chat.id,
        f"📊 **Общая статистика**\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"👑 Админов: {len(ADMIN_IDS)}",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['add_crystals'])
@admin_only
def admin_add_crystals_command(message):
    """Начать процесс начисления кристаллов"""
    msg = bot.send_message(
        message.chat.id,
        "✏️ Введи ID пользователя и количество кристаллов через пробел\n"
        "Пример: `123456789 50`",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, process_add_crystals)

def process_add_crystals(message):
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.send_message(message.chat.id, "❌ Неверный формат. Используй: `user_id количество`")
            return
        
        user_id = int(parts[0])
        amount = int(parts[1])
        
        add_crystals(user_id, amount, f"Начислено админом {message.from_user.id}")
        bot.send_message(
            message.chat.id,
            f"✅ Пользователю {user_id} начислено {amount}💎"
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['broadcast'])
@admin_only
def admin_broadcast_command(message):
    """Начать рассылку"""
    msg = bot.send_message(
        message.chat.id,
        "📢 **Режим рассылки**\n\n"
        "Отправь сообщение, которое нужно разослать всем пользователям.\n"
        "Можно использовать текст, фото, видео, кнопки.\n\n"
        "Для отмены отправь /cancel",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, process_broadcast)

def process_broadcast(message):
    if message.text == "/cancel":
        bot.send_message(message.chat.id, "❌ Рассылка отменена")
        return
    
    # Сохраняем сообщение для рассылки
    broadcast_msg = message
    
    # Получаем всех пользователей
    users = get_all_users()
    total = len(users)
    
    status_msg = bot.send_message(
        message.chat.id,
        f"📢 **Начинаю рассылку**\n\n"
        f"Всего пользователей: {total}\n"
        f"Прогресс: 0/{total} (0%)"
    )
    
    successful = 0
    failed = 0
    blocked = 0
    
    for i, user_id in enumerate(users):
        try:
            # Копируем сообщение пользователю
            if broadcast_msg.content_type == 'text':
                bot.send_message(user_id, broadcast_msg.text)
            elif broadcast_msg.content_type == 'photo':
                bot.send_photo(
                    user_id,
                    broadcast_msg.photo[-1].file_id,
                    caption=broadcast_msg.caption
                )
            elif broadcast_msg.content_type == 'video':
                bot.send_video(
                    user_id,
                    broadcast_msg.video.file_id,
                    caption=broadcast_msg.caption
                )
            elif broadcast_msg.content_type == 'voice':
                bot.send_voice(user_id, broadcast_msg.voice.file_id)
            else:
                bot.copy_message(user_id, broadcast_msg.chat.id, broadcast_msg.message_id)
            
            successful += 1
        except Exception as e:
            failed += 1
            if "bot was blocked by the user" in str(e):
                blocked += 1
        
        # Обновляем прогресс каждые 10 сообщений
        if (i + 1) % 10 == 0:
            percent = (i + 1) * 100 // total
            bot.edit_message_text(
                f"📢 **Рассылка**\n\n"
                f"Прогресс: {i + 1}/{total} ({percent}%)",
                status_msg.chat.id,
                status_msg.message_id
            )
    
    # Финальный отчет
    bot.edit_message_text(
        f"✅ **Рассылка завершена!**\n\n"
        f"📊 Статистика:\n"
        f"• Всего: {total}\n"
        f"• ✅ Успешно: {successful}\n"
        f"• ❌ Ошибок: {failed}\n"
        f"• 🚫 Заблокировали бота: {blocked}",
        status_msg.chat.id,
        status_msg.message_id
    )

# ==================== ОБРАБОТЧИКИ КНОПОК АДМИНКИ ====================
@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback_handler(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Доступ запрещен", show_alert=True)
        return
    
    if call.data == "admin_stats":
        total_users = get_total_users_count()
        bot.edit_message_text(
            f"📊 **Общая статистика**\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"👑 Админов: {len(ADMIN_IDS)}",
            call.message.chat.id,
            call.message.message_id
        )
    
    elif call.data == "admin_users":
        total_users = get_total_users_count()
        bot.edit_message_text(
            f"👥 **Пользователи**\n\n"
            f"Всего: {total_users}\n\n"
            f"Используй /find_user [id или юзернейм] для поиска",
            call.message.chat.id,
            call.message.message_id
        )
    
    elif call.data == "admin_add_crystals":
        bot.edit_message_text(
            "✏️ Введи ID пользователя и количество кристаллов через пробел\n"
            "Пример: `123456789 50`",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(call.message, process_add_crystals)
    
    elif call.data == "admin_bonus_all":
        users = get_all_users()
        total = len(users)
        
        msg = bot.edit_message_text(
            f"🎁 **Выдача бонуса всем**\n\n"
            f"Всего пользователей: {total}\n"
            f"Введи количество кристаллов:",
            call.message.chat.id,
            call.message.message_id
        )
        bot.register_next_step_handler(msg, process_bonus_all)
    
    elif call.data == "admin_broadcast":
        msg = bot.edit_message_text(
            "📢 **Режим рассылки**\n\n"
            "Отправь сообщение для рассылки всем пользователям.\n"
            "Для отмены отправь /cancel",
            call.message.chat.id,
            call.message.message_id
        )
        bot.register_next_step_handler(msg, process_broadcast)
    
    elif call.data == "admin_find_user":
        msg = bot.edit_message_text(
            "🔍 Введи ID пользователя или @username:",
            call.message.chat.id,
            call.message.message_id
        )
        bot.register_next_step_handler(msg, process_find_user)
    
    elif call.data == "admin_transactions":
        # Показать последние 10 транзакций
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM transactions 
            ORDER BY created_at DESC LIMIT 10
        ''')
        transactions = cursor.fetchall()
        conn.close()
        
        text = "📋 **Последние транзакции**\n\n"
        for t in transactions:
            text += f"• Пользователь {t[1]}: {t[2]}💎 ({t[3]})\n"
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id)

def process_bonus_all(message):
    try:
        amount = int(message.text)
        users = get_all_users()
        total = len(users)
        
        status_msg = bot.send_message(
            message.chat.id,
            f"🎁 **Выдаю бонус {amount}💎 всем пользователям**\n\n"
            f"Всего: {total}\n"
            f"Прогресс: 0/{total}"
        )
        
        for i, user_id in enumerate(users):
            add_crystals(user_id, amount, f"Бонус всем от админа {message.from_user.id}")
            
            if (i + 1) % 10 == 0:
                percent = (i + 1) * 100 // total
                bot.edit_message_text(
                    f"🎁 **Выдаю бонус**\n\n"
                    f"Прогресс: {i + 1}/{total} ({percent}%)",
                    status_msg.chat.id,
                    status_msg.message_id
                )
        
        bot.edit_message_text(
            f"✅ **Бонус выдан!**\n\n"
            f"{total} пользователей получили +{amount}💎",
            status_msg.chat.id,
            status_msg.message_id
        )
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введи число!")

def process_find_user(message):
    query = message.text.strip()
    
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    if query.isdigit():
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (int(query),))
    else:
        cursor.execute('SELECT * FROM users WHERE username = ?', (query.replace('@', ''),))
    
    user = cursor.fetchone()
    conn.close()
    
    if user:
        text = f"🔍 **Пользователь найден**\n\n"
        text += f"🆔 ID: {user[0]}\n"
        text += f"🎭 Режим: {user[1]}\n"
        text += f"💬 Сообщений: {user[2]}\n"
        text += f"🎨 Фото: {user[3]}\n"
        text += f"🎨 Мемов: {user[4]}\n"
        text += f"🎤 Голосовых: {user[5]}\n"
        text += f"💎 Кристаллов: {user[6]}\n"
        text += f"📅 В боте с: {user[7]}\n"
        text += f"🖱️ Кликов: {user[12]}\n"
        text += f"🎲 Побед в рулетке: {user[13]}\n"
        text += f"🏆 Челленджей: {user[14]}"
        
        bot.send_message(message.chat.id, text)
    else:
        bot.send_message(message.chat.id, "❌ Пользователь не найден")

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
            "model": "llama-3.3-70b-versatile",
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
            logger.error(f"Groq ошибка {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Ошибка при запросе к Groq: {e}")
        return None

# ==================== ГЕНЕРАЦИЯ ФОТО ====================
def generate_real_image(prompt):
    try:
        encoded_prompt = urllib.parse.quote(prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
        return image_url
    except Exception as e:
        logger.error(f"Ошибка генерации фото: {e}")
        return None

# ==================== ГЕНЕРАЦИЯ МЕМОВ ====================
MEME_TEMPLATES = {
    "краб": "https://imgflip.com/s/meme/Crab-Rave.jpg",
    "дрейк": "https://imgflip.com/s/meme/Drake-Hotline-Bling.jpg",
    "батман": "https://imgflip.com/s/meme/Batman-Slapping-Robin.jpg",
    "ожог": "https://imgflip.com/s/meme/Burn-Kitty.jpg",
    "дог": "https://imgflip.com/s/meme/Doge.jpg",
    "вселенная": "https://imgflip.com/s/meme/Expanding-Brain.jpg",
    "фрай": "https://imgflip.com/s/meme/Futurama-Fry.jpg",
    "девушка": "https://imgflip.com/s/meme/Disaster-Girl.jpg",
    "тронь": "https://imgflip.com/s/meme/Ill-just-wait-here.jpg",
    "парашют": "https://imgflip.com/s/meme/Always-Has-Been.jpg"
}

def create_meme(template_key, top_text, bottom_text):
    try:
        url = f"https://api.memegen.link/images/{template_key}/{top_text}/{bottom_text}.png"
        return url
    except:
        return None

# ==================== ГОЛОСОВЫЕ СООБЩЕНИЯ ====================
def text_to_speech(text):
    try:
        url = f"http://translate.google.com/translate_tts?ie=UTF-8&q={urllib.parse.quote(text)}&tl=ru&client=tw-ob"
        return url
    except:
        return None

# ==================== РЕЖИМЫ ====================
MODES = {
    "assistant": {
        "name": "🤵 Обычный помощник",
        "prompt": "Ты полезный ассистент. Отвечай кратко и по делу. Будь дружелюбным."
    },
    "developer": {
        "name": "💻 Разработчик",
        "prompt": "Ты эксперт по программированию. Помогай с кодом, объясняй сложные концепции простыми словами."
    },
    "writer": {
        "name": "✍️ Писатель",
        "prompt": "Ты профессиональный писатель. Помогай с текстами, пиши красиво и образно."
    },
    "creative": {
        "name": "🎨 Креативщик",
        "prompt": "Ты креативный директор. Генерируй идеи, предлагай нестандартные решения."
    },
    "psychologist": {
        "name": "🧠 Психолог",
        "prompt": "Ты профессиональный психолог. Слушай проблемы, давай советы, поддерживай. Анализируй настроение по тексту."
    }
}

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("💬 Чат"),
        KeyboardButton("🎨 Создать фото"),
        KeyboardButton("🎭 Режимы"),
        KeyboardButton("🎮 Игры"),
        KeyboardButton("🎨 Создать мем"),
        KeyboardButton("🎤 Голос"),
        KeyboardButton("🏆 Челлендж"),
        KeyboardButton("💎 Кристаллы"),
        KeyboardButton("📊 Статистика"),
        KeyboardButton("🏅 Топ игроков"),
        KeyboardButton("❓ Помощь")
    )
    return markup

def get_modes_keyboard(user_id):
    current_mode = get_user_mode(user_id)
    markup = InlineKeyboardMarkup(row_width=1)
    
    for mode_id, mode_info in MODES.items():
        name = mode_info['name']
        if mode_id == current_mode:
            name = f"✅ {name}"
        markup.add(InlineKeyboardButton(name, callback_data=f"mode_{mode_id}"))
    
    return markup

def get_games_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🖱️ Кликер", callback_data="game_clicker"),
        InlineKeyboardButton("🎲 Рулетка", callback_data="game_roulette"),
        InlineKeyboardButton("🏆 Топ игроков", callback_data="game_leaderboard")
    )
    return markup

def get_meme_templates_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    for template in MEME_TEMPLATES.keys():
        markup.add(InlineKeyboardButton(template.capitalize(), callback_data=f"meme_{template}"))
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
    return "🤖 @r1zzert_bot MEGA работает!"

@app.route('/health')
def health():
    return "OK", 200

# ==================== ЖИВЫЕ ОТВЕТЫ ====================
def get_stats_message(user_id):
    user = get_user(user_id)
    if not user:
        return "📊 Статистика пуста"
    
    return f"""
📊 **Твоя статистика**

💬 Сообщений: {user[2]}
🎨 Фото: {user[3]}
🎨 Мемов: {user[4]}
🎤 Голосовых: {user[5]}
💎 Кристаллов: {user[6]}
🖱️ Кликов: {user[12]}
🎲 Побед в рулетке: {user[13]}
🏆 Челленджей: {user[14]}

📅 В боте с: {datetime.fromisoformat(user[7]).strftime('%d.%m.%Y')}
"""

def get_help_message():
    return f"""
❓ **Помощь по боту @r1zzert_bot**

🔥 **ОСНОВНОЕ:**
💬 Чат — общайся с ИИ
🎭 Режимы — меняй стиль (есть психолог!)
🎨 Создать фото — генерация картинок

🎮 **ИГРЫ:**
• Кликер — собирай очки
• Рулетка — угадай число
• Топ игроков — рейтинг

🎨 **МЕМЫ:**
• Выбери шаблон, добавь текст

🎤 **ГОЛОС:**
• Отправь текст → получи голосовое

🏆 **ЧЕЛЛЕНДЖИ:**
• Ежедневные задания
• Награда в кристаллах

💎 **МОНЕТИЗАЦИЯ:**
• 20 кристаллов ежедневно
• Играй и зарабатывай

🔐 Канал: {CHANNEL_USERNAME}
"""

# ==================== КОМАНДЫ ====================
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "друг"
    
    get_user(user_id)
    
    if not check_subscription(user_id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=f"https://t.me/{CHANNEL_USERNAME[1:]}"))
        markup.add(InlineKeyboardButton("✅ Я ПОДПИСАЛСЯ", callback_data="check_sub"))
        bot.send_message(
            message.chat.id,
            f"👋 Привет, {user_name}!\n\n🔒 Подпишись на {CHANNEL_USERNAME}",
            reply_markup=markup
        )
        return
    
    # Ежедневный бонус
    if get_daily_bonus(user_id):
        bot.send_message(message.chat.id, "🎁 **Ежедневный бонус:** +20 кристаллов!")
    
    bot.send_message(
        message.chat.id,
        f"👋 **С возвращением, {user_name}!**\n\n"
        f"💎 Кристаллов: {get_crystals(user_id)}",
        reply_markup=get_main_keyboard()
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    
    if call.data == "check_sub":
        if check_subscription(user_id):
            bot.edit_message_text("✅ Подписка подтверждена!", call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "🎉 Добро пожаловать!", reply_markup=get_main_keyboard())
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
    
    elif call.data == "game_clicker":
        update_stats(user_id, 'click')
        bot.answer_callback_query(call.id, "+1 клик!")
        
        if random.randint(1, 10) == 1:
            add_crystals(user_id, 1, "Бонус в кликере")
            bot.send_message(call.message.chat.id, "🎉 **Ты нашёл кристалл!** +1💎")
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🖱️ Ещё клик", callback_data="game_clicker"))
        markup.add(InlineKeyboardButton("🎲 В рулетку", callback_data="game_roulette"))
        
        bot.edit_message_text(
            f"🖱️ **Кликер**\n\nКликов: {get_user(user_id)[12]}\n💎 Кристаллов: {get_crystals(user_id)}",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
    
    elif call.data == "game_roulette":
        markup = InlineKeyboardMarkup(row_width=5)
        buttons = []
        for i in range(1, 11):
            buttons.append(InlineKeyboardButton(str(i), callback_data=f"roulette_{i}"))
        markup.add(*buttons)
        
        bot.edit_message_text(
            "🎲 **Рулетка**\n\nВыбери число от 1 до 10:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
    
    elif call.data.startswith("roulette_"):
        guess = int(call.data.replace("roulette_", ""))
        number = random.randint(1, 10)
        
        if guess == number:
            add_crystals(user_id, 5, "Победа в рулетке")
            update_stats(user_id, 'roulette_win')
            result = f"🎉 **Победа!** Число {number}\n+5💎"
        else:
            result = f"❌ **Мимо!** Было число {number}"
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎲 Ещё раз", callback_data="game_roulette"))
        markup.add(InlineKeyboardButton("🖱️ В кликер", callback_data="game_clicker"))
        
        bot.edit_message_text(
            f"🎲 **Рулетка**\n\n{result}\n💎 Кристаллов: {get_crystals(user_id)}",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
    
    elif call.data == "game_leaderboard":
        leaders = get_leaderboard()
        text = "🏆 **Топ игроков**\n\n"
        for i, (uid, clicks, wins, crystals, challenges) in enumerate(leaders, 1):
            try:
                user = bot.get_chat_member(uid, uid).user
                name = user.first_name or "Аноним"
                text += f"{i}. {name} — {crystals}💎, {wins}🎲, {challenges}🏆\n"
            except:
                text += f"{i}. Аноним — {crystals}💎\n"
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id)
    
    elif call.data.startswith("meme_"):
        template = call.data.replace("meme_", "")
        bot.edit_message_text(
            f"🎨 Выбран шаблон: {template}\n\nОтправь текст в формате: верхний текст | нижний текст",
            call.message.chat.id,
            call.message.message_id
        )
        bot.register_next_step_handler(call.message, lambda m: process_meme(m, template))

def process_meme(message, template):
    user_id = message.from_user.id
    
    if '|' not in message.text:
        bot.send_message(message.chat.id, "❌ Нужно отправить в формате: верхний текст | нижний текст")
        return
    
    top, bottom = message.text.split('|', 1)
    top = top.strip()
    bottom = bottom.strip()
    
    if spend_crystals(user_id, 5, "Создание мема"):
        meme_url = create_meme(template, top, bottom)
        if meme_url:
            update_stats(user_id, 'meme')
            bot.send_photo(message.chat.id, meme_url, caption=f"🎨 Твой мем")
        else:
            add_crystals(user_id, 5, "Возврат за неудачный мем")
            bot.send_message(message.chat.id, "😕 Не удалось создать мем")
    else:
        bot.send_message(message.chat.id, "❌ Недостаточно кристаллов!")

# ==================== ТЕКСТОВЫЕ СООБЩЕНИЯ ====================
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id
    text = message.text
    
    if not check_subscription(user_id):
        bot.send_message(message.chat.id, "❌ Сначала подпишись!")
        return
    
    # Ежедневный бонус
    if get_daily_bonus(user_id):
        bot.send_message(message.chat.id, "🎁 **Ежедневный бонус:** +20 кристаллов!")
    
    if text == "💬 Чат":
        bot.send_message(message.chat.id, "💬 **Давай поболтаем!**")
    
    elif text == "🎨 Создать фото":
        if spend_crystals(user_id, 10, "Генерация фото"):
            bot.send_message(message.chat.id, "✏️ **Напиши промпт для фото:**")
            bot.register_next_step_handler(message, process_image)
        else:
            bot.send_message(message.chat.id, "❌ Недостаточно кристаллов! Нужно 10💎")
    
    elif text == "🎭 Режимы":
        bot.send_message(
            message.chat.id,
            "🎭 **Выбери режим:**\n✅ отмечен текущий",
            reply_markup=get_modes_keyboard(user_id)
        )
    
    elif text == "🎮 Игры":
        bot.send_message(message.chat.id, "🎮 **Выбери игру:**", reply_markup=get_games_keyboard())
    
    elif text == "🎨 Создать мем":
        bot.send_message(message.chat.id, "🎨 **Выбери шаблон мема:**", reply_markup=get_meme_templates_keyboard())
    
    elif text == "🎤 Голос":
        if spend_crystals(user_id, 5, "Голосовое сообщение"):
            bot.send_message(message.chat.id, "✏️ **Напиши текст для озвучки:**")
            bot.register_next_step_handler(message, process_voice)
        else:
            bot.send_message(message.chat.id, "❌ Недостаточно кристаллов! Нужно 5💎")
    
    elif text == "🏆 Челлендж":
        challenge = get_todays_challenge()
        if challenge:
            cid, title, desc, reward = challenge
            if not check_challenge_completed(user_id, cid):
                bot.send_message(
                    message.chat.id,
                    f"🏆 **Ежедневный челлендж**\n\n**{title}**\n{desc}\n\nНаграда: {reward}💎"
                )
            else:
                bot.send_message(message.chat.id, "✅ Ты уже выполнил сегодняшний челлендж!")
        else:
            bot.send_message(message.chat.id, "😕 Нет активного челленджа")
    
    elif text == "💎 Кристаллы":
        bot.send_message(
            message.chat.id,
            f"💎 **Твои кристаллы:** {get_crystals(user_id)}\n\n"
            f"🎁 Ежедневный бонус: +20\n"
            f"🎲 Игры: до +5 за раунд\n"
            f"🏆 Челлендж: +15\n\n"
            f"Трата:\n"
            f"🎨 Фото: 10💎\n"
            f"🎨 Мем: 5💎\n"
            f"🎤 Голос: 5💎"
        )
    
    elif text == "📊 Статистика":
        bot.send_message(message.chat.id, get_stats_message(user_id))
    
    elif text == "🏅 Топ игроков":
        leaders = get_leaderboard()
        text = "🏆 **Топ игроков**\n\n"
        for i, (uid, clicks, wins, crystals, challenges) in enumerate(leaders, 1):
            try:
                user = bot.get_chat_member(uid, uid).user
                name = user.first_name or "Аноним"
                text += f"{i}. {name} — {crystals}💎, {wins}🎲, {challenges}🏆\n"
            except:
                text += f"{i}. Аноним — {crystals}💎\n"
        bot.send_message(message.chat.id, text)
    
    elif text == "❓ Помощь":
        bot.send_message(message.chat.id, get_help_message())
    
    else:
        bot.send_chat_action(message.chat.id, 'typing')
        
        mode = get_user_mode(user_id)
        system_prompt = MODES[mode]['prompt']
        answer = ask_groq(text, system_prompt)
        
        if answer:
            update_stats(user_id, 'message')
            bot.send_message(message.chat.id, answer)
            
            challenge = get_todays_challenge()
            if challenge and not check_challenge_completed(user_id, challenge[0]):
                if challenge[1] == "Поговори с психологом" and mode == "psychologist":
                    complete_challenge(user_id, challenge[0], challenge[3])
                    bot.send_message(message.chat.id, f"🏆 **Челлендж выполнен!** +{challenge[3]}💎")
        else:
            bot.send_message(message.chat.id, random.choice(["😕 Ошибка", "😕 Попробуй ещё"]))

def process_image(message):
    user_id = message.from_user.id
    prompt = message.text
    
    bot.send_chat_action(message.chat.id, 'upload_photo')
    bot.send_message(message.chat.id, "🎨 **Генерирую фото...**")
    
    image_url = generate_real_image(prompt)
    
    if image_url:
        update_stats(user_id, 'image')
        bot.send_photo(message.chat.id, image_url, caption=f"🎨 Промпт: {prompt}")
    else:
        add_crystals(user_id, 10, "Возврат за неудачную генерацию")
        bot.send_message(message.chat.id, "😕 Не удалось сгенерировать фото")

def process_voice(message):
    user_id = message.from_user.id
    text = message.text
    
    bot.send_chat_action(message.chat.id, 'record_voice')
    bot.send_message(message.chat.id, "🎤 **Генерирую голос...**")
    
    voice_url = text_to_speech(text)
    
    if voice_url:
        update_stats(user_id, 'voice')
        bot.send_voice(message.chat.id, voice_url)
    else:
        add_crystals(user_id, 5, "Возврат за неудачную озвучку")
        bot.send_message(message.chat.id, "😕 Не удалось создать голос")

# ==================== ЗАПУСК ====================
if __name__ == '__main__':
    logger.info("🚀 Запуск MEGA AI с админкой...")
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"https://r1zzert-bot.onrender.com/webhook")
    logger.info("✅ Вебхук установлен")
    app.run(host='0.0.0.0', port=PORT)
