# Временный код для очистки базы данных
import os
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# Очистка всех таблиц
cursor.execute("DROP TABLE IF EXISTS users CASCADE")
cursor.execute("DROP TABLE IF EXISTS promo_codes CASCADE")
cursor.execute("DROP TABLE IF EXISTS messages CASCADE")
conn.commit()
print("Все таблицы удалены.")

cursor.close()
conn.close()



# main.py (часть 1)
import os
import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import psycopg2
from keep_alive import keep_alive

# Конфигурация логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Переменные окружения
TOKEN = os.getenv("TOKEN")
ADMIN_IDS = [int(admin_id) for admin_id in os.getenv("ADMIN_IDS", "").split(",") if admin_id]
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS не указаны в переменных окружения!")
CARD_NUMBER = "1234 5678 9012 3456"

# Инициализация бота
bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# PostgreSQL база данных через Supabase
class Database:
    def __init__(self):
        try:
            self.conn = psycopg2.connect(os.getenv("DATABASE_URL"))
            self.cursor = self.conn.cursor()
            logger.info("Подключение к базе данных PostgreSQL успешно")
            self._create_tables()
            self._initialize_promo_codes()
        except Exception as e:
            logger.error(f"Ошибка подключения к базе данных: {e}")
            raise

    def _create_tables(self):
        try:
            # Создаём таблицу users, если она ещё не существует
            self.cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                user_id BIGINT UNIQUE,
                source TEXT,
                email TEXT UNIQUE,
                telegram TEXT,
                books TEXT,
                trial_end TEXT,
                payment_due TEXT,
                paid_months INTEGER DEFAULT 0,
                payment_confirmed INTEGER DEFAULT 0,
                promo_code TEXT
            )''')
            # Добавляем столбец is_active, если он отсутствует
            self.cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active INTEGER DEFAULT 1")

            # Создаём таблицу promo_codes
            self.cursor.execute('''CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                teacher_name TEXT,
                used_count INTEGER DEFAULT 0,
                bonus_days INTEGER DEFAULT 7
            )''')

            # Создаём таблицу messages
            self.cursor.execute('''CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                message_text TEXT,
                is_from_user INTEGER DEFAULT 1,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            self.conn.commit()
            logger.info("Таблицы созданы или уже существуют")
        except Exception as e:
            logger.error(f"Ошибка при создании таблиц: {e}")
            self.conn.rollback()
            raise
            # main.py (часть 2)
    def _initialize_promo_codes(self):
        try:
            promo_codes = [
                "Teacher01", "Teacher02", "Teacher03", "Teacher04", "Teacher05",
                "Teacher06", "Teacher07", "Teacher08", "Teacher09", "Teacher10",
                "Teacher11", "Teacher12", "Teacher13", "Teacher14", "Teacher15"
            ]
            for code in promo_codes:
                self.cursor.execute(
                    "INSERT INTO promo_codes (code, teacher_name, used_count, bonus_days) VALUES (%s, %s, 0, 7) ON CONFLICT (code) DO NOTHING",
                    (code, code)
                )
            self.conn.commit()
            logger.info("Промокоды инициализированы")
        except Exception as e:
            logger.error(f"Ошибка при инициализации промокодов: {e}")
            self.conn.rollback()

    def add_user(self, user_id, source, email, telegram, books, promo_code=None):
        try:
            trial_end = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
            if promo_code:
                promo = self.get_promo_code(promo_code)
                if promo:
                    bonus_days = promo[3]
                    trial_end = (datetime.now() + timedelta(days=3 + bonus_days)).strftime('%Y-%m-%d')
                    self.cursor.execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE code = %s", (promo_code,))
            self.cursor.execute(
                "INSERT INTO users (user_id, source, email, telegram, books, trial_end, payment_due, promo_code, is_active) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1) ON CONFLICT (user_id) DO NOTHING",
                (user_id, source, email, telegram, books, trial_end, trial_end, promo_code)
            )
            self.conn.commit()
            logger.info(f"Добавлен пользователь: user_id={user_id}, source={source}, email={email}, promo_code={promo_code}")
        except Exception as e:
            logger.error(f"Ошибка при добавлении пользователя: {e}")
            self.conn.rollback()

    def get_user(self, user_id):
        try:
            self.cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            result = self.cursor.fetchone()
            logger.info(f"Поиск пользователя: user_id={user_id}, результат={result}")
            return result
        except Exception as e:
            logger.error(f"Ошибка при получении пользователя: {e}")
            return None

    def update_payment(self, user_id, months, bonus=0):
        try:
            total = months + bonus
            self.cursor.execute(
                "UPDATE users SET paid_months = paid_months + %s, payment_confirmed = 1, payment_due = %s, is_active = 1 WHERE user_id = %s",
                (total, (datetime.now() + timedelta(days=30 * total)).strftime('%Y-%m-%d'), user_id)
            )
            self.conn.commit()
            logger.info(f"Обновлена оплата: user_id={user_id}, months={months}, bonus={bonus}")
        except Exception as e:
            logger.error(f"Ошибка при обновлении оплаты: {e}")
            self.conn.rollback()

    def deactivate_user(self, user_id):
        try:
            self.cursor.execute("UPDATE users SET is_active = 0 WHERE user_id = %s", (user_id,))
            self.conn.commit()
            logger.info(f"Пользователь деактивирован: user_id={user_id}")
        except Exception as e:
            logger.error(f"Ошибка при деактивации пользователя: {e}")
            self.conn.rollback()

    def reset_books(self, user_id):
        try:
            self.cursor.execute("UPDATE users SET books = NULL WHERE user_id = %s", (user_id,))
            self.conn.commit()
            logger.info(f"Книги сброшены для user_id={user_id}")
        except Exception as e:
            logger.error(f"Ошибка при сбросе книг: {e}")
            self.conn.rollback()

    def get_promo_code(self, code):
        try:
            self.cursor.execute("SELECT code, teacher_name, used_count, bonus_days FROM promo_codes WHERE code = %s", (code,))
            return self.cursor.fetchone()
        except Exception as e:
            logger.error(f"Ошибка при получении промокода: {e}")
            return None

    def get_promo_stats(self):
        try:
            self.cursor.execute("SELECT code, teacher_name, used_count, bonus_days FROM promo_codes")
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении статистики промокодов: {e}")
            return []

    def get_unpaid_users(self, date):
        try:
            self.cursor.execute("SELECT user_id, email, telegram FROM users WHERE payment_due = %s AND payment_confirmed = 0 AND is_active = 1", (date,))
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении пользователей без оплаты: {e}")
            return []

    def get_users_near_trial_end(self, date):
        try:
            self.cursor.execute("SELECT user_id, email, telegram FROM users WHERE trial_end = %s AND payment_confirmed = 0 AND is_active = 1", (date,))
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении пользователей с истекающим пробным периодом: {e}")
            return []

    def get_all_users(self):
        try:
            self.cursor.execute("SELECT user_id, source, email, telegram, books, trial_end, payment_due, paid_months, payment_confirmed, promo_code, is_active FROM users")
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении всех пользователей: {e}")
            return []

    def get_stats(self):
        try:
            self.cursor.execute("SELECT COUNT(*) FROM users")
            total_users = self.cursor.fetchone()[0]
            self.cursor.execute("SELECT COUNT(*) FROM users WHERE payment_confirmed = 1")
            paid_users = self.cursor.fetchone()[0]
            self.cursor.execute("SELECT COUNT(*) FROM users WHERE promo_code IS NOT NULL")
            promo_users = self.cursor.fetchone()[0]
            return total_users, paid_users, promo_users
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {e}")
            return 0, 0, 0

    def add_message(self, user_id, message_text, is_from_user=True):
        try:
            self.cursor.execute(
                "INSERT INTO messages (user_id, message_text, is_from_user) VALUES (%s, %s, %s)",
                (user_id, message_text, 1 if is_from_user else 0)
            )
            self.conn.commit()
            logger.info(f"Сообщение добавлено: user_id={user_id}, from_user={is_from_user}")
        except Exception as e:
            logger.error(f"Ошибка при добавлении сообщения: {e}")
            self.conn.rollback()

    def get_user_messages(self, user_id):
        try:
            self.cursor.execute("SELECT message_text, is_from_user, timestamp FROM messages WHERE user_id = %s ORDER BY timestamp", (user_id,))
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении сообщений пользователя: {e}")
            return []

