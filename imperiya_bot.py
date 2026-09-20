"""
IMPERIYA — "Imperiyaning eng sodiq xodimi" konkurs boti
-------------------------------------------------------
Ishga tushirish:
    Windows PowerShell:  $env:BOT_TOKEN="8904776341:AAFc-O9o2VnOpGQBH0fhlg0m8nb0TCR77AM"; python bot.py
    Linux / macOS:       export BOT_TOKEN="8904776341:AAFc-O9o2VnOpGQBH0fhlg0m8nb0TCR77AM" && python bot.py

Admin buyruqlari:
    /admin            — admin panel
    /setdays N        — konkurs davomiyligini N kunga o‘rnatish (boshlanishdan hisoblanadi)
    /extend N         — konkursni N kunga uzaytirish
    /restart          — konkurs vaqtini hozirdan qayta boshlash
    /timeleft         — qolgan vaqt
"""

import html
import logging
import os
import sqlite3
from datetime import datetime, timedelta

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# =========================================================
# SOZLAMALAR
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable topilmadi.")

CHANNEL_USERNAME = "@imperiya_edu"
CHANNEL_LINK = "https://t.me/imperiya_edu"
INSTAGRAM_LINK = "https://www.instagram.com/imperiya_edu/"

ADMIN_ID = 7050215692

# Konkurs necha kun davom etishi (admin /setdays bilan o‘zgartira oladi)
DEFAULT_CONTEST_DAYS = int(os.getenv("CONTEST_DAYS", "10"))

# Har necha referral = 1 bonus ovoz
REFERRALS_PER_BONUS = 5

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "imperiya_konkurs.db")

PRIZES = [
    ("🥇", "1-o‘rin", "Smart TV"),
    ("🥈", "2-o‘rin", "Tefal"),
    ("🥉", "3-o‘rin", "Choper"),
]

CANDIDATES = [
    "Axmadjonov Sardorbek",
    "Axmedov Davron",
    "Aliboyeva Barchinoy",
    "Erkinboyev Muhammadqodir",
    "G‘aybullayeva Feruza",
    "Hakimova Nozima",
    "Menaliyeva Leniyara",
    "Muhammadjanova Xurshidabonu",
    "Diyorbek Eraliyev",
    "Ne'matillayev Jahongir",
    "Ergashev Husanboy",
    "Tursunboyeva Sevara",
    "O'monov Sardorbek",
    "Eraliyev Diyorbek",
    "Ergashev Husanboy",
    "Shohsanam Otamirzayeva",
    "Gulrux Hoshimjonova",
    "Mirzayo'ldosheva Durdonaxon",
    "G'aniyeva Yulduzxon",
    "Abdug'aniyeva Shaxnoza",
    "Yo‘ldashev Xojiakbar",
    "Abduqahhorov Diyorbek",
    "Ibragimov Sodiqjon",
    "Abduraxmonova Arofat",
    "Nematillayev Jahongir",
]

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("imperiya-bot")

# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
cursor = db.cursor()

