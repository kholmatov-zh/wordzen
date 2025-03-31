import os
import asyncio
import logging
import random
import string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from keep_alive import keep_alive
import psycopg2

# Конфигурация логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TOKEN")
ADMIN_IDS = [int(admin_id) for admin_id in os.getenv("ADMIN_IDS", "").split(",") if admin_id]
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS не указаны в переменных окружения!")
CHANNEL_LINK = "https://t.me/your_channel"
CARD_NUMBER = "1234 5678 9012 3456"

bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# PostgreSQL база данных через Supabase
class Database:
    def __init__(self):
        self.conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        self.cursor = self.conn.cursor()
        logger.info("Подключение к базе данных PostgreSQL")
        self._create_tables()

    def _create_tables(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE,
            email TEXT UNIQUE,
            telegram TEXT,
            books TEXT,
            trial_end TEXT,
            payment_due TEXT,
            paid_months INTEGER DEFAULT 0,
            payment_confirmed INTEGER DEFAULT 0,
            promo_code TEXT
        )''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            usage_limit INTEGER DEFAULT 5,
            used_count INTEGER DEFAULT 0,
            bonus_days INTEGER DEFAULT 7
        )''')
        self.conn.commit()
        logger.info("Таблицы созданы или уже существуют")

    def add_user(self, user_id, email, telegram, books, promo_code=None):
        trial_end = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
        if promo_code:
            promo = self.get_promo_code(promo_code)
            if promo and promo[2] < promo[1]:  # used_count < usage_limit
                bonus_days = promo[3]
                trial_end = (datetime.now() + timedelta(days=3 + bonus_days)).strftime('%Y-%m-%d')
                self.cursor.execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE code = %s", (promo_code,))
        self.cursor.execute(
            "INSERT INTO users (user_id, email, telegram, books, trial_end, payment_due, promo_code) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (user_id) DO NOTHING",
            (user_id, email, telegram, books, trial_end, trial_end, promo_code)
        )
        self.conn.commit()
        logger.info(f"Добавлен пользователь: user_id={user_id}, email={email}, promo_code={promo_code}")

    def get_user(self, user_id):
        self.cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        result = self.cursor.fetchone()
        logger.info(f"Поиск пользователя: user_id={user_id}, результат={result}")
        return result

    def update_payment(self, user_id, months, bonus=0):
        total = months + bonus
        self.cursor.execute(
            "UPDATE users SET paid_months = paid_months + %s, payment_confirmed = 1, payment_due = %s WHERE user_id = %s",
            (total, (datetime.now() + timedelta(days=30 * total)).strftime('%Y-%m-%d'), user_id)
        )
        self.conn.commit()
        logger.info(f"Обновлена оплата: user_id={user_id}, months={months}, bonus={bonus}")

    def get_promo_code(self, code):
        self.cursor.execute("SELECT code, usage_limit, used_count, bonus_days FROM promo_codes WHERE code = %s", (code,))
        return self.cursor.fetchone()

    def add_promo_code(self, code, usage_limit=5, bonus_days=7):
        self.cursor.execute(
            "INSERT INTO promo_codes (code, usage_limit, used_count, bonus_days) VALUES (%s, %s, 0, %s) ON CONFLICT (code) DO NOTHING",
            (code, usage_limit, bonus_days)
        )
        self.conn.commit()

    def get_promo_stats(self):
        self.cursor.execute("SELECT code, usage_limit, used_count, bonus_days FROM promo_codes")
        return self.cursor.fetchall()

    def get_unpaid_users(self, date):
        self.cursor.execute("SELECT email, telegram FROM users WHERE payment_due = %s AND payment_confirmed = 0", (date,))
        return self.cursor.fetchall()

    def get_users_near_trial_end(self, date):
        self.cursor.execute("SELECT email, telegram FROM users WHERE trial_end = %s AND payment_confirmed = 0", (date,))
        return self.cursor.fetchall()

    def get_all_users(self):
        self.cursor.execute("SELECT user_id, email, telegram, trial_end, paid_months, payment_confirmed, promo_code FROM users")
        return self.cursor.fetchall()

    def delete_user(self, user_id):
        self.cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        self.conn.commit()
        logger.info(f"Пользователь удалён: user_id={user_id}")

    def reset_promo_code(self, code):
        self.cursor.execute("UPDATE promo_codes SET used_count = 0 WHERE code = %s", (code,))
        self.conn.commit()
        logger.info(f"Счётчик промокода сброшен: code={code}")

    def get_stats(self):
        self.cursor.execute("SELECT COUNT(*) FROM users")
        total_users = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE payment_confirmed = 1")
        paid_users = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE promo_code IS NOT NULL")
        promo_users = self.cursor.fetchone()[0]
        return total_users, paid_users, promo_users

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

# Клавиатуры
def get_main_menu():
    return ReplyKeyboardMarkup(resize_keyboard=True).add(
        KeyboardButton("👤 Профилим")
    )

def get_start_button():
    return InlineKeyboardMarkup().add(InlineKeyboardButton("\u25B6\uFE0F Рўйхатдан ўтиш", callback_data="start_registration"))

def get_books_keyboard(selected_books=[]):
    books = ["Китоб 1", "Китоб 2", "Китоб 3", "Китоб 4"]
    markup = InlineKeyboardMarkup(row_width=2)
    for book in books:
        prefix = "\u2705 " if book in selected_books else ""
        markup.add(InlineKeyboardButton(prefix + book, callback_data=f"book_{book}"))
    markup.add(InlineKeyboardButton("\U0001F4E6 Тайёр", callback_data="confirm_books"))
    return markup

def get_payment_options(user_id):
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("📅 1 ой — 100 сўм", callback_data=f"pay_1_{user_id}"),
        InlineKeyboardButton("📅 3 ой — 300 сўм +1 ой 🎁", callback_data=f"pay_3_{user_id}")
    )

def get_confirmation_buttons(user_id):
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ Тасдиқлаш (1 ой)", callback_data=f"payment_approve_{user_id}_1"),
        InlineKeyboardButton("✅ Тасдиқлаш (3 ой)", callback_data=f"payment_approve_{user_id}_3"),
        InlineKeyboardButton("❌ Рад этиш", callback_data=f"payment_reject_{user_id}")
    )

def get_profile_buttons(email):
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("💳 Обунани узайтириш", callback_data=f"extend_subscription_{email}"),
        InlineKeyboardButton("🔙 Орқага", callback_data="back_to_menu")
    )

# Вспомогательные функции
def format_user_info(user_id, email, telegram, books, trial_end, payment_due, paid, confirmed, promo_code):
    obfuscated_email = obfuscate_email(email)
    return (
        f"👤 *Сизнинг профилингиз:*\n"
        f"🆔 Фойдаланувчи ID: `{user_id}`\n"
        f"📧 Email: `{obfuscated_email}`\n"
        f"👤 Telegram: `{telegram}`\n"
        f"📚 Китоблар: {books or 'танланмаган'}\n"
        f"⏳ Синов муддати: *{trial_end}*\n"
        f"⏳ Обуна муддати: *{payment_due}*\n"
        f"💰 Тўланган ойлар: {paid}\n"
        f"✅ Ҳолат: {'Тўланган' if confirmed else 'Синов/тўланмаган'}\n"
        f"🎟️ Промокод: {promo_code if promo_code else 'қўлланилмаган'}"
    )

def calculate_bonus(months):
    return 1 if months == 3 else 0

# Состояния
class UserState(StatesGroup):
    email = State()
    telegram = State()
    promo = State()
    books = State()
    payment = State()

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
    await callback_query.message.delete()
    await callback_query.message.answer("\U0001F4E7 Email манзилингизни киритинг:")
    await UserState.email.set()

@dp.message_handler(state=UserState.email)
async def get_email(message: types.Message, state: FSMContext):
    await state.update_data(email=message.text)
    await message.answer("Telegram аккаунтингиз линкни юборинг (масалан, @username):")
    await UserState.telegram.set()

@dp.message_handler(state=UserState.telegram)
async def get_telegram(message: types.Message, state: FSMContext):
    await state.update_data(telegram=message.text, user_id=message.from_user.id)
    await message.answer("Сизда промокод борми? Уни киритинг ёки 'йўқ' деб ёзинг:")
    await UserState.promo.set()

@dp.message_handler(state=UserState.promo)
async def get_promo(message: types.Message, state: FSMContext):
    promo_code = message.text.strip().upper() if message.text.lower() != 'йўқ' else None
    if promo_code:
        promo = db.get_promo_code(promo_code)
        if not promo:
            await message.answer("❌ Промокод топилмади. Яна уриниб кўринг ёки 'йўқ' деб ёзинг:")
            return
        if promo[2] >= promo[1]:
            await message.answer("❌ Бу промокод максимал фойдаланилди. Бошқа промокод киритинг ёки 'йўқ' деб ёзинг:")
            return
    await state.update_data(promo_code=promo_code)
    await state.update_data(books=[])
    await message.answer("\U0001F4DA Китоблар рўйхати. 3 тагача танланг:", reply_markup=get_books_keyboard())
    await UserState.books.set()

@dp.callback_query_handler(lambda c: c.data.startswith("book_"), state=UserState.books)
async def choose_books(callback_query: types.CallbackQuery, state: FSMContext):
    book = callback_query.data[5:]
    user_data = await state.get_data()
    chosen_books = user_data.get("books", [])

    if book in chosen_books:
        chosen_books.remove(book)
    elif len(chosen_books) < 3:
        chosen_books.append(book)
    else:
        await callback_query.answer("Энг кўпи билан 3 та китоб танлаш мумкин.")
        return

    await state.update_data(books=chosen_books)
    selected_text = (
        "\U0001F4DA *Сиз танлаган китоблар:*\n" + "\n".join([f"• {b}" for b in chosen_books])
        if chosen_books else "Сиз ҳали ҳеч нарса танламангиз."
    )
    await callback_query.message.edit_text(
        selected_text + "\n\nСиз 3 тагача китоб танлашингиз мумкин:",
        reply_markup=get_books_keyboard(chosen_books),
        parse_mode="Markdown"
    )

@dp.callback_query_handler(lambda c: c.data == "confirm_books", state=UserState.books)
async def confirm_books(callback_query: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    user_id = user_data["user_id"]
    email = user_data["email"]
    telegram = user_data["telegram"]
    books = ", ".join(user_data.get("books", []))
    promo_code = user_data.get("promo_code")
    db.add_user(user_id, email, telegram, books, promo_code)

    user = db.get_user(user_id)
    trial_end = user[5]  # trial_end из базы
    text = (
        f"📝 *Рўйхатдан ўтиш муваффақиятли якунланди!* 🎉\n\n"
        f"📧 Email: `{obfuscate_email(email)}`\n"
        f"👤 Telegram: `{telegram}`\n"
        f"📚 Китоблар: {books or 'танланмаган'}\n"
        f"⏳ Синов муддати: *{trial_end}*\n"
        f"🎟️ Промокод: {promo_code if promo_code else 'қўлланилмаган'}\n\n"
        f"💳 Фойдаланишни давом эттириш учун қуйидаги тугма орқали тўлов амалга оширинг ва чекни юборинг."
    )
    buttons = InlineKeyboardMarkup().add(
        InlineKeyboardButton("✅ Каналга ўтиш", url=CHANNEL_LINK),
        InlineKeyboardButton("💳 Тўлаш", callback_data="payment_options")
    )
    await callback_query.message.edit_text(text, reply_markup=buttons, parse_mode="Markdown")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "payment_options")
async def show_tariffs(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"Показ тарифов для user_id={user_id}")
    await callback_query.message.edit_text("💳 Тарифни танланг:", reply_markup=get_payment_options(user_id))

@dp.callback_query_handler(lambda c: c.data.startswith("pay_"))
async def start_payment(callback_query: types.CallbackQuery, state: FSMContext):
    parts = callback_query.data.split("_")
    months = int(parts[1])
    user_id = int(parts[2])
    user = db.get_user(user_id)
    if user:
        logger.info(f"Начало оплаты: user_id={user_id}, months={months}")
        await state.update_data(user_id=user_id, months=months, email=user[2])
        await callback_query.message.answer(
            f"💳 Сиз танлаган тариф: *{months} ой*\n"
            f"Карта рақами: `{CARD_NUMBER}`\n\n"
            f"📸 Тўловдан сўнг чекни бу ерга юборинг. Текшириш — 30 дақиқа ичида.",
            parse_mode="Markdown"
        )
        await UserState.payment.set()
        logger.info(f"Состояние установлено: UserState.payment для user_id={user_id}")
    else:
        await callback_query.message.answer("❗ Сизнинг аккаунтингиз топилмади.")

@dp.message_handler(state=UserState.payment, content_types=types.ContentType.ANY)
async def receive_payment(message: types.Message, state: FSMContext):
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
    promo_code = user[9] if user else None
    telegram = f"https://t.me/{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    caption = (
        f"📥 Янги тўлов текшириш учун:\n\n"
        f"🆔 Фойдаланувчи ID: {user_id}\n"
        f"📧 Email: {obfuscate_email(email)}\n"
        f"👤 Telegram: {telegram}\n"
        f"📅 Танланган тариф: {months} ой\n"
        f"🎟️ Промокод: {promo_code if promo_code else 'қўлланилмаган'}"
    )

    try:
        for admin_id in ADMIN_IDS:
            if message.photo:
                await bot.send_photo(admin_id, message.photo[-1].file_id, caption=caption, reply_markup=get_confirmation_buttons(user_id))
            elif message.document:
                await bot.send_document(admin_id, message.document.file_id, caption=caption, reply_markup=get_confirmation_buttons(user_id))
            else:
                await bot.send_message(admin_id, caption + f"\n\n📄 Матн:\n{message.text}", reply_markup=get_confirmation_buttons(user_id))
        await message.reply("🧾 Раҳмат! Биз маълумотларни администраторга юбордик. ⏳ Жавобни кутинг.")
        logger.info(f"Чек отправлен админу: user_id={user_id}, months={months}")
    except Exception as e:
        logger.error(f"Ошибка при отправке чека админу: {e}")
        await message.reply("❌ Чекни юборишда хатолик. Яна уриниб кўринг.")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("payment_approve_"))
async def confirm_payment(callback_query: types.CallbackQuery):
    logger.info(f"Получен callback: {callback_query.data}")
    parts = callback_query.data.split("_")
    if len(parts) != 4:
        logger.error(f"Неверный формат callback_data: {callback_query.data}")
        await callback_query.answer("❌ Хатолик: нотўғри сўров.")
        return

    user_id = int(parts[2])
    months = int(parts[3])
    user = db.get_user(user_id)
    if not user:
        logger.error(f"Пользователь с user_id={user_id} не найден")
        await callback_query.answer("❌ Фойдаланувчи топилмади.")
        return

    email = user[2]
    promo_code = user[9]
    bonus = calculate_bonus(months)
    db.update_payment(user_id, months, bonus)

    if callback_query.message.text:
        await callback_query.message.edit_text(
            f"✅ {obfuscate_email(email)} учун тўлов тасдиқланди. Қўшилди: {months} ой + {bonus} ой 🎁\n"
            f"🎟️ Промокод: {promo_code if promo_code else 'қўлланилмаган'}"
        )
    else:
        await bot.send_message(
            callback_query.message.chat.id,
            f"✅ {obfuscate_email(email)} учун тўлов тасдиқланди. Қўшилди: {months} ой + {bonus} ой 🎁\n"
            f"🎟️ Промокод: {promo_code if promo_code else 'қўлланилмаган'}"
        )
        await callback_query.message.delete()

    await bot.send_message(
        user_id,
        "✅ Хуш келибсиз! Профилингизга ўтиш учун қуйидаги тугмани босинг.",
        reply_markup=get_main_menu()
    )
    await bot.send_message(user_id, f"🎉 Табриклаймиз! Сиз {months} ойга обуна харид қилдингиз ва +{bonus} ой бонус оласиз!")
    logger.info(f"Оплата подтверждена: user_id={user_id}, months={months}, bonus={bonus}")

@dp.callback_query_handler(lambda c: c.data.startswith("payment_reject_"))
async def reject_payment(callback_query: types.CallbackQuery):
    logger.info(f"Получен callback: {callback_query.data}")
    user_id = int(callback_query.data.split("_")[2])
    await bot.send_message(user_id, "❌ Афсуски, тўлов текширишдан ўтмади. Яна уриниб кўринг ёки қўллаб-қувватлаш хизматига мурожаат қилинг.")
    await callback_query.answer("Тўлов рад этилди.")
    logger.info(f"Оплата отклонена для user_id={user_id}")

@dp.message_handler(lambda message: message.text == "👤 Профилим")
async def profile_info(message: types.Message):
    user_id = message.from_user.id
    logger.info(f"Поиск профиля для user_id: {user_id}")
    user = db.get_user(user_id)
    if user:
        user_id, _, email, telegram, books, trial_end, payment_due, paid, confirmed, promo_code = user
        text = format_user_info(user_id, email, telegram, books, trial_end, payment_due, paid, confirmed, promo_code) + "\n\nСиз қуйида обунани узайтиришингиз мумкин:"
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

@dp.callback_query_handler(lambda c: c.data.startswith("extend_subscription_"))
async def extend_subscription(callback_query: types.CallbackQuery, state: FSMContext):
    email = callback_query.data.split("_")[-1]
    user_id = callback_query.from_user.id
    user = db.get_user(user_id)
    if user and user[2] == email:
        await callback_query.message.edit_text("💳 Обунани узайтириш учун тарифни танланг:", reply_markup=get_payment_options(user_id))
    else:
        await callback_query.message.edit_text("❗ Сизнинг аккаунтингиз топилмади.")

@dp.callback_query_handler(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback_query: types.CallbackQuery):
    await callback_query.message.delete()

@dp.message_handler(commands=["users"])
async def list_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Сизда бу команда учун рухсат йўқ.")
        return
    users = db.get_all_users()
    text = "👥 Фойдаланувчилар рўйхати:\n"
    for user in users:
        user_id, email, telegram, trial_end, paid, confirmed, promo_code = user
        text += f"\n🆔 {user_id}\n📧 {obfuscate_email(email)}\n👤 {telegram}\n⏳ Муддат: {trial_end}\n💰 Ойлар: {paid}\n✅ Тўланган: {'Ҳа' if confirmed else 'Йўқ'}\n🎟️ Промокод: {promo_code if promo_code else 'қўлланилмаган'}\n---"
    await message.answer(text)

@dp.message_handler(commands=["generate_promo"])
async def generate_promo(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Сизда бу команда учун рухсат йўқ.")
        return
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    db.add_promo_code(code)
    await message.answer(f"✅ Янги промокод яратилди: `{code}`\n5 марта фойдаланиш мумкин, 7 кун бонус беради.")

@dp.message_handler(commands=["promo_stats"])
async def promo_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Сизда бу команда учун рухсат йўқ.")
        return
    stats = db.get_promo_stats()
    if not stats:
        await message.answer("📊 Ҳозирча промокодлар йўқ.")
        return
    text = "📊 Промокодлар статистикаси:\n"
    for code, limit, used, days in stats:
        text += f"\nКод: `{code}`\nЧеклов: {limit}\nФойдаланилди: {used}\nБонус: {days} кун\n---"
    await message.answer(text)

@dp.message_handler(commands=["delete_user"])
async def delete_user(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Сизда бу команда учун рухсат йўқ.")
        return
    try:
        user_id = int(message.get_args())
        user = db.get_user(user_id)
        if not user:
            await message.answer(f"❌ ID {user_id} билан фойдаланувчи топилмади.")
            return
        db.delete_user(user_id)
        await message.answer(f"✅ ID {user_id} билан фойдаланувчи ўчирилди.")
    except ValueError:
        await message.answer("❌ Фойдаланувчи ID'ни киритинг. Масалан: /delete_user 123456789")

@dp.message_handler(commands=["reset_promo"])
async def reset_promo(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Сизда бу команда учун рухсат йўқ.")
        return
    code = message.get_args().strip().upper()
    if not code:
        await message.answer("❌ Промокодни киритинг. Масалан: /reset_promo ABC123")
        return
    promo = db.get_promo_code(code)
    if not promo:
        await message.answer(f"❌ {code} промокоди топилмади.")
        return
    db.reset_promo_code(code)
    await message.answer(f"✅ {code} промокоди счётчиги тозаланди. Энди уни яна ишлатиш мумкин.")

@dp.message_handler(commands=["stats"])
async def show_stats(message: types.Message):
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

@dp.message_handler(commands=["notify_all"])
async def notify_all(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Сизда бу команда учун рухсат йўқ.")
        return
    msg_text = message.get_args()
    if not msg_text:
        await message.answer("❌ Хабарни киритинг. Масалан: /notify_all Мухим эълон!")
        return
    users = db.get_all_users()
    for user in users:
        user_id = user[0]
        try:
            await bot.send_message(user_id, f"📢 Эълон:\n{msg_text}")
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
    await message.answer(f"✅ Хабар {len(users)} фойдаланувчига юборилди.")

async def check_payments():
    while True:
        now = datetime.now().strftime('%Y-%m-%d')
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        for email, telegram in db.get_unpaid_users(now):
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, f"❗ Фойдаланувчи тўлов қилмади:\nEmail: {obfuscate_email(email)}\nTelegram: {telegram}")

        for email, telegram in db.get_users_near_trial_end(tomorrow):
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, f"⏰ Эртага синов муддати тугайди:\nEmail: {obfuscate_email(email)}\nTelegram: {telegram}")
            try:
                await bot.send_message(telegram, f"⏳ Эртага Wordzen'да синов муддати тугайди. Обунани тўланг: {CARD_NUMBER}")
            except Exception as e:
                logger.error(f"Ошибка уведомления {telegram}: {e}")
        await asyncio.sleep(86400)

# Проверка и очистка webhook'ов перед запуском
async def on_startup(_):
    logger.info("Запуск бота...")
    webhook_info = await bot.get_webhook_info()
    if webhook_info.url:
        logger.info(f"Обнаружен активный webhook: {webhook_info.url}. Удаляем его...")
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook удалён.")
    else:
        logger.info("Webhook не обнаружен, продолжаем с polling.")
    logger.info("Бот успешно запущен.")

# Запуск
if __name__ == "__main__":
    keep_alive()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(on_startup(dp))
    loop.create_task(check_payments())
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
