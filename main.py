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
TOKEN = os.environ.get('BOT_TOKEN')  # Сюда вставишь токен в Render
PORT = int(os.environ.get('PORT', 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Временные данные
waiting_for = {}  # {user_id: {'action': 'set_code', 'room': 'ABCD'}}

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    # Комнаты
    c.execute('''CREATE TABLE IF NOT EXISTS rooms
                 (code TEXT PRIMARY KEY,
                  creator_id INTEGER,
                  creator_name TEXT,
                  joiner_id INTEGER DEFAULT 0,
                  joiner_name TEXT DEFAULT '',
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
                  player_name TEXT,
                  guess TEXT,
                  matches INTEGER,
                  move_number INTEGER,
                  created_at TEXT)''')
    
    # Статистика
    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (user_id INTEGER PRIMARY KEY,
                  games INTEGER DEFAULT 0,
                  wins INTEGER DEFAULT 0,
                  name TEXT)''')
    
    conn.commit()
    conn.close()
    print("✅ База данных готова")

init_db()

# ==================== ФУНКЦИИ ====================

def generate_code():
    """Код комнаты из 4 букв"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase, k=4))
        conn = sqlite3.connect('game.db')
        c = conn.cursor()
        c.execute('SELECT code FROM rooms WHERE code = ?', (code,))
        if not c.fetchone():
            conn.close()
            return code
        conn.close()

def create_room(user_id, user_name, difficulty):
    """Создать комнату"""
    code = generate_code()
    now = datetime.now().isoformat()
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('''INSERT INTO rooms 
                 (code, creator_id, creator_name, difficulty, turn_id, created_at, status)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (code, user_id, user_name, difficulty, user_id, now, 'waiting'))
    conn.commit()
    conn.close()
    return code

def join_room(code, user_id, user_name):
    """Присоединиться к комнате"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    # Проверяем комнату
    c.execute('SELECT * FROM rooms WHERE code = ? AND status = "waiting"', (code,))
    room = c.fetchone()
    
    if not room:
        conn.close()
        return False, "❌ Комната не найдена"
    
    if room[1] == user_id:
        conn.close()
        return False, "❌ Нельзя играть с собой"
    
    # Присоединяемся
    c.execute('''UPDATE rooms 
                 SET joiner_id = ?, joiner_name = ?, status = "setting"
                 WHERE code = ?''', (user_id, user_name, code))
    conn.commit()
    conn.close()
    
    return True, code

def set_code(room_code, user_id, secret):
    """Установить секретный код"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    c.execute('SELECT * FROM rooms WHERE code = ?', (room_code,))
    room = c.fetchone()
    
    if not room:
        conn.close()
        return False, "❌ Комната не найдена"
    
    # Проверка длины
    if len(secret) != room[5]:
        conn.close()
        return False, f"❌ Нужно {room[5]} цифр"
    
    if not secret.isdigit():
        conn.close()
        return False, "❌ Только цифры"
    
    # Кто устанавливает
    if user_id == room[1]:  # создатель
        c.execute('UPDATE rooms SET creator_code = ? WHERE code = ?', (secret, room_code))
    elif user_id == room[2]:  # второй игрок
        c.execute('UPDATE rooms SET joiner_code = ? WHERE code = ?', (secret, room_code))
    else:
        conn.close()
        return False, "❌ Ты не в этой игре"
    
    # Проверяем, готовы ли оба
    c.execute('SELECT creator_code, joiner_code FROM rooms WHERE code = ?', (room_code,))
    codes = c.fetchone()
    
    if codes[0] and codes[1]:  # оба кода есть
        c.execute('''UPDATE rooms 
                     SET status = "playing", turn_id = ?
                     WHERE code = ?''', (room[1], room_code))
        conn.commit()
        conn.close()
        return True, "start", room[1], room[2]
    
    conn.commit()
    conn.close()
    return True, "waiting", None, None

def check_match(secret, guess):
    """Сколько цифр совпало по позициям"""
    matches = 0
    for i in range(len(secret)):
        if secret[i] == guess[i]:
            matches += 1
    return matches

def make_move(room_code, user_id, user_name, guess):
    """Сделать ход"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    c.execute('SELECT * FROM rooms WHERE code = ? AND status = "playing"', (room_code,))
    room = c.fetchone()
    
    if not room:
        conn.close()
        return False, "❌ Игра не найдена"
    
    # Проверка очереди
    if user_id != room[9]:
        conn.close()
        return False, "⏳ Не твой ход"
    
    # Проверка длины
    if len(guess) != room[5]:
        conn.close()
        return False, f"❌ Нужно {room[5]} цифр"
    
    if not guess.isdigit():
        conn.close()
        return False, "❌ Только цифры"
    
    # Определяем код соперника
    if user_id == room[1]:  # создатель
        secret = room[7]  # код второго
        opponent = room[2]
    else:  # второй игрок
        secret = room[6]  # код создателя
        opponent = room[1]
    
    # Номер хода
    c.execute('SELECT COUNT(*) FROM moves WHERE room_code = ?', (room_code,))
    move_num = c.fetchone()[0] + 1
    
    # Считаем совпадения
    matches = check_match(secret, guess)
    
    # Сохраняем ход
    c.execute('''INSERT INTO moves 
                 (room_code, player_id, player_name, guess, matches, move_number, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (room_code, user_id, user_name, guess, matches, move_num, datetime.now().isoformat()))
    
    # Проверка победы
    if matches == room[5]:
        c.execute('UPDATE rooms SET status = "finished", winner_id = ? WHERE code = ?', (user_id, room_code))
        
        # Обновляем статистику
        c.execute('UPDATE stats SET games = games + 1, wins = wins + 1 WHERE user_id = ?', (user_id,))
        c.execute('UPDATE stats SET games = games + 1 WHERE user_id = ?', (opponent,))
        
        conn.commit()
        conn.close()
        return True, "win", matches, opponent, move_num, secret
    
    # Меняем очередь
    c.execute('UPDATE rooms SET turn_id = ? WHERE code = ?', (opponent, room_code))
    conn.commit()
    conn.close()
    return True, "continue", matches, opponent, move_num, None

def get_game(room_code, user_id):
    """Получить информацию об игре"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    c.execute('SELECT * FROM rooms WHERE code = ?', (room_code,))
    room = c.fetchone()
    
    if not room:
        conn.close()
        return None
    
    if user_id not in [room[1], room[2]]:
        conn.close()
        return None
    
    # Последние ходы
    c.execute('''SELECT player_id, player_name, guess, matches, move_number 
                 FROM moves WHERE room_code = ? 
                 ORDER BY move_number DESC LIMIT 5''', (room_code,))
    moves = c.fetchall()
    
    # Количество ходов
    c.execute('SELECT COUNT(*) FROM moves WHERE room_code = ?', (room_code,))
    total = c.fetchone()[0]
    
    conn.close()
    
    # Имя соперника
    if user_id == room[1]:
        opp_name = room[3] if room[3] else "Соперник"
    else:
        opp_name = room[1]
        if isinstance(opp_name, int):
            conn = sqlite3.connect('game.db')
            c = conn.cursor()
            c.execute('SELECT name FROM stats WHERE user_id = ?', (opp_name,))
            name_data = c.fetchone()
            opp_name = name_data[0] if name_data else "Соперник"
            conn.close()
    
    return {
        'room': room,
        'moves': moves,
        'total_moves': total,
        'opponent_name': opp_name
    }

# ==================== КНОПКИ ====================

def main_keyboard():
    """Главное меню"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎮 СОЗДАТЬ ИГРУ", callback_data="create"),
        InlineKeyboardButton("🔑 ПРИСОЕДИНИТЬСЯ", callback_data="join"),
        InlineKeyboardButton("📊 СТАТИСТИКА", callback_data="stats"),
        InlineKeyboardButton("❓ ПРАВИЛА", callback_data="help")
    )
    return markup

def difficulty_keyboard():
    """Выбор сложности"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("4 цифры", callback_data="diff_4"),
        InlineKeyboardButton("6 цифр", callback_data="diff_6"),
        InlineKeyboardButton("8 цифр", callback_data="diff_8"),
        InlineKeyboardButton("12 цифр", callback_data="diff_12"),
        InlineKeyboardButton("◀️ НАЗАД", callback_data="back")
    )
    return markup

