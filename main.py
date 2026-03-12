import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import random
import string
import sqlite3
from datetime import datetime
from flask import Flask, request, render_template_string, redirect, url_for, session
import time
import logging
import re

# ==================== НАСТРОЙКИ ====================
TOKEN = os.environ.get('BOT_TOKEN')
PORT = int(os.environ.get('PORT', 10000))
ADMIN_PASSWORD = '150107'  # Пароль для админки (ты просил)
ADMIN_USERNAME = 'admin'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey')

# Временные данные для ожидания ввода
temp_data = {}

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
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
    c.execute('''CREATE TABLE IF NOT EXISTS moves
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  room_code TEXT,
                  player_id INTEGER,
                  player_name TEXT,
                  guess TEXT,
                  matches INTEGER,
                  move_number INTEGER,
                  created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS game_chat
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  room_code TEXT,
                  player_id INTEGER,
                  player_name TEXT,
                  message TEXT,
                  created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (user_id INTEGER PRIMARY KEY,
                  games_total INTEGER DEFAULT 0,
                  games_won INTEGER DEFAULT 0,
                  games_lost INTEGER DEFAULT 0,
                  username TEXT,
                  first_name TEXT,
                  last_active TEXT,
                  is_banned INTEGER DEFAULT 0,
                  ban_reason TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS rating
                 (user_id INTEGER PRIMARY KEY,
                  rating_score INTEGER DEFAULT 1000)''')
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

init_db()

# ==================== РАБОТА С БД ====================
def execute_query(query, params=(), fetch_one=False, fetch_all=False, commit=False):
    conn = sqlite3.connect('game.db')
    try:
        c = conn.cursor()
        c.execute(query, params)
        if commit:
            conn.commit()
            return True
        if fetch_one:
            return c.fetchone()
        if fetch_all:
            return c.fetchall()
        return True
    except Exception as e:
        logger.error(f"DB error: {e}")
        return None
    finally:
        conn.close()

def init_player(user_id, username, first_name):
    now = datetime.now().isoformat()
    user = execute_query('SELECT user_id FROM stats WHERE user_id = ?', (user_id,), fetch_one=True)
    if not user:
        execute_query('INSERT INTO stats (user_id, username, first_name, last_active) VALUES (?,?,?,?)',
                      (user_id, username, first_name, now), commit=True)
        execute_query('INSERT INTO rating (user_id) VALUES (?)', (user_id,), commit=True)
        return True
    else:
        execute_query('UPDATE stats SET last_active = ? WHERE user_id = ?', (now, user_id), commit=True)
        return False

def check_banned(user_id):
    res = execute_query('SELECT is_banned, ban_reason FROM stats WHERE user_id = ?', (user_id,), fetch_one=True)
    if res and res[0]:
        return True, res[1]
    return False, None

def generate_room_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase, k=4))
        if not execute_query('SELECT code FROM rooms WHERE code = ?', (code,), fetch_one=True):
            return code

def create_room(creator_id, creator_name, difficulty):
    code = generate_room_code()
    now = datetime.now().isoformat()
    execute_query('''INSERT INTO rooms (code, creator_id, creator_name, difficulty, turn_id, created_at, status)
                     VALUES (?,?,?,?,?,?,?)''',
                  (code, creator_id, creator_name, difficulty, creator_id, now, 'waiting'), commit=True)
    return code

def join_room(code, joiner_id, joiner_name):
    room = execute_query('SELECT * FROM rooms WHERE code = ? AND status = "waiting"', (code,), fetch_one=True)
    if not room:
        return False, "❌ Комната не найдена или уже заполнена"
    if room[1] == joiner_id:
        return False, "❌ Нельзя играть с самим собой"
    execute_query('UPDATE rooms SET joiner_id = ?, joiner_name = ?, status = "setting" WHERE code = ?',
                  (joiner_id, joiner_name, code), commit=True)
    return True, code

