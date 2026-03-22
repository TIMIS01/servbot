import logging
import sqlite3
import json
import os
import asyncio
import requests
import secrets
import string
import aiohttp
import aiofiles
from datetime import datetime, timedelta
from typing import List, Optional
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, 
    CallbackQuery, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    WebAppInfo,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# Игнорируем предупреждения
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Загружаем переменные окружения
load_dotenv()

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN", "8758750734:AAHw9HokfvqB3ltT6M9g289zfcNut-9TVSs")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "8562390004"))
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://timis01.github.io/miniappss/")
WEBHOOK_URL = "https://tg-shop-server.onrender.com"

# ========== ТОВАРЫ И ГОРОДА ==========
CITIES = [
    "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань",
    "Нижний Новгород", "Челябинск", "Самара", "Омск", "Ростов-на-Дону",
    "Уфа", "Красноярск", "Воронеж", "Пермь", "Волгоград"
]

# ========== БАЗА ДАННЫХ АДМИНИСТРАТОРОВ ==========
ADMINS_DB = 'admins.db'

def init_admins_db():
    conn = sqlite3.connect(ADMINS_DB)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        added_by INTEGER,
        added_date TEXT,
        can_respond INTEGER DEFAULT 1,
        can_view_orders INTEGER DEFAULT 1,
        can_view_history INTEGER DEFAULT 1,
        is_active INTEGER DEFAULT 1
    )
    ''')
    cursor.execute("INSERT OR IGNORE INTO admins (user_id, username, added_by, added_date, can_respond, can_view_orders, can_view_history, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (SUPER_ADMIN_ID, "super_admin", SUPER_ADMIN_ID, datetime.now().isoformat(), 1, 1, 1, 1))
    conn.commit()
    conn.close()

init_admins_db()

# ========== БАЗА ДАННЫХ ТОВАРОВ (ЛОКАЛЬНАЯ, ДЛЯ СПИСКА В БОТЕ) ==========
PRODUCTS_DB = 'products.db'

def init_products_db():
    """Инициализация локальной базы данных товаров для бота"""
    conn = sqlite3.connect(PRODUCTS_DB)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        unit TEXT DEFAULT 'гр',
        image_url TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT,
        created_by INTEGER
    )
    ''')
    conn.commit()
    conn.close()
    print("✅ Локальная база данных товаров инициализирована")

init_products_db()

