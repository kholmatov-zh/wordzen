import os
import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from keep_alive import keep_alive
import sqlite3

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

# SQLite база данных
class Database:
    def __init__(self, db_name="users.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_table()

    def _create_table(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            email TEXT UNIQUE,
            telegram TEXT,
            books TEXT,
            trial_end TEXT,
            payment_due TEXT,
            paid_months INTEGER DEFAULT 0,
            payment_confirmed INTEGER DEFAULT 0
        )''')
        self.conn.commit()

    def add_user(self, user_id, email, telegram, books):
        trial_end = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
        self.cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, email, telegram, books, trial_end, payment_due) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, email, telegram, books, trial_end, trial_end)
        )
        self.conn.commit()
        logger.info(f"Добавлен пользователь: user_id={user_id}, email={email}, telegram={telegram}, books={books}")

    def get_user(self, user_id):
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()
        logger.info(f"Поиск пользователя: user_id={user_id}, результат={result}")
        return result

    def update_payment(self, user_id, months, bonus=0):
        total = months + bonus
        self.cursor.execute(
            "UPDATE users SET paid_months = paid_months + ?, payment_confirmed = 1, payment_due = ? WHERE user_id = ?",
            (total, (datetime.now() + timedelta(days=30 * total)).strftime('%Y-%m-%d'), user_id)
        )
        self.conn.commit()
        logger.info(f"Обновлена оплата: user_id={user_id}, months={months}, bonus={bonus}")

    def get_unpaid_users(self, date):
        self.cursor.execute("SELECT email, telegram FROM users WHERE payment_due = ? AND payment_confirmed = 0", (date,))
        return self.cursor.fetchall()

    def get_users_near_trial_end(self, date):
        self.cursor.execute("SELECT email, telegram FROM users WHERE trial_end = ? AND payment_confirmed = 0", (date,))
        return self.cursor.fetchall()

    def get_all_users(self):
        self.cursor.execute("SELECT user_id, email, telegram, trial_end, paid_months, payment_confirmed FROM users")
        return self.cursor.fetchall()

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
        KeyboardButton("👤 Профиль")
    )

def get_start_button():
    return InlineKeyboardMarkup().add(InlineKeyboardButton("\u25B6\uFE0F Начать регистрацию", callback_data="start_registration"))

def get_books_keyboard(selected_books=[]):
    books = ["Книга 1", "Книга 2", "Книга 3", "Книга 4"]
    markup = InlineKeyboardMarkup(row_width=2)
    for book in books:
        prefix = "\u2705 " if book in selected_books else ""
        markup.add(InlineKeyboardButton(prefix + book, callback_data=f"book_{book}"))
    markup.add(InlineKeyboardButton("\U0001F4E6 Готово", callback_data="confirm_books"))
    return markup

def get_payment_options(user_id):
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("📅 1 месяц — 100₽", callback_data=f"pay_1_{user_id}"),
        InlineKeyboardButton("📅 3 месяца — 300₽ +1 мес 🎁", callback_data=f"pay_3_{user_id}")
    )

def get_confirmation_buttons(user_id):
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ Подтвердить (1 мес)", callback_data=f"payment_approve_{user_id}_1"),
        InlineKeyboardButton("✅ Подтвердить (3 мес)", callback_data=f"payment_approve_{user_id}_3"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"payment_reject_{user_id}")
    )

def get_profile_buttons(email):
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("💳 Продлить подписку", callback_data=f"extend_subscription_{email}"),
        InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")
    )

# Вспомогательные функции
def format_user_info(user_id, email, telegram, books, trial_end, payment_due, paid, confirmed):
    obfuscated_email = obfuscate_email(email)
    return (
        f"👤 *Ваш профиль:*\n"
        f"🆔 User ID: `{user_id}`\n"
        f"📧 Email: `{obfuscated_email}`\n"
        f"👤 Telegram: `{telegram}`\n"
        f"📚 Книги: {books or 'не выбрано'}\n"
        f"⏳ Пробный доступ до: *{trial_end}*\n"
        f"⏳ Подписка активна до: *{payment_due}*\n"
        f"💰 Оплачено месяцев: {paid}\n"
        f"✅ Статус: {'Оплачено' if confirmed else 'Пробный/не оплачен'}"
    )

def calculate_bonus(months):
    return 1 if months == 3 else 0

# Состояния
class UserState(StatesGroup):
    email = State()
    telegram = State()
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
                    "\U0001F4DA *Добро пожаловать в Wordzen!*\n\n"
                    "Здесь ты получишь доступ к тщательно отобранным книгам.\n\n"
                    "\U0001F381 *3 дня бесплатного доступа для новых пользователей!*\n\n"
                    "Нажми кнопку ниже, чтобы начать \U0001F447"
                ),
                parse_mode="Markdown",
                reply_markup=get_start_button()
            )
    except Exception as e:
        logger.error(f"Ошибка в /start: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")

@dp.callback_query_handler(lambda c: c.data == "start_registration")
async def start_registration(callback_query: types.CallbackQuery):
    await callback_query.message.delete()
    await callback_query.message.answer("\U0001F4E7 Введите ваш email:")
    await UserState.email.set()

@dp.message_handler(state=UserState.email)
async def get_email(message: types.Message, state: FSMContext):
    await state.update_data(email=message.text)
    await message.answer("Отправьте ссылку на ваш Telegram-аккаунт (например, @username):")
    await UserState.telegram.set()

@dp.message_handler(state=UserState.telegram)
async def get_telegram(message: types.Message, state: FSMContext):
    await state.update_data(telegram=message.text, user_id=message.from_user.id)
    await state.update_data(books=[])
    await message.answer("\U0001F4DA Вот список книг. Выберите до 3 штук:", reply_markup=get_books_keyboard())
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
        await callback_query.answer("Можно выбрать максимум 3 книги.")
        return

    await state.update_data(books=chosen_books)
    selected_text = (
        "\U0001F4DA *Вы выбрали:*\n" + "\n".join([f"• {b}" for b in chosen_books])
        if chosen_books else "Вы пока ничего не выбрали."
    )
    await callback_query.message.edit_text(
        selected_text + "\n\nВы можете выбрать до 3 книг:",
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
    db.add_user(user_id, email, telegram, books)

    text = (
        f"📝 *Ваша регистрация завершена!* 🎉\n\n"
        f"📧 Email: `{obfuscate_email(email)}`\n"
        f"👤 Telegram: `{telegram}`\n"
        f"📚 Книги: {books or 'не выбрано'}\n"
        f"⏳ Пробный доступ до: *{(datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')}*\n\n"
        f"💳 Чтобы сохранить доступ, нажмите кнопку оплатить ниже и отправьте чек об оплате."
    )
    buttons = InlineKeyboardMarkup().add(
        InlineKeyboardButton("✅ Перейти в канал", url=CHANNEL_LINK),
        InlineKeyboardButton("💳 Оплатить", callback_data="payment_options")
    )
    await callback_query.message.edit_text(text, reply_markup=buttons, parse_mode="Markdown")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "payment_options")
async def show_tariffs(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"Показ тарифов для user_id={user_id}")
    await callback_query.message.edit_text("💳 Выберите тариф:", reply_markup=get_payment_options(user_id))

@dp.callback_query_handler(lambda c: c.data.startswith("pay_"))
async def start_payment(callback_query: types.CallbackQuery, state: FSMContext):
    parts = callback_query.data.split("_")
    months = int(parts[1])
    user_id = int(parts[2])
    user = db.get_user(user_id)
    if user:
        logger.info(f"Начало оплаты: user_id={user_id}, months={months}")
        await state.update_data(user_id=user_id, months=months, email=user[2])  # Email из базы
        await callback_query.message.answer(
            f"💳 Вы выбрали тариф: *{months} мес.*\n"
            f"Номер карты: `{CARD_NUMBER}`\n\n"
            f"📸 После оплаты отправьте сюда чек. Проверка — до 30 мин.",
            parse_mode="Markdown"
        )
        await UserState.payment.set()
        logger.info(f"Состояние установлено: UserState.payment для user_id={user_id}")
    else:
        await callback_query.message.answer("❗ Не удалось найти ваш аккаунт.")

@dp.message_handler(state=UserState.payment, content_types=types.ContentType.ANY)
async def receive_payment(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    user_id = user_data.get("user_id")
    email = user_data.get("email")
    months = user_data.get("months")
    if not all([user_id, email, months]):
        logger.error(f"Недостаточно данных в state: user_id={user_id}, email={email}, months={months}")
        await message.reply("❌ Ошибка: данные не найдены. Попробуйте начать заново.")
        await state.finish()
        return

    telegram = f"https://t.me/{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    caption = f"📥 Новый платёж на проверку:\n\n🆔 User ID: {user_id}\n📧 Email: {obfuscate_email(email)}\n👤 Telegram: {telegram}\n📅 Выбранный тариф: {months} мес"

    try:
        for admin_id in ADMIN_IDS:
            if message.photo:
                await bot.send_photo(admin_id, message.photo[-1].file_id, caption=caption, reply_markup=get_confirmation_buttons(user_id))
            elif message.document:
                await bot.send_document(admin_id, message.document.file_id, caption=caption, reply_markup=get_confirmation_buttons(user_id))
            else:
                await bot.send_message(admin_id, caption + f"\n\n📄 Текст:\n{message.text}", reply_markup=get_confirmation_buttons(user_id))
        await message.reply("🧾 Спасибо! Мы передали данные администратору. ⏳ Ожидайте решения.")
        logger.info(f"Чек отправлен админу: user_id={user_id}, months={months}")
    except Exception as e:
        logger.error(f"Ошибка при отправке чека админу: {e}")
        await message.reply("❌ Ошибка при отправке чека. Попробуйте снова.")
    await state.finish()
@dp.callback_query_handler(lambda c: c.data.startswith("payment_approve_"))
async def confirm_payment(callback_query: types.CallbackQuery):
    logger.info(f"Получен callback: {callback_query.data}")
    parts = callback_query.data.split("_")
    user_id = int(parts[2])
    months = int(parts[3])
    user = db.get_user(user_id)
    if not user:
        logger.error(f"Пользователь с user_id={user_id} не найден")
        await callback_query.answer("Пользователь не найден.")
        return

    email = user[2]
    bonus = calculate_bonus(months)
    db.update_payment(user_id, months, bonus)

    await callback_query.message.edit_text(f"✅ Оплата подтверждена для {obfuscate_email(email)}. Добавлено: {months} мес + {bonus} мес 🎁")
    await bot.send_message(
        user_id,
        "✅ Добро пожаловать! Используйте кнопку снизу для доступа к профилю.",
        reply_markup=get_main_menu()
    )
    await bot.send_message(user_id, f"🎉 Поздравляем! Вы приобрели доступ на {months} месяцев и получили +{bonus} месяцев в подарок!")
    logger.info(f"Оплата подтверждена: user_id={user_id}, months={months}, bonus={bonus}")

@dp.callback_query_handler(lambda c: c.data.startswith("payment_reject_"))
async def reject_payment(callback_query: types.CallbackQuery):
    logger.info(f"Получен callback: {callback_query.data}")
    user_id = int(callback_query.data.split("_")[2])
    await bot.send_message(user_id, "❌ К сожалению, оплата не прошла проверку. Попробуйте ещё раз или свяжитесь с поддержкой.")
    await callback_query.answer("Оплата отклонена.")
    logger.info(f"Оплата отклонена для user_id={user_id}")

@dp.message_handler(lambda message: message.text == "👤 Профиль")
async def profile_info(message: types.Message):
    user_id = message.from_user.id
    logger.info(f"Поиск профиля для user_id: {user_id}")
    user = db.get_user(user_id)
    if user:
        user_id, _, email, telegram, books, trial_end, payment_due, paid, confirmed = user
        text = format_user_info(user_id, email, telegram, books, trial_end, payment_due, paid, confirmed) + "\n\nВы можете продлить подписку ниже:"
        await message.answer(text, reply_markup=get_profile_buttons(email), parse_mode="Markdown")
    else:
        await message.answer(
            "👋 *Вы ещё не зарегистрированы в Wordzen!*\n\n"
            "Чтобы начать пользоваться ботом и получить 3 дня бесплатного доступа, нажмите кнопку ниже:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("\u25B6\uFE0F Зарегистрироваться", callback_data="start_registration")
            )
        )

@dp.callback_query_handler(lambda c: c.data.startswith("extend_subscription_"))
async def extend_subscription(callback_query: types.CallbackQuery, state: FSMContext):
    email = callback_query.data.split("_")[-1]
    user_id = callback_query.from_user.id
    user = db.get_user(user_id)
    if user and user[2] == email:
        await callback_query.message.edit_text("💳 Выберите тариф для продления:", reply_markup=get_payment_options(user_id))
    else:
        await callback_query.message.edit_text("❗ Не удалось найти ваш аккаунт.")

@dp.callback_query_handler(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback_query: types.CallbackQuery):
    await callback_query.message.delete()

@dp.message_handler(commands=["users"])
async def list_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для этой команды.")
        return
    users = db.get_all_users()
    text = "👥 Список пользователей:\n"
    for user in users:
        user_id, email, telegram, trial_end, paid, confirmed = user
        text += f"\n🆔 {user_id}\n📧 {obfuscate_email(email)}\n👤 {telegram}\n⏳ До: {trial_end}\n💰 Месяцев: {paid}\n✅ Оплачен: {'Да' if confirmed else 'Нет'}\n---"
    await message.answer(text)

async def check_payments():
    while True:
        now = datetime.now().strftime('%Y-%m-%d')
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        for email, telegram in db.get_unpaid_users(now):
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, f"❗ Ученик не оплатил:\nEmail: {obfuscate_email(email)}\nTelegram: {telegram}")

        for email, telegram in db.get_users_near_trial_end(tomorrow):
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, f"⏰ Завтра заканчивается триал у:\nEmail: {obfuscate_email(email)}\nTelegram: {telegram}")
            try:
                await bot.send_message(telegram, f"⏳ Завтра заканчивается ваш пробный период в Wordzen. Оплатите подписку: {CARD_NUMBER}")
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