def set_code(room_code, player_id, secret):
    room = execute_query('SELECT * FROM rooms WHERE code = ?', (room_code,), fetch_one=True)
    if not room:
        return False, "❌ Комната не найдена", None
    if len(secret) != room[5]:
        return False, f"❌ Нужно {room[5]} цифр", None
    if not secret.isdigit():
        return False, "❌ Только цифры", None

    if player_id == room[1]:
        execute_query('UPDATE rooms SET creator_code = ? WHERE code = ?', (secret, room_code), commit=True)
    elif player_id == room[2]:
        execute_query('UPDATE rooms SET joiner_code = ? WHERE code = ?', (secret, room_code), commit=True)
    else:
        return False, "❌ Ты не в этой игре", None

    codes = execute_query('SELECT creator_code, joiner_code FROM rooms WHERE code = ?', (room_code,), fetch_one=True)
    if codes and codes[0] and codes[1]:
        execute_query('UPDATE rooms SET status = "playing", turn_id = ? WHERE code = ?', (room[1], room_code), commit=True)
        return True, "start", room
    return True, "waiting", None

def check_guess(secret, guess):
    return sum(1 for i in range(len(secret)) if secret[i] == guess[i])

def make_move(room_code, player_id, player_name, guess):
    room = execute_query('SELECT * FROM rooms WHERE code = ? AND status = "playing"', (room_code,), fetch_one=True)
    if not room:
        return False, "❌ Игра не найдена", 0, 0, None
    if player_id != room[9]:
        return False, "⏳ Сейчас не твой ход", 0, 0, None
    if len(guess) != room[5]:
        return False, f"❌ Нужно {room[5]} цифр", 0, 0, None
    if not guess.isdigit():
        return False, "❌ Только цифры", 0, 0, None

    if player_id == room[1]:
        secret = room[7]  # joiner_code
        opponent_id = room[2]
    else:
        secret = room[6]  # creator_code
        opponent_id = room[1]

    move_count = execute_query('SELECT COUNT(*) FROM moves WHERE room_code = ?', (room_code,), fetch_one=True)[0]
    move_num = move_count + 1
    matches = check_guess(secret, guess)

    execute_query('''INSERT INTO moves (room_code, player_id, player_name, guess, matches, move_number, created_at)
                     VALUES (?,?,?,?,?,?,?)''',
                  (room_code, player_id, player_name, guess, matches, move_num, datetime.now().isoformat()), commit=True)

    if matches == room[5]:
        execute_query('UPDATE rooms SET status = "finished", winner_id = ? WHERE code = ?', (player_id, room_code), commit=True)
        # Обновление статистики и рейтинга
        execute_query('UPDATE stats SET games_total = games_total + 1, games_won = games_won + 1 WHERE user_id = ?', (player_id,), commit=True)
        execute_query('UPDATE stats SET games_total = games_total + 1, games_lost = games_lost + 1 WHERE user_id = ?', (opponent_id,), commit=True)
        # Рейтинг: победитель +15, проигравший -10 (минимум 100)
        r_win = execute_query('SELECT rating_score FROM rating WHERE user_id = ?', (player_id,), fetch_one=True)[0]
        execute_query('UPDATE rating SET rating_score = ? WHERE user_id = ?', (r_win + 15, player_id), commit=True)
        r_loss = execute_query('SELECT rating_score FROM rating WHERE user_id = ?', (opponent_id,), fetch_one=True)[0]
        new_loss = max(100, r_loss - 10)
        execute_query('UPDATE rating SET rating_score = ? WHERE user_id = ?', (new_loss, opponent_id), commit=True)
        return True, "win", matches, opponent_id, move_num, secret
    else:
        execute_query('UPDATE rooms SET turn_id = ? WHERE code = ?', (opponent_id, room_code), commit=True)
        return True, "continue", matches, opponent_id, move_num, None

def get_game_info(room_code, user_id):
    room = execute_query('SELECT * FROM rooms WHERE code = ?', (room_code,), fetch_one=True)
    if not room:
        return None
    if user_id not in (room[1], room[2]):
        return None
    moves = execute_query('''SELECT player_id, player_name, guess, matches, move_number FROM moves
                             WHERE room_code = ? ORDER BY move_number DESC LIMIT 10''', (room_code,), fetch_all=True) or []
    total_moves = execute_query('SELECT COUNT(*) FROM moves WHERE room_code = ?', (room_code,), fetch_one=True)[0]
    return {'room': room, 'moves': moves, 'total_moves': total_moves}