def game_keyboard(room_code, is_my_turn):
    """Кнопки во время игры"""
    markup = InlineKeyboardMarkup(row_width=2)
    if is_my_turn:
        markup.add(InlineKeyboardButton("🎯 СДЕЛАТЬ ХОД", callback_data=f"move_{room_code}"))
    markup.add(
        InlineKeyboardButton("🔄 ОБНОВИТЬ", callback_data=f"refresh_{room_code}"),
        InlineKeyboardButton("🏳️ СДАТЬСЯ", callback_data=f"surrender_{room_code}")
    )
    return markup

# ==================== КОМАНДЫ ====================

@bot.message_handler(commands=['start'])
def start(message):
    """Старт"""
    user_id = message.from_user.id
    name = message.from_user.first_name or "Игрок"
    
    # Сохраняем в статистику
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO stats (user_id, name) VALUES (?, ?)', (user_id, name))
    conn.commit()
    conn.close()
    
    bot.send_message(
        message.chat.id,
        f"🔐 Привет, {name}!\n\nСыграй с другом в игру Взлом замка!",
        reply_markup=main_keyboard()
    )

# ==================== КОЛЛБЭКИ ====================

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    user_id = call.from_user.id
    name = call.from_user.first_name or "Игрок"
    
    # Главное меню
    if call.data == "create":
        bot.edit_message_text(
            "🎮 Создание игры\n\nВыбери сколько цифр будет в коде:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=difficulty_keyboard()
        )
    
    elif call.data == "join":
        bot.edit_message_text(
            "🔑 Присоединение к игре\n\nВведи код комнаты из 4 букв:",
            call.message.chat.id,
            call.message.message_id
        )
        waiting_for[user_id] = {'action': 'join'}
        bot.register_next_step_handler_by_chat_id(call.message.chat.id, handle_join)
    
    elif call.data == "stats":
        conn = sqlite3.connect('game.db')
        c = conn.cursor()
        c.execute('SELECT games, wins FROM stats WHERE user_id = ?', (user_id,))
        stats = c.fetchone()
        conn.close()
        
        if stats and stats[0] > 0:
            games, wins = stats
            text = f"📊 Статистика\n\nВсего игр: {games}\nПобед: {wins}\nПоражений: {games - wins}"
        else:
            text = "📊 У тебя пока нет игр"
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_keyboard()
        )
    
    elif call.data == "help":
        text = """
🔐 ПРАВИЛА ИГРЫ

1. Каждый загадывает свой код из цифр
2. Ходите по очереди
3. После каждой догадки бот показывает сколько цифр совпало ПО ПОЗИЦИЯМ

Пример:
Загадано: 3781
Догадка: 9713
Результат: 1 совпадение (цифра 7)

🏆 Победа: угадал все цифры первым
        """
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_keyboard()
        )
    
    elif call.data == "back":
        bot.edit_message_text(
            f"🔐 Привет, {name}!\n\nСыграй с другом в игру Взлом замка!",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_keyboard()
        )
    
    # Выбор сложности
    elif call.data.startswith("diff_"):
        diff = int(call.data.split('_')[1])
        code = create_room(user_id, name, diff)
        
        bot.edit_message_text(
            f"✅ Комната создана!\n\n"
            f"🔑 Код: {code}\n"
            f"🎯 Сложность: {diff} цифр\n\n"
            f"Отправь этот код другу.\n"
            f"Ожидаем второго игрока...\n\n"
            f"Загадай свой код:\n"
            f"Напиши {diff} цифр",
            call.message.chat.id,
            call.message.message_id
        )
        waiting_for[user_id] = {'action': 'set_code', 'room': code}
    
    # Ход
    elif call.data.startswith("move_"):
        room_code = call.data.replace("move_", "")
        game = get_game(room_code, user_id)
        
        if not game or game['room'][8] != 'playing':
            bot.answer_callback_query(call.id, "❌ Игра не найдена", show_alert=True)
            return
        
        if game['room'][9] != user_id:
            bot.answer_callback_query(call.id, "⏳ Сейчас не твой ход", show_alert=True)
            return
        
        bot.edit_message_text(
            f"🎯 Твой ход\n\nВведи {game['room'][5]} цифр:",
            call.message.chat.id,
            call.message.message_id
        )
        waiting_for[user_id] = {'action': 'make_move', 'room': room_code}
    
    # Обновить статус
    elif call.data.startswith("refresh_"):
        room_code = call.data.replace("refresh_", "")
        show_game(call.message.chat.id, call.message.message_id, room_code, user_id)
    
    # Сдаться
    elif call.data.startswith("surrender_"):
        room_code = call.data.replace("surrender_", "")
        
        conn = sqlite3.connect('game.db')
        c = conn.cursor()
        c.execute('SELECT * FROM rooms WHERE code = ? AND status = "playing"', (room_code,))
        room = c.fetchone()
        
        if room:
            winner = room[2] if user_id == room[1] else room[1]
            c.execute('UPDATE rooms SET status = "finished", winner_id = ? WHERE code = ?', (winner, room_code))
            
            # Обновляем статистику
            c.execute('UPDATE stats SET games = games + 1 WHERE user_id = ?', (user_id,))
            c.execute('UPDATE stats SET games = games + 1, wins = wins + 1 WHERE user_id = ?', (winner,))
            
            conn.commit()
            
            bot.edit_message_text(
                "🏳️ Ты сдался",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_keyboard()
            )
            
            bot.send_message(
                winner,
                "🏆 Соперник сдался! Ты победил!",
                reply_markup=main_keyboard()
            )
        
        conn.close()

