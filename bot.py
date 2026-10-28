import asyncio
import os
import json
from pathlib import Path
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import ChatJoinRequest, Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, MenuButtonWebApp, MenuButtonCommands, WebAppInfo, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from aiogram.filters import Command, ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiohttp import web

# --- НАСТРОЙКИ ---
WELCOME_TOKEN = os.getenv("WELCOME_BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080)) 
SOURCE_CHANNEL_ID = -1004306238403
INVITE_LINK = "https://t.me/+ТВОЯ_ССЫЛКА_В_КАНАЛ" 

ADMIN_ID = 8720671692 

bot = Bot(token=WELCOME_TOKEN)
dp = Dispatcher()

data_dir = Path("/app/data")
data_dir.mkdir(parents=True, exist_ok=True)
WELCOME_FILE = data_dir / "welcome.json"
PENDING_FILE = data_dir / "pending.json"

# --- ФАЙЛЫ ---
def load_json(file):
    if file.exists():
        with open(file, "r", encoding="utf-8") as f: return json.load(f)
    return {}

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

# --- ОТПРАВКА СООБЩЕНИЙ (С ПОДДЕРЖКОЙ АЛЬБОМОВ) ---
async def send_msg(chat_id, msg_data, name, username):
    text = msg_data.get("text", "").replace("{name}", name).replace("{username}", f"@{username}" if username else "")
    media_str = msg_data.get("media_url", "").strip()
    
    kb = None
    buttons = msg_data.get("buttons", [])
    if buttons:
        inline_buttons = []
        for btn in buttons:
            if btn.get("text") and btn.get("url"):
                inline_buttons.append([InlineKeyboardButton(text=btn["text"], url=btn["url"])])
        if inline_buttons:
            kb = InlineKeyboardMarkup(inline_keyboard=inline_buttons)

    media_list = [m.strip() for m in media_str.split(",") if m.strip()]

    try:
        if len(media_list) == 0:
            # Только текст
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
        
        elif len(media_list) == 1:
            # Одно фото или видео
            media = media_list[0]
            try:
                # Пробуем отправить как фото
                await bot.send_photo(chat_id=chat_id, photo=media, caption=text, reply_markup=kb, parse_mode="HTML")
            except:
                try:
                    # Если не вышло - пробуем как видео
                    await bot.send_video(chat_id=chat_id, video=media, caption=text, reply_markup=kb, parse_mode="HTML")
                except:
                    # Если вообще не вышло - шлем просто текст
                    await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
        
        else:
            # Несколько файлов (Альбом)
            # Сначала отправляем текст с кнопками
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
            
            # Потом собираем альбом
            media_group = []
            for m in media_list:
                if m.startswith("AgAC") or m.startswith("http"): # Предполагаем фото
                    media_group.append(InputMediaPhoto(media=m))
                elif m.startswith("BAAC") or "video" in m: # Предполагаем видео
                    media_group.append(InputMediaVideo(media=m))
                else:
                    media_group.append(InputMediaDocument(media=m))
            
            # Telegram разрешает максимум 10 файлов в одном альбоме
            if media_group:
                await bot.send_media_group(chat_id, media=media_group[:10])

    except Exception as e:
        print(f"Ошибка отправки {chat_id}: {e}")

# --- ОБРАБОТЧИК МЕДИА ДЛЯ АДМИНА (ПОЛУЧЕНИЕ FILE_ID) ---
@dp.message(F.photo | F.video | F.document)
async def handle_admin_media(message: Message):
    if message.from_user.id != ADMIN_ID: return
    
    # Если это альбом - игнорируем, чтобы не спамить
    if message.media_group_id:
        return

    file_id = None
    if message.photo: file_id = message.photo[-1].file_id
    elif message.video: file_id = message.video.file_id
    elif message.document: file_id = message.document.file_id

    if file_id:
        await message.reply(
            f"✅ <b>Медиа получено!</b>\n\nСкопируй этот код и вставь в поле «Ссылка на картинку» в админке:\n\n<code>{file_id}</code>", 
            parse_mode="HTML"
        )

# --- ЗАЯВКИ И ВСТУПЛЕНИЯ ---
@dp.chat_join_request()
async def handle_join_request(update: ChatJoinRequest):
    if update.chat.id != SOURCE_CHANNEL_ID: return
    
    settings = load_json(WELCOME_FILE)
    if not settings.get("enabled", False): return

    user = update.from_user
    name = user.first_name
    username = user.username if user.username else ""
    
    # 1. Отправляем цепочку приветствий
    asyncio.create_task(run_chain(user.id, name, username, settings.get("messages", [])))

    # 2. Запускаем "повторку" (FOMO)
    fomo = settings.get("fomo", {})
    if fomo.get("enabled") and fomo.get("delay", 0) > 0:
        pending = load_json(PENDING_FILE)
        pending[str(user.id)] = {
            "name": name, 
            "username": username,
            "time": datetime.now().timestamp()
        }
        save_json(PENDING_FILE, pending)
        asyncio.create_task(run_fomo(user.id, name, username, fomo["delay"] * 60, fomo.get("text", "")))

@dp.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def handle_user_join(update: ChatMemberUpdated):
    if update.chat.id != SOURCE_CHANNEL_ID: return
    user_id = str(update.new_chat_member.user.id)
    pending = load_json(PENDING_FILE)
    if user_id in pending:
        del pending[user_id]
        save_json(PENDING_FILE, pending)

async def run_chain(user_id, name, username, messages):
    for msg in messages:
        if not msg.get("enabled", True): continue
        delay = msg.get("delay", 0)
        if delay > 0: await asyncio.sleep(delay)
        await send_msg(user_id, msg, name, username)

async def run_fomo(user_id, name, username, delay, text):
    await asyncio.sleep(delay)
    pending = load_json(PENDING_FILE)
    if str(user_id) in pending:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔥 Занять место", url=INVITE_LINK)]])
        try:
            await bot.send_message(user_id, text.replace("{name}", name), reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            print(f"Ошибка FOMO: {e}")
        del pending[str(user_id)]
        save_json(PENDING_FILE, pending)

# --- КОМАНДА /start ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id == ADMIN_ID:
        web_app = WebAppInfo(url="https://lavrinuksasha5-prog.github.io/Privet/")
        menu_btn = MenuButtonWebApp(text="⚙️ Настройки", web_app=web_app)
        await bot.set_chat_menu_button(chat_id=ADMIN_ID, menu_button=menu_btn)
        await message.answer("Привет, Админ! Кнопка управления внизу 👇")
    else:
        await message.answer("Привет! Твоя заявка скоро будет рассмотрена.")

# --- API ---
async def handle_get_welcome(request):
    return web.json_response(load_json(WELCOME_FILE), headers={"Access-Control-Allow-Origin": "*"})

async def handle_save_welcome(request):
    if request.method == 'OPTIONS': 
        return web.Response(headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"})
    try:
        data = await request.json()
        save_json(WELCOME_FILE, data)
        return web.json_response({"status": "ok"}, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500, headers={"Access-Control-Allow-Origin": "*"})

async def handle_test_welcome(request):
    if request.method == 'OPTIONS': 
        return web.Response(headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"})
    try:
        data = await request.json()
        user_id = data.get("user_id")
        msg_data = data.get("message")
        if int(user_id) != ADMIN_ID: return web.json_response({"status": "error"}, status=403, headers={"Access-Control-Allow-Origin": "*"})
        await send_msg(user_id, msg_data, "Тест", "test")
        return web.json_response({"status": "ok"}, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500, headers={"Access-Control-Allow-Origin": "*"})

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
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
