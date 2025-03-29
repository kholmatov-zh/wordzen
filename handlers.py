import os
import logging
from aiogram import Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from .database import Database
from .keyboards import *
from .utils import format_user_info, calculate_bonus
from datetime import datetime, timedelta

TOKEN = os.getenv("TOKEN")
ADMIN_IDS = [int(admin_id) for admin_id in os.getenv("ADMIN_IDS", "").split(",") if admin_id]  # Список ID админов
CHANNEL_LINK = "https://t.me/your_channel"
CARD_NUMBER = "1234 5678 9012 3456"

class UserState(StatesGroup):
    email = State()
    telegram = State()
    books = State()
    payment = State()

db = Database()

async def start(message: types.Message):
    try:
        with open("wordzen_logo.jpg", "rb") as photo:
            await message.bot.send_photo(
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

async def start_registration(callback_query: types.CallbackQuery):
    await callback_query.message.delete()
    await callback_query.message.answer("\U0001F4E7 Введите ваш email:")
    await UserState.email.set()

async def get_email(message: types.Message, state: FSMContext):
    await state.update_data(email=message.text)
    await message.answer("Отправьте ссылку на ваш Telegram-аккаунт:")
    await UserState.telegram.set()

async def get_telegram(message: types.Message, state: FSMContext):
    await state.update_data(telegram=message.text)
    await state.update_data(books=[])
    await message.answer("\U0001F4DA Вот список книг. Выберите до 3 штук:", reply_markup=get_books_keyboard())
    await UserState.books.set()

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

async def show_tariffs(callback_query: types.CallbackQuery):
    await callback_query.message.edit_text("💳 Выберите тариф:", reply_markup=get_payment_options())

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

async def receive_payment(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    email = user_data.get("email")
    telegram = f"https://t.me/{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    caption = f"📥 Новый платёж на проверку:\n\n📧 Email: {email}\n👤 Telegram: @{telegram}"

    try:
        for admin_id in ADMIN_IDS:  # Отправка всем администраторам
            if message.photo:
                await message.bot.send_photo(admin_id, message.photo[-1].file_id, caption=caption, reply_markup=get_confirmation_buttons(message.from_user.id))
            elif message.document:
                await message.bot.send_document(admin_id, message.document.file_id, caption=caption, reply_markup=get_confirmation_buttons(message.from_user.id))
            else:
                await message.bot.send_message(admin_id, caption + f"\n\n📄 Текст:\n{message.text}", reply_markup=get_confirmation_buttons(message.from_user.id))
        await message.reply("🧾 Спасибо! Мы передали данные администратору. ⏳ Ожидайте решения.")
    except Exception as e:
        logging.error(f"Ошибка при отправке чека админу: {e}")
        await message.reply("❌ Ошибка при отправке чека. Попробуйте снова.")
    await state.finish()

async def confirm_payment(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = int(callback_query.data.split("_")[-1])
    telegram = f"https://t.me/{callback_query.from_user.username}" if callback_query.from_user.username else callback_query.from_user.full_name
    user = db.get_user(telegram)
    if not user:
        await callback_query.answer("Пользователь не найден.")
        return

    email = user[1]
    user_data = await state.get_data()  # Получаем данные из состояния
    months = user_data.get("months", 1)  # Предполагаем, что месяцы хранятся в состоянии
    bonus = calculate_bonus(months)
    db.update_payment(email, months, bonus)

    await callback_query.message.edit_text(f"✅ Оплата подтверждена для {email}. Добавлено: {months} мес + {bonus} мес 🎁")
    await callback_query.message.bot.send_message(
        user_id,
        "✅ Добро пожаловать! Используйте кнопку снизу для доступа к аккаунту.",
        reply_markup=get_main_menu()
    )
    await callback_query.message.bot.send_message(telegram, f"🎉 Поздравляем! Вы приобрели доступ на {months} месяцев и получили +{bonus} месяцев в подарок!")

async def reject_payment(callback_query: types.CallbackQuery):
    user_id = int(callback_query.data.split("_")[-1])
    await callback_query.message.bot.send_message(user_id, "❌ К сожалению, оплата не прошла проверку. Попробуйте ещё раз или свяжитесь с поддержкой.")
    await callback_query.answer("Оплата отклонена.")

async def account_info(message: types.Message):
    telegram = f"https://t.me/{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    user = db.get_user(telegram)
    if user:
        email, _, books, trial_end, _, paid, confirmed = user
        await message.answer(format_user_info(email, books, trial_end, paid, confirmed), reply_markup=get_account_buttons(email), parse_mode="Markdown")
    else:
        await message.answer("❗️ Вы ещё не зарегистрированы.")

async def profile_info(message: types.Message):  # Новый обработчик для профиля
    telegram = f"https://t.me/{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    user = db.get_user(telegram)
    if user:
        email, _, books, trial_end, payment_due, paid, confirmed = user
        text = (
            f"👤 *Ваш профиль:*\n"
            f"📧 Email: `{email}`\n"
            f"👤 Telegram: `{telegram}`\n"
            f"📚 Книги: {books or 'не выбрано'}\n"
            f"⏳ Пробный доступ до: *{trial_end}*\n"
            f"⏳ Подписка активна до: *{payment_due}*\n"
            f"💰 Оплачено месяцев: {paid}\n"
            f"✅ Статус: {'Оплачено' if confirmed else 'Пробный/не оплачен'}\n\n"
            "Вы можете продлить подписку ниже:"
        )
        await message.answer(text, reply_markup=get_profile_buttons(email), parse_mode="Markdown")
    else:
        await message.answer("❗️ Вы ещё не зарегистрированы.")

async def extend_subscription(callback_query: types.CallbackQuery, state: FSMContext):  # Логика продления подписки
    email = callback_query.data.split("_")[-1]
    telegram = f"https://t.me/{callback_query.from_user.username}" if callback_query.from_user.username else callback_query.from_user.full_name
    user = db.get_user(telegram)
    if user and user[1] == email:
        await callback_query.message.edit_text("💳 Выберите тариф для продления:", reply_markup=get_payment_options())
    else:
        await callback_query.message.edit_text("❗ Не удалось найти ваш аккаунт.")

async def back_to_menu(callback_query: types.CallbackQuery):
    await callback_query.message.delete()

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

async def check_payments(bot):
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

def register_handlers(dp: Dispatcher):
    dp.register_message_handler(start, commands=["start"])
    dp.register_callback_query_handler(start_registration, lambda c: c.data == "start_registration")
    dp.register_message_handler(get_email, state=UserState.email)
    dp.register_message_handler(get_telegram, state=UserState.telegram)
    dp.register_callback_query_handler(choose_books, lambda c: c.data.startswith("book_"), state=UserState.books)
    dp.register_callback_query_handler(confirm_books, lambda c: c.data == "confirm_books", state=UserState.books)
    dp.register_callback_query_handler(show_tariffs, lambda c: c.data == "payment_options")
    dp.register_callback_query_handler(start_payment, lambda c: c.data.startswith("pay_"))
    dp.register_message_handler(receive_payment, state=UserState.payment, content_types=types.ContentType.ANY)
    dp.register_callback_query_handler(confirm_payment, lambda c: c.data.startswith("payment_approve_"))
    dp.register_callback_query_handler(reject_payment, lambda c: c.data.startswith("payment_reject_"))
    dp.register_message_handler(account_info, lambda message: message.text == "👤 Аккаунт")
    dp.register_message_handler(profile_info, lambda message: message.text == "👤 Профиль")  # Новый обработчик
    dp.register_callback_query_handler(extend_subscription, lambda c: c.data.startswith("extend_subscription_"))
    dp.register_callback_query_handler(back_to_menu, lambda c: c.data == "back_to_menu")
    dp.register_message_handler(list_users, commands=["users"])