cursor.executescript(
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        subscribed INTEGER DEFAULT 0,
        instagram_verified INTEGER DEFAULT 0,
        referrer_id INTEGER,
        referral_count INTEGER DEFAULT 0,
        points INTEGER DEFAULT 0,
        bonus_votes INTEGER DEFAULT 0,
        bonus_granted INTEGER DEFAULT 0,
        main_vote_used INTEGER DEFAULT 0,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS votes (
        vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        candidate TEXT NOT NULL,
        vote_type TEXT NOT NULL,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS referral_done (
        user_id INTEGER PRIMARY KEY,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """
)

# Eski bazadan yangilash (bonus_granted ustuni yo‘q bo‘lsa qo‘shamiz)
cols = [r["name"] for r in cursor.execute("PRAGMA table_info(users)")]
if "bonus_granted" not in cols:
    cursor.execute("ALTER TABLE users ADD COLUMN bonus_granted INTEGER DEFAULT 0")
    # Eski foydalanuvchilar uchun: hozirgi bonusni "berilgan" deb hisoblaymiz
    cursor.execute("UPDATE users SET bonus_granted = points / ?", (REFERRALS_PER_BONUS,))
db.commit()

# =========================================================
# KONKURS VAQTI
# =========================================================


def get_setting(key: str, default=None):
    row = cursor.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    cursor.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    db.commit()


def contest_start() -> datetime:
    value = get_setting("contest_start")
    if value:
        return datetime.fromisoformat(value)
    now = datetime.now()
    set_setting("contest_start", now.isoformat())
    return now


def contest_days() -> int:
    return int(get_setting("contest_days", DEFAULT_CONTEST_DAYS))


def contest_end() -> datetime:
    return contest_start() + timedelta(days=contest_days())


def contest_active() -> bool:
    return datetime.now() < contest_end()


def time_left_text() -> str:
    left = contest_end() - datetime.now()
    if left.total_seconds() <= 0:
        return "yakunlangan"
    days = left.days
    hours, rem = divmod(left.seconds, 3600)
    minutes = rem // 60
    return f"{days} kun {hours} soat {minutes} daqiqa"


# Bazani ishga tushirishda boshlanish vaqtini saqlab qo‘yamiz
contest_start()

# =========================================================
# YORDAMCHI FUNKSIYALAR
# =========================================================


def esc(text) -> str:
    return html.escape(str(text or ""))


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def save_user(user):
    cursor.execute(
        """
        INSERT INTO users (user_id, first_name, username, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            first_name = excluded.first_name,
            username = excluded.username
        """,
        (user.id, user.first_name or "", user.username or "", datetime.now().isoformat()),
    )
    db.commit()


def get_user(user_id: int):
    return cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def user_has_requirements(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["subscribed"] == 1 and row["instagram_verified"] == 1)


def vote_counts() -> list:
    """[(nomzod, ovozlar soni), ...] — ovozi bo‘yicha kamayish tartibida."""
    counts = {c: 0 for c in CANDIDATES}
    for r in cursor.execute("SELECT candidate, COUNT(*) AS n FROM votes GROUP BY candidate"):
        if r["candidate"] in counts:
            counts[r["candidate"]] = r["n"]
    return sorted(counts.items(), key=lambda x: (-x[1], x[0]))


def progress_bar(value: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return "░" * length
    filled = round(value / total * length)
    return "█" * filled + "░" * (length - filled)


def prizes_text() -> str:
    return "\n".join(f"{icon} <b>{place}:</b> {prize}" for icon, place, prize in PRIZES)


def contest_text() -> str:
    return (
        "🏆 <b>IMPERIYANING ENG SODIQ XODIMI</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎁 <b>SOVG‘ALAR</b>\n"
        f"{prizes_text()}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"➕ Har {REFERRALS_PER_BONUS} ta haqiqiy referral = 1 ta bonus ovoz\n"
        f"⏳ Qolgan vaqt: <b>{time_left_text()}</b>\n\n"
        "⚠️ Soxta akkauntlar, nakrutka va sun’iy ovozlar hisobga olinmaydi. "
        "Qoidabuzarlik aniqlansa, ishtirokchi chetlashtiriladi."
    )


def leaderboard_text(title: str = "📈 REYTING") -> str:
    counts = vote_counts()
    total = sum(n for _, n in counts)
    top = counts[0][1] if counts else 0
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

    lines = [f"<b>{title}</b>", f"🗳 Jami ovozlar: <b>{total}</b>", ""]
    for i, (name, n) in enumerate(counts):
        icon = medals[i] if i < len(medals) else f"{i + 1}."
        percent = (n / total * 100) if total else 0
        lines.append(f"{icon} <b>{esc(name)}</b>")
        lines.append(f"<code>{progress_bar(n, top)}</code> {n} ta • {percent:.0f}%")
        lines.append("")
    return "\n".join(lines)


# =========================================================
# KLAVIATURALAR
# =========================================================


def requirements_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Telegram kanalga obuna bo‘lish", url="https://t.me/imperiya_edu")],
            [InlineKeyboardButton("📸 Instagram sahifaga obuna bo‘lish", url="https://www.instagram.com/imperiya_edu?utm_source=ig_web_button_share_sheet&stkn=ZDNlZDc0MzIxNw==")],
            [InlineKeyboardButton("✅ Obunalarni tekshirish", callback_data="check_subscription")],
        ]
    )


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗳 Ovoz berish", callback_data="show_candidates")],
            [InlineKeyboardButton("📈 Reyting", callback_data="leaderboard")],
            [
                InlineKeyboardButton("🔗 Referral", callback_data="my_referral"),
                InlineKeyboardButton("📊 Statistikam", callback_data="my_stats"),
            ],
        ]
    )


def candidate_keyboard():
    rows = []
    for i in range(0, len(CANDIDATES), 2):
        rows.append(
            [
                InlineKeyboardButton(f"👤 {CANDIDATES[j]}", callback_data=f"vote_{j}")
                for j in range(i, min(i + 2, len(CANDIDATES)))
            ]
        )
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def confirm_keyboard(index: int):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_{index}"),
                InlineKeyboardButton("↩️ Boshqasini tanlash", callback_data="show_candidates"),
            ]
        ]
    )


def admin_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 Umumiy statistika", callback_data="admin_stats")],
            [InlineKeyboardButton("🏆 Natijalar", callback_data="admin_results")],
            [InlineKeyboardButton("👥 Ovoz berganlar", callback_data="admin_voters")],
            [InlineKeyboardButton("🎁 Referral statistikasi", callback_data="admin_referrals")],
            [InlineKeyboardButton("🔄 Yangilash", callback_data="admin_panel")],
        ]
    )


async def edit(query, text: str, keyboard=None):
    """Xabarni tahrirlash (HTML formatda)."""
    try:
        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:  # masalan "message is not modified"
        log.debug("edit xatosi: %s", e)


# =========================================================
# REFERRAL
# =========================================================


async def process_referral(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    row = get_user(user_id)
    if not row:
        return

    referrer_id = row["referrer_id"]
    if not referrer_id or referrer_id == user_id:
        return
    if row["subscribed"] != 1 or row["instagram_verified"] != 1:
        return
    if cursor.execute("SELECT 1 FROM referral_done WHERE user_id = ?", (user_id,)).fetchone():
        return
    if not get_user(referrer_id):
        return

    cursor.execute(
        "INSERT INTO referral_done (user_id, created_at) VALUES (?, ?)",
        (user_id, datetime.now().isoformat()),
    )
    cursor.execute(
        "UPDATE users SET referral_count = referral_count + 1, points = points + 1 "
        "WHERE user_id = ?",
        (referrer_id,),
    )

    ref = get_user(referrer_id)
    should_have = ref["points"] // REFERRALS_PER_BONUS
    new_bonus = should_have - ref["bonus_granted"]
    if new_bonus > 0:
        cursor.execute(
            "UPDATE users SET bonus_votes = bonus_votes + ?, bonus_granted = ? "
            "WHERE user_id = ?",
            (new_bonus, should_have, referrer_id),
        )
    db.commit()

    # Taklif qilgan odamga xabar
    try:
        text = (
            "🎉 <b>Yangi referral!</b>\n"
            f"Sizning havolangiz orqali <b>{esc(row['first_name'])}</b> qo‘shildi.\n"
            f"👥 Jami referral: <b>{ref['referral_count']}</b>"
        )
        if new_bonus > 0:
            text += f"\n🎁 Sizga <b>{new_bonus}</b> ta bonus ovoz berildi!"
        await context.bot.send_message(referrer_id, text, parse_mode=ParseMode.HTML)
    except Exception as e:
        log.warning("Referrerga xabar yuborilmadi: %s", e)


# =========================================================
# START
# =========================================================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    # /start REFERRER_ID
    if context.args:
        try:
            referrer_id = int(context.args[0])
            row = get_user(user.id)
            if referrer_id != user.id and row["referrer_id"] is None and get_user(referrer_id):
                cursor.execute(
                    "UPDATE users SET referrer_id = ? WHERE user_id = ?",
                    (referrer_id, user.id),
                )
                db.commit()
        except (ValueError, TypeError):
            pass

    if not contest_active():
        await update.message.reply_text(
            "⛔ <b>Konkurs yakunlangan.</b>\n\n"
            f"Tugagan vaqt: {contest_end().strftime('%d.%m.%Y %H:%M')}",
            parse_mode=ParseMode.HTML,
        )
        return

    if user_has_requirements(user.id):
        await process_referral(user.id, context)
        await update.message.reply_text(
            contest_text(), reply_markup=main_menu_keyboard(), parse_mode=ParseMode.HTML
        )
        return

    await update.message.reply_text(
        contest_text()
        + "\n\n🔐 <b>Ovoz berishdan oldin:</b>\n"
        "1️⃣ Telegram kanalga obuna bo‘ling\n"
        "2️⃣ Instagram sahifamizga obuna bo‘ling\n\n"
        "So‘ng «Obunalarni tekshirish» tugmasini bosing.",
        reply_markup=requirements_keyboard(),
        parse_mode=ParseMode.HTML,
    )


# =========================================================
# OBUNA TEKSHIRISH
# =========================================================


async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    save_user(query.from_user)

    telegram_ok = False
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        telegram_ok = member.status in ("member", "administrator", "creator")
    except Exception as e:
        log.warning("Telegram obuna tekshiruvi xatosi: %s", e)

    # Eslatma: Instagram obunasini oddiy bot API orqali tekshirib bo‘lmaydi.
    # Hozircha foydalanuvchi tugmani bosib tasdiqlaydi.
    cursor.execute(
        "UPDATE users SET subscribed = ?, instagram_verified = 1 WHERE user_id = ?",
        (1 if telegram_ok else 0, user_id),
    )
    db.commit()

    if not telegram_ok:
        await edit(
            query,
            "❌ <b>Telegram kanal obunasi tasdiqlanmadi.</b>\n\n"
            "Kanalga obuna bo‘ling va qayta tekshiring.",
            requirements_keyboard(),
        )
        return

    await process_referral(user_id, context)
    await edit(
        query,
        "✅ <b>Shartlar qabul qilindi!</b>\n\nEndi konkursda ishtirok etishingiz mumkin.",
        main_menu_keyboard(),
    )


# =========================================================
# NOMZODLAR VA OVOZ BERISH
# =========================================================


def votes_available(row) -> int:
    """Foydalanuvchida nechta ovoz qolgan."""
    return (0 if row["main_vote_used"] else 1) + row["bonus_votes"]


async def _guard(query) -> bool:
    """Konkurs faol va shartlar bajarilganini tekshiradi."""
    if not contest_active():
        await edit(query, "⛔ <b>Konkurs yakunlangan.</b>")
        return False
    if not user_has_requirements(query.from_user.id):
        await edit(
            query,
            "❌ Avval majburiy obuna shartlarini bajaring.",
            requirements_keyboard(),
        )
        return False
    return True


async def show_candidates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await _guard(query):
        return

    row = get_user(query.from_user.id)
    left = votes_available(row)

    if left <= 0:
        await edit(
            query,
            "ℹ️ <b>Sizning ovozlaringiz tugagan.</b>\n\n"
            f"Qo‘shimcha ovoz olish uchun do‘stlaringizni taklif qiling: "
            f"har {REFERRALS_PER_BONUS} ta referral = 1 ovoz.",
            main_menu_keyboard(),
        )
        return

    await edit(
        query,
        "🗳 <b>OVOZ BERISH</b>\n\n"
        f"🎟 Sizda <b>{left}</b> ta ovoz bor.\n"
        "Kimga ovoz bermoqchisiz? Xodimni tanlang 👇",
        candidate_keyboard(),
    )


async def vote_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nomzod tanlanganda tasdiqlash so‘raladi."""
    query = update.callback_query
    await query.answer()

    if not await _guard(query):
        return

    try:
        index = int(query.data.replace("vote_", ""))
        candidate = CANDIDATES[index]
    except (ValueError, IndexError):
        await query.answer("❌ Nomzod topilmadi.", show_alert=True)
        return

    await edit(
        query,
        "🗳 <b>OVOZNI TASDIQLANG</b>\n\n"
        f"👤 <b>{esc(candidate)}</b>\n\n"
        "Ovoz berilgach, uni qaytarib bo‘lmaydi.",
        confirm_keyboard(index),
    )


async def vote_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await _guard(query):
        return

    user_id = query.from_user.id
    try:
        index = int(query.data.replace("confirm_", ""))
        candidate = CANDIDATES[index]
    except (ValueError, IndexError):
        await query.answer("❌ Nomzod topilmadi.", show_alert=True)
        return

    row = get_user(user_id)

    if row["main_vote_used"] == 0:
        vote_type = "main"
        cursor.execute("UPDATE users SET main_vote_used = 1 WHERE user_id = ?", (user_id,))
    elif row["bonus_votes"] > 0:
        vote_type = "bonus"
        cursor.execute(
            "UPDATE users SET bonus_votes = bonus_votes - 1 WHERE user_id = ?", (user_id,)
        )
    else:
        await query.answer("❌ Sizda ovoz qolmagan.", show_alert=True)
        return

    cursor.execute(
        "INSERT INTO votes (user_id, candidate, vote_type, created_at) VALUES (?, ?, ?, ?)",
        (user_id, candidate, vote_type, datetime.now().isoformat()),
    )
    db.commit()

    # Yangi reytingdagi o‘rni
    counts = vote_counts()
    rank = next(i for i, (n, _) in enumerate(counts, 1) if n == candidate)
    votes_now = dict(counts)[candidate]

    row = get_user(user_id)
    await edit(
        query,
        "✅ <b>OVOZINGIZ QABUL QILINDI!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Xodim: <b>{esc(candidate)}</b>\n"
        f"🎟 Ovoz turi: {'asosiy' if vote_type == 'main' else 'bonus'}\n"
        f"📈 Hozirgi o‘rni: <b>{rank}-o‘rin</b> ({votes_now} ta ovoz)\n\n"
        f"🎁 Qolgan ovozlaringiz: <b>{votes_available(row)}</b>\n\n"
        "Rahmat! Ko‘proq ovoz olish uchun do‘stlaringizni taklif qiling 🔗",
        main_menu_keyboard(),
    )


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await edit(
        query,
        leaderboard_text() + f"\n⏳ Qolgan vaqt: <b>{time_left_text()}</b>",
        InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔄 Yangilash", callback_data="leaderboard")],
                [InlineKeyboardButton("⬅️ Orqaga", callback_data="back_main")],
            ]
        ),
    )


# =========================================================
# REFERRAL VA STATISTIKA
# =========================================================


async def _referral_text(context, user_id: int) -> str:
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start={user_id}"
    row = get_user(user_id)
    until_next = REFERRALS_PER_BONUS - (row["points"] % REFERRALS_PER_BONUS)
    return (
        "🔗 <b>SIZNING REFERRAL HAVOLANGIZ</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"👥 Taklif qilganlar: <b>{row['referral_count']}</b> ta\n"
        f"⭐ Ball: <b>{row['points']}</b>\n"
        f"🎁 Bonus ovozlar: <b>{row['bonus_votes']}</b> ta\n"
        f"🎯 Keyingi bonusgacha: <b>{until_next}</b> ta referral\n\n"
        f"Har {REFERRALS_PER_BONUS} ta haqiqiy referral = 1 ta bonus ovoz."
    )


async def my_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await edit(query, await _referral_text(context, query.from_user.id), main_menu_keyboard())


async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    await update.message.reply_text(
        await _referral_text(context, update.effective_user.id),
        parse_mode=ParseMode.HTML,
    )


async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    row = get_user(user_id)

    total_votes = cursor.execute(
        "SELECT COUNT(*) AS n FROM votes WHERE user_id = ?", (user_id,)
    ).fetchone()["n"]
    last = cursor.execute(
        "SELECT candidate FROM votes WHERE user_id = ? ORDER BY vote_id DESC LIMIT 1",
        (user_id,),
    ).fetchone()

    await edit(
        query,
        "📊 <b>SIZNING STATISTIKANGIZ</b>\n\n"
        f"👤 Ism: {esc(row['first_name'])}\n"
        f"👥 Referral: {row['referral_count']}\n"
        f"⭐ Ball: {row['points']}\n"
        f"🎁 Bonus ovozlar: {row['bonus_votes']}\n"
        f"🎟 Qolgan ovozlar: {votes_available(row)}\n"
        f"🗳 Jami bergan ovozlar: {total_votes}\n"
        f"🏆 Oxirgi ovoz: {esc(last['candidate']) if last else 'Hali ovoz berilmagan'}",
        main_menu_keyboard(),
    )


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await edit(query, contest_text(), main_menu_keyboard())


# =========================================================
# ADMIN
# =========================================================


async def _admin_only(query) -> bool:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Ruxsat yo‘q!", show_alert=True)
        return False
    await query.answer()
    return True


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Sizda admin huquqi mavjud emas.")
        return
    await update.message.reply_text(
        "🔐 <b>IMPERIYA KONKURS — ADMIN PANEL</b>\n\nKerakli bo‘limni tanlang:",
        reply_markup=admin_keyboard(),
        parse_mode=ParseMode.HTML,
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _admin_only(query):
        return
    await edit(
        query,
        "🔐 <b>IMPERIYA KONKURS — ADMIN PANEL</b>\n\nKerakli bo‘limni tanlang:",
        admin_keyboard(),
    )


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _admin_only(query):
        return

    def one(sql):
        return cursor.execute(sql).fetchone()[0]

    await edit(
        query,
        "📊 <b>UMUMIY STATISTIKA</b>\n\n"
        f"👥 Jami foydalanuvchilar: {one('SELECT COUNT(*) FROM users')}\n"
        f"📢 Telegram obunachilari: {one('SELECT COUNT(*) FROM users WHERE subscribed = 1')}\n"
        f"📸 Instagram tasdiqlari: {one('SELECT COUNT(*) FROM users WHERE instagram_verified = 1')}\n"
        f"🗳 Jami ovozlar: {one('SELECT COUNT(*) FROM votes')}\n"
        f"👤 Ovoz berganlar: {one('SELECT COUNT(DISTINCT user_id) FROM votes')}\n"
        f"🔗 Jami referral: {one('SELECT COALESCE(SUM(referral_count), 0) FROM users')}\n"
        f"🎁 Ishlatilmagan bonus: {one('SELECT COALESCE(SUM(bonus_votes), 0) FROM users')}\n\n"
        f"🟢 Konkurs: <b>{'FAOL' if contest_active() else 'YAKUNLANGAN'}</b>\n"
        f"📅 Davomiyligi: {contest_days()} kun\n"
        f"⏱ Tugash: {contest_end().strftime('%d.%m.%Y %H:%M')}\n"
        f"⏳ Qolgan: {time_left_text()}",
        admin_keyboard(),
    )


async def admin_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _admin_only(query):
        return
    await edit(query, leaderboard_text("🏆 KONKURS NATIJALARI"), admin_keyboard())


async def admin_voters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _admin_only(query):
        return

    voters = cursor.execute(
        """
        SELECT votes.vote_id, votes.user_id, votes.candidate, votes.vote_type,
               votes.created_at, users.first_name, users.username
        FROM votes LEFT JOIN users ON users.user_id = votes.user_id
        ORDER BY votes.vote_id DESC LIMIT 15
        """
    ).fetchall()

    if not voters:
        text = "👥 <b>OVOZ BERGANLAR</b>\n\nHozircha hech kim ovoz bermagan."
    else:
        text = "👥 <b>OVOZ BERGANLAR</b>\nOxirgi 15 ta ovoz:\n\n"
        for i, r in enumerate(voters, 1):
            try:
                date_text = datetime.fromisoformat(r["created_at"]).strftime("%d.%m %H:%M:%S")
            except Exception:
                date_text = r["created_at"]
            username = f"@{esc(r['username'])}" if r["username"] else "username yo‘q"
            text += (
                f"{i}. 👤 {esc(r['first_name'] or 'Noma’lum')} ({username})\n"
                f"   🆔 <code>{r['user_id']}</code> • 🕐 {date_text}\n"
                f"   🗳 {esc(r['candidate'])} • {r['vote_type']}\n\n"
            )

    await edit(query, text, admin_keyboard())


async def admin_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _admin_only(query):
        return

    rows = cursor.execute(
        """
        SELECT user_id, first_name, username, referral_count, points, bonus_votes
        FROM users WHERE referral_count > 0
        ORDER BY referral_count DESC LIMIT 20
        """
    ).fetchall()

    text = "🎁 <b>REFERRAL STATISTIKASI</b>\n\n"
    if not rows:
        text += "Hozircha referral mavjud emas."
    for i, r in enumerate(rows, 1):
        username = f"@{esc(r['username'])}" if r["username"] else "username yo‘q"
        text += (
            f"{i}. <b>{esc(r['first_name'] or 'Noma’lum')}</b> ({username})\n"
            f"   🆔 <code>{r['user_id']}</code>\n"
            f"   👥 {r['referral_count']} • ⭐ {r['points']} • 🎁 {r['bonus_votes']}\n\n"
        )

    await edit(query, text, admin_keyboard())


# ---- Admin buyruqlari: vaqtni boshqarish ----


async def setdays_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        days = int(context.args[0])
        if days < 1:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("Ishlatilishi: /setdays 10")
        return
    set_setting("contest_days", str(days))
    await update.message.reply_text(
        f"✅ Konkurs davomiyligi {days} kunga o‘rnatildi.\n"
        f"⏱ Tugash: {contest_end().strftime('%d.%m.%Y %H:%M')}"
    )


async def extend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        days = int(context.args[0])
        if days < 1:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("Ishlatilishi: /extend 3")
        return
    set_setting("contest_days", str(contest_days() + days))
    await update.message.reply_text(
        f"✅ Konkurs {days} kunga uzaytirildi.\n"
        f"⏱ Yangi tugash: {contest_end().strftime('%d.%m.%Y %H:%M')}"
    )


async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    set_setting("contest_start", datetime.now().isoformat())
    await update.message.reply_text(
        f"🔄 Konkurs hozirdan qayta boshlandi ({contest_days()} kun).\n"
        f"⏱ Tugash: {contest_end().strftime('%d.%m.%Y %H:%M')}"
    )


async def timeleft_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"⏳ Konkursning qolgan vaqti: {time_left_text()}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ YORDAM\n\n"
        "/start — konkursni boshlash\n"
        "/referral — referral havolangiz\n"
        "/timeleft — konkursning qolgan vaqti\n"
        "/help — yordam\n\n"
        "Muammo bo‘lsa administratorga murojaat qiling."
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("BOT ERROR: %r", context.error)


async def post_init(application: Application):
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Konkursni boshlash"),
            BotCommand("referral", "Referral havolam"),
            BotCommand("timeleft", "Qolgan vaqt"),
            BotCommand("help", "Yordam"),
        ]
    )


# =========================================================
# MAIN
# =========================================================


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    for name, handler in [
        ("start", start),
        ("referral", referral_command),
        ("help", help_command),
        ("timeleft", timeleft_command),
        ("admin", admin_command),
        ("setdays", setdays_command),
        ("extend", extend_command),
        ("restart", restart_command),
    ]:
        app.add_handler(CommandHandler(name, handler))

    for pattern, handler in [
        (r"^check_subscription$", check_subscription),
        (r"^show_candidates$", show_candidates),
        (r"^vote_\d+$", vote_select),
        (r"^confirm_\d+$", vote_confirm),
        (r"^leaderboard$", leaderboard),
        (r"^my_referral$", my_referral),
        (r"^my_stats$", my_stats),
        (r"^back_main$", back_main),
        (r"^admin_panel$", admin_panel),
        (r"^admin_stats$", admin_stats),
        (r"^admin_results$", admin_results),
        (r"^admin_voters$", admin_voters),
        (r"^admin_referrals$", admin_referrals),
    ]:
        app.add_handler(CallbackQueryHandler(handler, pattern=pattern))

    app.add_error_handler(error_handler)

    log.info("IMPERIYA KONKURS BOT ISHLAYAPTI (davomiyligi: %s kun)", contest_days())
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()