# ==================== ОБРАБОТЧИКИ ТЕКСТА ====================

def handle_join(message):
    """Ввод кода комнаты"""
    user_id = message.from_user.id
    name = message.from_user.first_name or "Игрок"
    code = message.text.strip().upper()
    
    if user_id not in waiting_for or waiting_for[user_id].get('action') != 'join':
        return
    
    if len(code) != 4 or not code.isalpha():
        bot.send_message(message.chat.id, "❌ Код должен быть из 4 букв")
        bot.send_message(message.chat.id, "🔐 Главное меню:", reply_markup=main_keyboard())
        del waiting_for[user_id]
        return
    
    success, result = join_room(code, user_id, name)
    
    if not success:
        bot.send_message(message.chat.id, result)
        bot.send_message(message.chat.id, "🔐 Главное меню:", reply_markup=main_keyboard())
        del waiting_for[user_id]
        return
    
    # Получаем сложность
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('SELECT difficulty FROM rooms WHERE code = ?', (code,))
    diff = c.fetchone()[0]
    conn.close()
    
    bot.send_message(
        message.chat.id,
        f"✅ Ты присоединился!\n\n"
        f"Комната: {code}\n"
        f"Сложность: {diff} цифр\n\n"
        f"Загадай свой код:\n"
        f"Напиши {diff} цифр"
    )
    waiting_for[user_id] = {'action': 'set_code', 'room': code}

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    """Обработка текста"""
    user_id = message.from_user.id
    name = message.from_user.first_name or "Игрок"
    text = message.text.strip()
    
    if user_id not in waiting_for:
        bot.send_message(message.chat.id, "🔑 Используй кнопки меню", reply_markup=main_keyboard())
        return
    
    action = waiting_for[user_id].get('action')
    
    # Установка кода
    if action == 'set_code':
        room_code = waiting_for[user_id]['room']
        success, msg, creator, joiner = set_code(room_code, user_id, text)
        
        if not success:
            bot.send_message(message.chat.id, msg)
            return
        
        if msg == "start":
            # Игра началась
            bot.send_message(creator, "✅ Код принят!\n\n🎮 Игра началась! Твой ход!")
            bot.send_message(joiner, "✅ Код принят!\n\n🎮 Игра началась! Ход соперника!")
            
            show_game(creator, None, room_code, creator)
            show_game(joiner, None, room_code, joiner)
            
            del waiting_for[user_id]
        else:
            bot.send_message(message.chat.id, "✅ Код сохранён. Ожидаем соперника...")
            del waiting_for[user_id]
    
    # Ход
    elif action == 'make_move':
        room_code = waiting_for[user_id]['room']
        success, status, matches, opponent, move_num, secret = make_move(room_code, user_id, name, text)
        
        if not success:
            bot.send_message(message.chat.id, status)
            return
        
        # Получаем сложность
        conn = sqlite3.connect('game.db')
        c = conn.cursor()
        c.execute('SELECT difficulty FROM rooms WHERE code = ?', (room_code,))
        total = c.fetchone()[0]
        conn.close()
        
        result_text = f"🎯 Ход #{move_num}\n{name}: {text}\n✅ Совпадений: {matches} из {total}"
        
        bot.send_message(message.chat.id, result_text)
        bot.send_message(opponent, result_text)
        
        if status == "win":
            bot.send_message(
                user_id,
                f"🏆 ПОБЕДА!\n\nТы угадал код за {move_num} ходов!",
                reply_markup=main_keyboard()
            )
            bot.send_message(
                opponent,
                f"💔 Поражение\n\nТвой код: {secret}",
                reply_markup=main_keyboard()
            )
            
            if user_id in waiting_for:
                del waiting_for[user_id]
            if opponent in waiting_for:
                del waiting_for[opponent]
        else:
            bot.send_message(opponent, "⏳ Твой ход!")
            show_game(message.chat.id, None, room_code, user_id)
            show_game(opponent, None, room_code, opponent)
            del waiting_for[user_id]