db = Database()

# Функция для предотвращения распознавания email как ссылки
def obfuscate_email(email):
    parts = email.split("@")
    if len(parts) == 2:
        domain = parts[1].split(".")
        if len(domain) >= 2:
            obfuscated = parts[0] + "@\u200B" + ".".join(domain[:-1]) + ".\u200B" + domain[-1]
        else:
            obfuscated = parts[0] + "@\u200B" + parts[1]
    else:
        obfuscated = email
    return obfuscated

# Форматирование информации о пользователе
def format_user_info(user_id, source, email, telegram, books, trial_end, payment_due, paid, confirmed, promo_code, is_active):
    obfuscated_email = obfuscate_email(email)
    return (
        f"👤 *Сизнинг профилингиз:*\n"
        f"🆔 Фойдаланувчи ID: `{user_id}`\n"
        f"📡 Бизни қаердан топдингиз: {source}\n"
        f"📧 Email: `{obfuscated_email}`\n"
        f"👤 Telegram: `{telegram}`\n"
        f"📚 Китоблар: {books or 'танланмаган'}\n"
        f"⏳ Синов муддати: *{trial_end}*\n"
        f"⏳ Обуна муддати: *{payment_due}*\n"
        f"💰 Тўланган ойлар: {paid}\n"
        f"✅ Ҳолат: {'Тўланган' if confirmed else 'Синов/тўланмаган'}\n"
        f"🎟️ Промокод: {promo_code if promo_code else 'қўлланилмаган'}\n"
        f"🔄 Активлик: {'Фаол' if is_active else 'Ўчирилган'}"
    )