def save_chat(room_code, player_id, player_name, msg):
    execute_query('INSERT INTO game_chat (room_code, player_id, player_name, message, created_at) VALUES (?,?,?,?,?)',
                  (room_code, player_id, player_name, msg, datetime.now().isoformat()), commit=True)

def get_chat(room_code, limit=20):
    return execute_query('''SELECT player_name, message, created_at FROM game_chat
                            WHERE room_code = ? ORDER BY created_at DESC LIMIT ?''',
                         (room_code, limit), fetch_all=True) or []

# ==================== КЛАВИАТУРЫ ====================
def main_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎮 СОЗДАТЬ ИГРУ", callback_data="menu_create"),
        InlineKeyboardButton("🔑 ПРИСОЕДИНИТЬСЯ", callback_data="menu_join"),
        InlineKeyboardButton("📊 СТАТИСТИКА", callback_data="menu_stats"),
        InlineKeyboardButton("🏆 РЕЙТИНГ", callback_data="menu_top"),
        InlineKeyboardButton("❓ ПРАВИЛА", callback_data="menu_help")
    )
    return markup

def difficulty_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("4 цифры", callback_data="diff_4"),
        InlineKeyboardButton("6 цифр", callback_data="diff_6"),
        InlineKeyboardButton("8 цифр", callback_data="diff_8"),
        InlineKeyboardButton("12 цифр", callback_data="diff_12"),
        InlineKeyboardButton("◀️ НАЗАД", callback_data="back_main")
    )
    return markup

def game_menu(room_code, is_your_turn):
    markup = InlineKeyboardMarkup(row_width=2)
    if is_your_turn:
        markup.add(InlineKeyboardButton("🎯 СДЕЛАТЬ ХОД", callback_data=f"move_{room_code}"))
    markup.add(
        InlineKeyboardButton("💬 ЧАТ", callback_data=f"chat_{room_code}"),
        InlineKeyboardButton("🔄 ОБНОВИТЬ", callback_data=f"refresh_{room_code}"),
        InlineKeyboardButton("🏳️ СДАТЬСЯ", callback_data=f"surrender_{room_code}")
    )
    return markup

def chat_menu(room_code):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔄 ОБНОВИТЬ ЧАТ", callback_data=f"chat_refresh_{room_code}"),
        InlineKeyboardButton("⬅️ К ИГРЕ", callback_data=f"back_to_game_{room_code}")
    )
    return markup

# ==================== КОМАНДЫ ====================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    name = message.from_user.first_name or "Игрок"
    username = message.from_user.username or name
    banned, _ = check_banned(user_id)
    if banned:
        bot.send_message(message.chat.id, "🚫 Вы заблокированы")
        return
    init_player(user_id, username, name)
    bot.send_message(message.chat.id,
                     f"🔐 Привет, {name}!\n\nСыграй с другом в игру Взлом замка!",
                     reply_markup=main_menu())

