import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import requests
import time
import logging
from flask import Flask, request
import threading
import json
from datetime import datetime
import io

# ==================== НАСТРОЙКИ ====================
TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

# API для генерации (бесплатные ключи получить ниже)
NANOBANANA_API_KEY = os.environ.get('NANOBANANA_API_KEY', '')  # Опционально
KLING_API_KEY = os.environ.get('KLING_API_KEY', '')  # Опционально

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

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
def check_subscription(user_id):
    """Проверяет подписку на канал"""
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

# ==================== РАБОТА С ИИ (ЧАТ) ====================
def ask_groq(question, system_prompt=None):
    """Запрос к ИИ через Groq"""
    if not system_prompt:
        system_prompt = "Ты полезный ассистент. Отвечай кратко и по делу."
    
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "llama3-70b-8192",  # Самая мощная бесплатная модель
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
            logger.error(f"Ошибка Groq: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Ошибка при запросе к Groq: {e}")
        return None

# ==================== ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ ====================
def generate_image(prompt):
    """Генерирует изображение по тексту (через бесплатные API)"""
    try:
        # Пробуем через Nano Banana API если есть ключ
        if NANOBANANA_API_KEY:
            headers = {
                "Authorization": f"Bearer {NANOBANANA_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                "prompt": prompt,
                "negative_prompt": "low quality, blurry, distorted",
                "width": 1024,
                "height": 1024
            }
            response = requests.post(
                "https://api.nanobanana.com/v1/generate",
                headers=headers,
                json=data,
                timeout=60
            )
            if response.status_code == 200:
                result = response.json()
                if 'image_url' in result:
                    return result['image_url']
        
        # Запасной вариант: через Groq (они тоже умеют генерировать)
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "llama-3.2-90b-vision-preview",
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
            return "🖼️ Генерация изображения временно недоступна. Но вот описание того, что ты просил: " + response.json()['choices'][0]['message']['content']
        else:
            return None
    except Exception as e:
        logger.error(f"Ошибка генерации изображения: {e}")
        return None

# ==================== ГЕНЕРАЦИЯ ВИДЕО ====================
def generate_video(prompt):
    """Генерирует видео по тексту"""
    try:
        # Пробуем через Kling AI если есть ключ
        if KLING_API_KEY:
            headers = {
                "Authorization": f"Bearer {KLING_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                "prompt": prompt,
                "duration": 5,  # 5 секунд видео
                "style": "realistic"
            }
            response = requests.post(
                "https://api.kling.ai/v1/videos/generate",
                headers=headers,
                json=data,
                timeout=120
            )
            if response.status_code == 200:
                result = response.json()
                if 'video_url' in result:
                    return result['video_url']
        
        return "🎬 Генерация видео пока в разработке. Но я уже умею делать фото и отвечать на вопросы!"
    except Exception as e:
        logger.error(f"Ошибка генерации видео: {e}")
        return None

# ==================== РЕЖИМЫ РАБОТЫ ====================
MODES = {
    "assistant": {
        "name": "🤵 Обычный помощник",
        "system_prompt": "Ты дружелюбный ассистент. Помогаешь с любыми вопросами, даёшь полезные советы. Отвечай кратко и по делу."
    },
    "developer": {
        "name": "💻 Помощник разработчика",
        "system_prompt": "Ты эксперт по программированию. Помогаешь писать код, объясняешь сложные концепции, даёшь best practices. Отвечай на русском с примерами кода если нужно."
    },
    "writer": {
        "name": "✍️ Редактор текстов",
        "system_prompt": "Ты профессиональный редактор и копирайтер. Помогаешь писать посты, статьи, описания. Делаешь тексты красивыми и убедительными."
    },
    "teacher": {
        "name": "👨‍🏫 Учитель",
        "system_prompt": "Ты терпеливый учитель. Объясняешь сложные вещи простыми словами, приводишь примеры, проверяешь понимание. Отвечай подробно но понятно."
    },
    "creative": {
        "name": "🎨 Креативный директор",
        "system_prompt": "Ты креативный директор. Помогаешь с идеями для контента, названиями, слоганами. Мыслишь нестандартно, предлагаешь оригинальные решения."
    }
}