# Список книг
BOOKS = [
    "Essential 1", "Essential 2", "Essential 3", "Essential 4", "Essential 5", "Essential 6",
    "Essential 1 (rus)", "Essential 2 (rus)", "Essential 3 (rus)", "Essential 4 (rus)", "Essential 5 (rus)", "Essential 6 (rus)",
    "English vocabulary in use elementary", "English vocabulary in use intermediate", 
    "English vocabulary in use upper-intermediate", "English vocabulary in use advanced",
    "English vocabulary in use elementary (rus)", "English vocabulary in use intermediate (rus)", 
    "English vocabulary in use upper-intermediate (rus)", "English vocabulary in use advanced (rus)"
]

# Клавиатуры
def get_main_menu():
    return ReplyKeyboardMarkup(resize_keyboard=True).add(
        KeyboardButton("👤 Профилим"),
        KeyboardButton("📩 Админга хабар юбориш")
    )

def get_start_button():
    return InlineKeyboardMarkup().add(InlineKeyboardButton("\u25B6\uFE0F Рўйхатдан ўтиш", callback_data="start_registration"))

def get_source_keyboard():
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("Instagram", callback_data="source_instagram"),
        InlineKeyboardButton("Ўқитувчидан", callback_data="source_teacher")
    )

def get_payment_options(user_id, promo_code=None):
    price = "49.900 сўм" if promo_code else "59.900 сўм"
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton(f"📅 1 ой — {price}", callback_data=f"pay_1_{user_id}")
    )

def get_confirmation_buttons(user_id):
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ Тасдиқлаш", callback_data=f"payment_approve_{user_id}_0"),
        InlineKeyboardButton("✅ Тасдиқлаш (+1 ой бонус)", callback_data=f"payment_approve_{user_id}_1"),
        InlineKeyboardButton("❌ Рад этиш", callback_data=f"payment_reject_{user_id}")
    )

def get_profile_buttons(email):
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("💳 Обунани узайтириш", callback_data=f"extend_subscription_{email}"),
        InlineKeyboardButton("🔙 Орқага", callback_data="back_to_menu")
    )

def get_reset_books_button(user_id):
    return InlineKeyboardMarkup().add(
        InlineKeyboardButton("📚 Янги китоблар танлаш", callback_data=f"reset_books_{user_id}")
    )
    # main.py (часть 3)
# Состояния
class UserState(StatesGroup):
    source = State()
    promo = State()
    email = State()
    telegram = State()
    books = State()
    payment = State()
    message_to_admin = State()
    reply_to_user = State()
    reset_books = State()

# Обработчики
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    try:
        with open("wordzen_logo.jpg", "rb") as photo:
            await bot.send_photo(
                message.chat.id,
                photo=photo,
                caption=(
                    "\U0001F4DA *Wordzen'га хуш келибсиз!*\n\n"
                    "Бу ерда сиз танланган китобларга эга бўласиз.\n\n"
                    "\U0001F381 *Янги фойдаланувчилар учун 3 кунлик бепул муддат!*\n\n"
                    "Рўйхатдан ўтиш учун қуйидаги тугмани босинг \U0001F447"
                ),
                parse_mode="Markdown",
                reply_markup=get_start_button()
            )
    except Exception as e:
        logger.error(f"Ошибка в /start: {e}")
        await message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.callback_query_handler(lambda c: c.data == "start_registration")
async def start_registration(callback_query: types.CallbackQuery):
    try:
        user = db.get_user(callback_query.from_user.id)
        if user and user[11] == 1:  # is_active
            await callback_query.message.delete()
            await callback_query.message.answer("Сиз аллақачон рўйхатдан ўтгансиз. Профилингизни кўриш учун 'Профилим' тугмасини босинг.", reply_markup=get_main_menu())
            return
        elif user and user[11] == 0:  # is_active = 0
            await callback_query.message.delete()
            await callback_query.message.answer(
                "❌ Сизнинг обунангиз муддати тугади ва сиз ўчирилдингиз.\n"
                "Яна фойдаланиш учун тўлов қилинг ва чекни юборинг.",
                reply_markup=get_payment_options(callback_query.from_user.id, user[10])
            )
            await UserState.payment.set()
            await callback_query.message.answer("💳 Тарифни танланг:")
            return
        await callback_query.message.delete()
        await callback_query.message.answer("Бизни қаердан топдингиз?", reply_markup=get_source_keyboard())
        await UserState.source.set()
    except Exception as e:
        logger.error(f"Ошибка в start_registration: {e}")
        await callback_query.message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.callback_query_handler(lambda c: c.data.startswith("source_"), state=UserState.source)