# ==================== КОЛЛБЭКИ ====================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    name = call.from_user.first_name or "Игрок"
    banned, _ = check_banned(user_id)
    if banned:
        bot.answer_callback_query(call.id, "🚫 Вы заблокированы", show_alert=True)
        return

    data = call.data

    if data == "menu_create":
        bot.edit_message_text("🎮 Создание игры\n\nВыбери сколько цифр будет в коде:",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=difficulty_menu())
    elif data == "menu_join":
        bot.edit_message_text("🔑 Присоединение к игре\n\nВведи код комнаты из 4 букв:",
                              call.message.chat.id, call.message.message_id)
        temp_data[user_id] = {'action': 'join'}
        bot.register_next_step_handler_by_chat_id(call.message.chat.id, process_join)
    elif data == "menu_stats":
        stats = execute_query('''SELECT games_total, games_won, games_lost FROM stats WHERE user_id = ?''',
                              (user_id,), fetch_one=True)
        rating = execute_query('SELECT rating_score FROM rating WHERE user_id = ?', (user_id,), fetch_one=True)[0]
        if stats and stats[0] > 0:
            winrate = round((stats[1] / stats[0] * 100), 1)
            text = f"📊 Статистика\nРейтинг: {rating}\nИгр: {stats[0]}\nПобед: {stats[1]}\nПоражений: {stats[2]}\n% побед: {winrate}%"
        else:
            text = "📊 У тебя пока нет игр"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=main_menu())
    elif data == "menu_top":
        top = execute_query('''SELECT s.first_name, r.rating_score FROM rating r
                                JOIN stats s ON r.user_id = s.user_id
                                WHERE s.games_total > 0 ORDER BY r.rating_score DESC LIMIT 10''', fetch_all=True)
        if top:
            text = "🏆 ТОП ИГРОКОВ\n\n"
            for i, (name, rating) in enumerate(top, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                text += f"{medal} {name} – {rating}\n"
        else:
            text = "🏆 Топ пока пуст"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=main_menu())
    elif data == "menu_help":
        text = ("🔐 Правила:\n1. Каждый загадывает свой код из цифр.\n"
                "2. Ходите по очереди, угадывая код соперника.\n"
                "3. После каждой догадки бот показывает сколько цифр совпало ПО ПОЗИЦИЯМ.\n"
                "Пример: загадано 3781, догадка 9713 → 1 совпадение (цифра 7 на второй позиции).\n"
                "Победа: угадал все цифры первым.")
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=main_menu())
    elif data == "back_main":
        bot.edit_message_text(f"🔐 Привет, {name}!\n\nСыграй с другом в игру Взлом замка!",
                              call.message.chat.id, call.message.message_id, reply_markup=main_menu())
    elif data.startswith("diff_"):
        diff = int(data.split('_')[1])
        code = create_room(user_id, name, diff)
        bot.edit_message_text(f"✅ Комната создана!\nКод: {code}\nСложность: {diff} цифр\n\n"
                              f"Отправь код другу.\nОжидаем второго игрока...\n\n"
                              f"Загадай свой код: напиши {diff} цифр",
                              call.message.chat.id, call.message.message_id)
        temp_data[user_id] = {'action': 'set_code', 'room': code}
    elif data.startswith("move_"):
        room_code = data.replace("move_", "")
        info = get_game_info(room_code, user_id)
        if not info or info['room'][8] != 'playing':
            bot.answer_callback_query(call.id, "❌ Игра не найдена", show_alert=True)
            return
        if info['room'][9] != user_id:
            bot.answer_callback_query(call.id, "⏳ Сейчас не твой ход", show_alert=True)
            return
        move_num = info['total_moves'] + 1
        diff = info['room'][5]
        bot.edit_message_text(f"🎯 Твой ход\nПопытка №{move_num}\nВведи {diff} цифр:",
                              call.message.chat.id, call.message.message_id)
        temp_data[user_id] = {'action': 'make_move', 'room': room_code}
    elif data.startswith("refresh_"):
        room_code = data.replace("refresh_", "")
        show_game_status(call.message.chat.id, call.message.message_id, room_code, user_id)
    elif data.startswith("chat_"):
        if data.startswith("chat_refresh_"):
            room_code = data.replace("chat_refresh_", "")
            show_chat(call.message.chat.id, call.message.message_id, room_code, user_id)
        else:
            room_code = data.replace("chat_", "")
            show_chat(call.message.chat.id, call.message.message_id, room_code, user_id)
    elif data.startswith("back_to_game_"):
        room_code = data.replace("back_to_game_", "")
        show_game_status(call.message.chat.id, call.message.message_id, room_code, user_id)
    elif data.startswith("surrender_"):
        room_code = data.replace("surrender_", "")
        room = execute_query('SELECT * FROM rooms WHERE code = ? AND status = "playing"', (room_code,), fetch_one=True)
        if room:
            winner_id = room[2] if user_id == room[1] else room[1]
            execute_query('UPDATE rooms SET status = "finished", winner_id = ? WHERE code = ?', (winner_id, room_code), commit=True)
            execute_query('UPDATE stats SET games_total = games_total + 1, games_lost = games_lost + 1 WHERE user_id = ?', (user_id,), commit=True)
            execute_query('UPDATE stats SET games_total = games_total + 1, games_won = games_won + 1 WHERE user_id = ?', (winner_id,), commit=True)
            # Рейтинг: сдавшийся -10, победитель +15
            r_loss = execute_query('SELECT rating_score FROM rating WHERE user_id = ?', (user_id,), fetch_one=True)[0]
            execute_query('UPDATE rating SET rating_score = ? WHERE user_id = ?', (max(100, r_loss - 10), user_id), commit=True)
            r_win = execute_query('SELECT rating_score FROM rating WHERE user_id = ?', (winner_id,), fetch_one=True)[0]
            execute_query('UPDATE rating SET rating_score = ? WHERE user_id = ?', (r_win + 15, winner_id), commit=True)

            bot.edit_message_text("🏳️ Ты сдался", call.message.chat.id, call.message.message_id, reply_markup=main_menu())
            bot.send_message(winner_id, "🏆 Соперник сдался! Ты победил!", reply_markup=main_menu())
    else:
        bot.answer_callback_query(call.id, "⏳")

