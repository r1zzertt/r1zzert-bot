import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import time
import logging
from flask import Flask, request
import threading

# НАСТРОЙКИ - через переменные окружения (добавим позже)
TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

# Проверка что всё есть
if not TOKEN or not CHANNEL_USERNAME or not GROQ_API_KEY:
    print("❌ Ошибка: не все переменные окружения заданы!")
    print("Нужны: BOT_TOKEN, CHANNEL_USERNAME, GROQ_API_KEY")
    # Не выходим, чтобы Render не крашился, но бот не будет работать
    TOKEN = TOKEN or "fake_token"
    GROQ_API_KEY = GROQ_API_KEY or "fake_key"

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask приложение для health checks
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 @r1zzert_bot is running!"

@app.route('/health')
def health():
    return "OK", 200

# Инициализация бота
bot = telebot.TeleBot(TOKEN)

def check_subscription(user_id):
    """Проверяет подписку на канал"""
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

def ask_groq(question):
    """Запрос к ИИ (бесплатно через Groq)"""
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "mixtral-8x7b-32768",
            "messages": [
                {"role": "system", "content": "Ты полезный ассистент. Отвечай кратко и по делу, максимум 3 предложения. Будь дружелюбным."},
                {"role": "user", "content": question}
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=15
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

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "друг"
    
    logger.info(f"Пользователь {user_id} запустил бота")
    
    if check_subscription(user_id):
        bot.send_message(
            message.chat.id,
            f"👋 Привет, {user_name}!\n\n"
            f"✅ Ты подписан на канал. Теперь я твой ИИ-помощник!\n"
            f"Задавай любой вопрос:"
        )
    else:
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=f"https://t.me/{CHANNEL_USERNAME[1:]}"),
            InlineKeyboardButton("✅ Я ПОДПИСАЛСЯ", callback_data="check_sub")
        )
        bot.send_message(
            message.chat.id,
            f"👋 Привет, {user_name}!\n\n"
            f"🔒 Доступ только для подписчиков канала {CHANNEL_USERNAME}\n\n"
            f"Подпишись и нажми кнопку:",
            reply_markup=markup
        )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "check_sub":
        if check_subscription(call.from_user.id):
            bot.edit_message_text(
                "✅ Подписка подтверждена! Теперь задавай любой вопрос.",
                call.message.chat.id,
                call.message.message_id
            )
        else:
            bot.answer_callback_query(
                call.id,
                text="❌ Ты не подписан на канал! Сначала подпишись.",
                show_alert=True
            )

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.text.startswith('/'):
        return
    
    if not check_subscription(message.from_user.id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            "📢 ПОДПИСАТЬСЯ",
            url=f"https://t.me/{CHANNEL_USERNAME[1:]}"
        ))
        bot.send_message(
            message.chat.id,
            "❌ Сначала подпишись на канал!",
            reply_markup=markup
        )
        return
    
    bot.send_chat_action(message.chat.id, 'typing')
    answer = ask_groq(message.text)
    
    if answer:
        bot.send_message(message.chat.id, answer)
    else:
        bot.send_message(
            message.chat.id,
            "😕 Ошибка, попробуй позже или задай другой вопрос."
        )

def run_bot():
    """Запуск бота в отдельном потоке"""
    logger.info("🚀 Бот запускается...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            logger.error(f"Ошибка в polling: {e}")
            time.sleep(3)

# Запускаем Flask и бота
if __name__ == '__main__':
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("🌐 Flask сервер запускается на порту " + os.environ.get('PORT', '10000'))
    
    # Запускаем Flask (Render требует, чтобы сервер слушал порт)
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
