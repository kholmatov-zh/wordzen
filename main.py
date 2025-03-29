import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from handlers import register_handlers, check_payments
from keep_alive import keep_alive

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TOKEN")
ADMIN_IDS = [int(admin_id) for admin_id in os.getenv("ADMIN_IDS", "").split(",") if admin_id]
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS не указаны в переменных окружения!")

bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

if __name__ == "__main__":
    keep_alive()
    register_handlers(dp)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(bot.delete_webhook(drop_pending_updates=True))
    loop.create_task(check_payments(bot))
    executor.start_polling(dp, skip_updates=True)
