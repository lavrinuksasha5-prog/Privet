import asyncio
import os
import json
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.types import ChatJoinRequest
from aiohttp import web

# --- НАСТРОЙКИ ---
WELCOME_TOKEN = os.getenv("WELCOME_BOT_TOKEN") # Токен бота-приветствователя
PORT = int(os.getenv("PORT", 8080)) 
SOURCE_CHANNEL_ID = -1004306238403 # ID канала, где висят заявки

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

# --- ЛОГИКА ПРИВЕТСТВИЙ ---
@dp.chat_join_request()
async def handle_join_request(update: ChatJoinRequest):
    if update.chat.id != SOURCE_CHANNEL_ID: return

    settings = load_welcome()
    if not settings.get("enabled", False) or not settings.get("messages"): return

    user = update.from_user
    name = user.first_name
    username = user.username if user.username else ""
    
    # Запускаем цепочку в фоне
    asyncio.create_task(send_welcome_chain(user.id, name, username))

async def send_welcome_chain(user_id, name, username):
    settings = load_welcome()
    for msg in settings["messages"]:
        delay = msg.get("delay", 0)
        if delay > 0:
            await asyncio.sleep(delay)
            
        text = msg.get("text", "")
        text = text.replace("{name}", name).replace("{username}", f"@{username}" if username else "")
        
        try:
            await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
        except Exception as e:
            print(f"Ошибка приветствия для {user_id}: {e}")

# --- API ДЛЯ АДМИНКИ ---
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

# --- ЗАПУСК ---
async def main():
    app = web.Application()
    app.router.add_get('/api/welcome', handle_get_welcome)
    app.router.add_post('/api/welcome', handle_save_welcome)
    app.router.add_options('/api/welcome', handle_save_welcome)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
