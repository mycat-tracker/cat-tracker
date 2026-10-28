import asyncio
import os
from datetime import datetime
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

from db import init_db, add_event, month_stats
from keep_alive import keep_alive

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

class MedStates(StatesGroup):
    waiting_dose = State()

def main_menu():
    kb = [
        [InlineKeyboardButton(text="🍽 Кормление", callback_data="feed"),
         InlineKeyboardButton(text="😮‍💨 Кашель", callback_data="cough")],
        [InlineKeyboardButton(text="💊 Лекарство", callback_data="med"),
         InlineKeyboardButton(text="🚽 Туалет", callback_data="toilet")],
        [InlineKeyboardButton(text="📊 Статистика за месяц", callback_data="stats")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def feed_menu():
    kb = [
        [InlineKeyboardButton(text="Сухой", callback_data="feed:сухой"),
         InlineKeyboardButton(text="Влажный", callback_data="feed:влажный")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def cough_menu():
    kb = [
        [InlineKeyboardButton(text="Лёгкий", callback_data="cough:лёгкий"),
         InlineKeyboardButton(text="Сильный", callback_data="cough:сильный")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def toilet_menu():
    kb = [
        [InlineKeyboardButton(text="💧 Моча", callback_data="toilet:моча"),
         InlineKeyboardButton(text="💩 Кал", callback_data="toilet:кал")],
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

@dp.callback_query(F.data == "feed")
async def feed_menu_cb(cb: CallbackQuery):
    await cb.message.edit_text("Какой корм?", reply_markup=feed_menu())
    await cb.answer()

@dp.callback_query(F.data.startswith("feed:"))
async def feed_save(cb: CallbackQuery):
    subtype = cb.data.split(":", 1)[1]
    add_event(cb.from_user.id, "feed", subtype=subtype)
    await cb.message.edit_text(
        f"✅ Записано: кормление ({subtype})",
        reply_markup=main_menu()
    )
    await cb.answer("Сохранено")

@dp.callback_query(F.data == "cough")
async def cough_menu_cb(cb: CallbackQuery):
    await cb.message.edit_text("Какой кашель?", reply_markup=cough_menu())
    await cb.answer()

@dp.callback_query(F.data.startswith("cough:"))
async def cough_save(cb: CallbackQuery):
    subtype = cb.data.split(":", 1)[1]
    add_event(cb.from_user.id, "cough", subtype=subtype)
    await cb.message.edit_text(
        f"✅ Записано: кашель ({subtype})",
        reply_markup=main_menu()
    )
    await cb.answer("Сохранено")

@dp.callback_query(F.data == "toilet")
async def toilet_menu_cb(cb: CallbackQuery):
    await cb.message.edit_text("Что было?", reply_markup=toilet_menu())
    await cb.answer()

@dp.callback_query(F.data.startswith("toilet:"))
async def toilet_save(cb: CallbackQuery):
    subtype = cb.data.split(":", 1)[1]
    add_event(cb.from_user.id, "toilet", subtype=subtype)
    await cb.message.edit_text(
        f"✅ Записано: туалет ({subtype})",
        reply_markup=main_menu()
    )
    await cb.answer("Сохранено")

@dp.callback_query(F.data == "med")
async def med_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "Введи название и дозу через пробел, например:\n"
        "`Преднизолон 5`\n\n"
        "(отправь /cancel чтобы отменить)"
    )
    await state.set_state(MedStates.waiting_dose)
    await cb.answer()

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
    add_event(msg.from_user.id, "med", subtype=name, amount=dose)
    await state.clear()
    await msg.answer(
        f"✅ Записано: {name}, {dose} мг",
        reply_markup=main_menu()
    )

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

async def main():
    keep_alive()
    init_db()
    bot = Bot(token=BOT_TOKEN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