# ==================== ОБРАБОТЧИКИ ТЕКСТА ====================
def process_join(message):
    user_id = message.from_user.id
    name = message.from_user.first_name or "Игрок"
    code = message.text.strip().upper()
    if user_id not in temp_data or temp_data[user_id].get('action') != 'join':
        return
    if not re.match(r'^[A-Z]{4}$', code):
        bot.send_message(message.chat.id, "❌ Неверный формат. Код должен быть из 4 букв.")
        bot.send_message(message.chat.id, "🔐 Главное меню:", reply_markup=main_menu())
        del temp_data[user_id]
        return
    success, res = join_room(code, user_id, name)
    if not success:
        bot.send_message(message.chat.id, res)
        bot.send_message(message.chat.id, "🔐 Главное меню:", reply_markup=main_menu())
        del temp_data[user_id]
        return
    diff = execute_query('SELECT difficulty FROM rooms WHERE code = ?', (code,), fetch_one=True)[0]
    bot.send_message(message.chat.id, f"✅ Ты присоединился к игре!\nКомната: {code}\nСложность: {diff} цифр\n\nЗагадай свой код: напиши {diff} цифр")
    temp_data[user_id] = {'action': 'set_code', 'room': code}

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    user_id = message.from_user.id
    name = message.from_user.first_name or "Игрок"
    text = message.text.strip()
    banned, _ = check_banned(user_id)
    if banned:
        bot.send_message(message.chat.id, "🚫 Вы заблокированы")
        return

    # Если не в режиме ожидания – возможно, сообщение в чат
    if user_id not in temp_data:
        active = execute_query('''SELECT code FROM rooms WHERE (creator_id = ? OR joiner_id = ?) AND status = "playing"''',
                               (user_id, user_id), fetch_one=True)
        if active:
            room_code = active[0]
            save_chat(room_code, user_id, name, text)
            # Отправить сопернику
            room = execute_query('SELECT creator_id, joiner_id FROM rooms WHERE code = ?', (room_code,), fetch_one=True)
            opp = room[1] if user_id == room[0] else room[0]
            bot.send_message(opp, f"💬 {name}: {text}")
            bot.send_message(message.chat.id, "✅ Сообщение отправлено")
        else:
            bot.send_message(message.chat.id, "🔑 Используй кнопки меню", reply_markup=main_menu())
        return

    action = temp_data[user_id].get('action')
    if action == 'set_code':
        room_code = temp_data[user_id]['room']
        ok, msg, room = set_code(room_code, user_id, text)
        if not ok:
            bot.send_message(message.chat.id, msg)
            return
        if msg == "start":
            # Оба кода установлены – начинаем
            creator, joiner = room[1], room[2]
            bot.send_message(creator, "✅ Код принят!\n🎮 Игра началась! Твой ход!")
            bot.send_message(joiner, "✅ Код принят!\n🎮 Игра началась! Ход соперника!")
            show_game_status(creator, None, room_code, creator)
            show_game_status(joiner, None, room_code, joiner)
            del temp_data[user_id]
        else:
            bot.send_message(message.chat.id, "✅ Код сохранён. Ожидаем соперника...")
            del temp_data[user_id]
    elif action == 'make_move':
        room_code = temp_data[user_id]['room']
        ok, status, matches, opp, move_num, secret = make_move(room_code, user_id, name, text)
        if not ok:
            bot.send_message(message.chat.id, status)
            return
        total = execute_query('SELECT difficulty FROM rooms WHERE code = ?', (room_code,), fetch_one=True)[0]
        result_text = f"🎯 Ход #{move_num}\n{name}: {text}\n✅ Совпадений: {matches} из {total}"
        bot.send_message(message.chat.id, result_text)
        bot.send_message(opp, result_text)
        if status == "win":
            bot.send_message(user_id, f"🏆 ПОБЕДА! Ты угадал код за {move_num} ходов!", reply_markup=main_menu())
            bot.send_message(opp, f"💔 Поражение. Твой код: {secret}. Соперник угадал за {move_num} ходов.", reply_markup=main_menu())
            if user_id in temp_data:
                del temp_data[user_id]
            if opp in temp_data:
                del temp_data[opp]
        else:
            bot.send_message(opp, "⏳ Твой ход! Соперник сделал догадку.")
            show_game_status(message.chat.id, None, room_code, user_id)
            show_game_status(opp, None, room_code, opp)
            del temp_data[user_id]

