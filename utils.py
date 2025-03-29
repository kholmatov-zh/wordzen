from datetime import datetime, timedelta

def format_user_info(email, books, trial_end, paid, confirmed):
    return (
        f"👤 *Ваш аккаунт:*\n"
        f"📧 Email: `{email}`\n"
        f"📚 Книги: {books or 'не выбрано'}\n"
        f"⏳ Доступ до: *{trial_end}*\n"
        f"💰 Оплачено месяцев: {paid}\n"
        f"✅ Статус: {'Оплачено' if confirmed else 'Пробный/не оплачен'}"
    )

def calculate_bonus(months):
    return 1 if months == 3 else 0  # Бонус только для 3 месяцев