async def get_source(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        source = "Instagram" if callback_query.data == "source_instagram" else "Ўқитувчидан"
        await state.update_data(source=source)
        if source == "Ўқитувчидан":
            await callback_query.message.edit_text("Сизда промокод борми? Уни киритинг ёки 'йўқ' деб ёзинг:")
            await UserState.promo.set()
        else:
            await state.update_data(promo_code=None)
            await callback_query.message.edit_text("\U0001F4E7 Email манзилингизни киритинг:")
            await UserState.email.set()
    except Exception as e:
        logger.error(f"Ошибка в get_source: {e}")
        await callback_query.message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.message_handler(state=UserState.promo)
async def get_promo(message: types.Message, state: FSMContext):
    try:
        promo_code = message.text.strip().upper() if message.text.lower() != 'йўқ' else None
        if promo_code:
            promo = db.get_promo_code(promo_code)
            if not promo:
                await message.answer("❌ Промокод топилмади. Яна уриниб кўринг ёки 'йўқ' деб ёзинг:")
                return
        await state.update_data(promo_code=promo_code)
        await message.answer("\U0001F4E7 Email манзилингизни киритинг:")
        await UserState.email.set()
    except Exception as e:
        logger.error(f"Ошибка в get_promo: {e}")
        await message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.message_handler(state=UserState.email)
async def get_email(message: types.Message, state: FSMContext):
    try:
        await state.update_data(email=message.text)
        await message.answer("Telegram аккаунтингиз линкни юборинг (масалан, @username):")
        await UserState.telegram.set()
    except Exception as e:
        logger.error(f"Ошибка в get_email: {e}")
        await message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.message_handler(state=UserState.telegram)
async def get_telegram(message: types.Message, state: FSMContext):
    try:
        await state.update_data(telegram=message.text, user_id=message.from_user.id)
        await message.answer(
            "📚 Китоблар рўйхатидан 3 та китоб танланг. Рақамларни юборинг, масалан:\n"
            "1\n2\n3\n\n"
            "Рўйхат:\n" + "\n".join(f"{i+1}. {book}" for i, book in enumerate(BOOKS))
        )
        await UserState.books.set()
    except Exception as e:
        logger.error(f"Ошибка в get_telegram: {e}")
        await message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.message_handler(state=UserState.books)
async def choose_books(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        user_id = user_data["user_id"]
        source = user_data["source"]
        email = user_data["email"]
        telegram = user_data["telegram"]
        promo_code = user_data.get("promo_code")

        book_indices = [int(i.strip()) - 1 for i in message.text.split("\n") if i.strip().isdigit()]
        if len(book_indices) != 3:
            await message.answer("Илтимос, айнан 3 та китоб танланг. Рақамларни қайта юборинг:")
            return
        if any(i < 0 or i >= len(BOOKS) for i in book_indices):
            await message.answer("Нотўғри рақамлар. Рўйхатдан 3 та китоб рақамини танланг:")
            return
        books = ", ".join(BOOKS[i] for i in book_indices)

        db.add_user(user_id, source, email, telegram, books, promo_code)
        user = db.get_user(user_id)
        trial_end = user[6]  # trial_end из базы

        # Уведомление пользователю
        price = "49.900 сўм" if promo_code else "59.900 сўм"
        text = (
            f"📝 *Рўйхатдан ўтиш муваффақиятли якунланди!* 🎉\n\n"
            f"📡 Бизни қаердан топдингиз: {source}\n"
            f"📧 Email: `{obfuscate_email(email)}`\n"
            f"👤 Telegram: `{telegram}`\n"
            f"📚 Китоблар: {books}\n"
            f"⏳ Синов муддати: *{trial_end}*\n"
            f"🎟️ Промокод: {promo_code if promo_code else 'қўлланилмаган'}\n\n"
            f"💳 Фойдаланишни давом эттириш учун тўлов қилинг ({price})."
        )
        await message.answer(text, reply_markup=get_payment_options(user_id, promo_code), parse_mode="Markdown")

        # Уведомление админам
        admin_text = (
            f"📥 Янги фойдаланувчи рўйхатдан ўтди:\n\n"
            f"🆔 Фойдаланувчи ID: {user_id}\n"
            f"📡 Бизни қаердан топди: {source}\n"
            f"📧 Email: {obfuscate_email(email)}\n"
            f"👤 Telegram: {telegram}\n"
            f"📚 Китоблар: {books}\n"
            f"⏳ Синов муддати: {trial_end}\n"
            f"🎟️ Промокод: {promo_code if promo_code else 'қўлланилмаган'}"
        )
        for admin_id in ADMIN_IDS:
            await bot.send_message(admin_id, admin_text)

        await state.finish()
    except ValueError:
        await message.answer("Рақамларни тўғри киритинг, масалан:\n1\n2\n3")
    except Exception as e:
        logger.error(f"Ошибка в choose_books: {e}")
        await message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.callback_query_handler(lambda c: c.data.startswith("pay_"))
async def start_payment(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        parts = callback_query.data.split("_")
        months = int(parts[1])
        user_id = int(parts[2])
        user = db.get_user(user_id)
        if user:
            logger.info(f"Начало оплаты: user_id={user_id}, months={months}")
            await state.update_data(user_id=user_id, months=months, email=user[3])
            price = "49.900 сўм" if user[10] else "59.900 сўм"
            await callback_query.message.answer(
                f"💳 Сиз танлаган тариф: *{months} ой* ({price})\n"
                f"Карта рақами: `{CARD_NUMBER}`\n\n"
                f"📸 Тўловдан сўнг чекни бу ерга юборинг (фото, документ ёки матн). Текшириш — 30 дақиқа ичида.",
                parse_mode="Markdown"
            )
            await UserState.payment.set()
            logger.info(f"Состояние установлено: UserState.payment для user_id={user_id}")
        else:
            await callback_query.message.answer("❗ Сизнинг аккаунтингиз топилмади.")
    except Exception as e:
        logger.error(f"Ошибка в start_payment: {e}")
        await callback_query.message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.message_handler(state=UserState.payment, content_types=types.ContentType.ANY)
async def receive_payment(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        user_id = user_data.get("user_id")
        email = user_data.get("email")
        months = user_data.get("months")
        if not all([user_id, email, months]):
            logger.error(f"Недостаточно данных в state: user_id={user_id}, email={email}, months={months}")
            await message.reply("❌ Хатолик: маълумотлар топилмади. Яна уриниб кўринг.")
            await state.finish()
            return

        user = db.get_user(user_id)
        promo_code = user[10] if user else None
        telegram = f"https://t.me/{message.from_user.username}" if message.from_user.username else message.from_user.full_name
        price = "49.900 сўм" if promo_code else "59.900 сўм"
        caption = (
            f"📥 Янги тўлов текшириш учун:\n\n"
            f"🆔 Фойдаланувчи ID: {user_id}\n"
            f"📧 Email: {obfuscate_email(email)}\n"
            f"👤 Telegram: {telegram}\n"
            f"📅 Танланган тариф: {months} ой ({price})\n"
            f"🎟️ Промокод: {promo_code if promo_code else 'қўлланилмаган'}"
        )

        for admin_id in ADMIN_IDS:
            if message.photo:
                await bot.send_photo(admin_id, message.photo[-1].file_id, caption=caption, reply_markup=get_confirmation_buttons(user_id))
            elif message.document:
                await bot.send_document(admin_id, message.document.file_id, caption=caption, reply_markup=get_confirmation_buttons(user_id))
            else:
                await bot.send_message(admin_id, caption + f"\n\n📄 Матн:\n{message.text}", reply_markup=get_confirmation_buttons(user_id))
        await message.reply("🧾 Раҳмат! Биз маълумотларни администраторга юбордик. ⏳ Жавобни кутинг.")
        logger.info(f"Чек отправлен админу: user_id={user_id}, months={months}")
        await state.finish()
    except Exception as e:
        logger.error(f"Ошибка при отправке чека админу: {e}")
        await message.reply("❌ Чекни юборишда хатолик. Яна уриниб кўринг.")

@dp.callback_query_handler(lambda c: c.data.startswith("payment_approve_"))
async def confirm_payment(callback_query: types.CallbackQuery):
    try:
        logger.info(f"Получен callback: {callback_query.data}")
        parts = callback_query.data.split("_")
        if len(parts) != 4:
            logger.error(f"Неверный формат callback_data: {callback_query.data}")
            await callback_query.answer("❌ Хатолик: нотўғри сўров.")
            return

        user_id = int(parts[2])
        bonus = int(parts[3])
        user = db.get_user(user_id)
        if not user:
            logger.error(f"Пользователь с user_id={user_id} не найден")
            await callback_query.answer("❌ Фойдаланувчи топилмади.")
            return

        email = user[3]
        promo_code = user[10]
        months = 1  # Только 1 месяц
        db.update_payment(user_id, months, bonus)

        if callback_query.message.text:
            await callback_query.message.edit_text(
                f"✅ {obfuscate_email(email)} учун тўлов тасдиқланди. Қўшилди: {months} ой + {bonus} ой бонус\n"
                f"🎟️ Промокод: {promo_code if promo_code else 'қўлланилмаган'}"
            )
        else:
            await bot.send_message(
                callback_query.message.chat.id,
                f"✅ {obfuscate_email(email)} учун тўлов тасдиқланди. Қўшилди: {months} ой + {bonus} ой бонус\n"
                f"🎟️ Промокод: {promo_code if promo_code else 'қўлланилмаган'}"
            )
            await callback_query.message.delete()

        await bot.send_message(
            user_id,
            "✅ Хуш келибсиз! Профилингизга ўтиш учун қуйидаги тугмани босинг.",
            reply_markup=get_main_menu()
        )
        await bot.send_message(user_id, f"🎉 Табриклаймиз! Сиз {months} ойга обуна харид қилдингиз ва {bonus} ой бонус оласиз!")
        logger.info(f"Оплата подтверждена: user_id={user_id}, months={months}, bonus={bonus}")
    except Exception as e:
        logger.error(f"Ошибка в confirm_payment: {e}")
        await callback_query.answer("❌ Хатолик юз берди.")

@dp.callback_query_handler(lambda c: c.data.startswith("payment_reject_"))
async def reject_payment(callback_query: types.CallbackQuery):
    try:
        logger.info(f"Получен callback: {callback_query.data}")
        user_id = int(callback_query.data.split("_")[2])
        await bot.send_message(user_id, "❌ Афсуски, тўлов текширишдан ўтмади. Яна уриниб кўринг ёки қўллаб-қувватлаш хизматига мурожаат қилинг.")
        await callback_query.answer("Тўлов рад этилди.")
        logger.info(f"Оплата отклонена для user_id={user_id}")
    except Exception as e:
        logger.error(f"Ошибка в reject_payment: {e}")
        await callback_query.answer("❌ Хатолик юз берди.")

@dp.message_handler(lambda message: message.text == "👤 Профилим")
async def profile_info(message: types.Message):
    try:
        user_id = message.from_user.id
        logger.info(f"Поиск профиля для user_id: {user_id}")
        user = db.get_user(user_id)
        if user:
            user_id, _, source, email, telegram, books, trial_end, payment_due, paid, confirmed, promo_code, is_active = user
            if is_active == 0:
                await message.answer(
                    "❌ Сизнинг обунангиз муддати тугади ва сиз ўчирилдингиз.\n"
                    "Яна фойдаланиш учун тўлов қилинг ва чекни юборинг.",
                    reply_markup=get_payment_options(user_id, promo_code)
                )
                await UserState.payment.set()
                await message.answer("💳 Тарифни танланг:")
                return
            text = format_user_info(user_id, source, email, telegram, books, trial_end, payment_due, paid, confirmed, promo_code, is_active) + "\n\nСиз қуйида обунани узайтиришингиз мумкин:"
            await message.answer(text, reply_markup=get_profile_buttons(email), parse_mode="Markdown")
        else:
            await message.answer(
                "👋 *Сиз ҳали Wordzen'да рўйхатдан ўтмангиз!*\n\n"
                "Ботдан фойдаланишни бошлаш ва 3 кунлик бепул муддат олиш учун қуйидаги тугмани босинг:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("\u25B6\uFE0F Рўйхатдан ўтиш", callback_data="start_registration")
                )
            )
    except Exception as e:
        logger.error(f"Ошибка в profile_info: {e}")
        await message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.callback_query_handler(lambda c: c.data.startswith("extend_subscription_"))
async def extend_subscription(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        email = callback_query.data.split("_")[-1]
        user_id = callback_query.from_user.id
        user = db.get_user(user_id)
        if user and user[3] == email:
            await callback_query.message.edit_text("💳 Обунани узайтириш учун тарифни танланг:", reply_markup=get_payment_options(user_id, user[10]))
        else:
            await callback_query.message.edit_text("❗ Сизнинг аккаунтингиз топилмади.")
    except Exception as e:
        logger.error(f"Ошибка в extend_subscription: {e}")
        await callback_query.message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.callback_query_handler(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback_query: types.CallbackQuery):
    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.error(f"Ошибка в back_to_menu: {e}")
        await callback_query.answer("❌ Хатолик юз берди.")

@dp.message_handler(lambda message: message.text == "📩 Админга хабар юбориш")
async def message_to_admin(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        user = db.get_user(user_id)
        if not user or user[11] == 0:
            await message.answer("❌ Сиз рўйхатдан ўтмагансингиз ёки аккаунтингиз ўчирилган.")
            return
        await message.answer("Админга хабар юборинг (матн, фото ёки документ):")
        await state.update_data(user_id=user_id)
        await UserState.message_to_admin.set()
    except Exception as e:
        logger.error(f"Ошибка в message_to_admin: {e}")
        await message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.message_handler(state=UserState.message_to_admin, content_types=types.ContentType.ANY)
async def send_message_to_admin(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        user_id = user_data.get("user_id")
        user = db.get_user(user_id)
        if not user:
            await message.reply("❌ Фойдаланувчи топилмади.")
            await state.finish()
            return

        email = user[3]
        telegram = user[4]
        db.add_message(user_id, message.text if message.text else "Медиа хабар")

        caption = (
            f"📩 Янги хабар:\n\n"
            f"🆔 Фойдаланувчи ID: {user_id}\n"
            f"📧 Email: {obfuscate_email(email)}\n"
            f"👤 Telegram: {telegram}\n"
        )
        reply_button = InlineKeyboardMarkup().add(
            InlineKeyboardButton("✍️ Жавоб бериш", callback_data=f"reply_to_{user_id}")
        )

        for admin_id in ADMIN_IDS:
            if message.photo:
                await bot.send_photo(admin_id, message.photo[-1].file_id, caption=caption, reply_markup=reply_button)
            elif message.document:
                await bot.send_document(admin_id, message.document.file_id, caption=caption, reply_markup=reply_button)
            else:
                await bot.send_message(admin_id, caption + f"📄 Матн:\n{message.text}", reply_markup=reply_button)
        await message.reply("✅ Хабар админга юборилди. Жавобни кутинг.")
        await state.finish()
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения админу: {e}")
        await message.reply("❌ Хабарни юборишда хатолик. Яна уриниб кўринг.")

@dp.callback_query_handler(lambda c: c.data.startswith("reply_to_"))
async def reply_to_user(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        user_id = int(callback_query.data.split("_")[2])
        await callback_query.message.answer("Фойдаланувчига жавобингизни юборинг (матн, фото ёки документ):")
        await state.update_data(user_id=user_id)
        await UserState.reply_to_user.set()
    except Exception as e:
        logger.error(f"Ошибка в reply_to_user: {e}")
        await callback_query.answer("❌ Хатолик юз берди.")

@dp.message_handler(state=UserState.reply_to_user, content_types=types.ContentType.ANY)
async def send_reply_to_user(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        user_id = user_data.get("user_id")
        db.add_message(user_id, message.text if message.text else "Медиа хабар", is_from_user=False)

        if message.photo:
            await bot.send_photo(user_id, message.photo[-1].file_id, caption=message.caption or "Админдан жавоб:")
        elif message.document:
            await bot.send_document(user_id, message.document.file_id, caption=message.caption or "Админдан жавоб:")
        else:
            await bot.send_message(user_id, f"📩 Админдан жавоб:\n{message.text}")
        await message.reply("✅ Жавоб фойдаланувчига юборилди.")
        await state.finish()
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа пользователю {user_id}: {e}")
        await message.reply("❌ Жавобни юборишда хатолик. Яна уриниб кўринг.")
        # main.py (часть 4)
@dp.message_handler(commands=["users"])
async def list_users(message: types.Message):
    try:
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ Сизда бу команда учун рухсат йўқ.")
            return
        users = db.get_all_users()
        text = "👥 Фойдаланувчилар рўйхати:\n"
        for user in users:
            user_id, source, email, telegram, books, trial_end, payment_due, paid, confirmed, promo_code, is_active = user
            text += f"\n🆔 {user_id}\n📡 Бизни қаердан топди: {source}\n📧 {obfuscate_email(email)}\n👤 {telegram}\n📚 Китоблар: {books or 'танланмаган'}\n⏳ Синов: {trial_end}\n⏳ Обуна: {payment_due}\n💰 Ойлар: {paid}\n✅ Тўланган: {'Ҳа' if confirmed else 'Йўқ'}\n🎟️ Промокод: {promo_code if promo_code else 'қўлланилмаган'}\n🔄 Актив: {'Фаол' if is_active else 'Ўчирилган'}\n---"
        await message.answer(text)
    except Exception as e:
        logger.error(f"Ошибка в list_users: {e}")
        await message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.message_handler(commands=["promo_stats"])
async def promo_stats(message: types.Message):
    try:
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ Сизда бу команда учун рухсат йўқ.")
            return
        stats = db.get_promo_stats()
        if not stats:
            await message.answer("📊 Ҳозирча промокодлар йўқ.")
            return
        text = "📊 Промокодлар статистикаси:\n"
        for code, teacher_name, used_count, bonus_days in stats:
            text += f"\nКод: `{code}`\nЎқитувчи: {teacher_name}\nФойдаланилди: {used_count}\nБонус: {bonus_days} кун\n---"
        await message.answer(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в promo_stats: {e}")
        await message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.message_handler(commands=["stats"])
async def show_stats(message: types.Message):
    try:
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ Сизда бу команда учун рухсат йўқ.")
            return
        total_users, paid_users, promo_users = db.get_stats()
        text = (
            "📊 Умумий статистика:\n"
            f"👥 Жами фойдаланувчилар: {total_users}\n"
            f"💳 Обуна тўлаганлар: {paid_users}\n"
            f"🎟️ Промокод ишлатганлар: {promo_users}"
        )
        await message.answer(text)
    except Exception as e:
        logger.error(f"Ошибка в show_stats: {e}")
        await message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.message_handler(commands=["reset"])
async def reset_books_admin(message: types.Message):
    try:
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ Сизда бу команда учун рухсат йўқ.")
            return
        user_id = int(message.get_args())
        user = db.get_user(user_id)
        if not user:
            await message.answer(f"❌ ID {user_id} билан фойдаланувчи топилмади.")
            return
        db.reset_books(user_id)
        await message.answer(f"✅ ID {user_id} фойдаланувчиси учун китоблар тозаланди. Энди у янги китоблар танлай олади.")
        await bot.send_message(user_id, "📚 Сизнинг китобларингиз тозаланди. Янги китоблар танлаш учун /start буйруғини босинг.")
    except ValueError:
        await message.answer("❌ Фойдаланувчи ID'ни киритинг. Масалан: /reset 123456789")
    except Exception as e:
        logger.error(f"Ошибка в reset_books_admin: {e}")
        await message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.callback_query_handler(lambda c: c.data.startswith("reset_books_"))
async def reset_books_user(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        user_id = int(callback_query.data.split("_")[2])
        user = db.get_user(user_id)
        if not user:
            await callback_query.message.edit_text("❌ Фойдаланувчи топилмади.")
            return
        db.reset_books(user_id)
        await callback_query.message.edit_text(
            "📚 Сизнинг китобларингиз тозаланди. Янги китоблар танлаш учун рақамларни юборинг:\n"
            "Рўйхат:\n" + "\n".join(f"{i+1}. {book}" for i, book in enumerate(BOOKS))
        )
        await state.update_data(user_id=user_id)
        await UserState.reset_books.set()
    except Exception as e:
        logger.error(f"Ошибка в reset_books_user: {e}")
        await callback_query.message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

@dp.message_handler(state=UserState.reset_books)
async def choose_new_books(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        user_id = user_data.get("user_id")
        book_indices = [int(i.strip()) - 1 for i in message.text.split("\n") if i.strip().isdigit()]
        if len(book_indices) != 3:
            await message.answer("Илтимос, айнан 3 та китоб танланг. Рақамларни қайта юборинг:")
            return
        if any(i < 0 or i >= len(BOOKS) for i in book_indices):
            await message.answer("Нотўғри рақамлар. Рўйхатдан 3 та китоб рақамини танланг:")
            return
        books = ", ".join(BOOKS[i] for i in book_indices)
        user = db.get_user(user_id)
        if not user:
            await message.answer("❌ Фойдаланувчи топилмади.")
            await state.finish()
            return
        db.cursor.execute("UPDATE users SET books = %s WHERE user_id = %s", (books, user_id))
        db.conn.commit()
        user = db.get_user(user_id)
        user_id, _, source, email, telegram, books, trial_end, payment_due, paid, confirmed, promo_code, is_active = user
        text = format_user_info(user_id, source, email, telegram, books, trial_end, payment_due, paid, confirmed, promo_code, is_active)
        await message.answer("✅ Китоблар янгиланди!\n\n" + text, parse_mode="Markdown", reply_markup=get_main_menu())
        await state.finish()
    except ValueError:
        await message.answer("Рақамларни тўғри киритинг, масалан:\n1\n2\n3")
    except Exception as e:
        logger.error(f"Ошибка в choose_new_books: {e}")
        await message.answer("❌ Хатолик юз берди. Кейинроқ уриниб кўринг.")

# Проверка оплаты и пробного периода
async def check_payments():
    while True:
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            unpaid_users = db.get_unpaid_users(today)
            trial_ending_users = db.get_users_near_trial_end(today)

            for user_id, email, telegram in unpaid_users:
                db.deactivate_user(user_id)
                await bot.send_message(
                    user_id,
                    "❌ Сизнинг обунангиз муддати тугади. Яна фойдаланиш учун тўлов қилинг ва чекни юборинг.",
                    reply_markup=get_payment_options(user_id)
                )
                for admin_id in ADMIN_IDS:
                    await bot.send_message(
                        admin_id,
                        f"❌ Фойдаланувчи ўчирилди (обуна тугади):\n"
                        f"🆔 {user_id}\n📧 {obfuscate_email(email)}\n👤 {telegram}"
                    )

            for user_id, email, telegram in trial_ending_users:
                await bot.send_message(
                    user_id,
                    "⏳ Сизнинг синов муддатингиз бугун тугайди. Фойдаланишни давом эттириш учун тўлов қилинг.",
                    reply_markup=get_payment_options(user_id)
                )
                for admin_id in ADMIN_IDS:
                    await bot.send_message(
                        admin_id,
                        f"⏳ Синов муддати тугаяпти:\n"
                        f"🆔 {user_id}\n📧 {obfuscate_email(email)}\n👤 {telegram}"
                    )

        except Exception as e:
            logger.error(f"Ошибка в check_payments: {e}")
        await asyncio.sleep(24 * 60 * 60)  # Проверка раз в сутки

# Запуск бота с использованием webhook
async def on_startup(_):
    logger.info("Запуск бота...")
    await bot.delete_webhook(drop_pending_updates=True)
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook"
    await bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook установлен: {webhook_url}")
    asyncio.create_task(check_payments())

if __name__ == "__main__":
    keep_alive()
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token="",  # Если используешь секретный токен, укажи его
    )
    webhook_requests_handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
