import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import random
import string
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, render_template_string, redirect, url_for, session
import time
import logging
import hashlib
import hmac
import re

# ==================== НАСТРОЙКИ ====================
TOKEN = os.environ.get('BOT_TOKEN')
PORT = int(os.environ.get('PORT', 10000))
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')  # Смени на свой пароль!
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-key-change-this')

# Временные данные
temp_data = {}
active_rooms = {}

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    """Инициализация всех таблиц базы данных"""
    conn = sqlite3.connect('game.db', timeout=10)
    c = conn.cursor()
    
    # Таблица комнат
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
                  created_at TEXT,
                  started_at TEXT,
                  finished_at TEXT)''')
    
    # Таблица ходов
    c.execute('''CREATE TABLE IF NOT EXISTS moves
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  room_code TEXT,
                  player_id INTEGER,
                  player_name TEXT,
                  guess TEXT,
                  matches INTEGER,
                  move_number INTEGER,
                  created_at TEXT)''')
    
    # Таблица чата
    c.execute('''CREATE TABLE IF NOT EXISTS game_chat
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  room_code TEXT,
                  player_id INTEGER,
                  player_name TEXT,
                  message TEXT,
                  created_at TEXT)''')
    
    # Таблица статистики игроков
    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (user_id INTEGER PRIMARY KEY,
                  games_total INTEGER DEFAULT 0,
                  games_won INTEGER DEFAULT 0,
                  games_lost INTEGER DEFAULT 0,
                  total_moves INTEGER DEFAULT 0,
                  total_guesses INTEGER DEFAULT 0,
                  best_game_moves INTEGER DEFAULT 999,
                  current_win_streak INTEGER DEFAULT 0,
                  max_win_streak INTEGER DEFAULT 0,
                  chat_messages INTEGER DEFAULT 0,
                  username TEXT,
                  first_name TEXT,
                  last_active TEXT,
                  registered_at TEXT,
                  is_banned INTEGER DEFAULT 0,
                  ban_reason TEXT,
                  is_admin INTEGER DEFAULT 0)''')
    
    # Таблица истории игр
    c.execute('''CREATE TABLE IF NOT EXISTS game_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  room_code TEXT,
                  player1_id INTEGER,
                  player1_name TEXT,
                  player2_id INTEGER,
                  player2_name TEXT,
                  winner_id INTEGER,
                  difficulty INTEGER,
                  total_moves INTEGER,
                  played_at TEXT)''')
    
    # Таблица рейтинга
    c.execute('''CREATE TABLE IF NOT EXISTS rating
                 (user_id INTEGER PRIMARY KEY,
                  rating_score INTEGER DEFAULT 1000,
                  games_count INTEGER DEFAULT 0,
                  last_change TEXT,
                  FOREIGN KEY (user_id) REFERENCES stats(user_id))''')
    
    # Таблица жалоб
    c.execute('''CREATE TABLE IF NOT EXISTS reports
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  reporter_id INTEGER,
                  reported_id INTEGER,
                  room_code TEXT,
                  reason TEXT,
                  status TEXT DEFAULT 'pending',
                  created_at TEXT,
                  resolved_at TEXT,
                  resolved_by INTEGER)''')
    
    # Таблица уведомлений
    c.execute('''CREATE TABLE IF NOT EXISTS notifications
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  title TEXT,
                  message TEXT,
                  type TEXT,
                  read INTEGER DEFAULT 0,
                  created_at TEXT)''')
    
    # Создаем админа по умолчанию
    c.execute('''INSERT OR IGNORE INTO stats (user_id, first_name, username, is_admin, registered_at)
                 VALUES (?, ?, ?, ?, ?)''',
              (0, 'Admin', 'admin', 1, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_db()

# ==================== HTML ШАБЛОНЫ ДЛЯ АДМИНКИ ====================

ADMIN_LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>🔐 Вход в админ-панель</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
        }
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .login-container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 100%;
            max-width: 400px;
            overflow: hidden;
            animation: slideUp 0.5s ease;
        }
        @keyframes slideUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .header h1 {
            font-size: 24px;
            margin-bottom: 10px;
        }
        .header p {
            opacity: 0.9;
            font-size: 14px;
        }
        .form {
            padding: 30px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 500;
            font-size: 14px;
        }
        input {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 16px;
            transition: all 0.3s;
        }
        input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s;
        }
        button:hover {
            transform: translateY(-2px);
        }
        .error {
            background: #fee;
            color: #c33;
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 20px;
            font-size: 14px;
            border-left: 4px solid #c33;
        }
        .footer {
            text-align: center;
            padding: 20px;
            background: #f8f9fa;
            color: #666;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="header">
            <h1>🔐 Взлом Замка</h1>
            <p>Панель администратора</p>
        </div>
        <div class="form">
            {% if error %}
            <div class="error">{{ error }}</div>
            {% endif %}
            <form method="POST">
                <div class="form-group">
                    <label>👤 Логин</label>
                    <input type="text" name="username" required placeholder="Введите логин">
                </div>
                <div class="form-group">
                    <label>🔑 Пароль</label>
                    <input type="password" name="password" required placeholder="Введите пароль">
                </div>
                <button type="submit">Войти в панель</button>
            </form>
        </div>
        <div class="footer">
            ⚡️ Только для администраторов
        </div>
    </div>
</body>
</html>
'''

ADMIN_DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>🔐 Админ-панель</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
        }
        body {
            background: #f5f7fa;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .header-content {
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            font-size: 24px;
        }
        .logout-btn {
            background: rgba(255,255,255,0.2);
            color: white;
            padding: 10px 20px;
            border-radius: 10px;
            text-decoration: none;
            font-size: 14px;
            transition: background 0.3s;
        }
        .logout-btn:hover {
            background: rgba(255,255,255,0.3);
        }
        .container {
            max-width: 1200px;
            margin: 20px auto;
            padding: 0 20px;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
            transition: transform 0.2s;
        }
        .stat-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
        }
        .stat-title {
            color: #666;
            font-size: 14px;
            margin-bottom: 10px;
        }
        .stat-value {
            font-size: 32px;
            font-weight: bold;
            color: #333;
        }
        .stat-unit {
            font-size: 14px;
            color: #999;
            margin-left: 5px;
        }
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        .tab-btn {
            padding: 10px 20px;
            background: white;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            color: #666;
            box-shadow: 0 2px 5px rgba(0,0,0,0.05);
            transition: all 0.3s;
        }
        .tab-btn.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
        .table-container {
            background: white;
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
            overflow-x: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            text-align: left;
            padding: 12px;
            background: #f8f9fa;
            color: #666;
            font-weight: 600;
            font-size: 13px;
        }
        td {
            padding: 12px;
            border-bottom: 1px solid #eee;
            font-size: 14px;
        }
        tr:hover {
            background: #f8f9fa;
        }
        .badge {
            padding: 4px 8px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 500;
        }
        .badge.success {
            background: #e3fcef;
            color: #0a7b4b;
        }
        .badge.warning {
            background: #fff3e0;
            color: #b45b0a;
        }
        .badge.danger {
            background: #fee;
            color: #c33;
        }
        .badge.info {
            background: #e3f2fd;
            color: #0d47a1;
        }
        .action-btn {
            padding: 6px 12px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            margin: 0 3px;
            transition: opacity 0.2s;
        }
        .action-btn:hover {
            opacity: 0.8;
        }
        .btn-ban {
            background: #fee;
            color: #c33;
        }
        .btn-unban {
            background: #e3fcef;
            color: #0a7b4b;
        }
        .btn-admin {
            background: #e3f2fd;
            color: #0d47a1;
        }
        .search-box {
            margin-bottom: 20px;
        }
        .search-box input {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 14px;
        }
        .pagination {
            display: flex;
            justify-content: center;
            gap: 10px;
            margin-top: 20px;
        }
        .page-btn {
            padding: 8px 12px;
            background: white;
            border: 1px solid #ddd;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.3s;
        }
        .page-btn.active {
            background: #667eea;
            color: white;
            border-color: #667eea;
        }
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.5);
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }
        .modal.active {
            display: flex;
        }
        .modal-content {
            background: white;
            border-radius: 15px;
            padding: 30px;
            max-width: 500px;
            width: 90%;
        }
        .modal-content h3 {
            margin-bottom: 20px;
            color: #333;
        }
        .modal-content textarea {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            margin-bottom: 20px;
            min-height: 100px;
        }
        .modal-actions {
            display: flex;
            gap: 10px;
            justify-content: flex-end;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <h1>🔐 Взлом Замка - Админ-панель</h1>
            <a href="/admin/logout" class="logout-btn">🚪 Выйти</a>
        </div>
    </div>
    
    <div class="container">
        <!-- Статистика -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-title">👥 Всего игроков</div>
                <div class="stat-value">{{ stats.total_players }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">🎮 Активных игр</div>
                <div class="stat-value">{{ stats.active_games }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">💬 Сообщений в чате</div>
                <div class="stat-value">{{ stats.total_chat }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">🚫 Забанено</div>
                <div class="stat-value">{{ stats.banned_count }}</div>
            </div>
        </div>
        
        <!-- Табы -->
        <div class="tabs">
            <button class="tab-btn active" onclick="showTab('players')">👥 Игроки</button>
            <button class="tab-btn" onclick="showTab('games')">🎮 Игры</button>
            <button class="tab-btn" onclick="showTab('chat')">💬 Чат</button>
            <button class="tab-btn" onclick="showTab('reports')">⚠️ Жалобы</button>
            <button class="tab-btn" onclick="showTab('stats')">📊 Детальная статистика</button>
        </div>
        
        <!-- Вкладка Игроки -->
        <div id="tab-players" class="tab-content active">
            <div class="search-box">
                <input type="text" id="playerSearch" placeholder="🔍 Поиск по имени или ID..." onkeyup="searchPlayers()">
            </div>
            <div class="table-container">
                <table id="playersTable">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Имя</th>
                            <th>Username</th>
                            <th>Игр</th>
                            <th>Побед</th>
                            <th>Рейтинг</th>
                            <th>Статус</th>
                            <th>Действия</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for player in players %}
                        <tr>
                            <td>{{ player.user_id }}</td>
                            <td>{{ player.first_name }}</td>
                            <td>@{{ player.username }}</td>
                            <td>{{ player.games_total }}</td>
                            <td>{{ player.games_won }}</td>
                            <td>{{ player.rating }}</td>
                            <td>
                                {% if player.is_banned %}
                                <span class="badge danger">Забанен</span>
                                {% elif player.is_admin %}
                                <span class="badge info">Админ</span>
                                {% else %}
                                <span class="badge success">Активен</span>
                                {% endif %}
                            </td>
                            <td>
                                {% if not player.is_admin %}
                                    {% if player.is_banned %}
                                    <button class="action-btn btn-unban" onclick="unbanUser({{ player.user_id }})">✅ Разбанить</button>
                                    {% else %}
                                    <button class="action-btn btn-ban" onclick="showBanModal({{ player.user_id }}, '{{ player.first_name }}')">🚫 Забанить</button>
                                    {% endif %}
                                {% endif %}
                                <button class="action-btn btn-admin" onclick="viewPlayerStats({{ player.user_id }})">📊 Статистика</button>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <div class="pagination" id="playerPagination"></div>
        </div>
        
        <!-- Вкладка Игры -->
        <div id="tab-games" class="tab-content">
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Комната</th>
                            <th>Игрок 1</th>
                            <th>Игрок 2</th>
                            <th>Сложность</th>
                            <th>Статус</th>
                            <th>Ходов</th>
                            <th>Создана</th>
                            <th>Действия</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for game in games %}
                        <tr>
                            <td><code>{{ game.code }}</code></td>
                            <td>{{ game.player1 }}</td>
                            <td>{{ game.player2 or 'Ожидание...' }}</td>
                            <td>{{ game.difficulty }} цифр</td>
                            <td>
                                {% if game.status == 'playing' %}
                                <span class="badge success">🎮 Игра идет</span>
                                {% elif game.status == 'waiting' %}
                                <span class="badge warning">⏳ Ожидание</span>
                                {% elif game.status == 'finished' %}
                                <span class="badge info">✅ Завершена</span>
                                {% endif %}
                            </td>
                            <td>{{ game.moves_count }}</td>
                            <td>{{ game.created_at[:10] }}</td>
                            <td>
                                <button class="action-btn btn-admin" onclick="viewGameDetails('{{ game.code }}')">👁️ Смотреть</button>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Вкладка Чат -->
        <div id="tab-chat" class="tab-content">
            <div class="search-box">
                <input type="text" id="chatSearch" placeholder="🔍 Поиск по сообщениям..." onkeyup="searchChat()">
            </div>
            <div class="table-container">
                <table id="chatTable">
                    <thead>
                        <tr>
                            <th>Время</th>
                            <th>Комната</th>
                            <th>Игрок</th>
                            <th>Сообщение</th>
                            <th>Действия</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for msg in chat_messages %}
                        <tr>
                            <td>{{ msg.created_at[11:16] }}</td>
                            <td><code>{{ msg.room_code }}</code></td>
                            <td>{{ msg.player_name }}</td>
                            <td>{{ msg.message }}</td>
                            <td>
                                <button class="action-btn btn-ban" onclick="deleteChatMessage({{ msg.id }})">🗑️ Удалить</button>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Вкладка Жалобы -->
        <div id="tab-reports" class="tab-content">
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Отправитель</th>
                            <th>На кого</th>
                            <th>Комната</th>
                            <th>Причина</th>
                            <th>Статус</th>
                            <th>Дата</th>
                            <th>Действия</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for report in reports %}
                        <tr>
                            <td>#{{ report.id }}</td>
                            <td>{{ report.reporter_name }}</td>
                            <td>{{ report.reported_name }}</td>
                            <td><code>{{ report.room_code }}</code></td>
                            <td>{{ report.reason }}</td>
                            <td>
                                {% if report.status == 'pending' %}
                                <span class="badge warning">⏳ Ожидает</span>
                                {% elif report.status == 'resolved' %}
                                <span class="badge success">✅ Решено</span>
                                {% endif %}
                            </td>
                            <td>{{ report.created_at[:10] }}</td>
                            <td>
                                <button class="action-btn btn-admin" onclick="resolveReport({{ report.id }})">✅ Решить</button>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Вкладка Детальная статистика -->
        <div id="tab-stats" class="tab-content">
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-title">🏆 Средний рейтинг</div>
                    <div class="stat-value">{{ stats.avg_rating }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">📊 Всего игр</div>
                    <div class="stat-value">{{ stats.total_games }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">💬 Чатов активных</div>
                    <div class="stat-value">{{ stats.active_chats }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">⏳ Средняя игра</div>
                    <div class="stat-value">{{ stats.avg_moves }} <span class="stat-unit">ходов</span></div>
                </div>
            </div>
            
            <div class="table-container">
                <h3>🏆 Топ-10 игроков</h3>
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Игрок</th>
                            <th>Рейтинг</th>
                            <th>Игр</th>
                            <th>Побед</th>
                            <th>% побед</th>
                            <th>Лучшая игра</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for player in top_players %}
                        <tr>
                            <td>{{ loop.index }}</td>
                            <td>{{ player.first_name }}</td>
                            <td><strong>{{ player.rating }}</strong></td>
                            <td>{{ player.games_total }}</td>
                            <td>{{ player.games_won }}</td>
                            <td>{{ (player.games_won / player.games_total * 100)|round(1) if player.games_total > 0 else 0 }}%</td>
                            <td>{{ player.best_game_moves if player.best_game_moves != 999 else '—' }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    
    <!-- Модальное окно для бана -->
    <div id="banModal" class="modal">
        <div class="modal-content">
            <h3>🚫 Бан пользователя <span id="banUserName"></span></h3>
            <textarea id="banReason" placeholder="Причина бана..."></textarea>
            <div class="modal-actions">
                <button class="action-btn" onclick="closeBanModal()">Отмена</button>
                <button class="action-btn btn-ban" onclick="confirmBan()">Забанить</button>
            </div>
        </div>
    </div>
    
    <script>
        let currentUserId = null;
        
        function showTab(tabName) {
            // Скрыть все табы
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.classList.remove('active');
            });
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            
            // Показать выбранный таб
            document.getElementById(`tab-${tabName}`).classList.add('active');
            event.target.classList.add('active');
        }
        
        function searchPlayers() {
            let input = document.getElementById('playerSearch');
            let filter = input.value.toLowerCase();
            let rows = document.querySelectorAll('#playersTable tbody tr');
            
            rows.forEach(row => {
                let text = row.textContent.toLowerCase();
                row.style.display = text.includes(filter) ? '' : 'none';
            });
        }
        
        function searchChat() {
            let input = document.getElementById('chatSearch');
            let filter = input.value.toLowerCase();
            let rows = document.querySelectorAll('#chatTable tbody tr');
            
            rows.forEach(row => {
                let text = row.textContent.toLowerCase();
                row.style.display = text.includes(filter) ? '' : 'none';
            });
        }
        
        function showBanModal(userId, userName) {
            currentUserId = userId;
            document.getElementById('banUserName').textContent = userName;
            document.getElementById('banModal').classList.add('active');
        }
        
        function closeBanModal() {
            document.getElementById('banModal').classList.remove('active');
            currentUserId = null;
        }
        
        function confirmBan() {
            let reason = document.getElementById('banReason').value;
            if (!reason) {
                alert('Укажи причину бана!');
                return;
            }
            
            fetch('/admin/ban_user', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    user_id: currentUserId,
                    reason: reason
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('✅ Пользователь забанен');
                    location.reload();
                } else {
                    alert('❌ Ошибка: ' + data.error);
                }
            });
        }
        
        function unbanUser(userId) {
            if (!confirm('Разбанить пользователя?')) return;
            
            fetch('/admin/unban_user', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ user_id: userId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('✅ Пользователь разбанен');
                    location.reload();
                } else {
                    alert('❌ Ошибка: ' + data.error);
                }
            });
        }
        
        function deleteChatMessage(messageId) {
            if (!confirm('Удалить это сообщение?')) return;
            
            fetch('/admin/delete_chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message_id: messageId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('✅ Сообщение удалено');
                    location.reload();
                } else {
                    alert('❌ Ошибка: ' + data.error);
                }
            });
        }
        
        function resolveReport(reportId) {
            if (!confirm('Отметить жалобу как решенную?')) return;
            
            fetch('/admin/resolve_report', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ report_id: reportId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('✅ Жалоба решена');
                    location.reload();
                } else {
                    alert('❌ Ошибка: ' + data.error);
                }
            });
        }
        
        function viewPlayerStats(userId) {
            window.open(`/admin/player_stats/${userId}`, '_blank');
        }
        
        function viewGameDetails(roomCode) {
            window.open(`/admin/game_details/${roomCode}`, '_blank');
        }
    </script>
</body>
</html>
'''

# ==================== ФУНКЦИИ РАБОТЫ С БД ====================

def execute_query(query, params=(), fetch_one=False, fetch_all=False, commit=False):
    """Универсальная функция для работы с БД"""
    conn = None
    try:
        conn = sqlite3.connect('game.db', timeout=10)
        c = conn.cursor()
        c.execute(query, params)
        
        if commit:
            conn.commit()
            return True
        
        if fetch_one:
            result = c.fetchone()
            return result
        if fetch_all:
            result = c.fetchall()
            return result
            
        return True
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")
        return None if (fetch_one or fetch_all) else False
    finally:
        if conn:
            conn.close()

def init_player_stats(user_id, username, first_name):
    """Инициализация статистики нового игрока"""
    now = datetime.now().isoformat()
    
    # Проверяем, есть ли уже игрок
    exists = execute_query(
        'SELECT user_id FROM stats WHERE user_id = ?',
        (user_id,),
        fetch_one=True
    )
    
    if not exists:
        execute_query(
            '''INSERT INTO stats 
               (user_id, username, first_name, registered_at, last_active)
               VALUES (?, ?, ?, ?, ?)''',
            (user_id, username, first_name, now, now),
            commit=True
        )
        
        # Инициализируем рейтинг
        execute_query(
            'INSERT INTO rating (user_id, rating_score, last_change) VALUES (?, ?, ?)',
            (user_id, 1000, now),
            commit=True
        )
        
        return True
    else:
        # Проверяем, не забанен ли игрок
        banned = execute_query(
            'SELECT is_banned FROM stats WHERE user_id = ?',
            (user_id,),
            fetch_one=True
        )
        
        if banned and banned[0]:
            return False, "banned"
        
        # Обновляем последнюю активность
        execute_query(
            'UPDATE stats SET last_active = ? WHERE user_id = ?',
            (now, user_id),
            commit=True
        )
        return False, "ok"

def update_player_stats(user_id, won=False, moves_count=0):
    """Обновление статистики после игры"""
    now = datetime.now().isoformat()
    
    # Получаем текущую статистику
    stats = execute_query(
        '''SELECT games_total, games_won, games_lost, current_win_streak, 
                  max_win_streak, best_game_moves 
           FROM stats WHERE user_id = ?''',
        (user_id,),
        fetch_one=True
    )
    
    if stats:
        games_total, games_won, games_lost, current_streak, max_streak, best_moves = stats
        
        games_total += 1
        if won:
            games_won += 1
            current_streak += 1
            if current_streak > max_streak:
                max_streak = current_streak
        else:
            games_lost += 1
            current_streak = 0
        
        if moves_count > 0 and (best_moves == 999 or moves_count < best_moves):
            best_moves = moves_count
        
        execute_query(
            '''UPDATE stats SET 
               games_total = ?, games_won = ?, games_lost = ?,
               current_win_streak = ?, max_win_streak = ?,
               best_game_moves = ?, last_active = ?
               WHERE user_id = ?''',
            (games_total, games_won, games_lost, current_streak, max_streak, best_moves, now, user_id),
            commit=True
        )
        
        update_rating(user_id, won)

def update_rating(user_id, won):
    """Обновление рейтинга игрока"""
    rating = execute_query(
        'SELECT rating_score FROM rating WHERE user_id = ?',
        (user_id,),
        fetch_one=True
    )
    
    if rating:
        current = rating[0]
        change = 15 if won else -10
        new_rating = max(100, current + change)
        
        execute_query(
            'UPDATE rating SET rating_score = ?, last_change = ? WHERE user_id = ?',
            (new_rating, datetime.now().isoformat(), user_id),
            commit=True
        )

def save_game_history(room_code, player1_id, player1_name, player2_id, player2_name, winner_id, difficulty, total_moves):
    """Сохранение истории игры"""
    execute_query(
        '''INSERT INTO game_history 
           (room_code, player1_id, player1_name, player2_id, player2_name, winner_id, difficulty, total_moves, played_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (room_code, player1_id, player1_name, player2_id, player2_name, winner_id, difficulty, total_moves, datetime.now().isoformat()),
        commit=True
    )

def save_chat_message(room_code, player_id, player_name, message):
    """Сохранение сообщения в чате"""
    now = datetime.now().isoformat()
    
    execute_query(
        '''INSERT INTO game_chat (room_code, player_id, player_name, message, created_at)
           VALUES (?, ?, ?, ?, ?)''',
        (room_code, player_id, player_name, message, now),
        commit=True
    )
    
    # Обновляем счетчик сообщений в статистике
    execute_query(
        'UPDATE stats SET chat_messages = chat_messages + 1 WHERE user_id = ?',
        (player_id,),
        commit=True
    )
    
    # Получаем всех игроков комнаты
    room = execute_query(
        'SELECT creator_id, joiner_id FROM rooms WHERE code = ?',
        (room_code,),
        fetch_one=True
    )
    
    return room

def create_report(reporter_id, reported_id, room_code, reason):
    """Создание жалобы на игрока"""
    now = datetime.now().isoformat()
    
    execute_query(
        '''INSERT INTO reports (reporter_id, reported_id, room_code, reason, created_at)
           VALUES (?, ?, ?, ?, ?)''',
        (reporter_id, reported_id, room_code, reason, now),
        commit=True
    )

def check_if_banned(user_id):
    """Проверка, забанен ли игрок"""
    result = execute_query(
        'SELECT is_banned, ban_reason FROM stats WHERE user_id = ?',
        (user_id,),
        fetch_one=True
    )
    
    if result and result[0]:
        return True, result[1]
    return False, None

def generate_room_code():
    """Генерирует уникальный код комнаты из 4 букв"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase, k=4))
        exists = execute_query(
            'SELECT code FROM rooms WHERE code = ?',
            (code,),
            fetch_one=True
        )
        if not exists:
            return code

# ==================== ФУНКЦИИ ИГРЫ ====================

def create_room(creator_id, creator_name, difficulty):
    """Создание новой игровой комнаты"""
    code = generate_room_code()
    now = datetime.now().isoformat()
    
    success = execute_query(
        '''INSERT INTO rooms 
           (code, creator_id, creator_name, difficulty, turn_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (code, creator_id, creator_name, difficulty, creator_id, now),
        commit=True
    )
    
    if success:
        return code
    return None

def join_room(code, joiner_id, joiner_name):
    """Присоединение к комнате"""
    # Проверяем существование комнаты
    room = execute_query(
        'SELECT * FROM rooms WHERE code = ? AND status = "waiting"',
        (code,),
        fetch_one=True
    )
    
    if not room:
        return False, "❌ Комната не найдена или уже заполнена"
    
    if room[1] == joiner_id:
        return False, "❌ Нельзя играть с самим собой"
    
    # Присоединяемся
    success = execute_query(
        '''UPDATE rooms 
           SET joiner_id = ?, joiner_name = ?, status = "setting"
           WHERE code = ?''',
        (joiner_id, joiner_name, code),
        commit=True
    )
    
    if success:
        return True, code
    return False, "❌ Ошибка при присоединении"

def set_code(room_code, player_id, secret):
    """Установка секретного кода"""
    # Получаем информацию о комнате
    room = execute_query(
        'SELECT * FROM rooms WHERE code = ?',
        (room_code,),
        fetch_one=True
    )
    
    if not room:
        return False, "❌ Комната не найдена"
    
    # Проверка длины
    if len(secret) != room[5]:
        return False, f"❌ Нужно {room[5]} цифр, а ты ввел {len(secret)}"
    
    if not secret.isdigit():
        return False, "❌ Только цифры можно использовать"
    
    # Кто устанавливает
    if player_id == room[1]:  # создатель
        execute_query(
            'UPDATE rooms SET creator_code = ? WHERE code = ?',
            (secret, room_code),
            commit=True
        )
    elif player_id == room[2]:  # присоединившийся
        execute_query(
            'UPDATE rooms SET joiner_code = ? WHERE code = ?',
            (secret, room_code),
            commit=True
        )
    else:
        return False, "❌ Ты не в этой игре"
    
    # Проверяем, готовы ли оба
    codes = execute_query(
        'SELECT creator_code, joiner_code FROM rooms WHERE code = ?',
        (room_code,),
        fetch_one=True
    )
    
    if codes and codes[0] and codes[1]:
        now = datetime.now().isoformat()
        execute_query(
            '''UPDATE rooms 
               SET status = "playing", turn_id = ?, started_at = ?
               WHERE code = ?''',
            (room[1], now, room_code),
            commit=True
        )
        
        active_rooms[room_code] = {
            'creator_id': room[1],
            'joiner_id': room[2],
            'difficulty': room[5],
            'status': 'playing',
            'turn_id': room[1]
        }
        
        return True, "start", room[1], room[2], room[3], room[5]
    
    return True, "waiting", None, None, None, None

def check_guess(secret, guess):
    """Проверка совпадений по позициям"""
    matches = 0
    for i in range(len(secret)):
        if secret[i] == guess[i]:
            matches += 1
    return matches

def make_move(room_code, player_id, player_name, guess):
    """Сделать ход в игре"""
    room = execute_query(
        'SELECT * FROM rooms WHERE code = ? AND status = "playing"',
        (room_code,),
        fetch_one=True
    )
    
    if not room:
        return False, "❌ Игра не найдена"
    
    if player_id != room[9]:
        return False, "⏳ Сейчас не твой ход!"
    
    if len(guess) != room[5]:
        return False, f"❌ Нужно {room[5]} цифр"
    
    if not guess.isdigit():
        return False, "❌ Только цифры"
    
    if player_id == room[1]:
        secret = room[7]
        opponent_id = room[2]
        opponent_name = room[3]
    else:
        secret = room[6]
        opponent_id = room[1]
        opponent_name = room[1]
    
    if opponent_id == room[1]:
        opp_stats = execute_query(
            'SELECT first_name FROM stats WHERE user_id = ?',
            (opponent_id,),
            fetch_one=True
        )
        if opp_stats:
            opponent_name = opp_stats[0]
    
    move_count = execute_query(
        'SELECT COUNT(*) FROM moves WHERE room_code = ?',
        (room_code,),
        fetch_one=True
    )
    move_num = (move_count[0] if move_count else 0) + 1
    
    matches = check_guess(secret, guess)
    
    execute_query(
        '''INSERT INTO moves 
           (room_code, player_id, player_name, guess, matches, move_number, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (room_code, player_id, player_name, guess, matches, move_num, datetime.now().isoformat()),
        commit=True
    )
    
    execute_query(
        'UPDATE stats SET total_moves = total_moves + 1, total_guesses = total_guesses + 1 WHERE user_id = ?',
        (player_id,),
        commit=True
    )
    
    if matches == room[5]:
        now = datetime.now().isoformat()
        execute_query(
            '''UPDATE rooms 
               SET status = "finished", winner_id = ?, finished_at = ?
               WHERE code = ?''',
            (player_id, now, room_code),
            commit=True
        )
        
        update_player_stats(player_id, won=True, moves_count=move_num)
        update_player_stats(opponent_id, won=False)
        
        save_game_history(
            room_code,
            room[1], room[1],
            room[2], room[3],
            player_id,
            room[5],
            move_num
        )
        
        if room_code in active_rooms:
            del active_rooms[room_code]
        
        return True, "win", matches, opponent_id, opponent_name, move_num, secret
    
    execute_query(
        'UPDATE rooms SET turn_id = ? WHERE code = ?',
        (opponent_id, room_code),
        commit=True
    )
    
    if room_code in active_rooms:
        active_rooms[room_code]['turn_id'] = opponent_id
    
    return True, "continue", matches, opponent_id, opponent_name, move_num, None

def get_game_info(room_code, user_id):
    """Получение информации об игре"""
    room = execute_query(
        'SELECT * FROM rooms WHERE code = ?',
        (room_code,),
        fetch_one=True
    )
    
    if not room:
        return None
    
    is_creator = (user_id == room[1])
    is_joiner = (user_id == room[2])
    
    if not (is_creator or is_joiner):
        return None
    
    moves = execute_query(
        '''SELECT player_id, player_name, guess, matches, move_number 
           FROM moves 
           WHERE room_code = ? 
           ORDER BY move_number DESC 
           LIMIT 10''',
        (room_code,),
        fetch_all=True
    ) or []
    
    move_count = execute_query(
        'SELECT COUNT(*) FROM moves WHERE room_code = ?',
        (room_code,),
        fetch_one=True
    )
    total_moves = move_count[0] if move_count else 0
    
    creator_name = room[1]
    if isinstance(room[1], int):
        name_data = execute_query(
            'SELECT first_name FROM stats WHERE user_id = ?',
            (room[1],),
            fetch_one=True
        )
        creator_name = name_data[0] if name_data else f"ID{room[1]}"
    
    joiner_name = room[3] if room[3] else "Ожидание..."
    if room[2] and room[2] != 0 and (not room[3] or room[3] == ''):
        name_data = execute_query(
            'SELECT first_name FROM stats WHERE user_id = ?',
            (room[2],),
            fetch_one=True
        )
        joiner_name = name_data[0] if name_data else f"ID{room[2]}"
    
    return {
        'room': room,
        'moves': moves,
        'total_moves': total_moves,
        'is_creator': is_creator,
        'is_joiner': is_joiner,
        'creator_name': creator_name,
        'joiner_name': joiner_name
    }

def get_player_stats(user_id):
    """Получение полной статистики игрока"""
    stats = execute_query(
        '''SELECT games_total, games_won, games_lost, total_moves, 
                  total_guesses, best_game_moves, current_win_streak, 
                  max_win_streak, first_name, chat_messages
           FROM stats WHERE user_id = ?''',
        (user_id,),
        fetch_one=True
    )
    
    if not stats:
        return None
    
    rating = execute_query(
        'SELECT rating_score FROM rating WHERE user_id = ?',
        (user_id,),
        fetch_one=True
    )
    rating_score = rating[0] if rating else 1000
    
    history = execute_query(
        '''SELECT player1_name, player2_name, winner_id, difficulty, total_moves, played_at
           FROM game_history 
           WHERE player1_id = ? OR player2_id = ?
           ORDER BY played_at DESC LIMIT 5''',
        (user_id, user_id),
        fetch_all=True
    ) or []
    
    return {
        'games_total': stats[0],
        'games_won': stats[1],
        'games_lost': stats[2],
        'total_moves': stats[3],
        'total_guesses': stats[4],
        'best_game': stats[5] if stats[5] != 999 else '—',
        'current_streak': stats[6],
        'max_streak': stats[7],
        'name': stats[8],
        'chat_messages': stats[9],
        'rating': rating_score,
        'history': history
    }

def get_admin_stats():
    """Получение общей статистики для админки"""
    total_players = execute_query(
        'SELECT COUNT(*) FROM stats',
        fetch_one=True
    )[0]
    
    active_games = execute_query(
        'SELECT COUNT(*) FROM rooms WHERE status = "playing"',
        fetch_one=True
    )[0]
    
    total_chat = execute_query(
        'SELECT COUNT(*) FROM game_chat',
        fetch_one=True
    )[0]
    
    banned_count = execute_query(
        'SELECT COUNT(*) FROM stats WHERE is_banned = 1',
        fetch_one=True
    )[0]
    
    total_games = execute_query(
        'SELECT COUNT(*) FROM game_history',
        fetch_one=True
    )[0]
    
    avg_rating = execute_query(
        'SELECT AVG(rating_score) FROM rating',
        fetch_one=True
    )[0] or 0
    
    active_chats = execute_query(
        'SELECT COUNT(DISTINCT room_code) FROM game_chat WHERE created_at > ?',
        ((datetime.now() - timedelta(hours=24)).isoformat(),),
        fetch_one=True
    )[0]
    
    avg_moves = execute_query(
        'SELECT AVG(total_moves) FROM game_history',
        fetch_one=True
    )[0] or 0
    
    return {
        'total_players': total_players,
        'active_games': active_games,
        'total_chat': total_chat,
        'banned_count': banned_count,
        'total_games': total_games,
        'avg_rating': round(avg_rating, 1),
        'active_chats': active_chats,
        'avg_moves': round(avg_moves, 1)
    }

def get_all_players(limit=100, offset=0):
    """Получение списка всех игроков"""
    players = execute_query(
        '''SELECT s.user_id, s.first_name, s.username, s.games_total, 
                  s.games_won, s.games_lost, s.is_banned, s.is_admin,
                  r.rating_score
           FROM stats s
           LEFT JOIN rating r ON s.user_id = r.user_id
           ORDER BY r.rating_score DESC
           LIMIT ? OFFSET ?''',
        (limit, offset),
        fetch_all=True
    ) or []
    
    result = []
    for p in players:
        result.append({
            'user_id': p[0],
            'first_name': p[1],
            'username': p[2] or '—',
            'games_total': p[3],
            'games_won': p[4],
            'games_lost': p[5],
            'is_banned': p[6],
            'is_admin': p[7],
            'rating': p[8] or 1000
        })
    
    return result

def get_all_games(limit=50):
    """Получение списка всех игр"""
    games = execute_query(
        '''SELECT r.code, r.creator_name, r.joiner_name, r.difficulty, 
                  r.status, r.created_at,
                  (SELECT COUNT(*) FROM moves WHERE room_code = r.code) as moves_count
           FROM rooms r
           ORDER BY r.created_at DESC
           LIMIT ?''',
        (limit,),
        fetch_all=True
    ) or []
    
    result = []
    for g in games:
        result.append({
            'code': g[0],
            'player1': g[1],
            'player2': g[2],
            'difficulty': g[3],
            'status': g[4],
            'created_at': g[5],
            'moves_count': g[6]
        })
    
    return result

def get_chat_messages(limit=100):
    """Получение сообщений чата"""
    messages = execute_query(
        '''SELECT id, room_code, player_name, message, created_at
           FROM game_chat
           ORDER BY created_at DESC
           LIMIT ?''',
        (limit,),
        fetch_all=True
    ) or []
    
    result = []
    for m in messages:
        result.append({
            'id': m[0],
            'room_code': m[1],
            'player_name': m[2],
            'message': m[3],
            'created_at': m[4]
        })
    
    return result

def get_reports():
    """Получение списка жалоб"""
    reports = execute_query(
        '''SELECT r.id, r.reporter_id, r.reported_id, r.room_code, 
                  r.reason, r.status, r.created_at,
                  s1.first_name as reporter_name,
                  s2.first_name as reported_name
           FROM reports r
           LEFT JOIN stats s1 ON r.reporter_id = s1.user_id
           LEFT JOIN stats s2 ON r.reported_id = s2.user_id
           ORDER BY r.created_at DESC''',
        fetch_all=True
    ) or []
    
    result = []
    for rep in reports:
        result.append({
            'id': rep[0],
            'reporter_id': rep[1],
            'reported_id': rep[2],
            'room_code': rep[3],
            'reason': rep[4],
            'status': rep[5],
            'created_at': rep[6],
            'reporter_name': rep[7] or f"ID{rep[1]}",
            'reported_name': rep[8] or f"ID{rep[2]}"
        })
    
    return result

def get_top_players(limit=10):
    """Получение топ-игроков"""
    top = execute_query(
        '''SELECT s.user_id, s.first_name, s.games_total, s.games_won, 
                  s.best_game_moves, r.rating_score
           FROM rating r
           JOIN stats s ON r.user_id = s.user_id
           WHERE s.games_total > 0 AND s.is_banned = 0
           ORDER BY r.rating_score DESC
           LIMIT ?''',
        (limit,),
        fetch_all=True
    ) or []
    
    result = []
    for t in top:
        result.append({
            'user_id': t[0],
            'first_name': t[1],
            'games_total': t[2],
            'games_won': t[3],
            'best_game_moves': t[4],
            'rating': t[5]
        })
    
    return result

# ==================== КРАСИВЫЕ СООБЩЕНИЯ ====================

def format_main_menu(name):
    return f"""
🔐 ВЗЛОМ ЗАМКА

👤 Игрок: {name}

Выбери действие:
• 🎮 Создать новую игру
• 🔑 Присоединиться к игре
• 📊 Моя статистика
• 🏆 Топ игроков
• 💬 Чат поддержки
• ❓ Правила игры
"""

def format_rules():
    return """
🔐 ПРАВИЛА ИГРЫ "ВЗЛОМ ЗАМКА"

🎯 Суть игры:
Каждый игрок загадывает свой секретный код из цифр.
Нужно первым угадать код соперника.

📝 Как играть:
1. Создай игру или присоединись по коду
2. Загадай свой секретный код (только цифры!)
3. Ходите по очереди, пытаясь угадать код соперника
4. После каждой догадки бот показывает сколько цифр совпало ПО ПОЗИЦИЯМ

✅ Пример:
Загадано: 3 7 8 1
Догадка:  9 7 1 3
Результат: 1 совпадение (цифра 7 на второй позиции)

🏆 Победа:
Угадал все цифры первым

💬 Чат:
Во время игры можно общаться с соперником

⚡️ Советы:
• Запоминай результаты ходов
• Анализируй, какие цифры где стоят
• Общайся с соперником в чате
"""

def format_game_status(room_code, difficulty, opponent_name, total_moves, turn_status, moves_history):
    status_emoji = "⚡️" if turn_status == "your_turn" else "⏳"
    status_text = "ТВОЙ ХОД!" if turn_status == "your_turn" else "ХОД СОПЕРНИКА"
    
    text = f"""
🎮 ИГРА

🔑 Комната: {room_code}
🎯 Сложность: {difficulty} цифр
👤 Соперник: {opponent_name}
📊 Ходов: {total_moves}

{status_emoji} {status_text}

📋 История ходов:
"""
    
    if moves_history:
        for move in moves_history:
            text += f"{move}\n"
    else:
        text += "Пока нет ходов\n"
    
    text += "\n💬 Чтобы написать в чат, просто отправь сообщение"
    
    return text

def format_stats(stats):
    winrate = round((stats['games_won'] / stats['games_total'] * 100), 1) if stats['games_total'] > 0 else 0
    
    text = f"""
📊 СТАТИСТИКА ИГРОКА

👤 Имя: {stats['name']}
🏆 Рейтинг: {stats['rating']}

📈 Общая статистика:
• Всего игр: {stats['games_total']}
• Побед: {stats['games_won']}
• Поражений: {stats['games_lost']}
• Процент побед: {winrate}%

⚡️ Игровые показатели:
• Всего ходов: {stats['total_moves']}
• Всего догадок: {stats['total_guesses']}
• Лучшая игра: {stats['best_game']} ходов
• Сообщений в чате: {stats['chat_messages']}

🔥 Серии:
• Текущая победная: {stats['current_streak']}
• Максимальная: {stats['max_streak']}
"""

    if stats['history']:
        text += "\n📋 Последние игры:\n"
        for h in stats['history'][:3]:
            player1, player2, winner_id, diff, moves, date = h
            if winner_id == stats['name']:
                result = "✅"
            else:
                result = "❌"
            date_str = date[:10] if date else ""
            text += f"{result} {diff} цифр, {moves} ходов ({date_str})\n"
    
    return text

# ==================== КЛАВИАТУРЫ ====================

def main_menu_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎮 СОЗДАТЬ ИГРУ", callback_data="menu_create"),
        InlineKeyboardButton("🔑 ПРИСОЕДИНИТЬСЯ", callback_data="menu_join"),
        InlineKeyboardButton("📊 СТАТИСТИКА", callback_data="menu_stats"),
        InlineKeyboardButton("🏆 ТОП", callback_data="menu_top"),
        InlineKeyboardButton("💬 ПОДДЕРЖКА", callback_data="menu_support"),
        InlineKeyboardButton("❓ ПРАВИЛА", callback_data="menu_help")
    )
    return markup

def difficulty_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("4 🔢 (легко)", callback_data="diff_4"),
        InlineKeyboardButton("6 🔢 (средне)", callback_data="diff_6"),
        InlineKeyboardButton("8 🔢 (сложно)", callback_data="diff_8"),
        InlineKeyboardButton("12 🔢 (эксперт)", callback_data="diff_12"),
        InlineKeyboardButton("◀️ НАЗАД", callback_data="back_main")
    )
    return markup

def game_keyboard(room_code, is_your_turn=False, game_status='playing'):
    markup = InlineKeyboardMarkup(row_width=2)
    
    if game_status == 'playing':
        if is_your_turn:
            markup.add(InlineKeyboardButton("🎯 СДЕЛАТЬ ХОД", callback_data=f"move_{room_code}"))
        markup.add(
            InlineKeyboardButton("💬 ЧАТ", callback_data=f"chat_{room_code}"),
            InlineKeyboardButton("🔄 ОБНОВИТЬ", callback_data=f"refresh_{room_code}"),
            InlineKeyboardButton("🏳️ СДАТЬСЯ", callback_data=f"surrender_{room_code}")
        )
    else:
        markup.add(InlineKeyboardButton("🎮 В МЕНЮ", callback_data="back_main"))
    
    return markup

def chat_keyboard(room_code):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔄 ОБНОВИТЬ ЧАТ", callback_data=f"chat_refresh_{room_code}"),
        InlineKeyboardButton("⬅️ К ИГРЕ", callback_data=f"back_to_game_{room_code}")
    )
    return markup

# ==================== КОМАНДЫ ====================

@bot.message_handler(commands=['start', 'play'])
def start_cmd(message):
    user_id = message.from_user.id
    name = message.from_user.first_name or "Игрок"
    username = message.from_user.username or name
    
    # Проверяем, не забанен ли игрок
    banned, reason = check_if_banned(user_id)
    if banned:
        bot.send_message(
            message.chat.id,
            f"🚫 ВЫ ЗАБЛОКИРОВАНЫ\n\nПричина: {reason}\n\nОбратись в поддержку: @admin"
        )
        return
    
    result = init_player_stats(user_id, username, name)
    
    if result == "banned":
        bot.send_message(
            message.chat.id,
            f"🚫 ВЫ ЗАБЛОКИРОВАНЫ\n\nОбратись в поддержку: @admin"
        )
        return
    
    welcome_text = format_main_menu(name)
    if result:
        welcome_text = f"🔐 Добро пожаловать, {name}!\n\n" + welcome_text
    
    bot.send_message(
        message.chat.id,
        welcome_text,
        reply_markup=main_menu_keyboard()
    )

# ==================== КОЛЛБЭКИ ====================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    name = call.from_user.first_name or "Игрок"
    
    try:
        # Проверка на бан
        banned, reason = check_if_banned(user_id)
        if banned:
            bot.answer_callback_query(call.id, "🚫 Вы заблокированы", show_alert=True)
            return
        
        # ===== ГЛАВНОЕ МЕНЮ =====
        if call.data == "menu_create":
            bot.edit_message_text(
                "🎮 СОЗДАНИЕ ИГРЫ\n\nВыбери сложность:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=difficulty_keyboard()
            )
        
        elif call.data == "menu_join":
            bot.edit_message_text(
                "🔑 ПРИСОЕДИНЕНИЕ К ИГРЕ\n\nВведи код комнаты из 4 букв:",
                call.message.chat.id,
                call.message.message_id
            )
            temp_data[user_id] = {'action': 'join'}
            bot.register_next_step_handler_by_chat_id(call.message.chat.id, process_join)
        
        elif call.data == "menu_stats":
            stats = get_player_stats(user_id)
            if stats and stats['games_total'] > 0:
                text = format_stats(stats)
            else:
                text = "📊 У тебя пока нет игр. Сыграй первую!"
            
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_menu_keyboard()
            )
        
        elif call.data == "menu_top":
            top = get_top_players(10)
            if top:
                text = "🏆 ТОП ИГРОКОВ\n\n"
                for i, p in enumerate(top, 1):
                    medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "👤"
                    text += f"{medal} {i}. {p['first_name']}\n"
                    text += f"   Рейтинг: {p['rating']} | Побед: {p['games_won']}\n\n"
            else:
                text = "🏆 Топ пока пуст"
            
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_menu_keyboard()
            )
        
        elif call.data == "menu_support":
            text = """
💬 ЧАТ ПОДДЕРЖКИ

Если у тебя проблемы:
• Жалоба на игрока
• Технические вопросы
• Предложения

Напиши @admin
"""
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_menu_keyboard()
            )
        
        elif call.data == "menu_help":
            bot.edit_message_text(
                format_rules(),
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_menu_keyboard()
            )
        
        elif call.data == "back_main":
            bot.edit_message_text(
                format_main_menu(name),
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_menu_keyboard()
            )
        
        # ===== ВЫБОР СЛОЖНОСТИ =====
        elif call.data.startswith("diff_"):
            difficulty = int(call.data.split('_')[1])
            room_code = create_room(user_id, name, difficulty)
            
            if room_code:
                bot.edit_message_text(
                    f"✅ КОМНАТА СОЗДАНА!\n\n"
                    f"🔑 Код: {room_code}\n"
                    f"🎯 Сложность: {difficulty} цифр\n\n"
                    f"📤 Отправь этот код другу\n"
                    f"⏳ Ожидаем игрока...\n\n"
                    f"📝 Загадай свой код:\n"
                    f"Напиши {difficulty} цифр",
                    call.message.chat.id,
                    call.message.message_id
                )
                temp_data[user_id] = {'action': 'set_code', 'room': room_code}
            else:
                bot.answer_callback_query(call.id, "❌ Ошибка создания комнаты", show_alert=True)
        
        # ===== ИГРОВЫЕ ДЕЙСТВИЯ =====
        elif call.data.startswith("move_"):
            room_code = call.data.replace("move_", "")
            
            info = get_game_info(room_code, user_id)
            if not info or info['room'][8] != 'playing':
                bot.answer_callback_query(call.id, "❌ Игра не найдена", show_alert=True)
                return
            
            if info['room'][9] != user_id:
                bot.answer_callback_query(call.id, "⏳ Сейчас не твой ход!", show_alert=True)
                return
            
            move_num = info['total_moves'] + 1
            diff = info['room'][5]
            
            bot.edit_message_text(
                f"🎯 ТВОЙ ХОД\n\nПопытка №{move_num}\nВведи {diff} цифр:",
                call.message.chat.id,
                call.message.message_id
            )
            temp_data[user_id] = {'action': 'make_move', 'room': room_code}
        
        elif call.data.startswith("refresh_"):
            room_code = call.data.replace("refresh_", "")
            show_game_status(call.message.chat.id, call.message.message_id, room_code, user_id)
        
        elif call.data.startswith("chat_"):
            if call.data.startswith("chat_refresh_"):
                room_code = call.data.replace("chat_refresh_", "")
                show_chat(call.message.chat.id, call.message.message_id, room_code, user_id)
            elif call.data.startswith("chat_"):
                room_code = call.data.replace("chat_", "")
                show_chat(call.message.chat.id, call.message.message_id, room_code, user_id)
        
        elif call.data.startswith("back_to_game_"):
            room_code = call.data.replace("back_to_game_", "")
            show_game_status(call.message.chat.id, call.message.message_id, room_code, user_id)
        
        elif call.data.startswith("surrender_"):
            room_code = call.data.replace("surrender_", "")
            
            room = execute_query(
                'SELECT * FROM rooms WHERE code = ?',
                (room_code,),
                fetch_one=True
            )
            
            if room and room[8] == 'playing':
                winner_id = room[2] if user_id == room[1] else room[1]
                
                now = datetime.now().isoformat()
                execute_query(
                    '''UPDATE rooms 
                       SET status = "finished", winner_id = ?, finished_at = ?
                       WHERE code = ?''',
                    (winner_id, now, room_code),
                    commit=True
                )
                
                update_player_stats(user_id, won=False)
                update_player_stats(winner_id, won=True)
                
                move_count = execute_query(
                    'SELECT COUNT(*) FROM moves WHERE room_code = ?',
                    (room_code,),
                    fetch_one=True
                )
                total_moves = move_count[0] if move_count else 0
                
                save_game_history(
                    room_code,
                    room[1], room[1],
                    room[2], room[3],
                    winner_id,
                    room[5],
                    total_moves
                )
                
                if room_code in active_rooms:
                    del active_rooms[room_code]
                
                bot.edit_message_text(
                    "🏳️ Ты сдался\n\nВозвращайся в меню:",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=main_menu_keyboard()
                )
                
                bot.send_message(
                    winner_id,
                    f"🏆 ПОБЕДА!\n\nСоперник сдался!",
                    reply_markup=main_menu_keyboard()
                )
        
        else:
            bot.answer_callback_query(call.id, "⏳ Обработка...")
            
    except Exception as e:
        logger.error(f"Ошибка в callback_handler: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка", show_alert=True)

# ==================== ОБРАБОТЧИКИ ТЕКСТА ====================

def process_join(message):
    user_id = message.from_user.id
    name = message.from_user.first_name or "Игрок"
    code = message.text.strip().upper()
    
    if user_id in temp_data and temp_data[user_id].get('action') == 'join':
        try:
            if not re.match(r'^[A-Z]{4}$', code):
                bot.send_message(
                    message.chat.id,
                    "❌ Неверный формат кода. Код должен быть из 4 букв (A-Z)."
                )
                bot.send_message(
                    message.chat.id,
                    format_main_menu(name),
                    reply_markup=main_menu_keyboard()
                )
                del temp_data[user_id]
                return
            
            success, result = join_room(code, user_id, name)
            
            if not success:
                bot.send_message(message.chat.id, result)
                bot.send_message(
                    message.chat.id,
                    format_main_menu(name),
                    reply_markup=main_menu_keyboard()
                )
                del temp_data[user_id]
                return
            
            difficulty = execute_query(
                'SELECT difficulty FROM rooms WHERE code = ?',
                (code,),
                fetch_one=True
            )
            
            if difficulty:
                bot.send_message(
                    message.chat.id,
                    f"✅ ПРИСОЕДИНЕНИЕ ВЫПОЛНЕНО!\n\n"
                    f"🔑 Комната: {code}\n"
                    f"🎯 Сложность: {difficulty[0]} цифр\n\n"
                    f"📝 Загадай свой код:\n"
                    f"Напиши {difficulty[0]} цифр"
                )
                temp_data[user_id] = {'action': 'set_code', 'room': code}
            else:
                bot.send_message(message.chat.id, "❌ Ошибка получения данных комнаты")
                bot.send_message(
                    message.chat.id,
                    format_main_menu(name),
                    reply_markup=main_menu_keyboard()
                )
                del temp_data[user_id]
                
        except Exception as e:
            logger.error(f"Ошибка в process_join: {e}")
            bot.send_message(message.chat.id, "❌ Произошла ошибка. Попробуй снова.")
            bot.send_message(
                message.chat.id,
                format_main_menu(name),
                reply_markup=main_menu_keyboard()
            )
            del temp_data[user_id]

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    user_id = message.from_user.id
    name = message.from_user.first_name or "Игрок"
    text = message.text.strip()
    
    # Проверка на бан
    banned, reason = check_if_banned(user_id)
    if banned:
        bot.send_message(
            message.chat.id,
            f"🚫 ВЫ ЗАБЛОКИРОВАНЫ\n\nПричина: {reason}"
        )
        return
    
    # Если пользователь не в режиме ожидания - показываем меню
    if user_id not in temp_data:
        # Проверяем, может это сообщение в чат игры?
        # Ищем активные игры пользователя
        active_game = execute_query(
            '''SELECT code FROM rooms 
               WHERE (creator_id = ? OR joiner_id = ?) 
               AND status = "playing"''',
            (user_id, user_id),
            fetch_one=True
        )
        
        if active_game:
            # Это сообщение в чат
            room_code = active_game[0]
            save_chat_message(room_code, user_id, name, text)
            
            # Отправляем сообщение сопернику
            room = execute_query(
                'SELECT creator_id, joiner_id FROM rooms WHERE code = ?',
                (room_code,),
                fetch_one=True
            )
            
            opponent_id = room[1] if user_id == room[0] else room[0]
            
            bot.send_message(
                opponent_id,
                f"💬 {name}: {text}"
            )
            
            bot.send_message(
                user_id,
                "✅ Сообщение отправлено"
            )
        else:
            bot.send_message(
                message.chat.id,
                "🔑 Используй кнопки меню:",
                reply_markup=main_menu_keyboard()
            )
        return
    
    action = temp_data[user_id].get('action')
    
    try:
        if action == 'set_code':
            room_code = temp_data[user_id]['room']
            success, result, creator, joiner, creator_name, difficulty = set_code(room_code, user_id, text)
            
            if not success:
                bot.send_message(message.chat.id, result)
                return
            
            if result == "start":
                # Получаем имена
                creator_display = execute_query(
                    'SELECT first_name FROM stats WHERE user_id = ?',
                    (creator,),
                    fetch_one=True
                )
                creator_name = creator_display[0] if creator_display else f"ID{creator}"
                
                joiner_display = execute_query(
                    'SELECT first_name FROM stats WHERE user_id = ?',
                    (joiner,),
                    fetch_one=True
                )
                joiner_name = joiner_display[0] if joiner_display else f"ID{joiner}"
                
                # Уведомления
                bot.send_message(
                    creator,
                    f"🎮 ИГРА НАЧАЛАСЬ!\n\nТы ходишь первым!\nСоперник: {joiner_name}"
                )
                
                bot.send_message(
                    joiner,
                    f"🎮 ИГРА НАЧАЛАСЬ!\n\nХод соперника ({creator_name})\nОжидай..."
                )
                
                show_game_status(creator, None, room_code, creator)
                show_game_status(joiner, None, room_code, joiner)
                
                del temp_data[user_id]
            else:
                bot.send_message(
                    message.chat.id,
                    "✅ Код сохранен!\n\n⏳ Ожидаем соперника..."
                )
                del temp_data[user_id]
        
        elif action == 'make_move':
            room_code = temp_data[user_id]['room']
            success, status, matches, opponent_id, opponent_name, move_num, secret = make_move(room_code, user_id, name, text)
            
            if not success:
                bot.send_message(message.chat.id, status)
                return
            
            room_info = execute_query(
                'SELECT difficulty FROM rooms WHERE code = ?',
                (room_code,),
                fetch_one=True
            )
            total = room_info[0] if room_info else 0
            
            result_text = f"🎯 Ход #{move_num}\n\n{name}: {text}\n✅ Совпадений: {matches} из {total}"
            
            bot.send_message(message.chat.id, result_text)
            bot.send_message(opponent_id, result_text)
            
            if status == "win":
                bot.send_message(
                    user_id,
                    f"🏆 ПОБЕДА!\n\nТы угадал код за {move_num} ходов!\n+15 к рейтингу",
                    reply_markup=main_menu_keyboard()
                )
                
                bot.send_message(
                    opponent_id,
                    f"💔 ПОРАЖЕНИЕ\n\nТвой код: {secret}\nСоперник угадал за {move_num} ходов\n-10 к рейтингу",
                    reply_markup=main_menu_keyboard()
                )
                
                if user_id in temp_data:
                    del temp_data[user_id]
                if opponent_id in temp_data:
                    del temp_data[opponent_id]
            else:
                bot.send_message(
                    opponent_id,
                    f"⏳ Твой ход! Соперник ({name}) сделал догадку"
                )
                
                show_game_status(message.chat.id, None, room_code, user_id)
                show_game_status(opponent_id, None, room_code, opponent_id)
                
                del temp_data[user_id]
    
    except Exception as e:
        logger.error(f"Ошибка в handle_text: {e}")
        bot.send_message(message.chat.id, "❌ Произошла ошибка. Попробуй снова.")
        if user_id in temp_data:
            del temp_data[user_id]

def show_game_status(chat_id, message_id, room_code, user_id):
    info = get_game_info(room_code, user_id)
    if not info:
        bot.send_message(chat_id, "❌ Игра не найдена", reply_markup=main_menu_keyboard())
        return
    
    room = info['room']
    moves = info['moves']
    total_moves = info['total_moves']
    
    if info['is_creator']:
        opponent_id = room[2]
        opponent_name = info['joiner_name']
    else:
        opponent_id = room[1]
        opponent_name = info['creator_name']
    
    moves_history = []
    for player_id, player_name, guess, matches, move_num in moves[:5]:
        if player_id == user_id:
            prefix = "Ты:"
        else:
            prefix = f"{opponent_name}:"
        moves_history.append(f"#{move_num} {prefix} {guess} → {matches} совп.")
    
    turn_status = "your_turn" if (room[8] == 'playing' and room[9] == user_id) else "opponent_turn"
    
    text = format_game_status(
        room_code,
        room[5],
        opponent_name,
        total_moves,
        turn_status,
        moves_history
    )
    
    is_your_turn = (room[8] == 'playing' and room[9] == user_id)
    
    if message_id:
        bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=game_keyboard(room_code, is_your_turn, room[8])
        )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=game_keyboard(room_code, is_your_turn, room[8])
        )

def show_chat(chat_id, message_id, room_code, user_id):
    # Получаем последние сообщения
    messages = execute_query(
        '''SELECT player_name, message, created_at FROM game_chat 
           WHERE room_code = ? 
           ORDER BY created_at DESC LIMIT 20''',
        (room_code,),
        fetch_all=True
    ) or []
    
    text = f"💬 ЧАТ КОМНАТЫ {room_code}\n\n"
    
    if messages:
        for name, msg, time in reversed(messages):
            time_str = time[11:16] if time else ""
            text += f"[{time_str}] {name}: {msg}\n"
    else:
        text += "Пока нет сообщений\n\n"
    
    text += "\n📝 Просто отправь сообщение, чтобы написать в чат"
    
    if message_id:
        bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=chat_keyboard(room_code)
        )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=chat_keyboard(room_code)
        )

# ==================== АДМИН-ПАНЕЛЬ (FLASK) ====================

@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template_string(ADMIN_LOGIN_HTML, error="❌ Неверный логин или пароль")
    
    return render_template_string(ADMIN_LOGIN_HTML, error=None)

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    stats = get_admin_stats()
    players = get_all_players(100)
    games = get_all_games(50)
    chat = get_chat_messages(100)
    reports = get_reports()
    top_players = get_top_players(10)
    
    return render_template_string(
        ADMIN_DASHBOARD_HTML,
        stats=stats,
        players=players,
        games=games,
        chat_messages=chat,
        reports=reports,
        top_players=top_players
    )

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/ban_user', methods=['POST'])
def admin_ban_user():
    if not session.get('admin_logged_in'):
        return {'success': False, 'error': 'Not authorized'}, 401
    
    data = request.json
    user_id = data.get('user_id')
    reason = data.get('reason', 'Нарушение правил')
    
    execute_query(
        'UPDATE stats SET is_banned = 1, ban_reason = ? WHERE user_id = ?',
        (reason, user_id),
        commit=True
    )
    
    # Отправляем уведомление пользователю
    try:
        bot.send_message(
            user_id,
            f"🚫 ВЫ ЗАБЛОКИРОВАНЫ\n\nПричина: {reason}\n\nОбратись в поддержку: @admin"
        )
    except:
        pass
    
    return {'success': True}

@app.route('/admin/unban_user', methods=['POST'])
def admin_unban_user():
    if not session.get('admin_logged_in'):
        return {'success': False, 'error': 'Not authorized'}, 401
    
    data = request.json
    user_id = data.get('user_id')
    
    execute_query(
        'UPDATE stats SET is_banned = 0, ban_reason = NULL WHERE user_id = ?',
        (user_id,),
        commit=True
    )
    
    # Отправляем уведомление пользователю
    try:
        bot.send_message(
            user_id,
            f"✅ ВАС РАЗБЛОКИРОВАЛИ\n\nМожешь продолжать играть!"
        )
    except:
        pass
    
    return {'success': True}

@app.route('/admin/delete_chat', methods=['POST'])
def admin_delete_chat():
    if not session.get('admin_logged_in'):
        return {'success': False, 'error': 'Not authorized'}, 401
    
    data = request.json
    message_id = data.get('message_id')
    
    execute_query(
        'DELETE FROM game_chat WHERE id = ?',
        (message_id,),
        commit=True
    )
    
    return {'success': True}

@app.route('/admin/resolve_report', methods=['POST'])
def admin_resolve_report():
    if not session.get('admin_logged_in'):
        return {'success': False, 'error': 'Not authorized'}, 401
    
    data = request.json
    report_id = data.get('report_id')
    
    execute_query(
        'UPDATE reports SET status = "resolved", resolved_at = ? WHERE id = ?',
        (datetime.now().isoformat(), report_id),
        commit=True
    )
    
    return {'success': True}

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
    return "🔐 Game Bot is running! <a href='/admin'>Admin Panel</a>"

@app.route('/health')
def health():
    return "OK", 200

# ==================== ЗАПУСК ====================

if __name__ == '__main__':
    logger.info("🚀 Запуск Game Bot...")
    
    bot.remove_webhook()
    time.sleep(1)
    
    webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/webhook"
    bot.set_webhook(url=webhook_url)
    
    logger.info(f"✅ Вебхук установлен на {webhook_url}")
    app.run(host='0.0.0.0', port=PORT)
