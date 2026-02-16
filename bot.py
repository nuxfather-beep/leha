import asyncio
import logging
import sqlite3
import html
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- КОНФИГ ---
API_TOKEN = '8545421345:AAErY7Hx8BNhSgl386QYfIrAD2dcy1_6lpI'
ADMIN_ID = 6418255794

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- БАЗА ДАННЫХ (с поддержкой Блокировки) ---
def init_db():
    with sqlite3.connect('users.db') as conn:
        # Добавляем колонку is_blocked (0 - ок, 1 - забанен)
        conn.execute('''CREATE TABLE IF NOT EXISTS leads 
                        (user_id INTEGER PRIMARY KEY, 
                         full_name TEXT, 
                         username TEXT, 
                         status TEXT DEFAULT 'new',
                         is_blocked INTEGER DEFAULT 0)''')

def add_lead(user_id, name, username):
    with sqlite3.connect('users.db') as conn:
        conn.execute('INSERT OR IGNORE INTO leads (user_id, full_name, username) VALUES (?, ?, ?)', (user_id, name, username))

def is_user_blocked(user_id):
    with sqlite3.connect('users.db') as conn:
        res = conn.execute('SELECT is_blocked FROM leads WHERE user_id = ?', (user_id,)).fetchone()
        return res[0] == 1 if res else False

def toggle_block(user_id, block_status):
    with sqlite3.connect('users.db') as conn:
        conn.execute('UPDATE leads SET is_blocked = ? WHERE user_id = ?', (block_status, user_id))

# --- СОСТОЯНИЯ ---
class AdminStates(StatesGroup):
    waiting_for_reply = State()

# --- ЛОГИКА АДМИНА ---
@dp.message(Command("start"), F.from_user.id == ADMIN_ID)
async def admin_start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="📂 Все заявки", callback_data="admin_menu"))
    await message.answer("🛠 <b>Админ-панель Лёхи.</b>\nТут всё управление.", parse_mode="HTML", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "admin_menu")
async def admin_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="🔴 Новые", callback_data="list:new"),
           types.InlineKeyboardButton(text="🟢 Архив", callback_data="list:answered"))
    kb.row(types.InlineKeyboardButton(text="🚫 Забаненные", callback_data="list:blocked"))
    await callback.message.edit_text("<b>Выберите список:</b>", parse_mode="HTML", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("list:"))
async def show_list(callback: types.CallbackQuery):
    status = callback.data.split(":")[1]
    query = 'SELECT user_id, full_name, username FROM leads WHERE status = ? AND is_blocked = 0'
    if status == 'blocked':
        query = 'SELECT user_id, full_name, username FROM leads WHERE is_blocked = 1'
    
    with sqlite3.connect('users.db') as conn:
        leads = conn.execute(query, (status,) if status != 'blocked' else ()).fetchall()
    
    kb = InlineKeyboardBuilder()
    if not leads:
        kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"))
        await callback.message.edit_text("Тут пока пусто.", reply_markup=kb.as_markup()); return

    for uid, name, uname in leads:
        kb.row(types.InlineKeyboardButton(text=f"{name} (@{uname or '??'})", callback_data=f"view_user:{uid}"))
    kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"))
    await callback.message.edit_text(f"Список ({status}):", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("view_user:"))
async def view_user(callback: types.CallbackQuery):
    uid = int(callback.data.split(":")[1])
    blocked = is_user_blocked(uid)
    
    kb = InlineKeyboardBuilder()
    if not blocked:
        kb.row(types.InlineKeyboardButton(text="📝 Написать", callback_data=f"reply_to:{uid}"))
        kb.row(types.InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"block:{uid}"))
    else:
        kb.row(types.InlineKeyboardButton(text="✅ Разблокировать", callback_data=f"unblock:{uid}"))
    
    kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"))
    await callback.message.edit_text(f"Управление юзером <code>{uid}</code>\nСтатус: {'ЗАБАНЕН' if blocked else 'Активен'}", 
                                     parse_mode="HTML", reply_markup=kb.as_markup())

# --- БЛОКИРОВКА / РАЗБЛОКИРОВКА ---
@dp.callback_query(F.data.startswith(("block:", "unblock:")))
async def handle_block(callback: types.CallbackQuery):
    action, uid = callback.data.split(":")
    status = 1 if action == "block" else 0
    toggle_block(int(uid), status)
    await callback.answer("Готово!")
    await view_user(callback) # Обновляем меню юзера

# --- ОБЩЕНИЕ (с проверкой на бан) ---

@dp.message(F.from_user.id != ADMIN_ID)
async def handle_user_message(message: types.Message):
    if is_user_blocked(message.from_user.id):
        return # Просто игнорим забаненного

    if message.text == "/start":
        kb = InlineKeyboardBuilder()
        kb.row(types.InlineKeyboardButton(text="Заинтересован", callback_data="interested"))
        await message.answer("Если заинтересован, жми кнопку ниже 👇", reply_markup=kb.as_markup())
        return

    # Пересылка Лёхе с кнопкой бана под рукой
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_to:{message.from_user.id}"))
    kb.row(types.InlineKeyboardButton(text="🚫 В бан", callback_data=f"block:{message.from_user.id}"))
    
    user_info = f"👤 {html.escape(message.from_user.full_name)} (@{message.from_user.username or 'no_use'})"
    await bot.send_message(ADMIN_ID, f"📩 <b>Сообщение:</b>\n{user_info}\n\n<i>{html.escape(message.text)}</i>",
                           parse_mode="HTML", reply_markup=kb.as_markup())
    await message.answer("📨 Доставлено администратору.")

@dp.callback_query(F.data == "interested")
async def process_interested(callback: types.CallbackQuery):
    if is_user_blocked(callback.from_user.id):
        await callback.answer("Ошибка доступа.", show_alert=True); return

    add_lead(callback.from_user.id, callback.from_user.full_name, callback.from_user.username)
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_to:{callback.from_user.id}"))
    kb.row(types.InlineKeyboardButton(text="🚫 В бан", callback_data=f"block:{callback.from_user.id}"))
    
    await bot.send_message(ADMIN_ID, f"🎯 <b>Кнопку нажал:</b> {callback.from_user.full_name}", 
                           parse_mode="HTML", reply_markup=kb.as_markup())
    await callback.answer("Заявка принята!")
    await callback.message.edit_text("✅ Твой запрос принят.")

# Ответ админа (как и раньше)
@dp.callback_query(F.data.startswith("reply_to:"))
async def start_reply(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.data.split(":")[1]
    await state.update_data(target_id=uid)
    await state.set_state(AdminStates.waiting_for_reply)
    await callback.message.answer(f"💬 Пиши ответ для {uid}:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_reply, F.from_user.id == ADMIN_ID)
async def send_admin_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        await bot.send_message(data['target_id'], f"<b>Ответ от поддержки:</b>\n\n{message.text}", parse_mode="HTML")
        with sqlite3.connect('users.db') as conn:
            conn.execute('UPDATE leads SET status = "answered" WHERE user_id = ?', (data['target_id'],))
        await message.answer("✅ Отправлено!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    await state.clear()

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())