def show_game_status(chat_id, message_id, room_code, user_id):
    info = get_game_info(room_code, user_id)
    if not info:
        bot.send_message(chat_id, "❌ Игра не найдена", reply_markup=main_menu())
        return
    room = info['room']
    moves = info['moves']
    total = info['total_moves']

    # Определяем имя соперника
    if user_id == room[1]:
        opp_name = room[3] if room[3] else "Соперник"
        opp_id = room[2]
    else:
        opp_name = room[1]  # имя создателя
        opp_id = room[1]

    # Если имя соперника не строка, попробуем взять из статистики
    if isinstance(opp_name, int):
        name_data = execute_query('SELECT first_name FROM stats WHERE user_id = ?', (opp_id,), fetch_one=True)
        opp_name = name_data[0] if name_data else "Соперник"

    text = f"🎮 Игра\nКомната: {room_code}\nСложность: {room[5]} цифр\nСоперник: {opp_name}\nХодов: {total}\n\n"
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
        for pid, pname, guess, matches, move_num in moves[:5]:
            if pid == user_id:
                prefix = "Ты:"
            else:
                prefix = f"{opp_name}:"
            text += f"#{move_num} {prefix} {guess} → {matches} совп.\n"
    else:
        text += "Пока нет ходов\n"

    is_your_turn = (room[8] == 'playing' and room[9] == user_id)
    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=game_menu(room_code, is_your_turn))
    else:
        bot.send_message(chat_id, text, reply_markup=game_menu(room_code, is_your_turn))

def show_chat(chat_id, message_id, room_code, user_id):
    msgs = get_chat(room_code, 20)
    text = f"💬 ЧАТ КОМНАТЫ {room_code}\n\n"
    if msgs:
        for name, msg, ts in reversed(msgs):
            t = ts[11:16] if ts else ""
            text += f"[{t}] {name}: {msg}\n"
    else:
        text += "Пока нет сообщений\n\n"
    text += "\nПросто отправь сообщение, чтобы написать в чат"
    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=chat_menu(room_code))
    else:
        bot.send_message(chat_id, text, reply_markup=chat_menu(room_code))

# ==================== АДМИН-ПАНЕЛЬ (простая) ====================
ADMIN_LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Админка</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 50px;">
    <h2>🔐 Вход в админ-панель</h2>
    {% if error %}<p style="color:red">{{ error }}</p>{% endif %}
    <form method="post">
        <input type="text" name="username" placeholder="Логин" required><br><br>
        <input type="password" name="password" placeholder="Пароль" required><br><br>
        <button type="submit">Войти</button>
    </form>
