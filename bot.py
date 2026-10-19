import asyncio
import os
import json
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.types import ChatJoinRequest, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiohttp import web

# --- НАСТРОЙКИ ---
WELCOME_TOKEN = os.getenv("WELCOME_BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080)) 
SOURCE_CHANNEL_ID = -1004306238403

bot = Bot(token=WELCOME_TOKEN)
dp = Dispatcher()

data_dir = Path("/app/data")
data_dir.mkdir(parents=True, exist_ok=True)
WELCOME_FILE = data_dir / "welcome.json"

# --- ФАЙЛЫ ---
def load_welcome():
    if WELCOME_FILE.exists():
        with open(WELCOME_FILE, "r", encoding="utf-8") as f: return json.load(f)
    return {"enabled": True, "messages": []}

def save_welcome(data):
    with open(WELCOME_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

# --- ФУНКЦИЯ ОТПРАВКИ ОДНОГО СООБЩЕНИЯ ---
async def send_single_msg(chat_id, msg_data, name, username):
    text = msg_data.get("text", "").replace("{name}", name).replace("{username}", f"@{username}" if username else "")
    media_url = msg_data.get("media_url", "").strip()
    
    # Собираем кнопки
    kb = None
    buttons = msg_data.get("buttons", [])
    if buttons:
        inline_buttons = []
        for btn in buttons:
            if btn.get("text") and btn.get("url"):
                inline_buttons.append([InlineKeyboardButton(text=btn["text"], url=btn["url"])])
        if inline_buttons:
            kb = InlineKeyboardMarkup(inline_keyboard=inline_buttons)

    try:
        if media_url and media_url.startswith("http"):
            await bot.send_photo(chat_id=chat_id, photo=media_url, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка отправки для {chat_id}: {e}")

# --- ЛОГИКА ЗАЯВОК ---
@dp.chat_join_request()
async def handle_join_request(update: ChatJoinRequest):
    if update.chat.id != SOURCE_CHANNEL_ID: return
    settings = load_welcome()
    if not settings.get("enabled", False) or not settings.get("messages"): return

    user = update.from_user
    name = user.first_name
    username = user.username if user.username else ""
    
    asyncio.create_task(run_welcome_chain(user.id, name, username))

async def run_welcome_chain(user_id, name, username):
    settings = load_welcome()
    for msg in settings["messages"]:
        delay = msg.get("delay", 0)
        if delay > 0: await asyncio.sleep(delay)
        await send_single_msg(user_id, msg, name, username)

# --- API ---
async def handle_get_welcome(request):
    return web.json_response(load_welcome(), headers={"Access-Control-Allow-Origin": "*"})

async def handle_save_welcome(request):
    if request.method == 'OPTIONS': 
        return web.Response(headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"})
    try:
        data = await request.json()
        save_welcome(data)
        return web.json_response({"status": "ok"}, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500, headers={"Access-Control-Allow-Origin": "*"})

# --- API ДЛЯ ТЕСТА (Проверка) ---
async def handle_test_welcome(request):
    if request.method == 'OPTIONS': 
        return web.Response(headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"})
    try:
        data = await request.json()
        user_id = data.get("user_id")
        msg_data = data.get("message")
        
        # Отправляем тестовое сообщение пользователю, который нажал кнопку
        await send_single_msg(user_id, msg_data, "Тест", "test")
        return web.json_response({"status": "ok"}, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500, headers={"Access-Control-Allow-Origin": "*"})

# --- ЗАПУСК ---
async def main():
    app = web.Application()
    app.router.add_get('/api/welcome', handle_get_welcome)
    app.router.add_post('/api/welcome', handle_save_welcome)
    app.router.add_options('/api/welcome', handle_save_welcome)
    app.router.add_post('/api/test', handle_test_welcome)
    app.router.add_options('/api/test', handle_test_welcome)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