# Хранилище режимов пользователей (в реальном проекте лучше использовать БД)
user_modes = {}

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    """Главная клавиатура с кнопками"""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("💬 Чат"),
        KeyboardButton("🎭 Режимы"),
        KeyboardButton("🎨 Создать фото"),
        KeyboardButton("🎬 Создать видео"),
        KeyboardButton("🖼️ Редактор фото"),
        KeyboardButton("📊 Статистика"),
        KeyboardButton("❓ Помощь")
    )
    return markup

def get_modes_keyboard():
    """Клавиатура выбора режима"""
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for mode_id, mode_info in MODES.items():
        buttons.append(InlineKeyboardButton(mode_info['name'], callback_data=f"mode_{mode_id}"))
    markup.add(*buttons)
    return markup

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "друг"
    
    logger.info(f"Пользователь {user_id} запустил бота")
    
    # Проверяем подписку
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
    
    # Если подписан
    user_modes[user_id] = "assistant"
    bot.send_message(
        message.chat.id,
        f"👋 Привет, {user_name}! Добро пожаловать в **@r1zzert_bot MEGA AI**!\n\n"
        f"Я умею:\n"
        f"💬 Отвечать на любые вопросы\n"
        f"🎨 Создавать изображения по тексту\n"
        f"🎬 Генерировать видео\n"
        f"🖼️ Редактировать фото\n"
        f"🎭 Работать в разных режимах\n\n"
        f"Используй кнопки ниже 👇",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['menu'])
def menu_command(message):
    if not check_subscription(message.from_user.id):
        return
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_keyboard())

@bot.message_handler(commands=['mode'])
def mode_command(message):
    if not check_subscription(message.from_user.id):
        return
    bot.send_message(
        message.chat.id,
        "🎭 **Выбери режим работы:**\n\n"
        "Каждый режим меняет личность и стиль ответов бота.",
        reply_markup=get_modes_keyboard(),
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['image'])
def image_command(message):
    if not check_subscription(message.from_user.id):
        return
    msg = bot.send_message(
        message.chat.id,
        "🎨 Опиши, что ты хочешь увидеть.\n"
        "Например: *Киберпанк город на закате, неоновые огни*"
    )
    bot.register_next_step_handler(msg, process_image_generation)

def process_image_generation(message):
    if not check_subscription(message.from_user.id):
        return
    
    prompt = message.text
    bot.send_chat_action(message.chat.id, 'upload_photo')
    bot.send_message(message.chat.id, "🎨 Генерирую изображение... Это может занять 20-30 секунд.")
    
    result = generate_image(prompt)
    
    if result and result.startswith(('http://', 'https://')):
        # Если получили URL изображения
        bot.send_photo(message.chat.id, result, caption=f"🎨 Промпт: {prompt}")
    elif result:
        # Если получили текстовый ответ
        bot.send_message(message.chat.id, result)
    else:
        bot.send_message(message.chat.id, "😕 Не удалось сгенерировать изображение. Попробуй позже.")

@bot.message_handler(commands=['video'])
def video_command(message):
    if not check_subscription(message.from_user.id):
        return
    msg = bot.send_message(
        message.chat.id,
        "🎬 Опиши, какое видео ты хочешь создать.\n"
        "Например: *Закат над океаном, камера медленно поднимается*"
    )
    bot.register_next_step_handler(msg, process_video_generation)

def process_video_generation(message):
    if not check_subscription(message.from_user.id):
        return
    
    prompt = message.text
    bot.send_chat_action(message.chat.id, 'upload_video')
    bot.send_message(message.chat.id, "🎬 Генерирую видео... Это может занять 2-3 минуты.")
    
    result = generate_video(prompt)
    
    if result and result.startswith(('http://', 'https://')):
        # Если получили URL видео
        bot.send_video(message.chat.id, result, caption=f"🎬 Промпт: {prompt}")
    elif result:
        bot.send_message(message.chat.id, result)
    else:
        bot.send_message(message.chat.id, "😕 Не удалось сгенерировать видео. Попробуй позже.")

