import asyncio
import os
import re
from datetime import datetime, timedelta
from collections import Counter, defaultdict

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

from db import init_db, add_event, month_stats, get_last_events, delete_event
from keep_alive import keep_alive

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Хранилище для выбранных дат в памяти
user_dates = {}

class MedStates(StatesGroup):
    waiting_dose = State()

class CustomDateStates(StatesGroup):
    waiting_date = State()

def main_menu():
    kb = [
        [InlineKeyboardButton(text="🍽 Кормление", callback_data="feed"),
         InlineKeyboardButton(text="😮‍💨 Кашель", callback_data="cough")],
        [InlineKeyboardButton(text="💊 Лекарство", callback_data="med"),
         InlineKeyboardButton(text="🚽 Туалет", callback_data="toilet")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
         InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_last")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def date_menu(action: str):
    kb = [
        [InlineKeyboardButton(text="Сегодня", callback_data=f"{action}:today"),
         InlineKeyboardButton(text="Вчера", callback_data=f"{action}:yesterday")],
        [InlineKeyboardButton(text="📅 Другая дата", callback_data=f"{action}:custom")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def feed_menu():
    kb = [
        [InlineKeyboardButton(text="Сухой", callback_data="feed_type:сухой"),
         InlineKeyboardButton(text="Влажный", callback_data="feed_type:влажный")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def cough_menu():
    kb = [
        [InlineKeyboardButton(text="Лёгкий", callback_data="cough_type:лёгкий"),
         InlineKeyboardButton(text="Сильный", callback_data="cough_type:сильный")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def toilet_menu():
    kb = [
        [InlineKeyboardButton(text="💧 Моча", callback_data="toilet_type:моча"),
         InlineKeyboardButton(text="💩 Кал", callback_data="toilet_type:кал")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

dp = Dispatcher()

@dp.message(Command("start"))
async def start_cmd(msg: Message):
    await msg.answer(
        "Привет! Я трекер здоровья твоей кошки 🐈\n"
        "Выбирай, что произошло:",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "back")
async def back(cb: CallbackQuery):
    await cb.message.edit_text("Что дальше?", reply_markup=main_menu())
    await cb.answer()

# --- Старт выбора дат ---
@dp.callback_query(F.data == "feed")
async def feed_date_cb(cb: CallbackQuery):
    await cb.message.edit_text("Когда было кормление?", reply_markup=date_menu("feed_date"))
    await cb.answer()

@dp.callback_query(F.data == "cough")
async def cough_date_cb(cb: CallbackQuery):
    await cb.message.edit_text("Когда был кашель?", reply_markup=date_menu("cough_date"))
    await cb.answer()

@dp.callback_query(F.data == "toilet")
async def toilet_date_cb(cb: CallbackQuery):
    await cb.message.edit_text("Когда был поход в туалет?", reply_markup=date_menu("toilet_date"))
    await cb.answer()

@dp.callback_query(F.data == "med")
async def med_date_cb(cb: CallbackQuery):
    await cb.message.edit_text("Когда давали лекарство?", reply_markup=date_menu("med_date"))
    await cb.answer()

# --- Обработка "Сегодня/Вчера" ---
@dp.callback_query(F.data.endswith(":today") | F.data.endswith(":yesterday"))
async def date_chosen(cb: CallbackQuery, state: FSMContext):
    action = cb.data.split(":")[0]
    days_ago = 0 if cb.data.endswith("today") else 1
    dt = datetime.now() - timedelta(days=days_ago)
    user_dates[cb.from_user.id] = dt.isoformat(timespec="seconds")
    
    if action == "feed_date":
        await cb.message.edit_text("Какой корм?", reply_markup=feed_menu())
    elif action == "cough_date":
        await cb.message.edit_text("Какой кашель?", reply_markup=cough_menu())
    elif action == "toilet_date":
        await cb.message.edit_text("Что было?", reply_markup=toilet_menu())
    elif action == "med_date":
        await cb.message.edit_text(
            "Введи название и дозу через пробел, например:\n"
            "`Преднизолон 5`\n\n"
            "(отправь /cancel чтобы отменить)"
        )
        await state.set_state(MedStates.waiting_dose) # <-- ТУТ ИСПРАВЛЕНИЕ
    
    await cb.answer()

# --- Обработка "Другая дата" ---
@dp.callback_query(F.data.endswith(":custom"))
async def custom_date_start(cb: CallbackQuery, state: FSMContext):
    action = cb.data.split(":")[0]
    await state.update_data(action=action)
    await cb.message.edit_text(
        "Напиши дату в формате `ДД.ММ` или `ДД.ММ.ГГГГ`\n"
        "Например: `25.10`\n\n"
        "(отправь /cancel чтобы отменить)"
    )
    await state.set_state(CustomDateStates.waiting_date)
    await cb.answer()

@dp.message(CustomDateStates.waiting_date)
async def custom_date_entered(msg: Message, state: FSMContext):
    text = msg.text.strip()
    match = re.match(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?$", text)
    if not match:
        await msg.answer("Не понял дату. Напиши в формате `ДД.ММ` (например, 25.10):")
        return
    
    day, month, year = match.groups()
    day, month = int(day), int(month)
    now = datetime.now()
    if year:
        year = int(year)
        if year < 100: year += 2000
    else:
        year = now.year
        if month > now.month:
            year -= 1

    try:
        dt = datetime(year, month, day, now.hour, now.minute)
    except ValueError:
        await msg.answer("Такой даты не существует. Попробуй еще раз (например, 25.10):")
        return

    user_dates[msg.from_user.id] = dt.isoformat(timespec="seconds")
    data = await state.get_data()
    action = data.get("action")
    await state.clear()

    if action == "feed_date":
        await msg.answer("Какой корм?", reply_markup=feed_menu())
    elif action == "cough_date":
        await msg.answer("Какой кашель?", reply_markup=cough_menu())
    elif action == "toilet_date":
        await msg.answer("Что было?", reply_markup=toilet_menu())
    elif action == "med_date":
        await msg.answer(
            "Введи название и дозу через пробел, например:\n"
            "`Преднизолон 5`\n\n"
            "(отправь /cancel чтобы отменить)"
        )
        await state.set_state(MedStates.waiting_dose)

# --- Сохранение ---
@dp.callback_query(F.data.startswith("feed_type:"))
async def feed_save(cb: CallbackQuery):
    subtype = cb.data.split(":", 1)[1]
    date_str = user_dates.get(cb.from_user.id, datetime.now().isoformat(timespec="seconds"))
    add_event(cb.from_user.id, "feed", subtype=subtype, custom_date=date_str)
    await cb.message.edit_text(f"✅ Записано: кормление ({subtype})", reply_markup=main_menu())
    await cb.answer("Сохранено")

@dp.callback_query(F.data.startswith("cough_type:"))
async def cough_save(cb: CallbackQuery):
    subtype = cb.data.split(":", 1)[1]
    date_str = user_dates.get(cb.from_user.id, datetime.now().isoformat(timespec="seconds"))
    add_event(cb.from_user.id, "cough", subtype=subtype, custom_date=date_str)
    await cb.message.edit_text(f"✅ Записано: кашель ({subtype})", reply_markup=main_menu())
    await cb.answer("Сохранено")

@dp.callback_query(F.data.startswith("toilet_type:"))
async def toilet_save(cb: CallbackQuery):
    subtype = cb.data.split(":", 1)[1]
    date_str = user_dates.get(cb.from_user.id, datetime.now().isoformat(timespec="seconds"))
    add_event(cb.from_user.id, "toilet", subtype=subtype, custom_date=date_str)
    await cb.message.edit_text(f"✅ Записано: туалет ({subtype})", reply_markup=main_menu())
    await cb.answer("Сохранено")

@dp.message(Command("cancel"))
async def cancel(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Отменено.", reply_markup=main_menu())

@dp.message(MedStates.waiting_dose)
async def med_save(msg: Message, state: FSMContext):
    parts = msg.text.strip().rsplit(" ", 1)
    if len(parts) != 2:
        await msg.answer("Не понял. Формат: `Название 5`. Попробуй ещё раз.")
        return
    name, dose_str = parts
    try:
        dose = float(dose_str.replace(",", "."))
    except ValueError:
        await msg.answer("Доза должна быть числом. Например: `Преднизолон 5`")
        return
    
    date_str = user_dates.get(msg.from_user.id, datetime.now().isoformat(timespec="seconds"))
    add_event(msg.from_user.id, "med", subtype=name, amount=dose, custom_date=date_str)
    await state.clear()
    await msg.answer(f"✅ Записано: {name}, {dose} мг", reply_markup=main_menu())

# --- Статистика и Редактирование ---
@dp.callback_query(F.data == "stats")
async def stats(cb: CallbackQuery):
    now = datetime.now()
    rows = month_stats(cb.from_user.id, now.year, now.month)
    text = format_stats(rows, now.year, now.month)
    await cb.message.edit_text(text, reply_markup=main_menu())
    await cb.answer()

def format_stats(rows, year, month):
    if not rows:
        return f"📊 Статистика за {month:02d}.{year}\n\nПока нет записей."
    counts = Counter(r["type"] for r in rows)
    by_subtype = defaultdict(Counter)
    meds = defaultdict(float)
    days = defaultdict(Counter)
    for r in rows:
        d = r["created_at"][:10]
        days[d][r["type"]] += 1
        if r["subtype"]:
            by_subtype[r["type"]][r["subtype"]] += 1
        if r["type"] == "med" and r["amount"]:
            meds[r["subtype"]] += r["amount"]
    lines = [f"📊 Статистика за {month:02d}.{year}\n"]
    lines.append(f"🍽 Кормлений: {counts['feed']}")
    for k, v in by_subtype["feed"].items():
        lines.append(f"   • {k}: {v}")
    lines.append(f"\n😮‍💨 Кашель: {counts['cough']} раз")
    for k, v in by_subtype["cough"].items():
        lines.append(f"   • {k}: {v}")
    lines.append(f"\n💊 Лекарства: {counts['med']} приёмов")
    for name, total in meds.items():
        lines.append(f"   • {name}: {total:g} мг")
    lines.append(f"\n🚽 Туалет: {counts['toilet']}")
    for k, v in by_subtype["toilet"].items():
        lines.append(f"   • {k}: {v}")
    cough_days = [(d, c["cough"]) for d, c in days.items() if c["cough"]]
    if cough_days:
        cough_days.sort(key=lambda x: -x[1])
        lines.append("\n🔥 Больше всего кашля:")
        for d, c in cough_days[:3]:
            lines.append(f"   • {d}: {c} раз")
    return "\n".join(lines)

@dp.callback_query(F.data == "edit_last")
async def edit_last(cb: CallbackQuery):
    events = get_last_events(cb.from_user.id, limit=5)
    if not events:
        await cb.message.edit_text("У тебя пока нет записей.", reply_markup=main_menu())
        await cb.answer()
        return
    await cb.message.edit_text("Твои последние 5 записей. Нажми ❌, чтобы удалить лишнюю:")
    for ev in events:
        ev_type = ev["type"]
        if ev_type == "feed":
            text = f"🍽 Кормление ({ev['subtype']})"
        elif ev_type == "cough":
            text = f"😮‍💨 Кашель ({ev['subtype']})"
        elif ev_type == "toilet":
            text = f"🚽 Туалет ({ev['subtype']})"
        elif ev_type == "med":
            text = f"💊 {ev['subtype']} ({ev['amount']} мг)"
        dt = ev["created_at"].replace("T", " ")[:16]
        msg_text = f"{text}\n📅 {dt}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Удалить", callback_data=f"del_{ev['id']}")]
        ])
        await cb.message.answer(msg_text, reply_markup=kb)
    await cb.answer()

@dp.callback_query(F.data.startswith("del_"))
async def delete_event_cb(cb: CallbackQuery):
    event_id = int(cb.data.split("_")[1])
    delete_event(event_id, cb.from_user.id)
    await cb.message.edit_text("✅ Запись удалена! Статистика обновлена.")
    await cb.answer("Удалено")

async def main():
    keep_alive()
    init_db()
    bot = Bot(token=BOT_TOKEN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
