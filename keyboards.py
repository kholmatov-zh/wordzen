from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

def get_main_menu():
    return ReplyKeyboardMarkup(resize_keyboard=True).add(
        KeyboardButton("👤 Аккаунт"),
        KeyboardButton("👤 Профиль")  # Новая кнопка
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

def get_account_buttons(email):
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("💳 Оплатить", callback_data=f"payment_check_{email}"),
        InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")
    )

def get_profile_buttons(email):  # Новая клавиатура для профиля
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("💳 Продлить подписку", callback_data=f"extend_subscription_{email}"),
        InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")
    )