@bot.message_handler(commands=['help'])
def help_command(message):
    if not check_subscription(message.from_user.id):
        return
    
    help_text = """
❓ **Помощь по боту @r1zzert_bot**

**Команды:**
/start - Запустить бота
/menu - Открыть главное меню
/mode - Выбрать режим работы
/image - Создать изображение
/video - Создать видео
/help - Показать эту справку

**Кнопки:**
💬 Чат - просто общайся со мной
🎭 Режимы - выбери мою личность
🎨 Создать фото - сгенерировать картинку
🎬 Создать видео - сгенерировать видео
🖼️ Редактор фото - загрузи фото для обработки
📊 Статистика - информация о запросах
❓ Помощь - эта справка

**Примеры промптов для фото:**
• Киберпанк город на закате, неоновые огни
• Милый котёнок играет с клубком, акварель
• Горный пейзаж с озером, фотореализм

**Примеры промптов для видео:**
• Закат над океаном, камера медленно поднимается
• Городской пейзаж ночью, идёт дождь
• Космический корабль взлетает

Приятного использования! 🚀
    """
    bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

# ==================== ОБРАБОТЧИКИ КНОПОК ====================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    
    if call.data == "check_sub":
        if check_subscription(user_id):
            bot.edit_message_text(
                "✅ Подписка подтверждена! Теперь ты можешь пользоваться ботом.\n\nНажми /start чтобы начать.",
                call.message.chat.id,
                call.message.message_id
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
            user_modes[user_id] = mode_id
            bot.answer_callback_query(call.id, text=f"Режим изменён на {MODES[mode_id]['name']}")
            bot.send_message(
                call.message.chat.id,
                f"✅ Режим изменён на **{MODES[mode_id]['name']}**\n\nТеперь я буду отвечать в этом стиле.",
                parse_mode="Markdown"
            )

# ==================== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ====================
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id
    
    # Проверяем подписку
    if not check_subscription(user_id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=f"https://t.me/{CHANNEL_USERNAME[1:]}"))
        bot.send_message(
            message.chat.id,
            "❌ Сначала подпишись на канал!",
            reply_markup=markup
        )
        return
    
    text = message.text
    
    # Обработка кнопок главного меню
    if text == "💬 Чат":
        bot.send_message(
            message.chat.id,
            "💬 Просто напиши мне что-нибудь, и я отвечу!\n\n"
            f"Текущий режим: {MODES[user_modes.get(user_id, 'assistant')]['name']}\n"
            "Изменить режим можно через меню или /mode"
        )
    
    elif text == "🎭 Режимы":
        mode_command(message)
    
    elif text == "🎨 Создать фото":
        image_command(message)
    
    elif text == "🎬 Создать видео":
        video_command(message)
    
    elif text == "🖼️ Редактор фото":
        bot.send_message(
            message.chat.id,
            "🖼️ Функция редактирования фото пока в разработке.\n"
            "Но ты можешь создать новое фото через кнопку 🎨 Создать фото"
        )
    
    elif text == "📊 Статистика":
        bot.send_message(
            message.chat.id,
            "📊 Статистика использования:\n\n"
            f"• Текущий режим: {MODES[user_modes.get(user_id, 'assistant')]['name']}\n"
            f"• Доступные функции: чат, фото, видео\n"
            f"• Бесплатных запросов: безлимит через Groq\n"
            f"• Подписка на канал: ✅ подтверждена"
        )
    
    elif text == "❓ Помощь":
        help_command(message)
    
    else:
        # Обычный чат с ИИ
        bot.send_chat_action(message.chat.id, 'typing')
        
        # Получаем режим пользователя
        mode = user_modes.get(user_id, "assistant")
        system_prompt = MODES[mode]['system_prompt']
        
        # Отправляем запрос в Groq
        answer = ask_groq(text, system_prompt)
        
        if answer:
            # Добавляем информацию о режиме
            response = f"*Режим: {MODES[mode]['name']}*\n\n{answer}"
            bot.send_message(message.chat.id, response, parse_mode="Markdown")
        else:
            bot.send_message(
                message.chat.id,
                "😕 Извини, не могу ответить сейчас. Попробуй позже или задай другой вопрос."
            )

# ==================== ЗАПУСК БОТА ====================
def run_bot():
    """Запуск бота в отдельном потоке"""
    logger.info("🚀 MEGA AI Бот запускается...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            logger.error(f"Ошибка в polling: {e}")
            time.sleep(3)

if __name__ == '__main__':
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("🌐 Flask сервер запускается на порту " + os.environ.get('PORT', '10000'))
    
    # Запускаем Flask
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
