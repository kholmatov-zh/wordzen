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

# Конфигурация
logging.basicConfig(level=logging.INFO)
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
            email TEXT UNIQUE,
            telegram TEXT,
            books TEXT,
            trial_end TEXT,
            payment_due TEXT,
            paid_months INTEGER DEFAULT 0,
            payment_confirmed INTEGER DEFAULT 0
        )''')
        self.conn.commit()

    def add_user(self, email, telegram, books):
        trial_end = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
        self.cursor.execute(
            "INSERT OR IGNORE INTO users (email, telegram, books, trial_end, payment_due) VALUES (?, ?, ?, ?, ?)",
            (email, telegram, books, trial_end, trial_end)
        )
        self.conn.commit()

    def get_user(self, telegram):
        self.cursor.execute("SELECT * FROM users WHERE telegram = ?", (telegram,))
        return self.cursor.fetchone()

    def update_payment(self, email, months, bonus=0):
        total = months + bonus
        self.cursor.execute(
            "UPDATE users SET paid_months = paid_months + ?, payment_confirmed = 1, payment_due = ? WHERE email = ?",
            (total, (datetime.now() + timedelta(days=30 * total)).strftime('%Y-%m-%d'), email)
        )
        self.conn.commit()

    def get_unpaid_users(self, date):
        self.cursor.execute("SELECT email, telegram FROM users WHERE payment_due = ? AND payment_confirmed = 0", (date,))
        return self.cursor.fetchall()

    def get_users_near_trial_end(self, date):
        self.cursor.execute("SELECT email, telegram FROM users WHERE trial_end = ? AND payment_confirmed = 0", (date,))
        return self.cursor.fetchall()

    def get_all_users(self):
        self.cursor.execute("SELECT email, telegram, trial_end, paid_months, payment_confirmed FROM users")
        return self.cursor.fetchall()

db = Database()

# Клавиатуры
def get_main_menu():
    return ReplyKeyboardMarkup(resize_keyboard=True).add(
        KeyboardButton("👤 Профиль")  # Оставляем только одну кнопку
    )

def get_start_button():
    return InlineKeyboardMarkup().add(InlineKeyboardButton("\u25B6\uFE0F Продолжить", callback_data="start_registration"))

def get_books_keyboard(selected_books=[]):
    books = ["Книга 1", "Книга 2", "Книга 3", "Книга 4"]
    markup = InlineKeyboardMarkup(row_width=2)
    for book in books:
        prefix = "\u2705 " if book in selected_books else ""
        markup.add(InlineKeyboardButton(prefix + book, callback_data=f"book_{book}"))
    markup.add(InlineKeyboardButton("\U0001F4E6 Готово", callback_data="confirm_books"))
    return markup

def get_payment_options():
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("📅 1 месяц — 100₽", callback_data="pay_1"),
        InlineKeyboardButton("📅 3 месяца — 300₽ +1 мес 🎁", callback_data="pay_3")
    )

def get_confirmation_buttons(user_id):
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ Подтвердить", callback_data=f"payment_approve_{user_id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"payment_reject_{user_id}")
    )

def get_profile_buttons(email):
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("💳 Продлить подписку", callback_data=f"extend_subscription_{email}"),
        InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")
    )

# Вспомогательные функции
def format_user_info(email, telegram, books, trial_end, payment_due, paid, confirmed):
    return (
        f"👤 *Ваш профиль:*\n"
        f"📧 Email: `{email}`\n"
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
        logging.error(f"Ошибка в /start: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")

@dp.callback_query_handler(lambda c: c.data == "start_registration")
async def start_registration(callback_query: types.CallbackQuery):
    await callback_query.message.delete()
    await callback_query.message.answer("\U0001F4E7 Введите ваш email:")
    await UserState.email.set()

@dp.message_handler(state=UserState.email)
async def get_email(message: types.Message, state: FSMContext):
    await state.update_data(email=message.text)
    await message.answer("Отправьте ссылку на ваш Telegram-аккаунт:")
    await UserState.telegram.set()

@dp.message_handler(state=UserState.telegram)
async def get_telegram(message: types.Message, state: FSMContext):
    await state.update_data(telegram=message.text)
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
    email = user_data["email"]
    telegram = user_data["telegram"]
    books = ", ".join(user_data.get("books", []))
    db.add_user(email, telegram, books)

    text = (
        f"📝 *Ваша регистрация завершена!* 🎉\n\n"
        f"📧 Email: `{email}`\n"
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
    await callback_query.message.edit_text("💳 Выберите тариф:", reply_markup=get_payment_options())

@dp.callback_query_handler(lambda c: c.data.startswith("pay_"))
async def start_payment(callback_query: types.CallbackQuery, state: FSMContext):
    months = int(callback_query.data.split("_")[1])
    telegram = f"https://t.me/{callback_query.from_user.username}" if callback_query.from_user.username else callback_query.from_user.full_name
    user = db.get_user(telegram)
    if user:
        await state.update_data(email=user[1], months=months)
        await callback_query.message.answer(
            f"💳 Вы выбрали тариф: *{months} мес.*\n"
            f"Номер карты: `{CARD_NUMBER}`\n\n"
            f"📸 После оплаты отправьте сюда чек. Проверка — до 30 мин.",
            parse_mode="Markdown"
        )
        await UserState.payment.set()
    else:
        await callback_query.message.answer("❗ Не удалось найти ваш аккаунт.")

@dp.message_handler(state=UserState.payment, content_types=types.ContentType.ANY)
async def receive_payment(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    email = user_data.get("email")
    telegram = f"https://t.me/{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    caption = f"📥 Новый платёж на проверку:\n\n📧 Email: {email}\n👤 Telegram: @{telegram}"

    try:
        for admin_id in ADMIN_IDS:
            if message.photo:
                await bot.send_photo(admin_id, message.photo[-1].file_id, caption=caption, reply_markup=get_confirmation_buttons(message.from_user.id))
            elif message.document:
                await bot.send_document(admin_id, message.document.file_id, caption=caption, reply_markup=get_confirmation_buttons(message.from_user.id))
            else:
                await bot.send_message(admin_id, caption + f"\n\n📄 Текст:\n{message.text}", reply_markup=get_confirmation_buttons(message.from_user.id))
        await message.reply("🧾 Спасибо! Мы передали данные администратору. ⏳ Ожидайте решения.")
    except Exception as e:
        logging.error(f"Ошибка при отправке чека админу: {e}")
        await message.reply("❌ Ошибка при отправке чека. Попробуйте снова.")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("payment_approve_"))
async def confirm_payment(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = int(callback_query.data.split("_")[-1])
    telegram = f"https://t.me/{callback_query.from_user.username}" if callback_query.from_user.username else callback_query.from_user.full_name
    user = db.get_user(telegram)
    if not user:
        await callback_query.answer("Пользователь не найден.")
        return

    email = user[1]
    user_data = await state.get_data()
    months = user_data.get("months", 1)
    bonus = calculate_bonus(months)
    db.update_payment(email, months, bonus)

    await callback_query.message.edit_text(f"✅ Оплата подтверждена для {email}. Добавлено: {months} мес + {bonus} мес 🎁")
    await bot.send_message(
        user_id,
        "✅ Добро пожаловать! Используйте кнопку снизу для доступа к профилю.",
        reply_markup=get_main_menu()
    )
    await bot.send_message(telegram, f"🎉 Поздравляем! Вы приобрели доступ на {months} месяцев и получили +{bonus} месяцев в подарок!")

@dp.callback_query_handler(lambda c: c.data.startswith("payment_reject_"))
async def reject_payment(callback_query: types.CallbackQuery):
    user_id = int(callback_query.data.split("_")[-1])
    await bot.send_message(user_id, "❌ К сожалению, оплата не прошла проверку. Попробуйте ещё раз или свяжитесь с поддержкой.")
    await callback_query.answer("Оплата отклонена.")

@dp.message_handler(lambda message: message.text == "👤 Профиль")
async def profile_info(message: types.Message):
    telegram = f"https://t.me/{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    user = db.get_user(telegram)
    if user:
        email, _, books, trial_end, payment_due, paid, confirmed = user
        text = format_user_info(email, telegram, books, trial_end, payment_due, paid, confirmed) + "\n\nВы можете продлить подписку ниже:"
        await message.answer(text, reply_markup=get_profile_buttons(email), parse_mode="Markdown")
    else:
        await message.answer("❗️ Вы ещё не зарегистрированы.")

@dp.callback_query_handler(lambda c: c.data.startswith("extend_subscription_"))
async def extend_subscription(callback_query: types.CallbackQuery, state: FSMContext):
    email = callback_query.data.split("_")[-1]
    telegram = f"https://t.me/{callback_query.from_user.username}" if callback_query.from_user.username else callback_query.from_user.full_name
    user = db.get_user(telegram)
    if user and user[1] == email:
        await callback_query.message.edit_text("💳 Выберите тариф для продления:", reply_markup=get_payment_options())
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
        email, telegram, trial_end, paid, confirmed = user
        text += f"\n📧 {email}\n👤 {telegram}\n⏳ До: {trial_end}\n💰 Месяцев: {paid}\n✅ Оплачен: {'Да' if confirmed else 'Нет'}\n---"
    await message.answer(text)

async def check_payments():
    while True:
        now = datetime.now().strftime('%Y-%m-%d')
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        for email, telegram in db.get_unpaid_users(now):
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, f"❗ Ученик не оплатил:\nEmail: {email}\nTelegram: {telegram}")

        for email, telegram in db.get_users_near_trial_end(tomorrow):
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, f"⏰ Завтра заканчивается триал у:\nEmail: {email}\nTelegram: {telegram}")
            try:
                await bot.send_message(telegram, f"⏳ Завтра заканчивается ваш пробный период в Wordzen. Оплатите подписку: {CARD_NUMBER}")
            except Exception as e:
                logging.error(f"Ошибка уведомления {telegram}: {e}")
        await asyncio.sleep(86400)

# Запуск
if __name__ == "__main__":
    keep_alive()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(bot.delete_webhook(drop_pending_updates=True))
    loop.create_task(check_payments())
    executor.start_polling(dp, skip_updates=True)
