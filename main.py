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
import qrcode
from io import BytesIO

# ==================== НАСТРОЙКИ ====================
TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME', '@r1zzert')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
HF_TOKEN = os.environ.get('HF_TOKEN')
STABILITY_API_KEY = os.environ.get('STABILITY_API_KEY', '')
PORT = int(os.environ.get('PORT', 10000))

# 👑 ТВОЙ ID (АДМИН)
ADMIN_IDS = [1783230843]  # @Kotmff
SUPPORT_GROUP_ID = -1002424512894  # Группа поддержки

DONATE_URL = "https://dalink.to/r1zzert"  # Твоя ссылка для доната

if not TOKEN or not OPENROUTER_API_KEY:
    print("❌ Ошибка: не все переменные окружения заданы!")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ==================== БАЗА ДАННЫХ ====================
def init_database():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    # Пользователи
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            messages_count INTEGER DEFAULT 0,
            images_generated INTEGER DEFAULT 0,
            videos_generated INTEGER DEFAULT 0,
            crystals INTEGER DEFAULT 50,
            joined_date TIMESTAMP,
            last_active TIMESTAMP,
            last_daily TIMESTAMP,
            clicks INTEGER DEFAULT 0,
            roulette_wins INTEGER DEFAULT 0,
            casino_wins INTEGER DEFAULT 0,
            casino_losses INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT 0,
            referrals_count INTEGER DEFAULT 0,
            username TEXT,
            first_name TEXT
        )
    ''')
    
    # История диалогов (для памяти ИИ)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp TIMESTAMP
        )
    ''')
    
    # Транзакции
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            reason TEXT,
            created_at TIMESTAMP
        )
    ''')
    
    # Настройки голоса
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS voice_settings (
            user_id INTEGER PRIMARY KEY,
            voice TEXT DEFAULT 'male'
        )
    ''')
    
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

def update_stats(user_id, stat_type, amount=1):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET last_active = ? WHERE user_id = ?', (datetime.now(), user_id))
    
    if stat_type == 'message':
        cursor.execute('UPDATE users SET messages_count = messages_count + ? WHERE user_id = ?', (amount, user_id))
    elif stat_type == 'image':
        cursor.execute('UPDATE users SET images_generated = images_generated + ? WHERE user_id = ?', (amount, user_id))
    elif stat_type == 'video':
        cursor.execute('UPDATE users SET videos_generated = videos_generated + ? WHERE user_id = ?', (amount, user_id))
    elif stat_type == 'click':
        cursor.execute('UPDATE users SET clicks = clicks + ? WHERE user_id = ?', (amount, user_id))
    elif stat_type == 'roulette_win':
        cursor.execute('UPDATE users SET roulette_wins = roulette_wins + ? WHERE user_id = ?', (amount, user_id))
    elif stat_type == 'casino_win':
        cursor.execute('UPDATE users SET casino_wins = casino_wins + ? WHERE user_id = ?', (amount, user_id))
    elif stat_type == 'casino_loss':
        cursor.execute('UPDATE users SET casino_losses = casino_losses + ? WHERE user_id = ?', (amount, user_id))
    
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
    
    # Если есть реферер, начисляем ему бонус (10% от доната)
    cursor.execute('SELECT referrer_id FROM users WHERE user_id = ?', (user_id,))
    referrer = cursor.fetchone()
    if referrer and referrer[0] and amount > 0:
        bonus = amount // 10
        if bonus > 0:
            cursor.execute('UPDATE users SET crystals = crystals + ? WHERE user_id = ?', (bonus, referrer[0]))
            cursor.execute('''
                INSERT INTO transactions (user_id, amount, reason, created_at)
                VALUES (?, ?, ?, ?)
            ''', (referrer[0], bonus, f"Бонус за реферала {user_id}", datetime.now()))
    
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
    result = cursor.fetchone()
    if not result:
        conn.close()
        return False
    
    last_daily = result[0]
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