</body>
</html>
'''

ADMIN_DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Админка</title></head>
<body style="font-family: sans-serif; padding: 20px;">
    <h2>👑 Панель администратора</h2>
    <p><a href="/admin/logout">Выйти</a></p>
    <h3>Статистика</h3>
    <ul>
        <li>Всего игроков: {{ total_players }}</li>
        <li>Активных игр: {{ active_games }}</li>
        <li>Забанено: {{ banned_count }}</li>
    </ul>
    <h3>Игроки</h3>
    <table border="1" cellpadding="5">
        <tr><th>ID</th><th>Имя</th><th>Username</th><th>Игр</th><th>Побед</th><th>Рейтинг</th><th>Бан</th><th>Действие</th></tr>
        {% for p in players %}
        <tr>
            <td>{{ p.id }}</td>
            <td>{{ p.name }}</td>
            <td>@{{ p.username }}</td>
            <td>{{ p.games }}</td>
            <td>{{ p.wins }}</td>
            <td>{{ p.rating }}</td>
            <td>{% if p.banned %}✅{% else %}❌{% endif %}</td>
            <td>
                {% if not p.banned %}
                <form action="/admin/ban" method="post" style="display:inline">
                    <input type="hidden" name="user_id" value="{{ p.id }}">
                    <input type="text" name="reason" placeholder="Причина" required>
                    <button type="submit">Забанить</button>
                </form>
                {% else %}
                <form action="/admin/unban" method="post" style="display:inline">
                    <input type="hidden" name="user_id" value="{{ p.id }}">
                    <button type="submit">Разбанить</button>
                </form>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USERNAME and request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template_string(ADMIN_LOGIN_HTML, error="Неверные данные")
    return render_template_string(ADMIN_LOGIN_HTML, error=None)

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    total_players = execute_query('SELECT COUNT(*) FROM stats', fetch_one=True)[0]
    active_games = execute_query('SELECT COUNT(*) FROM rooms WHERE status = "playing"', fetch_one=True)[0]
    banned_count = execute_query('SELECT COUNT(*) FROM stats WHERE is_banned = 1', fetch_one=True)[0]
    players_data = execute_query('''SELECT s.user_id, s.first_name, s.username, s.games_total, s.games_won,
                                            r.rating_score, s.is_banned
                                     FROM stats s LEFT JOIN rating r ON s.user_id = r.user_id
                                     ORDER BY r.rating_score DESC LIMIT 50''', fetch_all=True) or []
    players = []
    for row in players_data:
        players.append({
            'id': row[0],
            'name': row[1],
            'username': row[2] or '',
            'games': row[3],
            'wins': row[4],
            'rating': row[5] or 1000,
            'banned': row[6]
        })
    return render_template_string(ADMIN_DASHBOARD_HTML, total_players=total_players,
                                  active_games=active_games, banned_count=banned_count, players=players)

@app.route('/admin/ban', methods=['POST'])
def admin_ban():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    user_id = int(request.form['user_id'])
    reason = request.form['reason']
    execute_query('UPDATE stats SET is_banned = 1, ban_reason = ? WHERE user_id = ?', (reason, user_id), commit=True)
    try:
        bot.send_message(user_id, f"🚫 Вы забанены. Причина: {reason}")
    except:
        pass
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/unban', methods=['POST'])
def admin_unban():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    user_id = int(request.form['user_id'])
    execute_query('UPDATE stats SET is_banned = 0, ban_reason = NULL WHERE user_id = ?', (user_id,), commit=True)
    try:
        bot.send_message(user_id, "✅ Вы разблокированы.")
    except:
        pass
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))

# ==================== ВЕБХУК ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        bot.process_new_updates([telebot.types.Update.de_json(request.get_data().decode('utf-8'))])
        return 'OK', 200
    except Exception as e:
        logger.error(e)
        return 'ERROR', 500

@app.route('/')
def home():
    return "🔐 Game Bot is running! <a href='/admin'>Admin</a>"

@app.route('/health')
def health():
    return "OK", 200

if __name__ == '__main__':
    logger.info("Бот запускается...")
    bot.remove_webhook()
    time.sleep(1)
    webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/webhook"
    bot.set_webhook(url=webhook_url)
    logger.info(f"Вебхук установлен на {webhook_url}")
    app.run(host='0.0.0.0', port=PORT)
