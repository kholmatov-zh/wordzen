import os
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from keep_alive import keep_alive

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

main_menu = ReplyKeyboardMarkup(resize_keyboard=True)
main_menu.add(KeyboardButton("👤 Аккаунт"))



# Конфигурация из Replit Secrets
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_LINK = "https://t.me/your_channel"
CARD_NUMBER = "1234 5678 9012 3456"

bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# SQLite база данных
conn = sqlite3.connect("users.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, 
                    email TEXT, 
                    telegram TEXT, 
                    books TEXT,
                    trial_end TEXT,
                    payment_due TEXT,
                    paid_months INTEGER DEFAULT 0,
                    payment_confirmed INTEGER DEFAULT 0)''')
conn.commit()

# Состояния пользователя
class UserState(StatesGroup):
    email = State()
    telegram = State()
    books = State()
    payment = State()

# /start приветствие с картинкой
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
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
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("\u25B6\uFE0F Продолжить", callback_data="start_registration")
            )
        )

@dp.callback_query_handler(lambda c: c.data == "start_registration")
async def start_registration(callback_query: types.CallbackQuery):
    await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
    await bot.send_message(callback_query.from_user.id, "\U0001F4E7 Введите ваш email:")
    await UserState.email.set()

@dp.message_handler(state=UserState.email)
async def get_email(message: types.Message, state: FSMContext):
    await state.update_data(email=message.text)
    await bot.send_message(message.chat.id, "Отправьте ссылку на ваш Telegram-аккаунт:")
    await UserState.telegram.set()

@dp.message_handler(state=UserState.telegram)
async def get_telegram(message: types.Message, state: FSMContext):
    await state.update_data(telegram=message.text)
    await state.update_data(books=[])

    books = ["Книга 1", "Книга 2", "Книга 3", "Книга 4"]
    markup = InlineKeyboardMarkup(row_width=2)
    for book in books:
        markup.add(InlineKeyboardButton(book, callback_data=f"book_{book}"))
    markup.add(InlineKeyboardButton("\U0001F4E6 Готово", callback_data='confirm_books'))

    await message.answer("\U0001F4DA Вот список книг. Выберите до 3 штук:", reply_markup=markup)
    await UserState.books.set()

@dp.callback_query_handler(lambda c: c.data.startswith('book_'), state=UserState.books)
async def choose_books(callback_query: types.CallbackQuery, state: FSMContext):
    book = callback_query.data[5:]
    user_data = await state.get_data()
    chosen_books = user_data.get('books', []) or []

    if book in chosen_books:
        chosen_books.remove(book)
    elif len(chosen_books) < 3:
        chosen_books.append(book)
    else:
        await callback_query.answer("Можно выбрать максимум 3 книги.")
        return

    await state.update_data(books=chosen_books)

    all_books = ["Книга 1", "Книга 2", "Книга 3", "Книга 4"]
    markup = InlineKeyboardMarkup(row_width=2)
    for b in all_books:
        prefix = "\u2705 " if b in chosen_books else ""
        markup.add(InlineKeyboardButton(prefix + b, callback_data=f"book_{b}"))
    markup.add(InlineKeyboardButton("\U0001F4E6 Готово", callback_data='confirm_books'))

    selected_text = (
        "\U0001F4DA *Вы выбрали:*\n" + "\n".join([f"• {b}" for b in chosen_books])
        if chosen_books else "Вы пока ничего не выбрали."
    )

    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=selected_text + "\n\nВы можете выбрать до 3 книг:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@dp.callback_query_handler(lambda c: c.data == 'confirm_books', state=UserState.books)
async def confirm_books(callback_query: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    email = user_data['email']
    telegram = user_data['telegram']
    books = ', '.join(user_data.get('books', []))
    trial_end = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
    payment_due = trial_end

    cursor.execute(
        "INSERT INTO users (email, telegram, books, trial_end, payment_due) VALUES (?, ?, ?, ?, ?)",
        (email, telegram, books, trial_end, payment_due)
    )
    conn.commit()

    text = (
        f"📝 *Ваша регистрация завершена!* 🎉\n\n"
        f"📧 Email: `{email}`\n"
        f"👤 Telegram: `{telegram}`\n"
        f"📚 Книги: {books or 'не выбрано'}\n"
        f"⏳ Пробный доступ до: *{trial_end}*\n\n"
        f"💳 Чтобы сохранить доступ, нажмите кнопку оплатить ниже и отправьте чек об оплате."
    )

    buttons = InlineKeyboardMarkup(row_width=1)
    buttons.add(
        InlineKeyboardButton("✅ Перейти в канал", url=CHANNEL_LINK),
        InlineKeyboardButton("💳 Оплатить", callback_data="payment_options")
    )
@dp.callback_query_handler(lambda c: c.data == "payment_options")
async def show_tariffs(callback_query: types.CallbackQuery):
    tariffs = InlineKeyboardMarkup(row_width=1)
    tariffs.add(
        InlineKeyboardButton("📅 1 месяц — 100₽", callback_data="pay_1"),
        InlineKeyboardButton("📅 3 месяца — 300₽ +1 мес 🎁", callback_data="pay_3"),
        InlineKeyboardButton("📅 6 месяцев — 600₽ +2 мес 🎁", callback_data="pay_6")
    )
    await callback_query.message.edit_text("💳 Выберите тариф:", reply_markup=tariffs)

  @dp.callback_query_handler(lambda c: c.data.startswith("pay_"))
async def start_payment(callback_query: types.CallbackQuery, state: FSMContext):
    months = int(callback_query.data.split("_")[1])
    email = None

    # Получаем email пользователя
    cursor.execute("SELECT email FROM users WHERE telegram = ?", (f"https://t.me/{callback_query.from_user.username}",))
    row = cursor.fetchone()
    if row:
        email = row[0]
        await state.update_data(email=email, months=months)
        await UserState.payment.set()

        await bot.send_message(
            callback_query.from_user.id,
            f"💳 Для оплаты выбрано: *{months} мес.*\n"
            f"Номер карты: `{CARD_NUMBER}`\n\n"
            f"📸 Отправьте чек сюда после оплаты. Проверка — до 30 минут.",
            parse_mode="Markdown"
        )
    else:
        await bot.send_message(callback_query.from_user.id, "❗ Не удалось найти ваш email в базе.")
@dp.callback_query_handler(lambda c: c.data.startswith("payment_approve_"))
async def confirm_payment_with_bonus(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = int(callback_query.data.split('_')[-1])

    cursor.execute("SELECT email FROM users WHERE telegram LIKE ?", (f"%{user_id}%",))
    row = cursor.fetchone()
    if not row:
        await callback_query.answer("Пользователь не найден.")
        return

    email = row[0]
    # Попробуем получить данные о выбранном тарифе
    months = 1  # по умолчанию
    bonus = 0

    # Если ты хочешь точно передавать тариф — храни его в БД или FSM

    # Простейшая логика бонусов:
    if months == 3:
        bonus = 1
    elif months == 6:
        bonus = 2

    total = months + bonus

    cursor.execute(
        "UPDATE users SET paid_months = paid_months + ?, payment_confirmed = 1 WHERE email = ?",
        (total, email)
    )
    conn.commit()

    await bot.send_message(callback_query.message.chat.id, f"✅ Оплата подтверждена для {email}. Добавлено: {months} мес + {bonus} мес 🎁")
    await bot.send_message(
    callback_query.from_user.id,
    "✅ Добро пожаловать! Используйте кнопку снизу для доступа к аккаунту.",
    reply_markup=main_menu
)
    cursor.execute("SELECT telegram FROM users WHERE email = ?", (email,))
    tg = cursor.fetchone()[0]
    await bot.send_message(tg, f"🎉 Поздравляем! Вы приобрели доступ на {months} месяцев и получили +{bonus} месяцев в подарок!")

    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=buttons
    )

    await state.finish()

@dp.message_handler(commands=['ping'])
async def ping(message: types.Message):
    await message.answer("✅ Бот работает")



@dp.callback_query_handler(lambda c: c.data.startswith('payment_check_'))
async def ask_payment(callback_query: types.CallbackQuery, state: FSMContext):
    email = callback_query.data.split('_')[-1]

    await state.update_data(email=email)
    await UserState.payment.set()

    await bot.send_message(
        callback_query.from_user.id,
        f"💳 Номер карты для оплаты: `{CARD_NUMBER}`\n\n"
        "📸 После оплаты отправьте сюда скриншот чека.\n"
        "⏳ Проверка занимает до *30 минут*.",
        parse_mode="Markdown"
    )

    await UserState.payment.set()
    async with FSMContext(callback_query.from_user.id, callback_query.from_user.id, dp.storage) as state:
        await state.update_data(email=email)
    async with FSMContext(callback_query.from_user.id, callback_query.from_user.id, dp.storage) as state:
        await state.update_data(email=email)

@dp.message_handler(state=UserState.payment, content_types=types.ContentType.ANY)
async def receive_any_payment(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    email = user_data.get('email', 'неизвестно')
    telegram = message.from_user.username or message.from_user.full_name or "не указано"

    caption = f"📥 Новый платёж на проверку:\n\n📧 Email: {email}\n👤 Telegram: @{telegram}"

    # Кнопки подтверждения
    markup = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ Подтвердить", callback_data=f'payment_approve_{message.from_user.id}'),
        InlineKeyboardButton("❌ Отклонить", callback_data=f'payment_reject_{message.from_user.id}')
    )

    # Отправляем админу
    try:
        if message.content_type == "photo":
            await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption, reply_markup=markup)
        elif message.content_type == "document":
            await bot.send_document(ADMIN_ID, message.document.file_id, caption=caption, reply_markup=markup)
        elif message.content_type == "text":
            await bot.send_message(ADMIN_ID, caption + f"\n\n📄 Текст:\n{message.text}", reply_markup=markup)
        else:
            await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
            await bot.send_message(ADMIN_ID, caption, reply_markup=markup)
    except Exception as e:
        print("Ошибка отправки админу:", e)

    await message.reply("🧾 Спасибо! Мы передали данные администратору. ⏳ Ожидайте решения.")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith('payment_approve_'))
async def approve_payment(callback_query: types.CallbackQuery):
            user_id = int(callback_query.data.split('_')[-1])
            await bot.send_message(user_id, "✅ Оплата подтверждена! Доступ открыт. Спасибо 🙌")
            await bot.answer_callback_query(callback_query.id, "Оплата подтверждена!")

@dp.callback_query_handler(lambda c: c.data.startswith('payment_reject_'))
async def reject_payment(callback_query: types.CallbackQuery):
            user_id = int(callback_query.data.split('_')[-1])
            await bot.send_message(user_id, "❌ К сожалению, оплата не прошла проверку. Попробуйте ещё раз или свяжитесь с поддержкой.")
            await bot.answer_callback_query(callback_query.id, "Оплата отклонена.")


# Ежедневная проверка неоплат + напоминание за 1 день до конца
async def check_payments():
    while True:
        now = datetime.now().strftime('%Y-%m-%d')
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        cursor.execute("SELECT email, telegram FROM users WHERE payment_due = ? AND payment_confirmed = 0", (now,))
        unpaid_users = cursor.fetchall()
        for email, telegram in unpaid_users:
            await bot.send_message(ADMIN_ID, f"❗ Ученик не оплатил:\nEmail: {email}\nTelegram: {telegram}")

        cursor.execute("SELECT email, telegram FROM users WHERE trial_end = ? AND payment_confirmed = 0", (tomorrow,))
        soon_ending = cursor.fetchall()
        for email, telegram in soon_ending:
            await bot.send_message(ADMIN_ID, f"⏰ Завтра заканчивается триал у:\nEmail: {email}\nTelegram: {telegram}")
            try:
                await bot.send_message(telegram, "⏳ Завтра заканчивается ваш пробный период в Wordzen. Не забудьте оплатить, чтобы не потерять доступ!\nНомер карты: " + CARD_NUMBER)
            except:
                pass

        await asyncio.sleep(86400)

# Команда для админа — список всех пользователей
@dp.message_handler(commands=['users'])
async def list_users(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    cursor.execute("SELECT email, telegram, trial_end, paid_months, payment_confirmed FROM users")
    users = cursor.fetchall()
    text = "👥 Список пользователей:\n"
    for user in users:
        email, telegram, trial_end, paid, confirmed = user
        text += f"\n📧 {email}\n👤 {telegram}\n⏳ До: {trial_end}\n💰 Месяцев: {paid}\n✅ Оплачен: {'Да' if confirmed else 'Нет'}\n---"
    await message.answer(text)


@dp.message_handler(lambda message: message.text == "👤 Аккаунт")
async def account_info(message: types.Message):
    telegram_link = f"https://t.me/{message.from_user.username}" if message.from_user.username else message.from_user.full_name

    cursor.execute("SELECT email, books, trial_end, paid_months, payment_confirmed FROM users WHERE telegram = ?", (telegram_link,))
    user = cursor.fetchone()

    if user:
        email, books, trial_end, paid, confirmed = user
        text = (
            f"👤 *Ваш аккаунт:*\n"
            f"📧 Email: `{email}`\n"
            f"📚 Книги: {books or 'не выбрано'}\n"
            f"⏳ Доступ до: *{trial_end}*\n"
            f"💰 Оплачено месяцев: {paid}\n"
            f"✅ Статус: {'Оплачено' if confirmed else 'Пробный/не оплачен'}"
        )

        buttons = InlineKeyboardMarkup(row_width=2)
        buttons.add(
            InlineKeyboardButton("💳 Оплатить", callback_data=f'payment_check_{email}'),
            InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')
        )

        await message.answer(text, reply_markup=buttons, parse_mode="Markdown")
    else:
        await message.answer("❗️ Вы ещё не зарегистрированы.")

@dp.callback_query_handler(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback_query: types.CallbackQuery):
    await callback_query.message.delete()


# Запуск
if __name__ == "__main__":
    keep_alive()
    logging.basicConfig(level=logging.INFO)
    loop = asyncio.get_event_loop()
    loop.create_task(check_payments())
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