def save_conversation(user_id, role, content):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    # Оставляем только последние 20 сообщений
    cursor.execute('''
        DELETE FROM conversations 
        WHERE id NOT IN (
            SELECT id FROM conversations 
            WHERE user_id = ? 
            ORDER BY timestamp DESC 
            LIMIT 20
        ) AND user_id = ?
    ''', (user_id, user_id))
    
    cursor.execute('''
        INSERT INTO conversations (user_id, role, content, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (user_id, role, content, datetime.now()))
    
    conn.commit()
    conn.close()

def get_conversation_history(user_id, limit=10):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT role, content FROM conversations 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT ?
    ''', (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    
    messages = []
    for role, content in reversed(rows):
        messages.append({"role": role, "content": content})
    return messages

def get_voice_setting(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT voice FROM voice_settings WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 'male'

def set_voice_setting(user_id, voice):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO voice_settings (user_id, voice) VALUES (?, ?)', (user_id, voice))
    conn.commit()
    conn.close()

def get_leaderboard():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, crystals, clicks, roulette_wins, casino_wins, casino_losses, referrals_count
        FROM users ORDER BY crystals DESC LIMIT 10
    ''')
    leaders = cursor.fetchall()
    conn.close()
    return leaders

def get_all_users():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    users = cursor.fetchall()
    conn.close()
    return [user[0] for user in users]

def get_total_users_count():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_stats(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT messages_count, images_generated, videos_generated, crystals, clicks,
               roulette_wins, casino_wins, casino_losses, referrals_count, joined_date
        FROM users WHERE user_id = ?
    ''', (user_id,))
    stats = cursor.fetchone()
    conn.close()
    return stats

def set_referrer(user_id, referrer_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET referrer_id = ? WHERE user_id = ?', (referrer_id, user_id))
    cursor.execute('UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ?', (referrer_id,))
    conn.commit()
    conn.close()

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
def check_subscription(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

# ==================== ИИ С ПАМЯТЬЮ (OPENROUTER) ====================
def ask_openrouter(user_id, message):
    try:
        history = get_conversation_history(user_id, 10)
        
        messages = [{"role": "system", "content": "Ты дружелюбный и умный ассистент по имени R1ZZERT. Отвечай как человек, поддерживай диалог, помни что обсуждали ранее. Будь полезным и креативным."}]
        
        for role, content in history:
            messages.append({"role": role, "content": content})
        
        messages.append({"role": "user", "content": message})
        
        save_conversation(user_id, "user", message)
        
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://r1zzert-bot.onrender.com",
            "X-Title": "R1ZZERT Bot"
        }
        data = {
            "model": "openai/gpt-4o-mini",  # Бесплатная модель
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": 1000
        }
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            answer = result['choices'][0]['message']['content']
            save_conversation(user_id, "assistant", answer)
            return answer
        else:
            logger.error(f"OpenRouter ошибка {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return None

# ==================== ГЕНЕРАЦИЯ ФОТО ====================
def generate_image(prompt):
    try:
        # Сначала пробуем Stability AI
        if STABILITY_API_KEY:
            response = requests.post(
                "https://api.stability.ai/v2beta/stable-image/generate/core",
                headers={
                    "authorization": f"Bearer {STABILITY_API_KEY}",
                    "accept": "image/*"
                },
                files={"none": ''},
                data={
                    "prompt": prompt,
                    "output_format": "png",
                    "aspect_ratio": "1:1"
                },
                timeout=30
            )
            
            if response.status_code == 200:
                image_path = f"/tmp/image_{int(time.time())}.png"
                with open(image_path, 'wb') as f:
                    f.write(response.content)
                return image_path
        
        # Запасной вариант через Pollinations
        encoded = urllib.parse.quote(prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
        return image_url
    except:
        return None

# ==================== ГЕНЕРАЦИЯ ВИДЕО ====================
def generate_video(prompt):
    try:
        API_URL = "https://api-inference.huggingface.co/models/ali-vilab/text-to-video-ms-1.7b"
        headers = {"Authorization": f"Bearer {HF_TOKEN}"}
        
        response = requests.post(
            API_URL,
            headers=headers,
            json={"inputs": prompt},
            timeout=60
        )
        
        if response.status_code == 200:
            video_path = f"/tmp/video_{int(time.time())}.mp4"
            with open(video_path, 'wb') as f:
                f.write(response.content)
            return video_path
        return None
    except Exception as e:
        logger.error(f"Ошибка видео: {e}")
        return None

# ==================== ГОЛОС (TTS) ====================
def text_to_speech(text, voice='male'):
    voices = {
        'male': 'ru-RU-DmitryNeural',      # Мужской
        'female': 'ru-RU-SvetlanaNeural',   # Женский
        'robot': 'ru-RU-CatherineNeural',    # Роботизированный
        'child': 'ru-RU-AnnaNeural',         # Детский
        'zэцтел': 'ru-RU-MarinaNeural'       # Zэцтел стиль
    }
    voice_name = voices.get(voice, 'ru-RU-DmitryNeural')
    try:
        url = f"https://api.streamelements.com/kappa/v2/speech?voice={voice_name}&text={urllib.parse.quote(text)}"
        return url
    except:
        return None

# ==================== QR-КОД ДЛЯ ДОНАТА ====================
def generate_qr_code(url):
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        bio = BytesIO()
        bio.name = 'qr.png'
        img.save(bio, 'PNG')
        bio.seek(0)
        return bio
    except:
        return None

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        KeyboardButton("🎨 Фото"),
        KeyboardButton("🎬 Видео"),
        KeyboardButton("🎤 Голос"),
        KeyboardButton("🎮 Игры"),
        KeyboardButton("💰 Донат"),
        KeyboardButton("📊 Статистика"),
        KeyboardButton("🔗 Рефералка"),
        KeyboardButton("❓ Помощь")
    ]
    
    if is_admin(user_id):
        buttons.append(KeyboardButton("👑 Админка"))
    
    markup.add(*buttons)
    return markup

def get_voice_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("👨 Мужской", callback_data="voice_male"),
        InlineKeyboardButton("👩 Женский", callback_data="voice_female"),
        InlineKeyboardButton("🤖 Робот", callback_data="voice_robot"),
        InlineKeyboardButton("🧒 Детский", callback_data="voice_child"),
        InlineKeyboardButton("👾 Zэцтел", callback_data="voice_zэцтел")
    )
    return markup

def get_games_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎰 Казино", callback_data="game_casino"),
        InlineKeyboardButton("🖱️ Кликер", callback_data="game_clicker"),
        InlineKeyboardButton("🎲 Рулетка", callback_data="game_roulette")
    )
    return markup

def get_casino_bet_keyboard():
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("10💎", callback_data="casino_10"),
        InlineKeyboardButton("25💎", callback_data="casino_25"),
        InlineKeyboardButton("50💎", callback_data="casino_50"),
        InlineKeyboardButton("100💎", callback_data="casino_100"),
        InlineKeyboardButton("❌ Назад", callback_data="game_back")
    )
    return markup

def get_casino_number_keyboard(bet):
    markup = InlineKeyboardMarkup(row_width=3)
    buttons = []
    for i in range(1, 7):
        buttons.append(InlineKeyboardButton(str(i), callback_data=f"casino_num_{bet}_{i}"))
    markup.add(*buttons)
    markup.add(InlineKeyboardButton("❌ Назад", callback_data="game_back"))
    return markup

def get_donate_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("✅ Я задонатил", callback_data="donate_done")
    )
    return markup

