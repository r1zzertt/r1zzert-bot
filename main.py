import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import random
import string
import sqlite3
from datetime import datetime
from flask import Flask, request
import time
import logging

# ==================== НАСТРОЙКИ ====================
TOKEN = os.environ.get('8752774430:AAGkYTK_xIZIGsmFdu0RMu094eNDpE-TYrg')  # Сюда вставишь токен бота
PORT = int(os.environ.get('PORT', 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Временные данные (пока игроки вводят коды)
temp_data = {}

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    # Комнаты игр
    c.execute('''CREATE TABLE IF NOT EXISTS rooms
                 (code TEXT PRIMARY KEY,
                  creator_id INTEGER,
                  joiner_id INTEGER DEFAULT 0,
                  difficulty INTEGER,
                  status TEXT DEFAULT 'waiting',
                  creator_code TEXT,
                  joiner_code TEXT,
                  turn_id INTEGER,
                  winner_id INTEGER DEFAULT 0,
                  created_at TEXT)''')
    
    # Ходы
    c.execute('''CREATE TABLE IF NOT EXISTS moves
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  room_code TEXT,
                  player_id INTEGER,
                  guess TEXT,
                  matches INTEGER,
                  created_at TEXT)''')
    
    # Статистика игроков
    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (user_id INTEGER PRIMARY KEY,
                  games INTEGER DEFAULT 0,
                  wins INTEGER DEFAULT 0,
                  losses INTEGER DEFAULT 0,
                  username TEXT)''')
    
    conn.commit()
    conn.close()

init_db()

# ==================== ФУНКЦИИ ====================

def generate_room_code():
    """Генерирует код комнаты из 4 букв"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase, k=4))
        conn = sqlite3.connect('game.db')
        c = conn.cursor()
        c.execute('SELECT code FROM rooms WHERE code = ?', (code,))
        if not c.fetchone():
            conn.close()
            return code
        conn.close()

def create_room(creator_id, difficulty):
    """Создает новую комнату"""
    code = generate_room_code()
    now = datetime.now().isoformat()
    
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('''INSERT INTO rooms 
                 (code, creator_id, difficulty, turn_id, created_at)
                 VALUES (?, ?, ?, ?, ?)''',
              (code, creator_id, difficulty, creator_id, now))
    conn.commit()
    conn.close()
    return code

def join_room(code, joiner_id, username):
    """Присоединение к комнате"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    c.execute('SELECT * FROM rooms WHERE code = ? AND status = "waiting"', (code,))
    room = c.fetchone()
    
    if not room:
        conn.close()
        return False, "Комната не найдена или уже заполнена"
    
    if room[1] == joiner_id:
        conn.close()
        return False, "Нельзя играть с самим собой"
    
    c.execute('''UPDATE rooms 
                 SET joiner_id = ?, status = "setting"
                 WHERE code = ?''', (joiner_id, code))
    conn.commit()
    conn.close()
    
    # Сохраняем username для статистики
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO stats (user_id, username)
                 VALUES (?, ?)''', (joiner_id, username))
    conn.commit()
    conn.close()
    
    return True, code

def set_code(room_code, player_id, secret):
    """Установка секретного кода"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    c.execute('SELECT * FROM rooms WHERE code = ?', (room_code,))
    room = c.fetchone()
    
    if not room:
        conn.close()
        return False, "Комната не найдена"
    
    # Проверка длины
    if len(secret) != room[3]:
        conn.close()
        return False, f"Нужно {room[3]} цифр"
    
    if not secret.isdigit():
        conn.close()
        return False, "Только цифры"
    
    # Кто устанавливает
    if player_id == room[1]:  # создатель
        c.execute('UPDATE rooms SET creator_code = ? WHERE code = ?', (secret, room_code))
    elif player_id == room[2]:  # присоединившийся
        c.execute('UPDATE rooms SET joiner_code = ? WHERE code = ?', (secret, room_code))
    else:
        conn.close()
        return False, "Ты не в этой игре"
    
    # Проверка, готовы ли оба
    c.execute('SELECT creator_code, joiner_code FROM rooms WHERE code = ?', (room_code,))
    codes = c.fetchone()
    
    if codes[0] and codes[1]:  # оба кода установлены
        c.execute('''UPDATE rooms 
                     SET status = "playing", turn_id = ?
                     WHERE code = ?''', (room[1], room_code))
        conn.commit()
        conn.close()
        return True, "start"
    
    conn.commit()
    conn.close()
    return True, "waiting"

def check_guess(secret, guess):
    """Считает совпадения по позициям"""
    matches = 0
    for i in range(len(secret)):
        if secret[i] == guess[i]:
            matches += 1
    return matches

def make_move(room_code, player_id, guess):
    """Сделать ход"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    c.execute('SELECT * FROM rooms WHERE code = ? AND status = "playing"', (room_code,))
    room = c.fetchone()
    
    if not room:
        conn.close()
        return False, "Игра не найдена"
    
    # Проверка очереди
    if player_id != room[5]:
        conn.close()
        return False, "Сейчас не твой ход"
    
    # Проверка длины
    if len(guess) != room[3]:
        conn.close()
        return False, f"Введи {room[3]} цифр"
    
    if not guess.isdigit():
        conn.close()
        return False, "Только цифры"
    
    # Определяем код соперника
    if player_id == room[1]:  # создатель
        secret = room[4]  # код присоединившегося
        opponent = room[2]
    else:  # присоединившийся
        secret = room[1]  # код создателя
        opponent = room[1]
    
    # Считаем совпадения
    matches = check_guess(secret, guess)
    
    # Сохраняем ход
    c.execute('''INSERT INTO moves (room_code, player_id, guess, matches, created_at)
                 VALUES (?, ?, ?, ?, ?)''',
              (room_code, player_id, guess, matches, datetime.now().isoformat()))
    
    # Проверка победы
    if matches == room[3]:
        c.execute('''UPDATE rooms SET status = "finished", winner_id = ?
                     WHERE code = ?''', (player_id, room_code))
        
        # Обновляем статистику
        c.execute('''UPDATE stats SET games = games + 1, wins = wins + 1
                     WHERE user_id = ?''', (player_id,))
        c.execute('''UPDATE stats SET games = games + 1, losses = losses + 1
                     WHERE user_id = ?''', (opponent,))
        
        conn.commit()
        conn.close()
        return True, "win", matches, opponent
    else:
        # Меняем очередь
        c.execute('UPDATE rooms SET turn_id = ? WHERE code = ?', (opponent, room_code))
        conn.commit()
        conn.close()
        return True, "continue", matches, opponent

def get_game_info(room_code, user_id):
    """Получить информацию об игре"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    c.execute('SELECT * FROM rooms WHERE code = ?', (room_code,))
    room = c.fetchone()
    
    if not room:
        conn.close()
        return None
    
    # Получаем последние ходы
    c.execute('''SELECT player_id, guess, matches FROM moves 
                 WHERE room_code = ? ORDER BY created_at DESC LIMIT 10''', (room_code,))
    moves = c.fetchall()
    
    conn.close()
    
    # Определяем роли
    is_creator = (user_id == room[1])
    is_joiner = (user_id == room[2])
    
    if not (is_creator or is_joiner):
        return None
    
    return {
        'room': room,
        'moves': moves,
        'is_creator': is_creator,
        'is_joiner': is_joiner
    }

def get_stats(user_id):
    """Получить статистику игрока"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('SELECT games, wins, losses FROM stats WHERE user_id = ?', (user_id,))
    stats = c.fetchone()
    conn.close()
    return stats

# ==================== КЛАВИАТУРЫ ====================

def main_menu():
    """Главное меню"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎮 Создать игру", callback_data="menu_create"),
        InlineKeyboardButton("🔑 Присоединиться", callback_data="menu_join"),
        InlineKeyboardButton("📊 Статистика", callback_data="menu_stats"),
        InlineKeyboardButton("❓ Правила", callback_data="menu_help")
    )
    return markup

def difficulty_menu():
    """Выбор сложности"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("4 цифры", callback_data="diff_4"),
        InlineKeyboardButton("6 цифр", callback_data="diff_6"),
        InlineKeyboardButton("8 цифр", callback_data="diff_8"),
        InlineKeyboardButton("12 цифр", callback_data="diff_12"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    return markup

def game_menu(room_code, is_your_turn=False):
    """Меню во время игры"""
    markup = InlineKeyboardMarkup(row_width=1)
    if is_your_turn:
        markup.add(InlineKeyboardButton("🎯 Сделать ход", callback_data=f"move_{room_code}"))
    markup.add(InlineKeyboardButton("🔄 Обновить", callback_data=f"refresh_{room_code}"))
    markup.add(InlineKeyboardButton("🏳️ Сдаться", callback_data=f"surrender_{room_code}"))
    return markup

# ==================== КОМАНДЫ ====================

@bot.message_handler(commands=['start'])
def start_cmd(message):
    """Старт"""
    user_id = message.from_user.id
    username = message.from_user.first_name or "Игрок"
    
    # Сохраняем юзера
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO stats (user_id, username)
                 VALUES (?, ?)''', (user_id, username))
    conn.commit()
    conn.close()
    
    bot.send_message(
        message.chat.id,
        f"🔐 **Взлом замка**\n\n"
        f"Привет, {username}!\n"
        f"Сыграй с другом в угадай цифры.\n\n"
        f"Выбирай:",
        reply_markup=main_menu()
    )

@bot.message_handler(commands=['play'])
def play_cmd(message):
    """Быстрый старт"""
    start_cmd(message)

# ==================== КОЛЛБЭКИ ====================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    username = call.from_user.first_name or "Игрок"
    
    # ===== ГЛАВНОЕ МЕНЮ =====
    if call.data == "menu_create":
        bot.edit_message_text(
            "🎮 **Создание игры**\n\nВыбери сложность:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=difficulty_menu()
        )
    
    elif call.data == "menu_join":
        msg = bot.edit_message_text(
            "🔑 **Присоединение к игре**\n\n"
            "Введи код комнаты:\n"
            "(например: ABCD)",
            call.message.chat.id,
            call.message.message_id
        )
        temp_data[user_id] = {'action': 'join'}
        bot.register_next_step_handler_by_chat_id(call.message.chat.id, process_join)
    
    elif call.data == "menu_stats":
        stats = get_stats(user_id)
        if stats and stats[0] > 0:
            winrate = (stats[1] / stats[0]) * 100
            text = f"📊 **Твоя статистика**\n\n"
            text += f"🎮 Всего игр: {stats[0]}\n"
            text += f"🏆 Побед: {stats[1]}\n"
            text += f"💔 Поражений: {stats[2]}\n"
            text += f"📈 Процент побед: {winrate:.1f}%"
        else:
            text = "📊 Ты еще не играл"
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_menu()
        )
    
    elif call.data == "menu_help":
        text = """
🔐 **Правила игры:**

1️⃣ Каждый загадывает свой секретный код
2️⃣ Ходите по очереди, угадывая код соперника
3️⃣ После каждой догадки бот показывает сколько цифр совпало по позициям

✅ **Пример:**
Загадано: 3781
Догадка: 9713
Результат: 1 цифра (цифра 7 на второй позиции)

🎯 **Победа:** угадал все цифры первым
        """
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_menu()
        )
    
    elif call.data == "back_main":
        bot.edit_message_text(
            "🔐 **Взлом замка**\n\nВыбирай:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_menu()
        )
    
    # ===== ВЫБОР СЛОЖНОСТИ =====
    elif call.data.startswith("diff_"):
        difficulty = int(call.data.split('_')[1])
        room_code = create_room(user_id, difficulty)
        
        text = f"✅ **Комната создана!**\n\n"
        text += f"🔑 **Код: `{room_code}`**\n"
        text += f"🎯 Сложность: {difficulty} цифр\n\n"
        text += f"Отправь код другу.\n"
        text += f"**Теперь загадай свой код:**\n"
        text += f"Напиши {difficulty} цифр"
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id
        )
        
        temp_data[user_id] = {'action': 'set_code', 'room': room_code}
    
    # ===== ИГРОВЫЕ ДЕЙСТВИЯ =====
    elif call.data.startswith("move_"):
        room_code = call.data.replace("move_", "")
        
        info = get_game_info(room_code, user_id)
        if not info or info['room'][6] != 'playing':
            bot.answer_callback_query(call.id, "❌ Игра не найдена", show_alert=True)
            return
        
        # Проверка очереди
        if info['room'][5] != user_id:
            bot.answer_callback_query(call.id, "⏳ Сейчас не твой ход!", show_alert=True)
            return
        
        bot.edit_message_text(
            f"🎯 **Твой ход**\n\nВведи {info['room'][3]} цифр:",
            call.message.chat.id,
            call.message.message_id
        )
        temp_data[user_id] = {'action': 'make_move', 'room': room_code}
    
    elif call.data.startswith("refresh_"):
        room_code = call.data.replace("refresh_", "")
        show_game_status(call.message.chat.id, call.message.message_id, room_code, user_id)
    
    elif call.data.startswith("surrender_"):
        room_code = call.data.replace("surrender_", "")
        
        conn = sqlite3.connect('game.db')
        c = conn.cursor()
        c.execute('SELECT * FROM rooms WHERE code = ?', (room_code,))
        room = c.fetchone()
        
        if room:
            # Определяем победителя
            winner = room[2] if user_id == room[1] else room[1]
            
            c.execute('UPDATE rooms SET status = "finished", winner_id = ? WHERE code = ?', (winner, room_code))
            
            # Обновляем статистику
            c.execute('''UPDATE stats SET games = games + 1, losses = losses + 1
                         WHERE user_id = ?''', (user_id,))
            c.execute('''UPDATE stats SET games = games + 1, wins = wins + 1
                         WHERE user_id = ?''', (winner,))
            
            conn.commit()
            
            # Уведомление
            bot.send_message(
                winner,
                f"🏆 Соперник сдался! Ты победил!"
            )
        
        conn.close()
        
        bot.edit_message_text(
            "🏳️ Ты сдался\n\nВозвращайся в меню:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_menu()
        )

# ==================== ОБРАБОТЧИКИ ТЕКСТА ====================

def process_join(message):
    """Обработка ввода кода для присоединения"""
    user_id = message.from_user.id
    code = message.text.strip().upper()
    
    if user_id in temp_data and temp_data[user_id].get('action') == 'join':
        success, result = join_room(code, user_id, message.from_user.first_name or "Игрок")
        
        if not success:
            bot.send_message(message.chat.id, f"❌ {result}")
            bot.send_message(message.chat.id, "🔐 **Взлом замка**", reply_markup=main_menu())
            del temp_data[user_id]
            return
        
        bot.send_message(
            message.chat.id,
            f"✅ **Присоединился к комнате {code}**\n\n"
            f"**Загадай свой код:**\n"
            f"Напиши нужное количество цифр"
        )
        temp_data[user_id] = {'action': 'set_code', 'room': code}

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    """Обработка всех текстовых сообщений"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Проверяем, ждем ли мы действие от пользователя
    if user_id not in temp_data:
        # Если не ждем - показываем меню
        bot.send_message(
            message.chat.id,
            "🔐 **Взлом замка**\n\nИспользуй меню:",
            reply_markup=main_menu()
        )
        return
    
    action = temp_data[user_id].get('action')
    
    # Установка кода
    if action == 'set_code':
        room_code = temp_data[user_id]['room']
        success, result = set_code(room_code, user_id, text)
        
        if not success:
            bot.send_message(message.chat.id, f"❌ {result}")
            return
        
        if result == "start":
            # Игра начинается
            bot.send_message(
                message.chat.id,
                "✅ **Код принят!**\n\n🎮 **Игра началась!**\nПервый ход за создателем"
            )
            
            # Уведомляем второго игрока
            conn = sqlite3.connect('game.db')
            c = conn.cursor()
            c.execute('SELECT creator_id, joiner_id FROM rooms WHERE code = ?', (room_code,))
            creator, joiner = c.fetchone()
            conn.close()
            
            other_id = joiner if user_id == creator else creator
            bot.send_message(
                other_id,
                "✅ **Код принят!**\n\n🎮 **Игра началась!**"
            )
            
            # Показываем статус обоим
            show_game_status(message.chat.id, None, room_code, user_id)
            if other_id:
                try:
                    show_game_status(other_id, None, room_code, other_id)
                except:
                    pass
            
            del temp_data[user_id]
        else:
            bot.send_message(message.chat.id, "✅ Код сохранен. Ждем соперника...")
            del temp_data[user_id]
    
    # Ход в игре
    elif action == 'make_move':
        room_code = temp_data[user_id]['room']
        success, status, matches, opponent = make_move(room_code, user_id, text)
        
        if not success:
            bot.send_message(message.chat.id, f"❌ {status}")
            return
        
        if status == "win":
            bot.send_message(
                message.chat.id,
                f"🎉 **ПОБЕДА!**\n\nТы угадал код!\nВсе {matches} цифр совпали!",
                reply_markup=main_menu()
            )
            bot.send_message(
                opponent,
                f"💔 **Поражение**\n\nСоперник угадал твой код",
                reply_markup=main_menu()
            )
        else:
            bot.send_message(
                message.chat.id,
                f"✅ Ход принят\nСовпадений: {matches} цифр"
            )
            bot.send_message(
                opponent,
                f"🎯 Соперник сделал ход\nСовпадений: {matches} цифр\n\nТвой ход!"
            )
        
        del temp_data[user_id]

def show_game_status(chat_id, message_id, room_code, user_id):
    """Показывает статус игры"""
    info = get_game_info(room_code, user_id)
    if not info:
        bot.send_message(chat_id, "❌ Игра не найдена", reply_markup=main_menu())
        return
    
    room = info['room']
    moves = info['moves']
    
    # Определяем соперника
    if info['is_creator']:
        opponent_id = room[2]
        role = "Создатель"
    else:
        opponent_id = room[1]
        role = "Игрок"
    
    # Получаем имена
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('SELECT username FROM stats WHERE user_id = ?', (opponent_id,))
    opp_name = c.fetchone()
    opp_name = opp_name[0] if opp_name else "Соперник"
    conn.close()
    
    text = f"🔐 **Игра**\n\n"
    text += f"Комната: `{room_code}`\n"
    text += f"Сложность: {room[3]} цифр\n"
    text += f"Соперник: {opp_name}\n\n"
    
    if room[6] == 'playing':
        if room[5] == user_id:
            text += "⏳ **ТВОЙ ХОД!**\n\n"
        else:
            text += "⏳ **ХОД СОПЕРНИКА**\n\n"
    
    text += "**История ходов:**\n"
    if moves:
        for player_id, guess, matches in moves:
            if player_id == user_id:
                prefix = "Ты:"
            else:
                prefix = f"{opp_name}:"
            text += f"{prefix} {guess} → {matches} совпад.\n"
    else:
        text += "Пока нет ходов\n"
    
    is_your_turn = (room[6] == 'playing' and room[5] == user_id)
    
    if message_id:
        bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=game_menu(room_code, is_your_turn)
        )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=game_menu(room_code, is_your_turn)
        )

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
    return "🔐 Game Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

# ==================== ЗАПУСК ====================

if __name__ == '__main__':
    logger.info("🚀 Запуск Game Bot...")
    
    # Удаляем старый вебхук и ставим новый
    bot.remove_webhook()
    time.sleep(1)
    
    # Ссылка на твоего бота (замени на свой URL)
    webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/webhook"
    bot.set_webhook(url=webhook_url)
    
    logger.info(f"✅ Вебхук установлен на {webhook_url}")
    app.run(host='0.0.0.0', port=PORT)
