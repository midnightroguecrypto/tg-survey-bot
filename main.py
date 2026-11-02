import os
import sqlite3
import telebot
from telebot import types
from dotenv import load_dotenv

# ====== НАСТРОЙКИ ======
load_dotenv() 

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Проверь файл .env")


_admin_raw = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = [int(x) for x in _admin_raw.split(",") if x.strip().isdigit()]

WELCOME_PHOTO = os.getenv("WELCOME_PHOTO", "").strip()

WELCOME_CAPTION = "Привет 🙂 Тут небольшой опрос, займёт меньше минуты."
WELCOME_TEXT = "Напиши своё имя "

bot = telebot.TeleBot(BOT_TOKEN)

# ====== БАЗА ДАННЫХ ======
conn = sqlite3.connect("survey.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_user_id INTEGER,
    name TEXT,
    q1 TEXT,
    q2 TEXT,
    q3 TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS state (
    tg_user_id INTEGER PRIMARY KEY,
    step INTEGER DEFAULT 0,
    name TEXT,
    q1 TEXT,
    q2 TEXT,
    q3 TEXT
)
""")

# Таблица для хранения message_id сообщений бота в текущей сессии
cur.execute("""
CREATE TABLE IF NOT EXISTS session_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_user_id INTEGER,
    chat_id INTEGER,
    message_id INTEGER
)
""")
conn.commit()

# ====== ВОПРОСЫ ======
QUESTIONS = {
    "q1": "Нравятся ли тебе мероприятия в школе?",
    "q2": "А сам(а) умеешь их создавать?",
    "q3": "Хочешь научиться это делать?",
}

# ====== ХЕЛПЕРЫ ======
def get_state(user_id):
    cur.execute("SELECT step, name, q1, q2, q3 FROM state WHERE tg_user_id = ?", (user_id,))
    return cur.fetchone()

def ensure_state(user_id):
    if not get_state(user_id):
        cur.execute("INSERT INTO state (tg_user_id, step) VALUES (?, 0)", (user_id,))
        conn.commit()

def set_state(user_id, **kwargs):
    ensure_state(user_id)
    for k, v in kwargs.items():
        cur.execute(f"UPDATE state SET {k} = ? WHERE tg_user_id = ?", (v, user_id))
    conn.commit()

def reset_state(user_id):
    cur.execute("""
        UPDATE state SET step = 1, name = NULL, q1 = NULL, q2 = NULL, q3 = NULL
        WHERE tg_user_id = ?
    """, (user_id,))
    conn.commit()

def save_msg(user_id, chat_id, message_id):
    """Запоминаем id отправленного сообщения, чтобы потом удалить."""
    cur.execute(
        "INSERT INTO session_messages (tg_user_id, chat_id, message_id) VALUES (?, ?, ?)",
        (user_id, chat_id, message_id),
    )
    conn.commit()

def clear_session_messages(user_id):
    """Удаляем все сообщения бота, отправленные в текущей сессии."""
    cur.execute("SELECT chat_id, message_id FROM session_messages WHERE tg_user_id = ?", (user_id,))
    rows = cur.fetchall()
    for chat_id, message_id in rows:
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            # сообщение старше 48ч или уже удалено — просто пропускаем
            pass
    cur.execute("DELETE FROM session_messages WHERE tg_user_id = ?", (user_id,))
    conn.commit()

def send_and_remember(user_id, chat_id, text, **kwargs):
    """Отправить сообщение и сразу запомнить его id."""
    msg = bot.send_message(chat_id, text, **kwargs)
    save_msg(user_id, chat_id, msg.message_id)
    return msg

def send_photo_and_remember(user_id, chat_id, photo, **kwargs):
    msg = bot.send_photo(chat_id, photo, **kwargs)
    save_msg(user_id, chat_id, msg.message_id)
    return msg

def edit_and_remember(user_id, chat_id, message_id, text, **kwargs):
    """Редактируем сообщение — его id уже сохранён ранее, повторно не сохраняем."""
    try:
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, **kwargs)
    except Exception as e:
        print(f"[WARN] Не удалось отредактировать сообщение: {e}")

def yes_no_kb(qkey):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Да 👍", callback_data=f"{qkey}:Да"),
        types.InlineKeyboardButton("Нет 👎", callback_data=f"{qkey}:Нет"),
    )
    return kb

def finish_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Передать телефон дальше 📲", callback_data="next_person"))
    kb.add(types.InlineKeyboardButton("Глянуть статистику 📊", callback_data="stats"))
    return kb

def photo_is_available():
    if not WELCOME_PHOTO:
        return False
    if WELCOME_PHOTO.startswith("http://") or WELCOME_PHOTO.startswith("https://"):
        return True
    return os.path.isfile(WELCOME_PHOTO)

def send_welcome(user_id, chat_id):
    """Фото с подписью + сразу просьба написать имя. Оба сообщения запоминаем."""
    sent_photo = False

    if photo_is_available():
        try:
            with open(WELCOME_PHOTO, "rb") if not WELCOME_PHOTO.startswith("http") else _nullcontext() as f:
                if f is not None:
                    send_photo_and_remember(user_id, chat_id, f, caption=WELCOME_CAPTION)
                else:
                    send_photo_and_remember(user_id, chat_id, WELCOME_PHOTO, caption=WELCOME_CAPTION)
            sent_photo = True
        except Exception as e:
            print(f"[WARN] Не удалось отправить фото: {e}")

    if not sent_photo:
        send_and_remember(user_id, chat_id, WELCOME_CAPTION)

    send_and_remember(user_id, chat_id, WELCOME_TEXT)

class _nullcontext:
    def __enter__(self): return None
    def __exit__(self, *a): return False

# ====== /start ======
@bot.message_handler(commands=["start"])
def cmd_start(message):
    user_id = message.from_user.id
    ensure_state(user_id)
    # Если вдруг остались сообщения от прошлой сессии — убираем их
    clear_session_messages(user_id)
    reset_state(user_id)
    send_welcome(user_id, message.chat.id)

# ====== Обработка текста (ввод имени) ======
@bot.message_handler(content_types=["text"])
def handle_text(message):
    user_id = message.from_user.id
    ensure_state(user_id)
    step, *_ = get_state(user_id)

    if step != 1:
        send_and_remember(
            user_id, message.chat.id,
            "Слушай, чтобы начать — нажми /start 🙂",
        )
        return

    name = (message.text or "").strip()
    if not name or len(name) > 50:
        send_and_remember(
            user_id, message.chat.id,
            "Напиши нормальное имя, до 50 символов 🙂",
        )
        return

    set_state(user_id, name=name, step=2)

    send_and_remember(
        user_id, message.chat.id,
        f"Окей, {name}! 👋\n\n{QUESTIONS['q1']}",
        reply_markup=yes_no_kb("q1"),
    )

# ====== Обработка inline-кнопок ======
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    data = call.data
    ensure_state(user_id)

    # ---- Передать телефон дальше ----
    if data == "next_person":
        # 1. Чистим все сообщения прошлой сессии
        clear_session_messages(user_id)
        # 2. Сбрасываем состояние
        reset_state(user_id)
        # 3. Отправляем приветствие новому человеку
        send_welcome(user_id, call.message.chat.id)
        bot.answer_callback_query(call.id)
        return

    # ---- Статистика ----
    if data == "stats":
        if ADMIN_IDS and user_id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "Сори, статистику видит только админ 🙈", show_alert=True)
            return
        send_stats(call.message.chat.id)
        bot.answer_callback_query(call.id)
        return

    # ---- Ответы на вопросы ----
    if ":" in data:
        qkey, answer = data.split(":", 1)
        if qkey not in QUESTIONS:
            bot.answer_callback_query(call.id)
            return

        set_state(user_id, **{qkey: answer})

        # Редактируем сообщение с вопросом (его id уже сохранён в session_messages)
        edit_and_remember(
            user_id,
            call.message.chat.id,
            call.message.message_id,
            f"{QUESTIONS[qkey]}\n\nТвой ответ: <b>{answer}</b>",
            parse_mode="HTML",
        )

        if qkey == "q1":
            set_state(user_id, step=3)
            send_and_remember(
                user_id, call.message.chat.id,
                QUESTIONS["q2"], reply_markup=yes_no_kb("q2"),
            )
        elif qkey == "q2":
            set_state(user_id, step=4)
            send_and_remember(
                user_id, call.message.chat.id,
                QUESTIONS["q3"], reply_markup=yes_no_kb("q3"),
            )
        elif qkey == "q3":
            st = get_state(user_id)
            cur.execute(
                "INSERT INTO responses (tg_user_id, name, q1, q2, q3) VALUES (?, ?, ?, ?, ?)",
                (user_id, st[1], st[2], st[3], st[4]),
            )
            conn.commit()
            set_state(user_id, step=0)

            cur.execute("SELECT COUNT(*) FROM responses")
            total = cur.fetchone()[0]

            send_and_remember(
                user_id, call.message.chat.id,
                f"Красавчик, {st[1]}! 🙌 Опрос пройден.\n\n"
                f"На этом телефоне уже прошли: <b>{total}</b> чел.",
                parse_mode="HTML",
                reply_markup=finish_kb(),
            )

        bot.answer_callback_query(call.id)

# ====== Статистика ======
def send_stats(chat_id):
    cur.execute("SELECT q1, q2, q3 FROM responses WHERE q1 IS NOT NULL AND q2 IS NOT NULL AND q3 IS NOT NULL")
    rows = cur.fetchall()
    total = len(rows)

    if total == 0:
        bot.send_message(chat_id, "Пока никто не проходил, статистики нет 🤷")
        return

    def count(idx):
        d = {"Да": 0, "Нет": 0}
        for r in rows:
            if r[idx] in d:
                d[r[idx]] += 1
        return d

    q1, q2, q3 = count(0), count(1), count(2)

    def pct(n):
        return f"{n} ({n * 100 // total}%)"

    text = (
        f"📊 <b>Вот что получилось</b>\n"
        f"Всего прошли: <b>{total}</b> чел.\n\n"
        f"<b>{QUESTIONS['q1']}</b>\n"
        f"  Да: {pct(q1['Да'])}\n"
        f"  Нет: {pct(q1['Нет'])}\n\n"
        f"<b>{QUESTIONS['q2']}</b>\n"
        f"  Да: {pct(q2['Да'])}\n"
        f"  Нет: {pct(q2['Нет'])}\n\n"
        f"<b>{QUESTIONS['q3']}</b>\n"
        f"  Да: {pct(q3['Да'])}\n"
        f"  Нет: {pct(q3['Нет'])}\n"
    )
    bot.send_message(chat_id, text, parse_mode="HTML")