def get_admin_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 Общая стата", callback_data="admin_stats"),
        InlineKeyboardButton("💎 Начислить", callback_data="admin_add_crystals"),
        InlineKeyboardButton("🎁 Бонус всем", callback_data="admin_bonus_all"),
        InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
        InlineKeyboardButton("🔍 Найти юзера", callback_data="admin_find_user"),
        InlineKeyboardButton("📦 Транзакции", callback_data="admin_transactions"),
        InlineKeyboardButton("🎮 Игры стата", callback_data="admin_games"),
        InlineKeyboardButton("💰 Донаты", callback_data="admin_donates")
    )
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

# ==================== КОМАНДЫ ====================
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "друг"
    
    # Проверка реферала
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id != user_id:
            set_referrer(user_id, referrer_id)
            add_crystals(referrer_id, 50, f"Реферал {user_id}")
            add_crystals(user_id, 20, "Бонус за регистрацию по рефералке")
            bot.send_message(referrer_id, f"🎉 По твоей рефералке зарегистрировался {user_name}! +50💎")
    
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
        bot.send_message(message.chat.id, "🎁 **Ежедневный бонус:** +20💎")
    
    bot.send_message(
        message.chat.id,
        f"👋 **С возвращением, {user_name}!**\n\n"
        f"💎 Кристаллов: {get_crystals(user_id)}\n\n"
        f"Я — твой умный ИИ помощник с памятью. Просто общайся со мной!",
        reply_markup=get_main_keyboard(user_id)
    )