def get_all_products_local():
    """Получить список всех активных товаров из локальной БД"""
    conn = sqlite3.connect(PRODUCTS_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, unit, image_url FROM products WHERE is_active = 1 ORDER BY id")
    products = cursor.fetchall()
    conn.close()
    return products

def get_product_local(product_id):
    """Получить товар по ID из локальной БД"""
    conn = sqlite3.connect(PRODUCTS_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, unit, image_url FROM products WHERE id = ? AND is_active = 1", (product_id,))
    product = cursor.fetchone()
    conn.close()
    return product

def add_product_local(name, price, unit, image_url, created_by):
    """Добавить новый товар в локальную БД (резерв)"""
    conn = sqlite3.connect(PRODUCTS_DB)
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO products (name, price, unit, image_url, created_at, created_by)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (name, price, unit, image_url, datetime.now().isoformat(), created_by))
    product_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return product_id

def delete_product_local(product_id):
    """Удалить товар из локальной БД (деактивировать)"""
    conn = sqlite3.connect(PRODUCTS_DB)
    cursor = conn.cursor()
    cursor.execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()

# ========== БАЗА ДАННЫХ МАГАЗИНА ==========
def init_shop_database():
    conn = sqlite3.connect('shop_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        message_text TEXT,
        message_type TEXT,
        timestamp TEXT,
        is_from_admin INTEGER DEFAULT 0
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        product_name TEXT,
        quantity REAL,
        city TEXT,
        total_price INTEGER,
        order_date TEXT,
        status TEXT DEFAULT 'новый'
    )
    ''')
    conn.commit()
    conn.close()

init_shop_database()

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С АДМИНИСТРАТОРАМИ ==========
def get_all_admins():
    conn = sqlite3.connect(ADMINS_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, can_respond, can_view_orders, can_view_history FROM admins WHERE is_active = 1")
    admins = cursor.fetchall()
    conn.close()
    return admins

def get_admin_ids():
    conn = sqlite3.connect(ADMINS_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins WHERE is_active = 1")
    ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return ids

def is_admin(user_id: int) -> bool:
    conn = sqlite3.connect(ADMINS_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins WHERE user_id = ? AND is_active = 1", (user_id,))
    result = cursor.fetchone() is not None
    conn.close()
    return result

def is_super_admin(user_id: int) -> bool:
    return user_id == SUPER_ADMIN_ID

def get_admin_permissions(user_id: int):
    conn = sqlite3.connect(ADMINS_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT can_respond, can_view_orders, can_view_history FROM admins WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {'respond': bool(result[0]), 'orders': bool(result[1]), 'history': bool(result[2])}
    return {'respond': False, 'orders': False, 'history': False}

def add_admin(user_id: int, username: str, added_by: int):
    conn = sqlite3.connect(ADMINS_DB)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO admins (user_id, username, added_by, added_date, is_active) VALUES (?, ?, ?, ?, 1)",
        (user_id, username, added_by, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def remove_admin(user_id: int):
    if user_id == SUPER_ADMIN_ID:
        return False
    conn = sqlite3.connect(ADMINS_DB)
    cursor = conn.cursor()
    cursor.execute("UPDATE admins SET is_active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True

def update_admin_permissions(user_id: int, can_respond=None, can_view_orders=None, can_view_history=None):
    if user_id == SUPER_ADMIN_ID:
        return
    conn = sqlite3.connect(ADMINS_DB)
    cursor = conn.cursor()
    
    updates = []
    params = []
    if can_respond is not None:
        updates.append("can_respond = ?")
        params.append(1 if can_respond else 0)
    if can_view_orders is not None:
        updates.append("can_view_orders = ?")
        params.append(1 if can_view_orders else 0)
    if can_view_history is not None:
        updates.append("can_view_history = ?")
        params.append(1 if can_view_history else 0)
    
    if updates:
        query = f"UPDATE admins SET {', '.join(updates)} WHERE user_id = ?"
        params.append(user_id)
        cursor.execute(query, params)
        conn.commit()
    conn.close()

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С ПРОМОКОДАМИ ==========
def generate_promocode(length=8):
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def create_promocode_on_server(code, discount_type, discount_value, max_uses, expires_days, created_by):
    try:
        response = requests.post(
            f"{WEBHOOK_URL}/api/create-promo",
            json={
                "code": code.upper(),
                "discount_type": discount_type,
                "discount_value": discount_value,
                "max_uses": max_uses,
                "expires_days": expires_days,
                "created_by": created_by
            },
            timeout=30
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Ошибка создания промокода: {e}")
        return False

def get_promocodes_from_server():
    try:
        response = requests.get(f"{WEBHOOK_URL}/api/promos", timeout=30)
        if response.status_code == 200:
            data = response.json()
            # Данные могут быть в data['promocodes'] или просто data
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'promocodes' in data:
                return data['promocodes']
            elif isinstance(data, dict) and 'data' in data:
                return data['data']
            return []
        return []
    except Exception as e:
        print(f"Ошибка получения промокодов: {e}")
        return []

def delete_promocode_on_server(promo_id):
    try:
        response = requests.post(
            f"{WEBHOOK_URL}/api/delete-promo",
            json={"promo_id": promo_id},
            timeout=30
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Ошибка удаления промокода: {e}")
        return False

# ========== ФУНКЦИИ ДЛЯ ОТПРАВКИ ТОВАРОВ НА СЕРВЕР ==========
def add_product_to_server(name, price, unit, image_url, created_by):
    """Отправляет запрос на создание товара на webhook сервер"""
    try:
        response = requests.post(
            f"{WEBHOOK_URL}/api/add-product",
            json={
                "name": name,
                "price": price,
                "unit": unit,
                "image_url": image_url,
                "created_by": created_by
            },
            timeout=30
        )
        print(f"📤 Отправка товара на сервер: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка добавления товара на сервер: {e}")
        return False

def update_product_on_server(product_id, name=None, price=None, unit=None, image_url=None):
    """Отправляет запрос на обновление товара на webhook сервер"""
    try:
        payload = {"product_id": product_id}
        if name is not None:
            payload["name"] = name
        if price is not None:
            payload["price"] = price
        if unit is not None:
            payload["unit"] = unit
        if image_url is not None:
            payload["image_url"] = image_url
        
        response = requests.post(
            f"{WEBHOOK_URL}/api/update-product",
            json=payload,
            timeout=30
        )
        print(f"📤 Обновление товара на сервере: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка обновления товара на сервере: {e}")
        return False

# ========== СОСТОЯНИЯ FSM ==========
class ShopStates(StatesGroup):
    choosing_city = State()
    browsing_catalog = State()
    chatting_with_admin = State()      # для АДМИНОВ (ответы)
    user_chatting_with_admin = State() # для ПОЛЬЗОВАТЕЛЕЙ (отправка сообщений)
    admin_add = State()
    admin_remove = State()
    admin_permissions = State()
    # Состояния для товаров
    product_add_name = State()
    product_add_unit = State()
    product_add_price = State()
    product_add_image = State()
    product_delete = State()
    # Состояния для редактирования
    product_edit_select = State()
    product_edit_field = State()
    product_edit_name = State()
    product_edit_price = State()
    product_edit_unit = State()
    product_edit_image = State()

class PromoStates(StatesGroup):
    waiting_for_code = State()
    waiting_for_discount_type = State()
    waiting_for_discount_value = State()
    waiting_for_max_uses = State()
    waiting_for_expiry_days = State()

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard(user_id=None, username=None, first_name=None, last_name=None):
    import urllib.parse
    base_url = "https://timis01.github.io/miniappss/"
    
    if user_id:
        web_app_url = f"{base_url}?city=Москва&user_id={user_id}&username={username or ''}&first_name={urllib.parse.quote(first_name or '')}&last_name={urllib.parse.quote(last_name or '')}"
    else:
        web_app_url = base_url
    
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍️ Открыть магазин", web_app=WebAppInfo(url=web_app_url))],
            [KeyboardButton(text="📞 Связаться с администратором")]
        ],
        resize_keyboard=True
    )

def get_admin_keyboard(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Ответить", callback_data=f"reply_{user_id}")],
        [InlineKeyboardButton(text="📜 История", callback_data=f"history_{user_id}")],
        [InlineKeyboardButton(text="📦 Заказы", callback_data=f"orders_{user_id}")]
    ])

def get_super_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Управление админами", callback_data="super_admin_menu")],
        [InlineKeyboardButton(text="🎫 Управление промокодами", callback_data="promo_menu_from_admin")],
        [InlineKeyboardButton(text="📦 Управление товарами", callback_data="product_menu_from_admin")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="super_admin_stats")],
    ])

def get_admin_management_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add")],
        [InlineKeyboardButton(text="➖ Удалить админа", callback_data="admin_remove")],
        [InlineKeyboardButton(text="⚙️ Настроить права", callback_data="admin_permissions")],
        [InlineKeyboardButton(text="📋 Список админов", callback_data="admin_list")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_super")]
    ])

def get_promo_management_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎫 Создать промокод", callback_data="promo_create")],
        [InlineKeyboardButton(text="📋 Список промокодов", callback_data="promo_list")],
        [InlineKeyboardButton(text="🗑 Удалить промокод", callback_data="promo_delete")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_super")]
    ])

def get_product_management_keyboard():
    """Клавиатура для управления товарами"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="product_add")],
        [InlineKeyboardButton(text="📋 Список товаров", callback_data="product_list")],
        [InlineKeyboardButton(text="🔄 Обновить из сервера", callback_data="product_sync")],
        [InlineKeyboardButton(text="✏️ Редактировать товар", callback_data="product_edit")],
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data="product_delete")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_super")]
    ])

def get_product_edit_keyboard(product_id):
    """Клавиатура для выбора поля для редактирования"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Название", callback_data=f"edit_product_name_{product_id}")],
        [InlineKeyboardButton(text="💰 Цена", callback_data=f"edit_product_price_{product_id}")],
        [InlineKeyboardButton(text="📏 Единица измерения", callback_data=f"edit_product_unit_{product_id}")],
        [InlineKeyboardButton(text="🖼️ Картинка", callback_data=f"edit_product_image_{product_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="product_menu_from_admin")]
    ])

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
async def cmd_start(message: Message, state: FSMContext):
    await state.set_state(ShopStates.choosing_city)
    
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    keyboard = get_main_keyboard(user_id, username, first_name, last_name)
    
    await message.answer(
        "Здравствуйте!\n\n"
        "В нашем магазине вы сможете найти все, что скрасит ваши будни "
        "Оформление заказа происходит через Mini App в боте.",
        reply_markup=keyboard
    )

async def open_shop(message: Message, state: FSMContext):
    data = await state.get_data()
    city = data.get('selected_city', 'Москва')
    
    import urllib.parse
    encoded_city = urllib.parse.quote(city)
    
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    
    web_app_url = f"{MINI_APP_URL}?city={encoded_city}&user_id={user_id}&username={username}&first_name={urllib.parse.quote(first_name)}&last_name={urllib.parse.quote(last_name)}"
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍️ Открыть магазин", web_app=WebAppInfo(url=web_app_url))],
            [KeyboardButton(text="📞 Связаться с администратором")]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        f"🏙️ ВАШ ГОРОД: {city}\n\n"
        f"✅ Город сохранён! Нажмите кнопку чтобы открыть магазин:",
        reply_markup=keyboard
    )

async def contact_admin(message: Message, state: FSMContext):
    print("🔍 contact_admin ВЫЗВАНА!")
    print(f"🔍 Пользователь: {message.from_user.id}")
    
    await state.set_state(ShopStates.user_chatting_with_admin)
    print(f"✅ Состояние установлено: {await state.get_state()}")
    
    await message.answer(
        "📝 Напишите ваше сообщение, и я передам его администратору.\n"
        "Вы можете отправить текст или фото."
    )

# ========== КОМАНДА /PROMO ==========
async def cmd_promo(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для управления промокодами.")
        return
    
    await message.answer(
        "🎫 <b>Управление промокодами</b>\n\n"
        "Выберите действие:",
        reply_markup=get_promo_management_keyboard(),
        parse_mode="HTML"
    )

# ========== ОБРАБОТЧИКИ ДЛЯ УПРАВЛЕНИЯ АДМИНАМИ ==========
async def super_admin_panel(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для доступа к этой панели.")
        return
    
    await message.answer(
        "👑 Панель главного администратора\n\n"
        "Выберите действие:",
        reply_markup=get_super_admin_keyboard()
    )

async def super_admin_callback(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    action = callback.data
    
    if action == "super_admin_menu":
        await callback.message.edit_text(
            "👑 Управление администраторами\n\n"
            "Выберите действие:",
            reply_markup=get_admin_management_keyboard()
        )
    elif action == "promo_menu_from_admin":
        await callback.message.edit_text(
            "🎫 Управление промокодами\n\n"
            "Выберите действие:",
            reply_markup=get_promo_management_keyboard()
        )
    elif action == "product_menu_from_admin":
        await callback.message.edit_text(
            "📦 Управление товарами\n\n"
            "Выберите действие:",
            reply_markup=get_product_management_keyboard()
        )
    elif action == "back_to_super":
        await callback.message.edit_text(
            "👑 Панель главного администратора\n\n"
            "Выберите действие:",
            reply_markup=get_super_admin_keyboard()
        )
    elif action == "super_admin_stats":
        conn = sqlite3.connect('shop_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM orders")
        orders_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM messages")
        messages_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT user_id) FROM messages")
        users_count = cursor.fetchone()[0]
        conn.close()
        
        admins = get_all_admins()
        text = f"📊 СТАТИСТИКА\n\n"
        text += f"👥 Пользователей: {users_count}\n"
        text += f"📦 Заказов: {orders_count}\n"
        text += f"💬 Сообщений: {messages_count}\n"
        text += f"👮‍♂️ Администраторов: {len(admins)}\n\n"
        text += f"Список админов:\n"
        for admin in admins:
            user_id, username, _, _, _ = admin
            text += f"• ID: {user_id} (@{username})\n"
        
        await callback.message.edit_text(text, reply_markup=get_super_admin_keyboard())
    elif action == "admin_list":
        admins = get_all_admins()
        text = "📋 СПИСОК АДМИНИСТРАТОРОВ\n\n"
        for admin in admins:
            user_id, username, can_respond, can_orders, can_history = admin
            permissions = []
            if can_respond:
                permissions.append("✏️ отвечать")
            if can_orders:
                permissions.append("📦 заказы")
            if can_history:
                permissions.append("📜 историю")
            rights = ", ".join(permissions) if permissions else "нет прав"
            text += f"• ID: {user_id} (@{username})\n"
            text += f"  Права: {rights}\n\n"
        
        await callback.message.edit_text(text, reply_markup=get_admin_management_keyboard())
    
    await callback.answer()

async def admin_add_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🔹 Добавление администратора\n\n"
        "Отправьте ID пользователя, которого хотите сделать администратором.\n"
        "Чтобы узнать ID, пользователь может написать боту @userinfobot\n\n"
        "Пример: 123456789"
    )
    await state.set_state(ShopStates.admin_add)
    await callback.answer()

async def admin_add_process(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    
    try:
        user_id = int(message.text.strip())
        
        if user_id == SUPER_ADMIN_ID:
            await message.answer("❌ Это уже главный администратор!")
            await state.clear()
            return
        
        try:
            user = await message.bot.get_chat(user_id)
            username = user.username or f"user_{user_id}"
        except:
            await message.answer("❌ Пользователь с таким ID не найден в Telegram.")
            await state.clear()
            return
        
        add_admin(user_id, username, message.from_user.id)
        
        await message.answer(
            f"✅ Администратор успешно добавлен!\n\n"
            f"ID: {user_id}\n"
            f"Username: @{username}\n\n"
            f"Теперь вы можете настроить его права в меню."
        )
        
    except ValueError:
        await message.answer("❌ Неверный формат ID. Отправьте число.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    
    await state.clear()

async def admin_remove_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    admins = get_all_admins()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for admin in admins:
        user_id, username, _, _, _ = admin
        if user_id != SUPER_ADMIN_ID:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"❌ Удалить {username} (ID: {user_id})",
                    callback_data=f"remove_admin_{user_id}"
                )
            ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="super_admin_menu")
    ])
    
    await callback.message.edit_text(
        "🔴 Удаление администратора\n\n"
        "Выберите администратора для удаления:",
        reply_markup=keyboard
    )
    await callback.answer()

async def admin_remove_process(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[2])
    
    if remove_admin(user_id):
        await callback.message.edit_text(
            f"✅ Администратор с ID {user_id} удален.",
            reply_markup=get_admin_management_keyboard()
        )
    else:
        await callback.message.edit_text(
            "❌ Нельзя удалить главного администратора!",
            reply_markup=get_admin_management_keyboard()
        )
    await callback.answer()

async def admin_permissions_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    admins = get_all_admins()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for admin in admins:
        user_id, username, _, _, _ = admin
        if user_id != SUPER_ADMIN_ID:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"⚙️ {username} (ID: {user_id})",
                    callback_data=f"permissions_admin_{user_id}"
                )
            ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="super_admin_menu")
    ])
    
    await callback.message.edit_text(
        "⚙️ Настройка прав администраторов\n\n"
        "Выберите администратора для настройки:",
        reply_markup=keyboard
    )
    await callback.answer()

async def admin_permissions_edit(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[2])
    perms = get_admin_permissions(user_id)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'✅' if perms['respond'] else '❌'} Отвечать пользователям", callback_data=f"toggle_respond_{user_id}")],
        [InlineKeyboardButton(text=f"{'✅' if perms['orders'] else '❌'} Просмотр заказов", callback_data=f"toggle_orders_{user_id}")],
        [InlineKeyboardButton(text=f"{'✅' if perms['history'] else '❌'} Просмотр истории", callback_data=f"toggle_history_{user_id}")],
        [InlineKeyboardButton(text="💾 Сохранить", callback_data=f"save_permissions_{user_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_permissions")]
    ])
    
    await callback.message.edit_text(
        f"⚙️ Настройка прав для ID: {user_id}\n\n"
        f"Нажмите на право, чтобы изменить его статус:",
        reply_markup=keyboard
    )
    await callback.answer()

async def toggle_permission(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    parts = callback.data.split("_")
    perm_type = parts[1]
    user_id = int(parts[2])
    
    perms = get_admin_permissions(user_id)
    
    if perm_type == "respond":
        perms['respond'] = not perms['respond']
        update_admin_permissions(user_id, can_respond=perms['respond'])
    elif perm_type == "orders":
        perms['orders'] = not perms['orders']
        update_admin_permissions(user_id, can_view_orders=perms['orders'])
    elif perm_type == "history":
        perms['history'] = not perms['history']
        update_admin_permissions(user_id, can_view_history=perms['history'])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'✅' if perms['respond'] else '❌'} Отвечать пользователям", callback_data=f"toggle_respond_{user_id}")],
        [InlineKeyboardButton(text=f"{'✅' if perms['orders'] else '❌'} Просмотр заказов", callback_data=f"toggle_orders_{user_id}")],
        [InlineKeyboardButton(text=f"{'✅' if perms['history'] else '❌'} Просмотр истории", callback_data=f"toggle_history_{user_id}")],
        [InlineKeyboardButton(text="💾 Сохранить", callback_data=f"save_permissions_{user_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_permissions")]
    ])
    
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer(f"✅ Право изменено")

async def save_permissions(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[2])
    
    await callback.message.edit_text(
        f"✅ Права для администратора ID: {user_id} сохранены.",
        reply_markup=get_admin_management_keyboard()
    )
    await callback.answer()

# ========== ОБРАБОТЧИКИ ДЛЯ ПРОМОКОДОВ ==========
async def promo_create_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🎫 <b>Создание промокода</b>\n\n"
        "Введите код промокода (или отправьте 'случайный' для генерации):\n\n"
        "Пример: <code>SUMMER2024</code> или <code>случайный</code>",
        parse_mode="HTML"
    )
    await state.set_state(PromoStates.waiting_for_code)
    await callback.answer()

async def promo_code_received(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    
    code = message.text.strip()
    
    if code.lower() == 'случайный':
        code = generate_promocode()
        await message.answer(f"🔑 Сгенерирован код: <code>{code}</code>", parse_mode="HTML")
    
    await state.update_data(promo_code=code.upper())
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Фиксированная сумма", callback_data="promo_type_fixed")],
        [InlineKeyboardButton(text="📊 Процент скидки", callback_data="promo_type_percent")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="promo_cancel")]
    ])
    
    await message.answer(
        "📊 <b>Выберите тип скидки:</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(PromoStates.waiting_for_discount_type)

async def promo_type_selected(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    promo_type = callback.data.split("_")[2]
    await state.update_data(promo_type=promo_type)
    
    type_text = "фиксированную сумму (руб)" if promo_type == "fixed" else "процент скидки (%)"
    
    await callback.message.edit_text(
        f"💰 <b>Введите {type_text}</b>\n\n"
        f"Пример: {10 if promo_type == 'percent' else 500}\n\n"
        f"<i>Скидка будет применена к общей сумме заказа</i>",
        parse_mode="HTML"
    )
    await state.set_state(PromoStates.waiting_for_discount_value)
    await callback.answer()

async def promo_value_received(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    
    try:
        value = int(message.text.strip())
        if value <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введите положительное число!")
        return
    
    data = await state.get_data()
    promo_type = data.get('promo_type')
    
    if promo_type == 'percent' and value > 100:
        await message.answer("❌ Процент скидки не может быть больше 100!")
        return
    
    await state.update_data(promo_value=value)
    
    await message.answer(
        "🔢 <b>Введите максимальное количество использований</b>\n\n"
        "Пример: <code>1</code> (одноразовый) или <code>100</code>\n"
        "Для бесконечных введите <code>0</code>",
        parse_mode="HTML"
    )
    await state.set_state(PromoStates.waiting_for_max_uses)

async def promo_max_uses_received(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    
    try:
        max_uses = int(message.text.strip())
        if max_uses < 0:
            raise ValueError
    except:
        await message.answer("❌ Введите число (0 для бесконечных)")
        return
    
    if max_uses == 0:
        max_uses = 999999
    
    await state.update_data(promo_max_uses=max_uses)
    
    await message.answer(
        "📅 <b>Введите срок действия (дней)</b>\n\n"
        "Пример: <code>30</code> (30 дней)\n"
        "Для бессрочных введите <code>0</code>",
        parse_mode="HTML"
    )
    await state.set_state(PromoStates.waiting_for_expiry_days)

async def promo_expiry_received(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    
    try:
        days = int(message.text.strip())
        if days < 0:
            raise ValueError
    except:
        await message.answer("❌ Введите число (0 для бессрочных)")
        return
    
    data = await state.get_data()
    code = data.get('promo_code')
    promo_type = data.get('promo_type')
    value = data.get('promo_value')
    max_uses = data.get('promo_max_uses')
    
    success = create_promocode_on_server(
        code=code,
        discount_type=promo_type,
        discount_value=value,
        max_uses=max_uses,
        expires_days=days if days > 0 else 3650,
        created_by=message.from_user.id
    )
    
    if success:
        type_text = "фиксированная сумма" if promo_type == "fixed" else "процент"
        await message.answer(
            f"✅ <b>Промокод создан!</b>\n\n"
            f"🎫 Код: <code>{code}</code>\n"
            f"📊 Тип: {type_text}\n"
            f"💰 Значение: {value}{'%' if promo_type == 'percent' else ' руб'}\n"
            f"🔢 Использований: {'∞' if max_uses == 999999 else max_uses}\n"
            f"📅 Дней: {days if days > 0 else '∞'}\n\n"
            f"Промокод можно активировать в Mini App при оформлении заказа!",
            parse_mode="HTML"
        )
    else:
        await message.answer("❌ Ошибка: не удалось создать промокод!")
    
    await state.clear()

async def promo_list(callback: CallbackQuery):
    print("🔍 promo_list ВЫЗВАНА!")
    promos = get_promocodes_from_server()
    print(f"🔍 Полученные промокоды: {promos}")  # ← Посмотри, что приходит
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    promos = get_promocodes_from_server()
    
    if not promos:
        await callback.message.edit_text("📭 Промокодов пока нет.")
        await callback.answer()
        return
    
    text = "📋 <b>Список промокодов</b>\n\n"
    for p in promos:
        status = "✅ активен" if p.get('is_active', 1) else "❌ неактивен"
        # Используем правильные названия полей
        discount_type = p.get('discount_type', p.get('type', 'percent'))
        discount_value = p.get('discount_value', p.get('value', 0))
        type_text = f"{discount_value}%" if discount_type == 'percent' else f"{discount_value} руб"
        text += f"🎫 <code>{p.get('code', '???')}</code>\n"
        text += f"   {type_text} | Использован: {p.get('used_count', 0)}/{p.get('max_uses', 0)}\n"
        text += f"   {status}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="promo_menu_from_admin")]
    ])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

async def promo_delete_start(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    promos = get_promocodes_from_server()
    
    if not promos:
        await callback.message.edit_text("📭 Нет промокодов для удаления.")
        await callback.answer()
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for p in promos:
        if p.get('is_active', 1):
            discount_type = p.get('discount_type', p.get('type', 'percent'))
            discount_value = p.get('discount_value', p.get('value', 0))
            type_text = f"{discount_value}%" if discount_type == 'percent' else f"{discount_value} руб"
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"🗑 {p.get('code', '???')} ({type_text})",
                    callback_data=f"delete_promo_{p.get('id')}"
                )
            ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="promo_menu_from_admin")
    ])
    
    await callback.message.edit_text(
        "🗑 <b>Выберите промокод для удаления:</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

async def promo_delete_confirm(callback: CallbackQuery):
    print("🔍🔍🔍 promo_delete_confirm ВЫЗВАНА! 🔍🔍🔍")
    print(f"callback.data: {callback.data}")
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    promo_id = int(callback.data.split("_")[2])
    
    success = delete_promocode_on_server(promo_id)
    
    if success:
        await callback.answer("✅ Промокод удален!", show_alert=True)
    else:
        await callback.answer("❌ Ошибка удаления!", show_alert=True)
    
    await callback.message.edit_text(
        "🎫 Управление промокодами\n\n"
        "Выберите действие:",
        reply_markup=get_promo_management_keyboard()
    )

async def promo_cancel(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    await state.clear()
    
    await callback.message.edit_text(
        "🎫 Управление промокодами\n\n"
        "Выберите действие:",
        reply_markup=get_promo_management_keyboard()
    )
    await callback.answer()

# ========== ОБРАБОТЧИКИ ДЛЯ ТОВАРОВ ==========
async def product_menu(callback: CallbackQuery):
    """Меню управления товарами"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📦 <b>Управление товарами</b>\n\n"
        "Выберите действие:",
        reply_markup=get_product_management_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

async def product_sync(callback: CallbackQuery):
    """Принудительная синхронизация товаров с сервером"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    await callback.answer("🔄 Синхронизация...", show_alert=False)
    
    try:
        response = requests.get(f"{WEBHOOK_URL}/api/products", timeout=15)
        if response.status_code == 200:
            data = response.json()
            products = data.get('products', [])
            
            conn = sqlite3.connect(PRODUCTS_DB)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM products")
            
            for p in products:
                cursor.execute('''
                INSERT INTO products (id, name, price, unit, image_url, created_at, created_by, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ''', (p['id'], p['name'], p['price'], p['unit'], p['image'], datetime.now().isoformat(), 1))
            
            conn.commit()
            conn.close()
            
            await callback.message.edit_text(
                f"✅ Синхронизировано {len(products)} товаров с сервера.\n\n"
                f"📦 <b>Управление товарами</b>\n\n"
                "Выберите действие:",
                reply_markup=get_product_management_keyboard(),
                parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                f"❌ Ошибка: статус {response.status_code}",
                reply_markup=get_product_management_keyboard()
            )
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка: {e}",
            reply_markup=get_product_management_keyboard()
        )

async def product_add_start(callback: CallbackQuery, state: FSMContext):
    """Начало добавления товара"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📦 <b>Добавление товара</b>\n\n"
        "Введите <b>название</b> товара:\n"
        "Пример: <code>Шишки 🌰</code>",
        parse_mode="HTML"
    )
    await state.set_state(ShopStates.product_add_name)
    await callback.answer()

async def product_add_name_received(message: Message, state: FSMContext):
    """Получено название товара"""
    if not is_super_admin(message.from_user.id):
        return
    
    name = message.text.strip()
    await state.update_data(product_name=name)
    
    await message.answer(
        "📏 Введите <b>единицу измерения</b>:\n"
        "Пример: <code>гр</code> (грамм), <code>мл</code> (миллилитр), <code>шт</code> (штук)",
        parse_mode="HTML"
    )
    await state.set_state(ShopStates.product_add_unit)

async def product_add_unit_received(message: Message, state: FSMContext):
    """Получена единица измерения"""
    if not is_super_admin(message.from_user.id):
        return
    
    unit = message.text.strip()
    await state.update_data(product_unit=unit)
    
    await message.answer(
        "💰 Введите <b>цену за 1 единицу</b> (в рублях):\n"
        f"Пример: <code>3000</code> (означает 3000 руб за 1 {unit})",
        parse_mode="HTML"
    )
    await state.set_state(ShopStates.product_add_price)

async def product_add_price_received(message: Message, state: FSMContext):
    """Получена цена за единицу"""
    if not is_super_admin(message.from_user.id):
        return
    
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введите положительное число!")
        return
    
    await state.update_data(product_price=price)
    
    await message.answer(
        "🖼️ Отправьте <b>картинку</b> для товара (файлом) или введите ссылку.\n"
        "Чтобы пропустить, отправьте <code>пропустить</code>",
        parse_mode="HTML"
    )
    await state.set_state(ShopStates.product_add_image)

async def product_add_image_received(message: Message, state: FSMContext):
    """Получена картинка - ОТПРАВЛЯЕТ НА СЕРВЕР"""
    if not is_super_admin(message.from_user.id):
        return
    
    image_url = None
    
    if message.photo:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        await message.answer("🖼️ Фото получено!")
    elif message.text:
        text = message.text.strip()
        if text.lower() != 'пропустить':
            image_url = text
    
    data = await state.get_data()
    name = data.get('product_name')
    unit = data.get('product_unit')
    price = data.get('product_price')
    
    print(f"📦 Отправка товара на сервер: {name}, {price} руб / {unit}")
    
    success = add_product_to_server(name, price, unit, image_url, message.from_user.id)
    
    if success:
        await message.answer(
            f"✅ <b>Товар добавлен на сервер!</b>\n\n"
            f"📦 Название: {name}\n"
            f"📏 Ед. изм.: {unit}\n"
            f"💰 Цена: {price} руб / {unit}\n"
            f"🖼️ Картинка: {'есть' if image_url else 'нет'}\n\n"
            f"Товар появится в Mini App после обновления страницы.",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "❌ <b>Ошибка при добавлении товара на сервер!</b>\n\n"
            f"Сервер: {WEBHOOK_URL}",
            parse_mode="HTML"
        )
    
    await state.clear()

async def product_list(callback: CallbackQuery):
    """Показать список товаров (из локальной БД для отображения в боте)"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    products = get_all_products_local()
    
    if not products:
        await callback.message.edit_text("📭 Товаров пока нет.")
        await callback.answer()
        return
    
    text = "📦 <b>Список товаров</b>\n\n"
    for p in products:
        text += f"🆔 <b>{p[0]}</b>. {p[1]}\n"
        text += f"   💰 {p[2]} руб / {p[3]}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="product_menu_from_admin")]
    ])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

async def product_delete_start(callback: CallbackQuery, state: FSMContext):
    """Начало удаления товара"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    products = get_all_products_local()
    
    if not products:
        await callback.message.edit_text("📭 Нет товаров для удаления.")
        await callback.answer()
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for p in products:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"🗑 {p[1]} (ID: {p[0]})",
                callback_data=f"delete_product_{p[0]}"
            )
        ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="product_menu_from_admin")
    ])
    
    await callback.message.edit_text(
        "🗑 <b>Выберите товар для удаления:</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

async def product_delete_confirm(callback: CallbackQuery):
    """Подтверждение удаления товара"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[2])
    product = get_product_local(product_id)
    product_name = product[1] if product else "Неизвестный"
    
    delete_product_local(product_id)
    
    try:
        requests.post(
            f"{WEBHOOK_URL}/api/delete-product",
            json={"product_id": product_id},
            timeout=10
        )
    except:
        pass
    
    await callback.answer(f"✅ Товар '{product_name}' удален!", show_alert=True)
    
    await callback.message.edit_text(
        "📦 <b>Управление товарами</b>\n\n"
        "Выберите действие:",
        reply_markup=get_product_management_keyboard(),
        parse_mode="HTML"
    )

async def product_edit_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования товара - выбор товара"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    products = get_all_products_local()
    
    if not products:
        await callback.message.edit_text("📭 Нет товаров для редактирования.")
        await callback.answer()
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for p in products:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"✏️ {p[1]} (ID: {p[0]})",
                callback_data=f"edit_select_{p[0]}"
            )
        ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="product_menu_from_admin")
    ])
    
    await callback.message.edit_text(
        "✏️ <b>Выберите товар для редактирования:</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

async def product_edit_select(callback: CallbackQuery, state: FSMContext):
    """Выбран товар для редактирования"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[2])
    product = get_product_local(product_id)
    
    if not product:
        await callback.answer("❌ Товар не найден", show_alert=True)
        return
    
    await state.update_data(edit_product_id=product_id)
    
    text = (
        f"✏️ <b>Редактирование товара</b>\n\n"
        f"🆔 ID: {product[0]}\n"
        f"📦 Название: {product[1]}\n"
        f"💰 Цена: {product[2]} руб / {product[3]}\n"
        f"📏 Ед. изм.: {product[3]}\n"
        f"🖼️ Картинка: {'есть' if product[4] else 'нет'}\n\n"
        f"Выберите поле для редактирования:"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_product_edit_keyboard(product_id),
        parse_mode="HTML"
    )
    await callback.answer()

async def product_edit_field(callback: CallbackQuery, state: FSMContext):
    """Выбрано поле для редактирования"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    parts = callback.data.split("_")
    field = parts[2]
    product_id = int(parts[3])
    
    await state.update_data(edit_field=field, edit_product_id=product_id)
    
    prompts = {
        'name': "📝 Введите <b>новое название</b> товара:",
        'price': "💰 Введите <b>новую цену</b> товара (в рублях):",
        'unit': "📏 Введите <b>новую единицу измерения</b> (например: гр, шт, мл):",
        'image': "🖼️ Отправьте <b>новую картинку</b> для товара (файлом) или введите ссылку:"
    }
    
    await callback.message.edit_text(
        prompts.get(field, "Введите новое значение:"),
        parse_mode="HTML"
    )
    
    if field == 'name':
        await state.set_state(ShopStates.product_edit_name)
    elif field == 'price':
        await state.set_state(ShopStates.product_edit_price)
    elif field == 'unit':
        await state.set_state(ShopStates.product_edit_unit)
    elif field == 'image':
        await state.set_state(ShopStates.product_edit_image)
    
    await callback.answer()

async def product_edit_name_received(message: Message, state: FSMContext):
    """Получено новое название - ОТПРАВЛЯЕТ НА СЕРВЕР"""
    if not is_super_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    product_id = data.get('edit_product_id')
    new_name = message.text.strip()
    
    if new_name:
        success = update_product_on_server(product_id, name=new_name)
        if success:
            await message.answer(f"✅ Название товара обновлено на: <b>{new_name}</b>", parse_mode="HTML")
        else:
            await message.answer("❌ Ошибка обновления товара на сервере!")
    else:
        await message.answer("❌ Название не может быть пустым!")
    
    await state.clear()

async def product_edit_price_received(message: Message, state: FSMContext):
    """Получена новая цена - ОТПРАВЛЯЕТ НА СЕРВЕР"""
    if not is_super_admin(message.from_user.id):
        return
    
    try:
        new_price = int(message.text.strip())
        if new_price <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введите положительное число!")
        return
    
    data = await state.get_data()
    product_id = data.get('edit_product_id')
    
    success = update_product_on_server(product_id, price=new_price)
    if success:
        await message.answer(f"✅ Цена товара обновлена на: <b>{new_price} руб.</b>", parse_mode="HTML")
    else:
        await message.answer("❌ Ошибка обновления товара на сервере!")
    
    await state.clear()

async def product_edit_unit_received(message: Message, state: FSMContext):
    """Получена новая единица измерения - ОТПРАВЛЯЕТ НА СЕРВЕР"""
    if not is_super_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    product_id = data.get('edit_product_id')
    new_unit = message.text.strip() or "гр"
    
    success = update_product_on_server(product_id, unit=new_unit)
    if success:
        await message.answer(f"✅ Единица измерения обновлена на: <b>{new_unit}</b>", parse_mode="HTML")
    else:
        await message.answer("❌ Ошибка обновления товара на сервере!")
    
    await state.clear()

async def product_edit_image_received(message: Message, state: FSMContext):
    """Получена новая картинка - ОТПРАВЛЯЕТ НА СЕРВЕР"""
    if not is_super_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    product_id = data.get('edit_product_id')
    image_url = None
    
    if message.photo:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        await message.answer("🖼️ Фото получено!")
    elif message.text:
        text = message.text.strip()
        if text.lower() != 'пропустить':
            image_url = text
    
    if image_url:
        success = update_product_on_server(product_id, image_url=image_url)
        if success:
            await message.answer(f"✅ Картинка товара обновлена!")
        else:
            await message.answer("❌ Ошибка обновления картинки на сервере!")
    else:
        await message.answer("❌ Не удалось обновить картинку")
    
    await state.clear()

# ========== ОБРАБОТЧИКИ ДЛЯ ВЗАИМОДЕЙСТВИЯ С ПОЛЬЗОВАТЕЛЯМИ ==========
async def handle_web_app_data(message: Message, state: FSMContext):
    try:
        data = json.loads(message.web_app_data.data)
        action = data.get('action')
        
        if action == 'contact_admin':
            user_id = message.from_user.id
            username = message.from_user.username or "нет username"
            city = data.get('city', 'не указан')
            
            conn = sqlite3.connect('shop_bot.db')
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO messages (user_id, username, message_text, message_type, timestamp) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, f"Запрос связи с администратором из Mini App (г. {city})", "contact_request", datetime.now().isoformat())
            )
            conn.commit()
            conn.close()
            
            admin_message = (
                f"📞 ЗАПРОС СВЯЗИ ИЗ MINI APP!\n\n"
                f"👤 Пользователь: @{username} (ID: {user_id})\n"
                f"🏙️ Город: {city}\n"
                f"📅 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"Пользователь хочет связаться с администратором."
            )
            
            for admin_id in get_admin_ids():
                try:
                    await message.bot.send_message(admin_id, admin_message, reply_markup=get_admin_keyboard(user_id))
                except:
                    pass
            
            await message.answer("✅ Запрос отправлен администратору!\n\nОн свяжется с вами в ближайшее время.")
            return
        
        if action == 'order':
            product_name = data.get('productName')
            quantity = data.get('quantity', 1)
            total_price = data.get('totalPrice')
            final_price = data.get('finalPrice', total_price)
            city = data.get('city', 'не указан')
            promocode = data.get('promocode')
            
            user_id = message.from_user.id
            username = message.from_user.username or "нет username"
            
            conn = sqlite3.connect('shop_bot.db')
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO orders (user_id, username, product_name, quantity, city, total_price, order_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, username, product_name, quantity, city, final_price, datetime.now().isoformat())
            )
            cursor.execute(
                "INSERT INTO messages (user_id, username, message_text, message_type, timestamp) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, f"Заказ через Mini App: {product_name} x{quantity} = {final_price} руб. (г. {city})", "order", datetime.now().isoformat())
            )
            conn.commit()
            conn.close()
            
            promo_text = f"\n🎫 Промокод: {promocode['code']} ({promocode['value']}{'%' if promocode['type'] == 'percent' else ' руб'})" if promocode else ""
            
            await message.answer(
                f"✅ Заказ через Mini App оформлен!\n\n"
                f"🏙️ Город: {city}\n"
                f"📦 Товар: {product_name}\n"
                f"📊 Количество: {quantity} {data.get('unit', 'гр')}\n"
                f"💰 Сумма: {total_price} руб.{promo_text}\n"
                f"💵 Итого: {final_price} руб.\n\n"
                f"В ближайшее время с вами свяжется менеджер."
            )
            
            admin_message = (
                f"🛍 НОВЫЙ ЗАКАЗ ЧЕРЕЗ MINI APP!\n\n"
                f"👤 Пользователь: @{username} (ID: {user_id})\n"
                f"🏙️ Город: {city}\n"
                f"📦 Товар: {product_name}\n"
                f"📊 Количество: {quantity} {data.get('unit', 'гр')}\n"
                f"💰 Сумма: {total_price} руб.{promo_text}\n"
                f"💵 Итого: {final_price} руб.\n"
                f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
            
            for admin_id in get_admin_ids():
                try:
                    await message.bot.send_message(admin_id, admin_message, reply_markup=get_admin_keyboard(user_id))
                except:
                    pass
            return
            
    except Exception as e:
        logging.error(f"Ошибка обработки данных Mini App: {e}")

async def handle_user_chatting_with_admin(message: Message, state: FSMContext):
    """Обрабатывает сообщения от пользователей, которые хотят связаться с админом"""
    print("🔍 handle_user_chatting_with_admin ВЫЗВАНА!")
    print(f"🔍 Текст: {message.text}")
    print(f"🔍 От кого: {message.from_user.id}")
    
    user_id = message.from_user.id
    username = message.from_user.username or "нет username"
    text = message.text
    
    # Сохраняем в БД
    conn = sqlite3.connect('shop_bot.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (user_id, username, message_text, message_type, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, text, "user", datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    
    # Получаем данные пользователя
    user_data = await state.get_data()
    city = user_data.get('selected_city', 'не указан')
    
    # Формируем сообщение для админов
    admin_text = (
        f"💬 СООБЩЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ\n\n"
        f"👤 Пользователь: @{username}\n"
        f"🆔 ID: {user_id}\n"
        f"🏙️ Город: {city}\n"
        f"📅 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        f"📝 Текст:\n{text}"
    )
    
    # Отправляем всем админам
    sent = 0
    for admin_id in get_admin_ids():
        try:
            perms = get_admin_permissions(admin_id)
            if is_super_admin(admin_id) or perms['respond']:
                await message.bot.send_message(
                    admin_id,
                    admin_text,
                    reply_markup=get_admin_keyboard(user_id)
                )
                sent += 1
        except Exception as e:
            print(f"Ошибка отправки админу {admin_id}: {e}")
    
    if sent > 0:
        await message.answer("✅ Ваше сообщение отправлено администратору.")
    else:
        await message.answer("⚠️ Не удалось отправить сообщение.")
    
    # Сбрасываем состояние
    await state.clear()

async def handle_user_message(message: Message, state: FSMContext):
    """Обрабатывает обычные сообщения от пользователей (не в режиме чата с админом)"""
    print("="*50)
    print("🔍 handle_user_message ВЫЗВАНА!")
    print(f"🔍 Текст: {message.text}")
    print(f"🔍 От кого: {message.from_user.id}")
    print(f"🔍 Текущее состояние: {await state.get_state()}")
    
    user_id = message.from_user.id
    username = message.from_user.username or "нет username"
    text = message.text
    
    if is_admin(user_id) or text.startswith('/'):
        print("⏭️ Пропуск (админ или команда)")
        return
    
    # Проверяем, не в режиме ли чата с админом (на всякий случай)
    current_state = await state.get_state()
    if current_state == ShopStates.user_chatting_with_admin:
        print("⚠️ Пользователь в режиме чата с админом, но сообщение попало в handle_user_message")
        # Перенаправляем в правильный обработчик
        await handle_user_chatting_with_admin(message, state)
        return
    
    conn = sqlite3.connect('shop_bot.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (user_id, username, message_text, message_type, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, text, "user", datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    
    user_data = await state.get_data()
    city = user_data.get('selected_city', 'не указан')
    
    admin_text = (
        f"💬 СООБЩЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ\n\n"
        f"👤 Пользователь: @{username}\n"
        f"🆔 ID: {user_id}\n"
        f"🏙️ Город: {city}\n"
        f"📅 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        f"📝 Текст:\n{text}"
    )
    
    sent = 0
    for admin_id in get_admin_ids():
        try:
            perms = get_admin_permissions(admin_id)
            if is_super_admin(admin_id) or perms['respond']:
                await message.bot.send_message(admin_id, admin_text, reply_markup=get_admin_keyboard(user_id))
                sent += 1
        except:
            pass
    
    if sent > 0:
        await message.answer("✅ Ваше сообщение отправлено администратору.")
    else:
        await message.answer("⚠️ Не удалось отправить сообщение.")
    
    print("="*50)

async def handle_user_photo(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or "нет username"
    caption = message.caption or "без подписи"
    
    if is_admin(user_id):
        return
    
    # Проверяем режим чата с админом
    current_state = await state.get_state()
    if current_state == ShopStates.user_chatting_with_admin:
        # Перенаправляем в обработчик чата с админом
        await handle_user_chatting_with_admin(message, state)
        return
    
    user_data = await state.get_data()
    city = user_data.get('selected_city', 'не указан')
    photo = message.photo[-1]
    
    conn = sqlite3.connect('shop_bot.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (user_id, username, message_text, message_type, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, f"[ФОТО] {caption}", "user_photo", datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    
    admin_caption = (
        f"📸 ФОТО ОТ ПОЛЬЗОВАТЕЛЯ\n\n"
        f"👤 @{username} (ID: {user_id})\n"
        f"🏙️ Город: {city}\n"
        f"📝 {caption}"
    )
    
    sent = 0
    for admin_id in get_admin_ids():
        try:
            perms = get_admin_permissions(admin_id)
            if is_super_admin(admin_id) or perms['respond']:
                await message.bot.send_photo(admin_id, photo=photo.file_id, caption=admin_caption, reply_markup=get_admin_keyboard(user_id))
                sent += 1
        except:
            pass
    
    if sent > 0:
        await message.answer("✅ Ваше фото отправлено администратору!")
    else:
        await message.answer("⚠️ Не удалось отправить фото.")

# ========== ОБРАБОТЧИКИ ДЛЯ АДМИНИСТРАТОРОВ ==========
async def admin_reply(callback: CallbackQuery, state: FSMContext):
    print("="*50)
    print("🔍 admin_reply ВЫЗВАНА!")
    print(f"🔍 callback.data: {callback.data}")
    print(f"🔍 from_user.id: {callback.from_user.id}")
    print(f"🔍 is_admin: {is_admin(callback.from_user.id)}")
    
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав администратора", show_alert=True)
        print("❌ Не админ!")
        return
    
    perms = get_admin_permissions(callback.from_user.id)
    if not perms['respond'] and not is_super_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет права отвечать пользователям", show_alert=True)
        print("❌ Нет прав отвечать!")
        return
    
    user_id = int(callback.data.split("_")[1])
    print(f"🔍 user_id для ответа: {user_id}")
    
    if user_id == callback.from_user.id:
        await callback.message.answer("❌ Нельзя ответить самому себе!")
        await callback.answer()
        print("❌ Нельзя ответить себе!")
        return
    
    try:
        user = await callback.bot.get_chat(user_id)
        username = user.username or f"id{user_id}"
        user_info = f"@{username} (ID: {user_id})"
        print(f"🔍 Пользователь: {user_info}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        user_info = f"ID: {user_id}"
    
    await state.update_data(reply_to_user=user_id)
    await state.set_state(ShopStates.chatting_with_admin)
    print(f"✅ Состояние изменено на chatting_with_admin")
    print(f"✅ reply_to_user = {user_id}")
    
    await callback.message.answer(
        f"✏️ Режим ответа пользователю {user_info}\n\n"
        f"Теперь все ваши сообщения и фото будут отправляться этому пользователю.\n"
        f"Чтобы выйти из режима ответа, отправьте /cancel"
    )
    await callback.answer("✅ Режим ответа активирован")
    print("="*50)

async def send_admin_reply(message: Message, state: FSMContext):
    print("="*50)
    print("🔍 send_admin_reply ВЫЗВАНА!")
    print(f"🔍 Текст сообщения: {message.text}")
    print(f"🔍 От кого: {message.from_user.id}")
    
    if not is_admin(message.from_user.id):
        print("❌ Не админ!")
        return
    
    current_state = await state.get_state()
    print(f"🔍 Текущее состояние: {current_state}")
    print(f"🔍 Нужное состояние: {ShopStates.chatting_with_admin}")
    
    if current_state != ShopStates.chatting_with_admin:
        print("❌ Не в режиме ответа!")
        await message.answer(
            "❌ Вы не в режиме ответа.\n"
            "Нажмите кнопку '✏️ Ответить' под сообщением пользователя."
        )
        return
    
    data = await state.get_data()
    user_id = data.get('reply_to_user')
    print(f"🔍 user_id для ответа: {user_id}")
    
    if not user_id:
        print("❌ Нет user_id!")
        await message.answer("❌ Ошибка: не выбран пользователь для ответа.")
        await state.clear()
        return
    
    try:
        user = await message.bot.get_chat(user_id)
        username = user.username or f"id{user_id}"
        user_info = f"@{username}" if user.username else f"ID: {user_id}"
        print(f"🔍 Пользователь: {user_info}")
    except Exception as e:
        print(f"❌ Ошибка получения пользователя: {e}")
        user_info = f"ID: {user_id}"
    
    conn = sqlite3.connect('shop_bot.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (user_id, username, message_text, message_type, timestamp, is_from_admin) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, "admin", message.text, "admin_reply", datetime.now().isoformat(), 1)
    )
    conn.commit()
    conn.close()
    print("✅ Сообщение сохранено в БД")
    
    try:
        await message.bot.send_message(
            user_id,
            f"✉️ Ответ от администратора:\n\n{message.text}"
        )
        print(f"✅ Сообщение отправлено пользователю {user_id}")
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        await message.answer(f"❌ Не удалось отправить сообщение: {e}")
        return
    
    await message.answer(
        f"✅ Ответ отправлен {user_info}\n"
        f"Текст: {message.text[:50]}{'...' if len(message.text) > 50 else ''}"
    )
    print("="*50)

async def send_admin_photo_reply(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    user_id = data.get('reply_to_user')
    
    if not user_id:
        await message.answer("❌ Ошибка: не выбран пользователь для ответа.")
        await state.clear()
        return
    
    try:
        user = await message.bot.get_chat(user_id)
        username = user.username or f"id{user_id}"
    except:
        username = f"id{user_id}"
    
    photo = message.photo[-1]
    caption = message.caption or "🖼️ Фото от администратора"
    
    await message.bot.send_photo(
        chat_id=user_id,
        photo=photo.file_id,
        caption=f"✉️ Ответ от администратора:\n\n{caption}"
    )
    
    conn = sqlite3.connect('shop_bot.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (user_id, username, message_text, message_type, timestamp, is_from_admin) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, "admin", f"[ФОТО] {caption}", "admin_photo", datetime.now().isoformat(), 1)
    )
    conn.commit()
    conn.close()
    
    await message.answer(f"✅ Фото отправлено пользователю {username} (ID: {user_id})")

async def show_user_history(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав администратора", show_alert=True)
        return
    
    perms = get_admin_permissions(callback.from_user.id)
    if not perms['history'] and not is_super_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет права просматривать историю", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[1])
    
    conn = sqlite3.connect('shop_bot.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT message_text, timestamp, is_from_admin FROM messages WHERE user_id = ? ORDER BY timestamp DESC LIMIT 30",
        (user_id,)
    )
    history = cursor.fetchall()
    conn.close()
    
    if not history:
        await callback.message.answer(f"📭 История сообщений для пользователя {user_id} пуста")
        await callback.answer()
        return
    
    history_text = f"📜 История сообщений пользователя ID: {user_id}\n\n"
    for msg_text, timestamp, is_from_admin in reversed(history):
        sender = "👤 Пользователь" if not is_from_admin else "👨‍💼 Админ"
        time_str = datetime.fromisoformat(timestamp).strftime("%d.%m.%Y %H:%M")
        history_text += f"[{time_str}] {sender}: {msg_text}\n\n"
        
        if len(history_text) > 3500:
            await callback.message.answer(history_text)
            history_text = ""
    
    if history_text:
        await callback.message.answer(history_text)
    
    await callback.answer()

async def show_user_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав администратора", show_alert=True)
        return
    
    perms = get_admin_permissions(callback.from_user.id)
    if not perms['orders'] and not is_super_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет права просматривать заказы", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[1])
    
    conn = sqlite3.connect('shop_bot.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT product_name, quantity, city, total_price, order_date, status FROM orders WHERE user_id = ? ORDER BY order_date DESC",
        (user_id,)
    )
    orders = cursor.fetchall()
    conn.close()
    
    if not orders:
        await callback.message.answer(f"📭 У пользователя {user_id} нет заказов")
        await callback.answer()
        return
    
    orders_text = f"📦 Заказы пользователя ID: {user_id}\n\n"
    for product_name, quantity, city, total_price, order_date, status in orders:
        date_str = datetime.fromisoformat(order_date).strftime("%d.%m.%Y %H:%M")
        orders_text += f"🛍 {date_str}\n"
        orders_text += f"Товар: {product_name}\n"
        orders_text += f"Количество: {quantity} гр\n"
        orders_text += f"Город: {city}\n"
        orders_text += f"Сумма: {total_price} руб.\n"
        orders_text += f"Статус: {status}\n"
        orders_text += "─" * 30 + "\n\n"
    
    await callback.message.answer(orders_text)
    await callback.answer()

async def cmd_cancel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    await state.clear()
    await message.answer("✅ Режим ответа отменен")

# ========== СИНХРОНИЗАЦИЯ ТОВАРОВ С СЕРВЕРА ==========
async def sync_products_from_server():
    """Синхронизирует локальную базу товаров с сервером при запуске бота"""
    try:
        print("🔄 Синхронизация товаров с сервером...")
        response = requests.get(f"{WEBHOOK_URL}/api/products", timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            products = data.get('products', [])
            
            if products:
                conn = sqlite3.connect(PRODUCTS_DB)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM products")
                
                for p in products:
                    cursor.execute('''
                    INSERT INTO products (id, name, price, unit, image_url, created_at, created_by, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    ''', (p['id'], p['name'], p['price'], p['unit'], p['image'], datetime.now().isoformat(), 1))
                
                conn.commit()
                conn.close()
                print(f"✅ Синхронизировано {len(products)} товаров с сервера")
            else:
                print("⚠️ Сервер вернул пустой список товаров")
        else:
            print(f"⚠️ Ошибка синхронизации: статус {response.status_code}")
            
    except requests.exceptions.Timeout:
        print("⚠️ Таймаут синхронизации товаров (сервер не ответил)")
    except Exception as e:
        print(f"⚠️ Ошибка синхронизации товаров: {e}")

# ========== РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ ==========
def register_handlers(dp: Dispatcher):
    # Основные команды
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_cancel, Command("cancel"))
    dp.message.register(super_admin_panel, Command("admin"))
    dp.message.register(cmd_promo, Command("promo"))
    
    # Callback-запросы для управления админами
    dp.callback_query.register(super_admin_callback, F.data.in_([
        "super_admin_menu", "super_admin_stats", "admin_list", "back_to_super", "promo_menu_from_admin", "product_menu_from_admin"
    ]))
    dp.callback_query.register(admin_add_start, F.data == "admin_add")
    dp.callback_query.register(admin_remove_start, F.data == "admin_remove")
    dp.callback_query.register(admin_permissions_start, F.data == "admin_permissions")
    dp.callback_query.register(admin_remove_process, F.data.startswith("remove_admin_"))
    dp.callback_query.register(admin_permissions_edit, F.data.startswith("permissions_admin_"))
    dp.callback_query.register(toggle_permission, F.data.startswith("toggle_"))
    dp.callback_query.register(save_permissions, F.data.startswith("save_permissions_"))
    
    # Callback-запросы для промокодов
    dp.callback_query.register(promo_create_start, F.data == "promo_create")
    dp.callback_query.register(promo_type_selected, F.data.startswith("promo_type_"))
    dp.callback_query.register(promo_list, F.data == "promo_list")
    dp.callback_query.register(promo_delete_start, F.data == "promo_delete")
    dp.callback_query.register(promo_delete_confirm, F.data.startswith("delete_promo_"))
    dp.callback_query.register(promo_cancel, F.data == "promo_cancel")
    
    # Callback-запросы для товаров
    dp.callback_query.register(product_menu, F.data == "product_menu_from_admin")
    dp.callback_query.register(product_sync, F.data == "product_sync")
    dp.callback_query.register(product_add_start, F.data == "product_add")
    dp.callback_query.register(product_list, F.data == "product_list")
    dp.callback_query.register(product_delete_start, F.data == "product_delete")
    dp.callback_query.register(product_delete_confirm, F.data.startswith("delete_product_"))
    dp.callback_query.register(product_edit_start, F.data == "product_edit")
    dp.callback_query.register(product_edit_select, F.data.startswith("edit_select_"))
    dp.callback_query.register(product_edit_field, F.data.startswith("edit_product_"))
    
    # Обработчики состояний
    dp.message.register(admin_add_process, ShopStates.admin_add)
    dp.message.register(promo_code_received, PromoStates.waiting_for_code)
    dp.message.register(promo_value_received, PromoStates.waiting_for_discount_value)
    dp.message.register(promo_max_uses_received, PromoStates.waiting_for_max_uses)
    dp.message.register(promo_expiry_received, PromoStates.waiting_for_expiry_days)
    
    # Состояния для товаров
    dp.message.register(product_add_name_received, ShopStates.product_add_name)
    dp.message.register(product_add_unit_received, ShopStates.product_add_unit)
    dp.message.register(product_add_price_received, ShopStates.product_add_price)
    dp.message.register(product_add_image_received, ShopStates.product_add_image)
    dp.message.register(product_edit_name_received, ShopStates.product_edit_name)
    dp.message.register(product_edit_price_received, ShopStates.product_edit_price)
    dp.message.register(product_edit_unit_received, ShopStates.product_edit_unit)
    dp.message.register(product_edit_image_received, ShopStates.product_edit_image)
    
    # Основные callback-запросы
    dp.callback_query.register(admin_reply, F.data.startswith("reply_"))
    dp.callback_query.register(show_user_history, F.data.startswith("history_"))
    dp.callback_query.register(show_user_orders, F.data.startswith("orders_"))
    
    # Кнопки меню
    dp.message.register(open_shop, F.text == "🛍️ Открыть магазин")
    dp.message.register(contact_admin, F.text == "📞 Связаться с администратором")
    
    # Данные из Mini App
    dp.message.register(handle_web_app_data, F.web_app_data)
    
    # ========== ОТВЕТЫ АДМИНИСТРАТОРОВ ==========
    dp.message.register(send_admin_reply, F.text, ShopStates.chatting_with_admin)
    dp.message.register(send_admin_photo_reply, F.photo, ShopStates.chatting_with_admin)
    
    # ========== ЧАТ ПОЛЬЗОВАТЕЛЯ С АДМИНОМ ==========
    dp.message.register(handle_user_chatting_with_admin, F.text, ShopStates.user_chatting_with_admin)
    dp.message.register(handle_user_photo, F.photo, ShopStates.user_chatting_with_admin)
    
    # ========== ОБЫЧНЫЕ СООБЩЕНИЯ ОТ ПОЛЬЗОВАТЕЛЕЙ ==========
    dp.message.register(handle_user_message, F.text, ~F.text.startswith('/'))
    dp.message.register(handle_user_photo, F.photo)

# ========== ЗАПУСК ==========
async def main():
    print("\n" + "="*60)
    print("🚀 ЗАПУСК ТЕЛЕГРАМ БОТА С MINI APP")
    print("="*60)
    
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    register_handlers(dp)
    
    # ========== СИНХРОНИЗАЦИЯ ТОВАРОВ ПРИ ЗАПУСКЕ ==========
    await sync_products_from_server()
    # ======================================================
    
    admins = get_all_admins()
    products = get_all_products_local()
    
    print(f"✅ Бот создан")
    print(f"✅ Mini App URL: {MINI_APP_URL}")
    print(f"✅ Webhook URL: {WEBHOOK_URL}")
    print(f"✅ Товаров в локальной базе: {len(products)}")
    print(f"✅ Городов: {len(CITIES)}")
    print(f"✅ Главный администратор: {SUPER_ADMIN_ID}")
    print(f"✅ Всего администраторов: {len(admins)}")
    print(f"✅ Команда /promo добавлена")
    print(f"✅ Управление товарами добавлено")
    
    if admins:
        print("✅ Список администраторов:")
        for admin in admins:
            user_id, username, can_resp, can_ord, can_hist = admin
            resp_symbol = "✅" if can_resp else "❌"
            ord_symbol = "✅" if can_ord else "❌"
            hist_symbol = "✅" if can_hist else "❌"
            print(f"   • {user_id} (@{username}) - Права: отвечать {resp_symbol}, заказы {ord_symbol}, история {hist_symbol}")
    
    print(f"✅ Поддержка фото: ВКЛЮЧЕНА")
    print("-"*60)
    print("📡 Запуск polling...")
    print("-"*60)
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Ошибка при запуске: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("🛑 Бот остановлен")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем")
