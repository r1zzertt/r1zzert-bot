import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import requests
import time
import logging
import sqlite3
from datetime import datetime
import hashlib
import threading
from flask import Flask, request
import random

# ==================== НАСТРОЙКИ (ВСЁ ЧЕРЕЗ RENDER) ====================
TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME', '@r1zzert')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
KLING_API_KEY = os.environ.get('KLING_API_KEY')
KLING_SECRET_KEY = os.environ.get('KLING_SECRET_KEY')
PORT = int(os.environ.get('PORT', 10000))

# Проверка наличия ключей
missing_keys = []
if not TOKEN:
    missing_keys.append("BOT_TOKEN")
if not GROQ_API_KEY:
    missing_keys.append("GROQ_API_KEY")
if missing_keys:
    print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Отсутствуют ключи: {', '.join(missing_keys)}")
    print("Добавь их в Environment Variables в Render!")

# Kling ключи опциональны
if not KLING_API_KEY or not KLING_SECRET_KEY:
    print("⚠️ Kling AI ключи не найдены — видео-генерация будет недоступна")

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
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

# ==================== РАБОТА С ИИ (GROQ) ====================
def ask_groq(question, system_prompt):
    if not GROQ_API_KEY:
        return "❌ Groq API ключ не настроен"
    
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        data = {
            "model": "llama3-70b-8192",
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
            return f"😕 Ошибка Groq: {response.status_code}"
    except Exception as e:
        logger.error(f"Ошибка при запросе к Groq: {e}")
        return "😕 Ошибка связи с ИИ"

# ==================== ГЕНЕРАЦИЯ ВИДЕО (KLING) ====================
def generate_video(prompt):
    if not KLING_API_KEY or not KLING_SECRET_KEY:
        return None
    
    try:
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
            "https://api.klingai.com/v1/videos/generations",  # Обновлённый домен
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0 and 'data' in result:
                task_id = result['data']['task_id']
                return check_video_task(task_id)
            else:
                logger.error(f"Kling API ошибка: {result}")
                return None
        else:
            logger.error(f"Kling HTTP ошибка: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Ошибка генерации видео: {e}")
        return None

def check_video_task(task_id):
    headers = {"Authorization": f"Bearer {KLING_API_KEY}"}
    
    for attempt in range(20):
        try:
            response = requests.get(
                f"https://api.klingai.com/v1/videos/generations/{task_id}",
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
    if not GROQ_API_KEY:
        return "❌ Groq API ключ не настроен"
    
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        data = {
            "model": "llama-3.2-11b-vision-preview",
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
        else:
            return None
    except Exception as e:
        logger.error(f"Ошибка генерации: {e}")
        return None

# ==================== РЕЖИМЫ ====================
MODES = {
    "assistant": {"name": "🤵 Обычный помощник", "prompt": "Ты полезный ассистент. Отвечай кратко и по делу."},
    "developer": {"name": "💻 Разработчик", "prompt": "Ты эксперт по программированию. Помогай с кодом, объясняй термины."},
    "writer": {"name": "✍️ Писатель", "prompt": "Ты профессиональный писатель. Помогай с текстами, пиши красиво."},
    "creative": {"name": "🎨 Креативщик", "prompt": "Ты креативный директор. Генерируй идеи, предлагай нестандартные решения."}
}

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("💬 Чат", "🎭 Режимы", "🎨 Фото", "🎬 Видео", "📊 Статистика", "❓ Помощь")
    return markup

def get_modes_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for mode_id, mode_info in MODES.items():
        buttons.append(InlineKeyboardButton(mode_info['name'], callback_data=f"mode_{mode_id}"))
    markup.add(*buttons)
    return markup

def get_video_presets():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌅 Закат на море", callback_data="video_sunset"),
        InlineKeyboardButton("🏙️ Ночной город", callback_data="video_city"),
        InlineKeyboardButton("🚀 Космос", callback_data="video_space"),
        InlineKeyboardButton("🎮 Игровой клип", callback_data="video_game"),
        InlineKeyboardButton("🌊 Океан", callback_data="video_ocean"),
        InlineKeyboardButton("✏️ Свой промпт", callback_data="video_custom")
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
    return "🤖 @r1zzert_bot MEGA AI работает 24/7!"

@app.route('/health')
def health():
    return "OK", 200

# ==================== ЖИВЫЕ ОТВЕТЫ ====================
def get_chat_welcome():
    responses = [
        "💬 **Давай поболтаем!** Спрашивай что хочешь — я отвечу на всё!",
        "💬 **Я слушаю тебя!** Расскажи, что у тебя нового или задай любой вопрос.",
        "💬 **Погнали общаться!** О чём поговорим сегодня?",
        "💬 **Твой личный ИИ-друг онлайн!** Что тебя интересует?"
    ]
    return random.choice(responses)

def get_photo_welcome():
    responses = [
        "🎨 **Опиши картинку своей мечты!** Я создам описание того, что ты хочешь увидеть.",
        "🎨 **Включи воображение!** Напиши, что должно быть на фото.",
        "🎨 **Генератор описаний запущен!** Что будем создавать?",
        "🎨 **Опиши сцену, персонажа или пейзаж** — я представлю это в деталях."
    ]
    return random.choice(responses)

def get_video_welcome():
    responses = [
        "🎬 **Создаём видео!** Выбери готовый сценарий или придумай свой.",
        "🎬 **Твой личный видеорежиссёр!** Что будем снимать?",
        "🎬 **Оживляем идеи!** Выбери пресет или напиши свой промпт.",
        "🎬 **От слов к видео!** Что ты хочешь увидеть на экране?"
    ]
    return random.choice(responses)

def get_stats_message(stats, mode_name):
    if not stats:
        return "📊 **Статистика пока пуста.** Начни общаться, и я всё посчитаю!"
    
    msgs, imgs, vids, joined = stats
    joined_str = datetime.fromisoformat(joined).strftime('%d.%m.%Y')
    return f"📊 **Твоя активность:**\n\n💬 Сообщений: {msgs}\n🎨 Фото: {imgs}\n🎬 Видео: {vids}\n📅 В боте с: {joined_str}\n🎭 Текущий режим: {mode_name}"

def get_help_message():
    return f"""
❓ **Помощь по боту @r1zzert_bot**

🔥 **Что я умею:**

💬 **Чат** — просто общайся со мной на любые темы  
   • Спроси совет, мнение или просто поболтай

🎭 **Режимы** — меняй мой стиль общения  
   • 🤵 Обычный помощник  
   • 💻 Разработчик  
   • ✍️ Писатель  
   • 🎨 Креативщик

🎨 **Фото** — опиши что хочешь увидеть, и я создам детальное описание

🎬 **Видео** — генерация видео по тексту  
   • Выбери готовый сценарий  
   • Или напиши свой промпт  
   • Видео создаётся 1-2 минуты

📊 **Статистика** — твоя активность в боте

🔐 **Подписка**  
   • Бот работает только для подписчиков канала {CHANNEL_USERNAME}  
   • После подписки нажми "✅ Я ПОДПИСАЛСЯ"

📝 **Примеры промптов для видео:**  
   • Закат над океаном, волны набегают на берег  
   • Ночной город, неон, дождь, киберпанк  
   • Космический корабль в туманности

🚀 **Приятного использования!**
"""

def get_mode_changed_message(mode_name):
    responses = [
        f"✅ **Режим изменён на {mode_name}!** Теперь я буду отвечать в этом стиле.",
        f"✅ **Готово!** Теперь я {mode_name}. Спрашивай что угодно!",
        f"✅ **Режим '{mode_name}' активирован.** Чем могу помочь?"
    ]
    return random.choice(responses)

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
            f"👋 Привет, {user_name}!\n\n"
            f"🔒 **Доступ к боту — только для подписчиков канала** {CHANNEL_USERNAME}\n\n"
            f"Подпишись и нажми кнопку ниже:",
            reply_markup=markup
        )
        return
    
    set_user_mode(user_id, 'assistant')
    bot.send_message(
        message.chat.id,
        f"👋 **С возвращением, {user_name}!**\n\n"
        f"🤖 Я — твой личный MEGA AI помощник.\n"
        f"Текущий режим: {MODES['assistant']['name']}\n"
        f"Используй кнопки ниже 👇",
        reply_markup=get_main_keyboard()
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    
    if call.data == "check_sub":
        if check_subscription(user_id):
            bot.edit_message_text(
                "✅ **Подписка подтверждена!**",
                call.message.chat.id,
                call.message.message_id
            )
            bot.send_message(
                call.message.chat.id,
                "🎉 **Добро пожаловать!** Тебе открыты все функции бота.",
                reply_markup=get_main_keyboard()
            )
        else:
            bot.answer_callback_query(
                call.id,
                "❌ Ты ещё не подписался! Подпишись и нажми кнопку ещё раз.",
                show_alert=True
            )
    
    elif call.data.startswith("mode_"):
        mode_id = call.data.replace("mode_", "")
        if mode_id in MODES:
            set_user_mode(user_id, mode_id)
            bot.answer_callback_query(call.id, f"Режим: {MODES[mode_id]['name']}")
            bot.send_message(
                call.message.chat.id,
                get_mode_changed_message(MODES[mode_id]['name']),
                reply_markup=get_main_keyboard()
            )
    
    elif call.data.startswith("video_"):
        presets = {
            "sunset": "Закат над океаном, волны набегают на берег, небо оранжево-розовое, облака, 4K",
            "city": "Ночной мегаполис, неоновые огни, идёт дождь, отражения в лужах, киберпанк",
            "space": "Космический корабль пролетает мимо красивой туманности, звёзды, планеты, эпично",
            "game": "Игровой персонаж в фэнтези мире, магия, эпичная битва, динамичный экшен",
            "ocean": "Подводный мир, коралловый риф, разноцветные рыбки, солнечные лучи",
            "custom": "custom"
        }
        
        preset_key = call.data.replace("video_", "")
        if preset_key == "custom":
            msg = bot.send_message(
                call.message.chat.id,
                "✏️ **Напиши свой промпт для видео**\n\n"
                "Опиши сцену, стиль, настроение. Чем подробнее, тем лучше!\n"
                "Например: *Киберпанк город будущего, летающие машины, дождь, неон*"
            )
            bot.register_next_step_handler(msg, process_video)
        else:
            bot.send_message(
                call.message.chat.id,
                f"✅ Выбран сценарий\n🎬 Запускаю генерацию..."
            )
            process_video_text(call.message, presets[preset_key])

def process_video_text(message, prompt):
    user_id = message.from_user.id
    queue_id = add_to_queue(user_id, prompt)
    
    bot.send_message(
        message.chat.id,
        f"🎬 **Видео добавлено в очередь!**\n\n"
        f"⏱️ Время ожидания: ~1-2 минуты\n\n"
        f"Я пришлю уведомление, когда видео будет готово!"
    )
    
    def generate():
        try:
            video_url = generate_video(prompt)
            if video_url:
                update_queue(queue_id, video_url)
                update_stats(user_id, 'video')
                try:
                    bot.send_video(
                        user_id,
                        video_url,
                        caption=f"🎬 **Видео готово!**",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    if "bots can't send messages to bots" not in str(e):
                        bot.send_message(
                            user_id,
                            f"❌ Ошибка отправки видео.\nНо ты можешь скачать его по ссылке:\n{video_url}"
                        )
            else:
                bot.send_message(
                    user_id,
                    "❌ **Не удалось создать видео.**\n"
                    "Попробуй изменить промпт или выбрать другой сценарий."
                )
        except Exception as e:
            logger.error(f"Ошибка в потоке генерации видео: {e}")
    
    threading.Thread(target=generate, daemon=True).start()

def process_video(message):
    process_video_text(message, message.text)

# ==================== ТЕКСТОВЫЕ СООБЩЕНИЯ ====================
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id
    text = message.text
    
    if not check_subscription(user_id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=f"https://t.me/{CHANNEL_USERNAME[1:]}"))
        bot.send_message(
            message.chat.id,
            "❌ **Сначала подпишись на канал!**",
            reply_markup=markup
        )
        return
    
    if text == "💬 Чат":
        bot.send_message(message.chat.id, get_chat_welcome())
    
    elif text == "🎭 Режимы":
        bot.send_message(
            message.chat.id,
            "🎭 **Выбери режим работы:**",
            reply_markup=get_modes_keyboard()
        )
    
    elif text == "🎨 Фото":
        bot.send_message(message.chat.id, get_photo_welcome())
        bot.register_next_step_handler(
            bot.send_message(message.chat.id, "✏️ **Напиши, что должно быть на картинке:**"),
            process_image
        )
    
    elif text == "🎬 Видео":
        bot.send_message(message.chat.id, get_video_welcome())
        bot.send_message(
            message.chat.id,
            "🎬 **Выбери сценарий или создай свой:**",
            reply_markup=get_video_presets()
        )
    
    elif text == "📊 Статистика":
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute('SELECT messages_count, images_count, videos_count, joined_date FROM users WHERE user_id = ?', (user_id,))
        stats = cursor.fetchone()
        conn.close()
        
        mode_name = MODES[get_user_mode(user_id)]['name']
        bot.send_message(message.chat.id, get_stats_message(stats, mode_name))
    
    elif text == "❓ Помощь":
        bot.send_message(message.chat.id, get_help_message())
    
    else:
        bot.send_chat_action(message.chat.id, 'typing')
        
        mode = get_user_mode(user_id)
        system_prompt = MODES[mode]['prompt']
        answer = ask_groq(text, system_prompt)
        
        if answer:
            update_stats(user_id, 'message')
            response = f"{MODES[mode]['name']}\n\n{answer}"
            bot.send_message(message.chat.id, response)
        else:
            error_responses = [
                "😕 Что-то пошло не так. Попробуй переформулировать вопрос.",
                "😕 Не могу ответить сейчас. Задай другой вопрос или повтори позже.",
                "😕 Ошибка связи с ИИ. Попробуй ещё раз!"
            ]
            bot.send_message(message.chat.id, random.choice(error_responses))

def process_image(message):
    user_id = message.from_user.id
    prompt = message.text
    
    bot.send_chat_action(message.chat.id, 'upload_photo')
    bot.send_message(message.chat.id, "🎨 **Генерирую описание...** Это займёт несколько секунд.")
    
    result = generate_image(prompt)
    
    if result:
        update_stats(user_id, 'image')
        responses = [
            f"🎨 **Вот что получилось:**\n\n{result}",
            f"🎨 **Описание твоего изображения:**\n\n{result}",
            f"🎨 **Я представил это так:**\n\n{result}"
        ]
        bot.send_message(message.chat.id, random.choice(responses))
    else:
        bot.send_message(
            message.chat.id,
            "😕 **Не удалось создать описание.** Попробуй другой промпт или напиши позже."
        )

# ==================== ЗАПУСК ====================
if __name__ == '__main__':
    logger.info("🚀 Запуск с вебхуками...")
    
    # Удаляем старые вебхуки
    bot.remove_webhook()
    time.sleep(1)
    
    # Устанавливаем новый вебхук
    webhook_url = f"https://r1zzert-bot.onrender.com/webhook"
    bot.set_webhook(url=webhook_url)
    logger.info(f"✅ Вебхук установлен на {webhook_url}")
    
    # Запускаем Flask
    app.run(host='0.0.0.0', port=PORT)
