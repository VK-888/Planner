# ✅ Полный main.py
# Поддерживает: задачи с датами, повторы, часовые пояса, напоминания, статистику, кнопки, многопользовательский режим

import logging
import sqlite3
import re
import pytz
import nest_asyncio
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters, ConversationHandler
)
import asyncio

nest_asyncio.apply()
TOKEN = "7934879470:AAE9FIp5kHBLhoT5x27sucUdFIc_IgbdB9Q"
DB_FILE = "tasks.db"
CHOOSE_ACTION, ADD_TASK, CHOOSE_TZ = range(3)
logging.basicConfig(level=logging.INFO)

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                tz TEXT DEFAULT 'UTC'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                task TEXT,
                remind_time TEXT,
                repeat TEXT,
                done INTEGER DEFAULT 0,
                notified_early INTEGER DEFAULT 0
            )
        """)

def get_user_timezone(user_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute("SELECT tz FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return pytz.timezone(row[0]) if row else pytz.utc

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO users (user_id, username, first_name, tz)
            VALUES (?, ?, ?, COALESCE((SELECT tz FROM users WHERE user_id = ?), 'UTC'))
        """, (user.id, user.username, user.first_name, user.id))

    keyboard = ReplyKeyboardMarkup([
        ["➕ Добавить задачу"],
        ["📋 Список задач", "📊 Статистика"],
        ["❓ Формат", "🌍 Установить часовой пояс"]
    ], resize_keyboard=True)
    await update.message.reply_text("Выберите действие:", reply_markup=keyboard)
    return CHOOSE_ACTION

async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "➕ Добавить задачу":
        await update.message.reply_text("✏️ Примеры:\n– Подать отчёт в 17:00 21-05-2025\n– Завтрак ежедневно в 08:00\n– Совещание каждый понедельник в 10:00")
        return ADD_TASK
    elif text == "📋 Список задач":
        return await list_tasks(update, context)
    elif text == "📊 Статистика":
        return await stats(update, context)
    elif text == "❓ Формат":
        await update.message.reply_text("📘 Формат:\n– Задача в 18:00\n– Задача в 09:30 22-05-2025\n– Уборка каждый понедельник в 10:00\n– Завтрак ежедневно в 08:00")
        return CHOOSE_ACTION
    elif text == "🌍 Установить часовой пояс":
        zones = ["Asia/Bishkek", "Europe/Moscow", "Asia/Almaty", "Asia/Tashkent"]
        buttons = [[InlineKeyboardButton(z, callback_data=f"tz_{z}")] for z in zones]
        await update.message.reply_text("🌍 Выберите ваш часовой пояс:", reply_markup=InlineKeyboardMarkup(buttons))
        return CHOOSE_TZ
    else:
        return CHOOSE_ACTION

async def handle_tz_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tz = query.data.replace("tz_", "")
    user_id = query.from_user.id
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE users SET tz = ? WHERE user_id = ?", (tz, user_id))
    await query.edit_message_text(f"✅ Часовой пояс установлен: {tz}")
    return CHOOSE_ACTION

async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tz = get_user_timezone(user_id)
    now = datetime.now(tz)
    text = update.message.text.strip()

    match = re.match(r"^(.*?) в (\d{1,2}:\d{2})(?: (\d{2}-\d{2}-\d{4}))?$", text)
    if not match:
        await update.message.reply_text("⚠️ Неверный формат. Пример: Подать отчёт в 17:00 18-05-2025")
        return ADD_TASK

    task = match.group(1).strip()
    time_str = match.group(2)
    date_str = match.group(3)
    repeat = ""

    if "ежедневно" in task.lower():
        repeat = "daily"
        task = task.replace("ежедневно", "").strip()
    else:
        repeat_match = re.search(r"(каждый|каждую)\s+([а-я]+)", task.lower())
        if repeat_match:
            weekdays = {
                "понедельник": 0, "вторник": 1, "среда": 2,
                "четверг": 3, "пятница": 4, "суббота": 5, "воскресенье": 6
            }
            day = repeat_match.group(2)
            if day in weekdays:
                repeat = day
                days_ahead = (weekdays[day] - now.weekday() + 7) % 7 or 7
                date_str = (now + timedelta(days=days_ahead)).strftime("%d-%m-%Y")
                task = re.sub(r"(каждый|каждую)\s+" + day, "", task, flags=re.IGNORECASE).strip()

    if date_str:
        try:
            day, month, year = map(int, date_str.split("-"))
            remind_date = datetime(year, month, day)
        except:
            await update.message.reply_text("⚠️ Неверная дата. Формат: ДД-ММ-ГГГГ.")
            return ADD_TASK
    else:
        remind_date = now
        if datetime.strptime(time_str, "%H:%M").time() <= now.time():
            remind_date += timedelta(days=1)

    remind_time = datetime.strptime(time_str, "%H:%M").replace(
        year=remind_date.year, month=remind_date.month, day=remind_date.day
    )
    remind_time = tz.localize(remind_time)

    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("INSERT INTO tasks (user_id, task, remind_time, repeat) VALUES (?, ?, ?, ?)",
                     (user_id, task, remind_time.isoformat(), repeat))
    await update.message.reply_text(f"✅ Задача добавлена: {task} — {remind_time.strftime('%d-%m-%Y %H:%M')}")
    return await start(update, context)