@bot.message_handler(commands=['ref'])
def ref_command(message):
    user_id = message.from_user.id
    ref_link = f"https://t.me/{bot.get_me().username}?start={user_id}"
    bot.send_message(
        message.chat.id,
        f"🔗 **Твоя реферальная ссылка:**\n`{ref_link}`\n\n"
        f"За каждого приглашенного друга ты получишь 50💎, а друг 20💎",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['admin'])
def admin_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Ты не админ")
        return
    
    bot.send_message(
        message.chat.id,
        "👑 **Панель администратора**",
        reply_markup=get_admin_keyboard()
    )

@bot.message_handler(commands=['clear'])
def clear_history(message):
    user_id = message.from_user.id
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM conversations WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    bot.reply_to(message, "🧠 **История диалога очищена!**")

# ==================== КОЛЛБЭКИ ====================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    
    if call.data == "check_sub":
        if check_subscription(user_id):
            bot.edit_message_text("✅ Подписка подтверждена!", call.message.chat.id, call.message.message_id)
            bot.send_message(
                call.message.chat.id,
                f"🎉 Добро пожаловать!\n💎 Кристаллов: {get_crystals(user_id)}",
                reply_markup=get_main_keyboard(user_id)
            )
        else:
            bot.answer_callback_query(call.id, "❌ Не подписан!", show_alert=True)
    
    # Голос
    elif call.data.startswith("voice_"):
        voice = call.data.replace("voice_", "")
        set_voice_setting(user_id, voice)
        bot.answer_callback_query(call.id, f"Голос изменён на {voice}")
        bot.edit_message_text(
            f"✅ Голос установлен: {voice}",
            call.message.chat.id,
            call.message.message_id
        )
    
    # Игры
    elif call.data == "game_casino":
        bot.edit_message_text(
            "🎰 **Казино**\n\nВыбери ставку:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_casino_bet_keyboard()
        )
    
    elif call.data.startswith("casino_"):
        if call.data == "casino_back":
            bot.edit_message_text(
                "🎮 **Игры**",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=get_games_keyboard()
            )
            return
        
        if call.data.count('_') == 1:
            bet = int(call.data.replace("casino_", ""))
            if get_crystals(user_id) < bet:
                bot.answer_callback_query(call.id, "❌ Недостаточно кристаллов!", show_alert=True)
                return
            bot.edit_message_text(
                f"🎰 Ставка: {bet}💎\n\nВыбери число от 1 до 6:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=get_casino_number_keyboard(bet)
            )
        else:
            parts = call.data.split('_')
            bet = int(parts[2])
            guess = int(parts[3])
            number = random.randint(1, 6)
            
            if guess == number:
                win = bet * 3
                spend_crystals(user_id, bet, "Ставка в казино")
                add_crystals(user_id, win, "Выигрыш в казино")
                update_stats(user_id, 'casino_win')
                result = f"🎉 **Ты выиграл!** Число {number}\n+{win}💎"
            else:
                spend_crystals(user_id, bet, "Ставка в казино")
                update_stats(user_id, 'casino_loss')
                result = f"❌ **Проигрыш!** Было число {number}\n-{bet}💎"
            
            bot.edit_message_text(
                f"🎰 **Казино**\n\n{result}\n\n💎 Кристаллов: {get_crystals(user_id)}",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=get_games_keyboard()
            )
    
    elif call.data == "game_clicker":
        update_stats(user_id, 'click')
        if random.randint(1, 10) == 1:
            add_crystals(user_id, 1, "Бонус в кликере")
            bot.answer_callback_query(call.id, "🎉 +1💎")
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🖱️ Ещё клик", callback_data="game_clicker"))
        markup.add(InlineKeyboardButton("🎮 Другие игры", callback_data="game_back"))
        
        bot.edit_message_text(
            f"🖱️ **Кликер**\n\nКликов: {get_user(user_id)[8]}\n💎: {get_crystals(user_id)}",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
    
    elif call.data == "game_roulette":
        markup = InlineKeyboardMarkup(row_width=5)
        buttons = [InlineKeyboardButton(str(i), callback_data=f"roulette_{i}") for i in range(1, 11)]
        markup.add(*buttons)
        markup.add(InlineKeyboardButton("❌ Назад", callback_data="game_back"))
        
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
        
        bot.edit_message_text(
            f"🎲 **Рулетка**\n\n{result}\n💎: {get_crystals(user_id)}",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_games_keyboard()
        )
    
    elif call.data == "game_back":
        bot.edit_message_text(
            "🎮 **Игры**",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_games_keyboard()
        )
    
    # Донат
    elif call.data == "donate_done":
        user_info = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
        admin_text = f"💰 **Донат от {user_info}**\nСумма: неизвестно (нажми кнопку чтобы ввести)\nСсылка: {DONATE_URL}"
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("💎 Начислить кристаллы", callback_data=f"donate_pay_{user_id}"))
        
        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, admin_text, reply_markup=markup)
        
        if SUPPORT_GROUP_ID:
            bot.send_message(SUPPORT_GROUP_ID, admin_text, reply_markup=markup)
        
        bot.answer_callback_query(call.id, "✅ Сообщение отправлено администратору")
        bot.send_message(
            call.message.chat.id,
            "✅ Сообщение о донате отправлено! Администратор скоро начислит кристаллы."
        )
    
    elif call.data.startswith("donate_pay_"):
        target_id = int(call.data.replace("donate_pay_", ""))
        msg = bot.send_message(
            call.message.chat.id,
            f"✏️ Введи сумму в рублях для пользователя {target_id} (1₽ = 1💎):"
        )
        bot.register_next_step_handler(msg, lambda m: process_donate_payment(m, target_id))
    
    # Админские коллбэки
    elif call.data.startswith("admin_") and is_admin(user_id):
        if call.data == "admin_stats":
            total_users = get_total_users_count()
            total_crystals = 0
            conn = sqlite3.connect('bot_database.db')
            cursor = conn.cursor()
            cursor.execute('SELECT SUM(crystals) FROM users')
            total_crystals = cursor.fetchone()[0] or 0
            conn.close()
            
            bot.edit_message_text(
                f"📊 **Общая статистика**\n\n"
                f"👥 Всего пользователей: {total_users}\n"
                f"💎 Всего кристаллов: {total_crystals}\n"
                f"👑 Админов: {len(ADMIN_IDS)}",
                call.message.chat.id,
                call.message.message_id
            )
        
        elif call.data == "admin_add_crystals":
            bot.edit_message_text(
                "✏️ Введи ID пользователя и количество кристаллов через пробел\nПример: `1783230843 100`",
                call.message.chat.id,
                call.message.message_id
            )
            bot.register_next_step_handler(call.message, process_admin_add_crystals)
        
        elif call.data == "admin_bonus_all":
            bot.edit_message_text(
                "✏️ Введи количество кристаллов для всех пользователей:",
                call.message.chat.id,
                call.message.message_id
            )
            bot.register_next_step_handler(call.message, process_admin_bonus_all)
        
        elif call.data == "admin_broadcast":
            bot.edit_message_text(
                "📢 Отправь сообщение для рассылки всем пользователям:",
                call.message.chat.id,
                call.message.message_id
            )
            bot.register_next_step_handler(call.message, process_admin_broadcast)
        
        elif call.data == "admin_find_user":
            bot.edit_message_text(
                "🔍 Введи ID пользователя или @username:",
                call.message.chat.id,
                call.message.message_id
            )
            bot.register_next_step_handler(call.message, process_admin_find_user)
        
        elif call.data == "admin_transactions":
            conn = sqlite3.connect('bot_database.db')
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM transactions 
                ORDER BY created_at DESC LIMIT 20
            ''')
            transactions = cursor.fetchall()
            conn.close()
            
            text = "📦 **Последние 20 транзакций**\n\n"
            for t in transactions:
                text += f"• {t[4][:16]}: {t[1]} → {t[2]}💎 ({t[3][:20]})\n"
            
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id)
        
        elif call.data == "admin_games":
            conn = sqlite3.connect('bot_database.db')
            cursor = conn.cursor()
            cursor.execute('''
                SELECT SUM(clicks), SUM(roulette_wins), SUM(casino_wins), SUM(casino_losses)
                FROM users
            ''')
            stats = cursor.fetchone()
            conn.close()
            
            bot.edit_message_text(
                f"🎮 **Игровая статистика**\n\n"
                f"🖱️ Всего кликов: {stats[0] or 0}\n"
                f"🎲 Побед в рулетке: {stats[1] or 0}\n"
                f"🎰 Побед в казино: {stats[2] or 0}\n"
                f"❌ Проигрышей в казино: {stats[3] or 0}",
                call.message.chat.id,
                call.message.message_id
            )
        
        elif call.data == "admin_donates":
            conn = sqlite3.connect('bot_database.db')
            cursor = conn.cursor()
            cursor.execute('''
                SELECT SUM(amount) FROM transactions WHERE reason LIKE '%Донат%' AND amount > 0
            ''')
            total_donates = cursor.fetchone()[0] or 0
            conn.close()
            
            bot.edit_message_text(
                f"💰 **Донаты**\n\n"
                f"💎 Всего начислено кристаллов за донаты: {total_donates}",
                call.message.chat.id,
                call.message.message_id
            )

def process_donate_payment(message, target_id):
    try:
        amount = int(message.text)
        add_crystals(target_id, amount, f"Донат от админа {message.from_user.id}")
        
        bot.send_message(target_id, f"💰 Вам начислено {amount}💎 за донат! Спасибо за поддержку!")
        bot.send_message(message.chat.id, f"✅ Пользователю {target_id} начислено {amount}💎")
        
        if SUPPORT_GROUP_ID:
            bot.send_message(SUPPORT_GROUP_ID, f"💰 Админ начислил {amount}💎 пользователю {target_id}")
    except:
        bot.send_message(message.chat.id, "❌ Введи число!")

def process_admin_add_crystals(message):
    try:
        target_id, amount = map(int, message.text.split())
        add_crystals(target_id, amount, f"Начислено админом {message.from_user.id}")
        bot.send_message(message.chat.id, f"✅ Пользователю {target_id} начислено {amount}💎")
        
        if SUPPORT_GROUP_ID:
            bot.send_message(SUPPORT_GROUP_ID, f"💎 Админ начислил {amount}💎 пользователю {target_id}")
    except:
        bot.send_message(message.chat.id, "❌ Неверный формат. Используй: `ID количество`")

def process_admin_bonus_all(message):
    try:
        amount = int(message.text)
        users = get_all_users()
        total = len(users)
        
        status_msg = bot.send_message(
            message.chat.id,
            f"🎁 Начинаю выдачу бонуса...\n0/{total}"
        )
        
        for i, user_id in enumerate(users):
            add_crystals(user_id, amount, f"Бонус всем от админа {message.from_user.id}")
            if (i + 1) % 10 == 0:
                bot.edit_message_text(
                    f"🎁 Выдача бонуса...\n{i + 1}/{total}",
                    status_msg.chat.id,
                    status_msg.message_id
                )
        
        bot.edit_message_text(
            f"✅ {total} пользователей получили +{amount}💎",
            status_msg.chat.id,
            status_msg.message_id
        )
        
        if SUPPORT_GROUP_ID:
            bot.send_message(SUPPORT_GROUP_ID, f"🎁 Админ выдал бонус {amount}💎 всем пользователям")
    except:
        bot.send_message(message.chat.id, "❌ Введи число!")

def process_admin_broadcast(message):
    users = get_all_users()
    total = len(users)
    successful = 0
    
    status_msg = bot.send_message(
        message.chat.id,
        f"📢 Начинаю рассылку...\n0/{total}"
    )
    
    for i, user_id in enumerate(users):
        try:
            bot.copy_message(user_id, message.chat.id, message.message_id)
            successful += 1
        except:
            pass
        
        if (i + 1) % 10 == 0:
            bot.edit_message_text(
                f"📢 Рассылка...\n{i + 1}/{total}",
                status_msg.chat.id,
                status_msg.message_id
            )
    
    bot.edit_message_text(
        f"✅ Рассылка завершена!\nУспешно: {successful}/{total}",
        status_msg.chat.id,
        status_msg.message_id
    )
    
    if SUPPORT_GROUP_ID:
        bot.send_message(SUPPORT_GROUP_ID, f"📢 Админ сделал рассылку. Успешно: {successful}/{total}")

def process_admin_find_user(message):
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
        text += f"💬 Сообщений: {user[1]}\n"
        text += f"🎨 Фото: {user[2]}\n"
        text += f"🎬 Видео: {user[3]}\n"
        text += f"💎 Кристаллов: {user[4]}\n"
        text += f"📅 В боте с: {user[5][:10]}\n"
        text += f"🖱️ Кликов: {user[8]}\n"
        text += f"🎲 Побед в рулетке: {user[9]}\n"
        text += f"🎰 Побед в казино: {user[10]}\n"
        text += f"❌ Проигрышей: {user[11]}\n"
        text += f"👥 Рефералов: {user[13]}"
        
        bot.send_message(message.chat.id, text)
    else:
        bot.send_message(message.chat.id, "❌ Пользователь не найден")

# ==================== ТЕКСТОВЫЕ СООБЩЕНИЯ ====================
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id
    text = message.text
    
    # Отправляем копию в группу поддержки (кроме админских команд)
    if SUPPORT_GROUP_ID and not text.startswith('/') and user_id not in ADMIN_IDS:
        try:
            user_info = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
            bot.send_message(
                SUPPORT_GROUP_ID,
                f"📩 **Сообщение от {user_info}**\n\n{text}"
            )
        except:
            pass
    
    if not check_subscription(user_id):
        bot.send_message(message.chat.id, "❌ Сначала подпишись!")
        return
    
    # Ежедневный бонус
    if get_daily_bonus(user_id):
        bot.send_message(message.chat.id, "🎁 **Ежедневный бонус:** +20💎")
    
    if text == "🎨 Фото":
        if spend_crystals(user_id, 10, "Генерация фото"):
            bot.send_message(message.chat.id, "✏️ **Напиши промпт для фото:**")
            bot.register_next_step_handler(message, process_image)
        else:
            bot.send_message(message.chat.id, "❌ Недостаточно кристаллов! Нужно 10💎")
    
    elif text == "🎬 Видео":
        if spend_crystals(user_id, 20, "Генерация видео"):
            bot.send_message(message.chat.id, "✏️ **Напиши промпт для видео:**")
            bot.register_next_step_handler(message, process_video)
        else:
            bot.send_message(message.chat.id, "❌ Недостаточно кристаллов! Нужно 20💎")
    
    elif text == "🎤 Голос":
        bot.send_message(
            message.chat.id,
            "🎤 **Выбери голос:**",
            reply_markup=get_voice_keyboard()
        )
        bot.register_next_step_handler(message, process_voice_text)
    
    elif text == "🎮 Игры":
        bot.send_message(message.chat.id, "🎮 **Выбери игру:**", reply_markup=get_games_keyboard())
    
    elif text == "💰 Донат":
        qr = generate_qr_code(DONATE_URL)
        if qr:
            bot.send_photo(
                message.chat.id,
                qr,
                caption=f"💰 **Поддержать проект**\n\n"
                        f"1. Переведи любую сумму по ссылке или QR-коду\n"
                        f"2. Нажми кнопку «✅ Я задонатил»\n"
                        f"3. Администратор начислит тебе кристаллы (1₽ = 1💎)\n\n"
                        f"Ссылка: {DONATE_URL}",
                reply_markup=get_donate_keyboard()
            )
        else:
            bot.send_message(
                message.chat.id,
                f"💰 **Поддержать проект**\n\n"
                f"Ссылка для доната: {DONATE_URL}\n\n"
                f"После доната нажми кнопку ниже:",
                reply_markup=get_donate_keyboard()
            )
    
    elif text == "📊 Статистика":
        stats = get_stats(user_id)
        if stats:
            joined = datetime.fromisoformat(stats[9]).strftime('%d.%m.%Y')
            msg = f"📊 **Твоя статистика**\n\n"
            msg += f"💬 Сообщений: {stats[0]}\n"
            msg += f"🎨 Фото: {stats[1]}\n"
            msg += f"🎬 Видео: {stats[2]}\n"
            msg += f"💎 Кристаллов: {stats[3]}\n"
            msg += f"🖱️ Кликов: {stats[4]}\n"
            msg += f"🎲 Побед в рулетке: {stats[5]}\n"
            msg += f"🎰 Побед в казино: {stats[6]}\n"
            msg += f"❌ Проигрышей в казино: {stats[7]}\n"
            msg += f"👥 Рефералов: {stats[8]}\n"
            msg += f"📅 В боте с: {joined}"
            bot.send_message(message.chat.id, msg)
        else:
            bot.send_message(message.chat.id, "📊 Статистика пуста")
    
    elif text == "🔗 Рефералка":
        ref_link = f"https://t.me/{bot.get_me().username}?start={user_id}"
        bot.send_message(
            message.chat.id,
            f"🔗 **Твоя реферальная ссылка:**\n`{ref_link}`\n\n"
            f"За каждого друга ты получишь 50💎, а друг 20💎",
            parse_mode="Markdown"
        )
    
    elif text == "❓ Помощь":
        help_text = f"""
❓ **Помощь по боту @r1zzert_bot**

🔥 **ОСНОВНОЕ:**
Просто общайся со мной — я умный ИИ с памятью!
Я помню историю диалога и обращаюсь по имени.

🎨 **Фото:** генерация картинок (10💎)
🎬 **Видео:** генерация видео (20💎)
🎤 **Голос:** озвучка текста разными голосами (бесплатно)

🎮 **ИГРЫ:**
• 🎰 Казино — угадай число 1-6, выигрыш x3
• 🖱️ Кликер — собирай очки и кристаллы
• 🎲 Рулетка — угадай число 1-10, выигрыш x2

💰 **ДОНАТ:**
Поддержи проект и получи кристаллы (1₽ = 1💎)

🔗 **РЕФЕРАЛКА:**
Приглашай друзей и получай 50💎 за каждого

🔐 **Канал:** {CHANNEL_USERNAME}
"""
        bot.send_message(message.chat.id, help_text)
    
    elif text == "👑 Админка" and is_admin(user_id):
        bot.send_message(
            message.chat.id,
            "👑 **Панель администратора**",
            reply_markup=get_admin_keyboard()
        )
    
    else:
        # Обычный диалог с ИИ
        bot.send_chat_action(message.chat.id, 'typing')
        answer = ask_openrouter(user_id, text)
        
        if answer:
            update_stats(user_id, 'message')
            bot.send_message(message.chat.id, answer)
        else:
            bot.send_message(message.chat.id, "😕 Ошибка связи с ИИ. Попробуй позже.")

def process_voice_text(message):
    user_id = message.from_user.id
    text = message.text
    
    voice = get_voice_setting(user_id)
    
    bot.send_chat_action(message.chat.id, 'record_voice')
    status_msg = bot.send_message(message.chat.id, "🎤 **Генерирую голос...**")
    
    voice_url = text_to_speech(text, voice)
    
    if voice_url:
        update_stats(user_id, 'voice')
        bot.send_voice(message.chat.id, voice_url)
        bot.delete_message(status_msg.chat.id, status_msg.message_id)
    else:
        bot.edit_message_text("😕 Не удалось создать голос", status_msg.chat.id, status_msg.message_id)

def process_image(message):
    user_id = message.from_user.id
    prompt = message.text
    
    bot.send_chat_action(message.chat.id, 'upload_photo')
    status_msg = bot.send_message(message.chat.id, "🎨 **Генерирую фото...**")
    
    result = generate_image(prompt)
    
    if result:
        update_stats(user_id, 'image')
        if isinstance(result, str) and result.startswith('http'):
            bot.send_photo(message.chat.id, result, caption=f"🎨 Промпт: {prompt}")
        else:
            with open(result, 'rb') as photo:
                bot.send_photo(message.chat.id, photo, caption=f"🎨 Промпт: {prompt}")
            os.remove(result)
        bot.delete_message(status_msg.chat.id, status_msg.message_id)
    else:
        add_crystals(user_id, 10, "Возврат за неудачную генерацию")
        bot.edit_message_text("😕 Не удалось сгенерировать фото", status_msg.chat.id, status_msg.message_id)

def process_video(message):
    user_id = message.from_user.id
    prompt = message.text
    
    bot.send_chat_action(message.chat.id, 'upload_video')
    status_msg = bot.send_message(message.chat.id, "🎬 **Генерирую видео...** Это займёт 1-2 минуты.")
    
    video_path = generate_video(prompt)
    
    if video_path:
        update_stats(user_id, 'video')
        with open(video_path, 'rb') as video:
            bot.send_video(message.chat.id, video, caption=f"🎬 Промпт: {prompt}")
        os.remove(video_path)
        bot.delete_message(status_msg.chat.id, status_msg.message_id)
    else:
        add_crystals(user_id, 20, "Возврат за неудачное видео")
        bot.edit_message_text("😕 Не удалось сгенерировать видео", status_msg.chat.id, status_msg.message_id)

# ==================== ЗАПУСК ====================
if __name__ == '__main__':
    logger.info("🚀 Запуск MEGA AI с памятью...")
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"https://r1zzert-bot.onrender.com/webhook")
    logger.info(f"✅ Вебхук установлен")
    app.run(host='0.0.0.0', port=PORT)