def show_game(chat_id, message_id, room_code, user_id):
    """Показать состояние игры"""
    game = get_game(room_code, user_id)
    
    if not game:
        bot.send_message(chat_id, "❌ Игра не найдена", reply_markup=main_keyboard())
        return
    
    room = game['room']
    moves = game['moves']
    total = game['total_moves']
    opp_name = game['opponent_name']
    
    text = f"🎮 ИГРА\n\n"
    text += f"🔑 Комната: {room_code}\n"
    text += f"🎯 Сложность: {room[5]} цифр\n"
    text += f"👤 Соперник: {opp_name}\n"
    text += f"📊 Ходов: {total}\n\n"
    
    if room[8] == 'playing':
        if room[9] == user_id:
            text += "⚡️ ТВОЙ ХОД!\n\n"
        else:
            text += "⏳ ХОД СОПЕРНИКА\n\n"
    elif room[8] == 'finished':
        if room[10] == user_id:
            text += "🏆 ТЫ ПОБЕДИЛ\n\n"
        else:
            text += "💔 ТЫ ПРОИГРАЛ\n\n"
    
    if moves:
        text += "История ходов:\n"
        for pid, pname, guess, matches, num in moves:
            if pid == user_id:
                prefix = "Ты:"
            else:
                prefix = f"{opp_name}:"
            text += f"#{num} {prefix} {guess} → {matches} совп.\n"
    else:
        text += "Пока нет ходов\n"
    
    is_my_turn = (room[8] == 'playing' and room[9] == user_id)
    
    if message_id:
        bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=game_keyboard(room_code, is_my_turn)
        )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=game_keyboard(room_code, is_my_turn)
        )

# ==================== ВЕБХУК ====================

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
        return 'OK', 200
    except Exception as e:
        print(f"Ошибка: {e}")
        return 'ERROR', 500

@app.route('/')
def home():
    return "🔐 Бот работает!"

@app.route('/health')
def health():
    return "OK", 200

# ==================== ЗАПУСК ====================

if __name__ == '__main__':
    print("🚀 Запуск бота...")
    
    # Удаляем старый вебхук
    bot.remove_webhook()
    time.sleep(1)
    
    # Устанавливаем новый
    webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/webhook"
    bot.set_webhook(url=webhook_url)
    
    print(f"✅ Вебхук: {webhook_url}")
    app.run(host='0.0.0.0', port=PORT)
