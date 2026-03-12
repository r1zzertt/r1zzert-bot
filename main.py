import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import random
import string
import sqlite3
from datetime import datetime
from flask import Flask, request
import time
import logging

# ==================== НАСТРОЙКИ ====================
TOKEN = os.environ.get('BOT_TOKEN')
PORT = int(os.environ.get('PORT', 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Временные данные
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
                  created_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (user_id INTEGER PRIMARY KEY,
                  games INTEGER DEFAULT 0,
                  wins INTEGER DEFAULT 0,
                  losses INTEGER DEFAULT 0,
                  username TEXT,
                  first_name TEXT)''')
    
    conn.commit()
    conn.close()

init_db()

# ==================== ПРИВЕТСТВИЯ ====================
WELCOME_MESSAGES = [
    "🔐 **Добро пожаловать в игру!**\n\nПривет, {name}! Готов взломать замок?",
    "🎯 **Взлом замка**\n\nО, {name}! Новый игрок? Сейчас научим!",
    "🔑 **Привет, {name}!**\n\nЗагадывай цифры, взламывай коды, побеждай!",
    "⚡️ **{name} в игре!**\n\nСыграем? Создай игру или присоединяйся!"
]

CREATOR_WAIT_MESSAGES = [
    "🔐 **Комната создана!**\n\nКод: `{code}`\nСложность: {diff} цифр\n\n🔑 Отправь этот код другу\n⏳ Ожидаем второго игрока...\n\n📝 **Загадай свой секретный код:**\nНапиши {diff} цифр",
    "🎯 **Игра создана!**\n\nКод комнаты: `{code}`\nСложность: {diff}\n\n👥 Пригласи друга\n\n🤫 **Загадай код:** {diff} цифр"
]

JOIN_SUCCESS_MESSAGES = [
    "✅ **Ты присоединился!**\n\nКомната: `{code}`\nСложность: {diff} цифр\n\n🤫 **Загадай свой секретный код:**\nНапиши {diff} цифр",
    "🔑 **Подключение успешно!**\n\nКод: `{code}`\nСложность: {diff}\n\n🎯 **Твоя очередь загадывать:**\nНапиши {diff} цифр"
]

GAME_START_MESSAGES = {
    'creator': [
        "🎮 **ИГРА НАЧАЛАСЬ!**\n\nТы ходишь ПЕРВЫМ!\nПопробуй взломать код соперника",
        "⚡️ **ТВОЙ ХОД!**\n\nСоперник загадал код. Угадай его!"
    ],
    'joiner': [
        "🎮 **ИГРА НАЧАЛАСЬ!**\n\nСейчас ходит СОЗДАТЕЛЬ\nЖди своей очереди",
        "⏳ **Ожидаем хода соперника**\n\nКак только он сходит - я сообщу"
    ]
}

YOUR_TURN_MESSAGES = [
    "🎯 **ТВОЙ ХОД!**\n\nВведи {diff} цифр, чтобы взломать код соперника",
    "⚡️ **УГАДЫВАЙ!**\n\nПопытка #{move_num}\nВведи {diff} цифр"
]

OPPONENT_TURN_MESSAGES = [
    "⏳ **ХОД СОПЕРНИКА**\n\nСейчас {name} пытается взломать твой код...",
    "🤔 **Соперник думает...**\n\nКак только сделает ход - я покажу результат"
]

MOVE_RESULT_MESSAGES = [
    "🎯 **Результат хода**\n\n{name}: `{guess}`\n✅ Совпадений: {matches} из {total}",
    "📊 **Попытка #{move_num}**\n\n{name}: `{guess}`\n🎯 Угадано цифр: {matches}/{total}"
]

WIN_MESSAGES = {
    'winner': [
        "🏆 **ПОБЕДА!** 🏆\n\nТы взломал код!\nВсе {total} цифр угаданы!\n\nПоздравляю, чемпион!",
        "🎉 **ТЫ ВЫИГРАЛ!** 🎉\n\nКод соперника раскрыт!\nОтличная работа!"
    ],
    'loser': [
        "💔 **ПОРАЖЕНИЕ**\n\nСоперник угадал твой код\nКод был: `{code}`\n\nВ следующий раз повезет!",
        "😢 **Ты проиграл**\n\nТвой секретный код `{code}` раскрыт\nСыграй еще!"
    ]
}

SURRENDER_MESSAGES = {
    'surrendered': [
        "🏳️ **Ты сдался**\n\nИгра завершена. Победа присуждена сопернику",
        "⚔️ **Капитуляция**\n\nСоперник победил по твоему решению"
    ],
    'winner': [
        "🏆 **ПОБЕДА!**\n\nСоперник сдался!\nТы выиграл не прилагая усилий",
        "🎉 **Техническая победа!**\n\nПротивник признал свое поражение"
    ]
}

STATS_MESSAGES = {
    'has_stats': [
        "📊 **Твоя статистика**\n\n"
        "🎮 Всего игр: {games}\n"
        "🏆 Побед: {wins}\n"
        "💔 Поражений: {losses}\n"
        "📈 Процент побед: {winrate}%\n\n"
        "🔐 Играй еще!",
        
        "📈 **Личная статистика**\n\n"
        "⚔️ Сыграно матчей: {games}\n"
        "🥇 Побед: {wins}\n"
        "🥈 Поражений: {losses}\n"
        "📊 Винрейт: {winrate}%"
    ],
    'no_stats': [
        "📊 **Ты еще не играл**\n\nСоздай игру или присоединись к другу!",
        "🎯 **Нулевая статистика**\n\nПора начинать играть!"
    ]
}

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

def create_room(creator_id, creator_name, difficulty):
    """Создает новую комнату"""
    code = generate_room_code()
    now = datetime.now().isoformat()
    
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('''INSERT INTO rooms 
                 (code, creator_id, creator_name, difficulty, turn_id, created_at)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (code, creator_id, creator_name, difficulty, creator_id, now))
    conn.commit()
    conn.close()
    return code

def join_room(code, joiner_id, joiner_name):
    """Присоединение к комнате"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    c.execute('SELECT * FROM rooms WHERE code = ? AND status = "waiting"', (code,))
    room = c.fetchone()
    
    if not room:
        conn.close()
        return False, "❌ Комната не найдена или уже заполнена"
    
    if room[1] == joiner_id:
        conn.close()
        return False, "❌ Нельзя играть с самим собой"
    
    c.execute('''UPDATE rooms 
                 SET joiner_id = ?, joiner_name = ?, status = "setting"
                 WHERE code = ?''', (joiner_id, joiner_name, code))
    conn.commit()
    conn.close()
    
    # Сохраняем в статистику
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO stats (user_id, username, first_name)
                 VALUES (?, ?, ?)''', (joiner_id, joiner_name, joiner_name))
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
        return False, "❌ Комната не найдена"
    
    # Проверка длины
    if len(secret) != room[4]:
        conn.close()
        return False, f"❌ Нужно {room[4]} цифр, а ты ввел {len(secret)}"
    
    if not secret.isdigit():
        conn.close()
        return False, "❌ Только цифры можно использовать"
    
    # Кто устанавливает
    if player_id == room[1]:  # создатель
        c.execute('UPDATE rooms SET creator_code = ? WHERE code = ?', (secret, room_code))
    elif player_id == room[2]:  # присоединившийся
        c.execute('UPDATE rooms SET joiner_code = ? WHERE code = ?', (secret, room_code))
    else:
        conn.close()
        return False, "❌ Ты не в этой игре"
    
    # Проверка, готовы ли оба
    c.execute('SELECT creator_code, joiner_code FROM rooms WHERE code = ?', (room_code,))
    codes = c.fetchone()
    
    if codes[0] and codes[1]:  # оба кода установлены
        c.execute('''UPDATE rooms 
                     SET status = "playing", turn_id = ?
                     WHERE code = ?''', (room[1], room_code))
        conn.commit()
        conn.close()
        return True, "start", room[1], room[2], room[3], room[4]
    
    conn.commit()
    conn.close()
    return True, "waiting", None, None, None, None

def check_guess(secret, guess):
    """Считает совпадения по позициям"""
    matches = 0
    for i in range(len(secret)):
        if secret[i] == guess[i]:
            matches += 1
    return matches

def make_move(room_code, player_id, player_name, guess):
    """Сделать ход"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    c.execute('SELECT * FROM rooms WHERE code = ? AND status = "playing"', (room_code,))
    room = c.fetchone()
    
    if not room:
        conn.close()
        return False, "❌ Игра не найдена"
    
    # Проверка очереди
    if player_id != room[7]:
        conn.close()
        return False, "⏳ Сейчас не твой ход!"
    
    # Проверка длины
    if len(guess) != room[4]:
        conn.close()
        return False, f"❌ Нужно {room[4]} цифр"
    
    if not guess.isdigit():
        conn.close()
        return False, "❌ Только цифры"
    
    # Определяем код соперника
    if player_id == room[1]:  # создатель
        secret = room[6]  # код присоединившегося
        opponent_id = room[2]
        opponent_name = room[3]
    else:  # присоединившийся
        secret = room[5]  # код создателя
        opponent_id = room[1]
        opponent_name = room[1]  # имя создателя получим отдельно
    
    # Получаем имя оппонента если нужно
    if opponent_id == room[1]:
        opponent_name = room[1]  # имя создателя
    else:
        opponent_name = room[3]
    
    # Считаем ходы для нумерации
    c.execute('SELECT COUNT(*) FROM moves WHERE room_code = ?', (room_code,))
    move_num = c.fetchone()[0] + 1
    
    # Считаем совпадения
    matches = check_guess(secret, guess)
    
    # Сохраняем ход
    c.execute('''INSERT INTO moves 
                 (room_code, player_id, player_name, guess, matches, created_at)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (room_code, player_id, player_name, guess, matches, datetime.now().isoformat()))
    
    # Проверка победы
    if matches == room[4]:
        c.execute('''UPDATE rooms SET status = "finished", winner_id = ?
                     WHERE code = ?''', (player_id, room_code))
        
        # Обновляем статистику
        c.execute('''UPDATE stats SET games = games + 1, wins = wins + 1
                     WHERE user_id = ?''', (player_id,))
        c.execute('''UPDATE stats SET games = games + 1, losses = losses + 1
                     WHERE user_id = ?''', (opponent_id,))
        
        conn.commit()
        conn.close()
        return True, "win", matches, opponent_id, opponent_name, move_num, secret
    else:
        # Меняем очередь
        c.execute('UPDATE rooms SET turn_id = ? WHERE code = ?', (opponent_id, room_code))
        conn.commit()
        conn.close()
        return True, "continue", matches, opponent_id, opponent_name, move_num, None

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
    c.execute('''SELECT player_id, player_name, guess, matches FROM moves 
                 WHERE room_code = ? ORDER BY created_at DESC LIMIT 10''', (room_code,))
    moves = c.fetchall()
    
    # Считаем общее количество ходов
    c.execute('SELECT COUNT(*) FROM moves WHERE room_code = ?', (room_code,))
    total_moves = c.fetchone()[0]
    
    conn.close()
    
    # Определяем роли
    is_creator = (user_id == room[1])
    is_joiner = (user_id == room[2])
    
    if not (is_creator or is_joiner):
        return None
    
    return {
        'room': room,
        'moves': moves,
        'total_moves': total_moves,
        'is_creator': is_creator,
        'is_joiner': is_joiner,
        'creator_name': room[1],  # имя создателя
        'joiner_name': room[3] if room[3] else 'Ожидание...'
    }

def get_stats(user_id):
    """Получить статистику игрока"""
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('SELECT games, wins, losses, first_name FROM stats WHERE user_id = ?', (user_id,))
    stats = c.fetchone()
    conn.close()
    return stats

# ==================== КЛАВИАТУРЫ ====================

def main_menu():
    """Главное меню"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎮 СОЗДАТЬ ИГРУ", callback_data="menu_create"),
        InlineKeyboardButton("🔑 ПРИСОЕДИНИТЬСЯ", callback_data="menu_join"),
        InlineKeyboardButton("📊 МОЯ СТАТИСТИКА", callback_data="menu_stats"),
        InlineKeyboardButton("❓ КАК ИГРАТЬ", callback_data="menu_help")
    )
    return markup

def difficulty_menu():
    """Выбор сложности"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("4 🔢 цифры", callback_data="diff_4"),
        InlineKeyboardButton("6 🔢 цифр", callback_data="diff_6"),
        InlineKeyboardButton("8 🔢 цифр", callback_data="diff_8"),
        InlineKeyboardButton("12 🔢 цифр", callback_data="diff_12"),
        InlineKeyboardButton("◀️ НАЗАД", callback_data="back_main")
    )
    return markup

def game_menu(room_code, is_your_turn=False, game_status='playing'):
    """Меню во время игры"""
    markup = InlineKeyboardMarkup(row_width=1)
    
    if game_status == 'playing':
        if is_your_turn:
            markup.add(InlineKeyboardButton("🎯 СДЕЛАТЬ ХОД", callback_data=f"move_{room_code}"))
        markup.add(InlineKeyboardButton("🔄 ОБНОВИТЬ СТАТУС", callback_data=f"refresh_{room_code}"))
        markup.add(InlineKeyboardButton("🏳️ СДАТЬСЯ", callback_data=f"surrender_{room_code}"))
    else:
        markup.add(InlineKeyboardButton("🎮 В ГЛАВНОЕ МЕНЮ", callback_data="back_main"))
        markup.add(InlineKeyboardButton("🔄 НОВАЯ ИГРА", callback_data="menu_create"))
    
    return markup

# ==================== КОМАНДЫ ====================

@bot.message_handler(commands=['start'])
def start_cmd(message):
    """Старт"""
    user_id = message.from_user.id
    name = message.from_user.first_name or "Игрок"
    
    # Сохраняем в статистику
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO stats (user_id, username, first_name)
                 VALUES (?, ?, ?)''', (user_id, name, name))
    conn.commit()
    conn.close()
    
    welcome = random.choice(WELCOME_MESSAGES).format(name=name)
    
    bot.send_message(
        message.chat.id,
        welcome,
        reply_markup=main_menu()
    )

@bot.message_handler(commands=['play'])
def play_cmd(message):
    """Быстрый старт"""
    start_cmd(message)

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    """Статистика"""
    user_id = message.from_user.id
    stats = get_stats(user_id)
    
    if stats and stats[0] > 0:
        games, wins, losses, name = stats
        winrate = round((wins / games) * 100, 1)
        text = random.choice(STATS_MESSAGES['has_stats']).format(
            name=name,
            games=games,
            wins=wins,
            losses=losses,
            winrate=winrate
        )
    else:
        text = random.choice(STATS_MESSAGES['no_stats'])
    
    bot.send_message(message.chat.id, text, reply_markup=main_menu())

# ==================== КОЛЛБЭКИ ====================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    name = call.from_user.first_name or "Игрок"
    
    # ===== ГЛАВНОЕ МЕНЮ =====
    if call.data == "menu_create":
        bot.edit_message_text(
            "🎮 **СОЗДАНИЕ НОВОЙ ИГРЫ**\n\n"
            "Выбери количество цифр в коде:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=difficulty_menu()
        )
    
    elif call.data == "menu_join":
        bot.edit_message_text(
            "🔑 **ПРИСОЕДИНЕНИЕ К ИГРЕ**\n\n"
            "Введи код комнаты из 4 букв:\n"
            "📝 Например: `ABCD` или `GAME`\n\n"
            "_Код тебе должен сказать друг_",
            call.message.chat.id,
            call.message.message_id
        )
        temp_data[user_id] = {'action': 'join'}
        bot.register_next_step_handler_by_chat_id(call.message.chat.id, process_join)
    
    elif call.data == "menu_stats":
        stats = get_stats(user_id)
        if stats and stats[0] > 0:
            games, wins, losses, name = stats
            winrate = round((wins / games) * 100, 1)
            text = random.choice(STATS_MESSAGES['has_stats']).format(
                games=games,
                wins=wins,
                losses=losses,
                winrate=winrate
            )
        else:
            text = random.choice(STATS_MESSAGES['no_stats'])
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_menu()
        )
    
    elif call.data == "menu_help":
        text = """
🔐 **ВЗЛОМ ЗАМКА — ПРАВИЛА ИГРЫ**

🎯 **Суть игры:**
Каждый игрок загадывает свой секретный код из цифр. Нужно первым угадать код соперника.

📝 **Как играть:**
1️⃣ Создай игру или присоединись по коду
2️⃣ Загадай свой секретный код
3️⃣ Ходите по очереди, пытаясь угадать код соперника
4️⃣ После каждой догадки бот показывает сколько цифр совпало ПО ПОЗИЦИЯМ

✅ **Пример:**
Загадано: `3 7 8 1`
Догадка:  `9 7 1 3`
Результат: **1 совпадение** (цифра 7 на второй позиции)

🏆 **Победа:** угадал все цифры первым

⚡️ **Совет:** Запоминай результаты ходов, чтобы вычислить код!
        """
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_menu()
        )
    
    elif call.data == "back_main":
        bot.edit_message_text(
            random.choice(WELCOME_MESSAGES).format(name=name),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_menu()
        )
    
    # ===== ВЫБОР СЛОЖНОСТИ =====
    elif call.data.startswith("diff_"):
        difficulty = int(call.data.split('_')[1])
        room_code = create_room(user_id, name, difficulty)
        
        text = random.choice(CREATOR_WAIT_MESSAGES).format(
            code=room_code,
            diff=difficulty
        )
        
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
        if not info or info['room'][8] != 'playing':
            bot.answer_callback_query(call.id, "❌ Игра не найдена", show_alert=True)
            return
        
        # Проверка очереди
        if info['room'][7] != user_id:
            bot.answer_callback_query(call.id, "⏳ Сейчас не твой ход!", show_alert=True)
            return
        
        move_num = info['total_moves'] + 1
        diff = info['room'][4]
        
        text = random.choice(YOUR_TURN_MESSAGES).format(
            diff=diff,
            move_num=move_num
        )
        
        bot.edit_message_text(
            text,
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
            winner_name = room[3] if winner == room[2] else room[1]
            
            c.execute('UPDATE rooms SET status = "finished", winner_id = ? WHERE code = ?', (winner, room_code))
            
            # Обновляем статистику
            c.execute('''UPDATE stats SET games = games + 1, losses = losses + 1
                         WHERE user_id = ?''', (user_id,))
            c.execute('''UPDATE stats SET games = games + 1, wins = wins + 1
                         WHERE user_id = ?''', (winner,))
            
            conn.commit()
            
            # Уведомления
            surr_text = random.choice(SURRENDER_MESSAGES['surrendered'])
            bot.edit_message_text(
                surr_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_menu()
            )
            
            win_text = random.choice(SURRENDER_MESSAGES['winner'])
            bot.send_message(
                winner,
                win_text,
                reply_markup=main_menu()
            )
        
        conn.close()

# ==================== ОБРАБОТЧИКИ ТЕКСТА ====================

def process_join(message):
    """Обработка ввода кода для присоединения"""
    user_id = message.from_user.id
    name = message.from_user.first_name or "Игрок"
    code = message.text.strip().upper()
    
    if user_id in temp_data and temp_data[user_id].get('action') == 'join':
        success, result = join_room(code, user_id, name)
        
        if not success:
            bot.send_message(message.chat.id, f"{result}")
            bot.send_message(
                message.chat.id,
                "🔐 Возвращаемся в меню:",
                reply_markup=main_menu()
            )
            del temp_data[user_id]
            return
        
        # Получаем сложность
        conn = sqlite3.connect('game.db')
        c = conn.cursor()
        c.execute('SELECT difficulty FROM rooms WHERE code = ?', (code,))
        diff = c.fetchone()[0]
        conn.close()
        
        text = random.choice(JOIN_SUCCESS_MESSAGES).format(
            code=code,
            diff=diff
        )
        
        bot.send_message(
            message.chat.id,
            text
        )
        temp_data[user_id] = {'action': 'set_code', 'room': code}

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    """Обработка всех текстовых сообщений"""
    user_id = message.from_user.id
    name = message.from_user.first_name or "Игрок"
    text = message.text.strip()
    
    # Проверяем, ждем ли мы действие
    if user_id not in temp_data:
        bot.send_message(
            message.chat.id,
            "🔐 Используй меню для навигации:",
            reply_markup=main_menu()
        )
        return
    
    action = temp_data[user_id].get('action')
    
    # Установка кода
    if action == 'set_code':
        room_code = temp_data[user_id]['room']
        success, result, creator, joiner, creator_name, difficulty = set_code(room_code, user_id, text)
        
        if not success:
            bot.send_message(message.chat.id, f"{result}")
            return
        
        if result == "start":
            # Игра начинается
            creator_msg = random.choice(GAME_START_MESSAGES['creator'])
            joiner_msg = random.choice(GAME_START_MESSAGES['joiner'])
            
            # Уведомляем создателя
            bot.send_message(
                creator,
                f"✅ Код принят!\n\n{creator_msg}"
            )
            
            # Уведомляем присоединившегося
            bot.send_message(
                joiner,
                f"✅ Код принят!\n\n{joiner_msg}"
            )
            
            # Показываем статус
            show_game_status(message.chat.id, None, room_code, user_id)
            show_game_status(creator, None, room_code, creator)
            show_game_status(joiner, None, room_code, joiner)
            
            del temp_data[user_id]
        else:
            bot.send_message(
                message.chat.id,
                "✅ **Код сохранен!**\n\n⏳ Ожидаем, пока соперник загадает свой код..."
            )
            del temp_data[user_id]
    
    # Ход в игре
    elif action == 'make_move':
        room_code = temp_data[user_id]['room']
        success, status, matches, opponent_id, opponent_name, move_num, secret = make_move(room_code, user_id, name, text)
        
        if not success:
            bot.send_message(message.chat.id, f"{status}")
            return
        
        # Получаем информацию о комнате для total
        conn = sqlite3.connect('game.db')
        c = conn.cursor()
        c.execute('SELECT difficulty FROM rooms WHERE code = ?', (room_code,))
        total = c.fetchone()[0]
        conn.close()
        
        # Сообщение о результате хода
        result_text = random.choice(MOVE_RESULT_MESSAGES).format(
            name=name,
            guess=text,
            matches=matches,
            total=total,
            move_num=move_num
        )
        
        bot.send_message(message.chat.id, result_text)
        bot.send_message(opponent_id, result_text)
        
        if status == "win":
            # Победа
            winner_msg = random.choice(WIN_MESSAGES['winner']).format(total=total)
            loser_msg = random.choice(WIN_MESSAGES['loser']).format(code=secret)
            
            bot.send_message(
                user_id,
                winner_msg,
                reply_markup=main_menu()
            )
            bot.send_message(
                opponent_id,
                loser_msg,
                reply_markup=main_menu()
            )
        else:
            # Ход продолжается
            turn_msg = random.choice(OPPONENT_TURN_MESSAGES).format(name=name)
            bot.send_message(
                opponent_id,
                turn_msg
            )
            
            # Показываем обновленный статус
            show_game_status(message.chat.id, None, room_code, user_id)
            show_game_status(opponent_id, None, room_code, opponent_id)
        
        del temp_data[user_id]

def show_game_status(chat_id, message_id, room_code, user_id):
    """Показывает статус игры"""
    info = get_game_info(room_code, user_id)
    if not info:
        bot.send_message(chat_id, "❌ Игра не найдена", reply_markup=main_menu())
        return
    
    room = info['room']
    moves = info['moves']
    total_moves = info['total_moves']
    
    # Определяем соперника
    if info['is_creator']:
        opponent_id = room[2]
        opponent_name = room[3] if room[3] else "Соперник"
    else:
        opponent_id = room[1]
        opponent_name = room[1]  # имя создателя
    
    # Если имя соперника не получено, берем из статистики
    if opponent_name == room[1] or not opponent_name:
        conn = sqlite3.connect('game.db')
        c = conn.cursor()
        c.execute('SELECT first_name FROM stats WHERE user_id = ?', (opponent_id,))
        name_data = c.fetchone()
        opponent_name = name_data[0] if name_data else "Соперник"
        conn.close()
    
    status_emoji = {
        'waiting': '⏳',
        'setting': '🔐',
        'playing': '⚔️',
        'finished': '🏁'
    }.get(room[8], '🎮')
    
    text = f"{status_emoji} **ИГРА**\n"
    text += f"┌ Комната: `{room_code}`\n"
    text += f"├ Сложность: {room[4]} цифр\n"
    text += f"├ Соперник: {opponent_name}\n"
    text += f"├ Ходов сделано: {total_moves}\n"
    
    if room[8] == 'playing':
        if room[7] == user_id:
            text += f"└ ⚡️ **ТВОЙ ХОД!**\n\n"
        else:
            text += f"└ ⏳ **ХОД СОПЕРНИКА**\n\n"
    elif room[8] == 'finished':
        if room[9] == user_id:
            text += f"└ 🏆 **ТЫ ПОБЕДИЛ**\n\n"
        else:
            text += f"└ 💔 **ТЫ ПРОИГРАЛ**\n\n"
    else:
        text += f"└ {status_emoji} Ожидание...\n\n"
    
    if moves:
        text += "**📊 История ходов:**\n"
        for player_id, player_name, guess, matches in moves[:5]:  # показываем последние 5
            if player_id == user_id:
                prefix = "🟢 Ты:"
            else:
                prefix = f"🔴 {opponent_name}:"
            text += f"{prefix} `{guess}` → {matches} совп.\n"
    else:
        text += "_Пока нет ходов_\n"
    
    is_your_turn = (room[8] == 'playing' and room[7] == user_id)
    
    if message_id:
        bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=game_menu(room_code, is_your_turn, room[8])
        )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=game_menu(room_code, is_your_turn, room[8])
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
    
    # Удаляем старый вебхук
    bot.remove_webhook()
    time.sleep(1)
    
    # Устанавливаем новый
    webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/webhook"
    bot.set_webhook(url=webhook_url)
    
    logger.info(f"✅ Вебхук установлен на {webhook_url}")
    app.run(host='0.0.0.0', port=PORT)
