"""
Arabic / English Telegram Booking Bot with Google Calendar Integration.

Commands:
  /start        — Choose language, then get greeted
  /availability — Show available time slots for the next 7 days
  /admin        — Admin panel (only for the configured ADMIN_CHAT_ID)
  /language     — Switch language at any time
"""

import datetime
import json
import logging
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# ── Load environment ──────────────────────────────────────
load_dotenv()

TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID     = int(os.getenv("ADMIN_CHAT_ID", "0"))
TIMEZONE          = os.getenv("TIMEZONE", "Asia/Riyadh")
AVAILABILITY_FILE = "availability.json"

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
#  Translations
# ══════════════════════════════════════════════════════════

STRINGS = {
    "ar": {
        # Language picker
        "choose_lang":      "مرحباً! 👋\nاختر لغتك المفضلة:\nHello! 👋\nChoose your preferred language:",
        "lang_set":         "تم اختيار اللغة العربية ✅",
        # Start
        "start":            "👋 أهلاً! أنا البوت الخاص بحجز المواعيد.\n\nاكتب /availability لعرض الأوقات المتاحة وحجز موعد. 📅",
        # Availability
        "pick_day":         "📅 اختر يوماً لعرض الأوقات المتاحة:",
        "no_slots_week":    "😅 لا توجد أوقات متاحة هذا الأسبوع، تحقق لاحقاً!",
        "no_slots_day":     "😕 لا توجد أوقات متاحة في هذا اليوم.",
        "pick_time":        "🕐 اختر الوقت المناسب ليوم *{date}*:",
        "slots_available":  "{n} أوقات متاحة",
        # Booking
        "slot_chosen":      "✅ اخترت: *{date}* الساعة *{time}*\n\nمن فضلك أرسل اسمك لإتمام الحجز:",
        "book_success":     "🎉 تم الحجز بنجاح!\n\n📅 *{date}*\n🕐 الساعة *{time}*\n\nنراك قريباً يا {name}! 😊",
        "book_error":       "❌ حدث خطأ أثناء الحجز. يرجى المحاولة مرة أخرى لاحقاً.",
        # Admin notification
        "new_booking":      "📬 *حجز جديد!*\n👤 الاسم: {name}\n📅 اليوم: {date}\n🕐 الوقت: {time}",
        # Admin panel
        "admin_menu":       "⚙️ *لوحة التحكم*\nماذا تريد أن تفعل؟",
        "admin_set":        "📅 تحديد وقت الفراغ",
        "admin_view":       "👁 عرض الجدول الحالي",
        "admin_clear":      "🗑 مسح يوم معين",
        "admin_no_slots":   "📭 لم يتم تحديد أي أوقات بعد.\nاستخدم /admin ثم اختر 'تحديد وقت الفراغ'.",
        "admin_schedule":   "📅 *جدول أوقات الفراغ الحالي:*\n\n",
        "admin_pick_day":   "📅 اختر اليوم:",
        "admin_pick_start": "🕐 وقت البداية ليوم *{day}*؟",
        "admin_pick_end":   "🕕 وقت النهاية ليوم *{day}* (يبدأ من {start})؟",
        "admin_saved":      "✅ تم الحفظ!\n*{day}*: {start} – {end}\n\nاستخدم /admin لإضافة المزيد أو عرض الجدول.",
        "admin_nothing":    "لا يوجد شيء لمسحه.",
        "admin_pick_clear": "🗑 اختر اليوم الذي تريد مسحه:",
        "admin_cleared":    "🗑 تم مسح جميع الأوقات ليوم *{day}*.",
        "admin_denied":     "⛔ غير مصرح لك باستخدام هذا الأمر.",
        # Language command
        "language_cmd":     "اختر لغتك:\nChoose your language:",
    },
    "en": {
        # Language picker
        "choose_lang":      "Hello! 👋\nChoose your preferred language:\nمرحباً! 👋\nاختر لغتك المفضلة:",
        "lang_set":         "English language selected ✅",
        # Start
        "start":            "👋 Hello! I'm the appointment booking bot.\n\nType /availability to see available slots and book a meeting. 📅",
        # Availability
        "pick_day":         "📅 Choose a day to see available slots:",
        "no_slots_week":    "😅 No available slots this week, check back later!",
        "no_slots_day":     "😕 No available slots on this day.",
        "pick_time":        "🕐 Choose a time on *{date}*:",
        "slots_available":  "{n} slots available",
        # Booking
        "slot_chosen":      "✅ You chose: *{date}* at *{time}*\n\nPlease send your name to complete the booking:",
        "book_success":     "🎉 Booking confirmed!\n\n📅 *{date}*\n🕐 At *{time}*\n\nSee you soon, {name}! 😊",
        "book_error":       "❌ An error occurred while booking. Please try again later.",
        # Admin notification
        "new_booking":      "📬 *New Booking!*\n👤 Name: {name}\n📅 Date: {date}\n🕐 Time: {time}",
        # Admin panel
        "admin_menu":       "⚙️ *Admin Panel*\nWhat would you like to do?",
        "admin_set":        "📅 Set Availability",
        "admin_view":       "👁 View Current Schedule",
        "admin_clear":      "🗑 Clear a Day",
        "admin_no_slots":   "📭 No availability set yet.\nUse /admin then choose 'Set Availability'.",
        "admin_schedule":   "📅 *Current Availability Schedule:*\n\n",
        "admin_pick_day":   "📅 Choose a day:",
        "admin_pick_start": "🕐 Start time for *{day}*?",
        "admin_pick_end":   "🕕 End time for *{day}* (starting from {start})?",
        "admin_saved":      "✅ Saved!\n*{day}*: {start} – {end}\n\nUse /admin to add more or view the schedule.",
        "admin_nothing":    "Nothing to clear.",
        "admin_pick_clear": "🗑 Choose the day to clear:",
        "admin_cleared":    "🗑 All slots for *{day}* have been cleared.",
        "admin_denied":     "⛔ You are not authorized to use this command.",
        # Language command
        "language_cmd":     "Choose your language:\nاختر لغتك:",
    },
}

def t(context: ContextTypes.DEFAULT_TYPE, key: str, **kwargs) -> str:
    """Return the translated string for the user's chosen language."""
    lang = context.user_data.get("lang", "ar")
    text = STRINGS[lang].get(key, STRINGS["ar"][key])
    return text.format(**kwargs) if kwargs else text

# ── Arabic date/time helpers ──────────────────────────────

DAYS_AR = {
    "Monday":    "الإثنين",
    "Tuesday":   "الثلاثاء",
    "Wednesday": "الأربعاء",
    "Thursday":  "الخميس",
    "Friday":    "الجمعة",
    "Saturday":  "السبت",
    "Sunday":    "الأحد",
}

MONTHS_AR = {
    1: "يناير",   2: "فبراير",  3: "مارس",    4: "أبريل",
    5: "مايو",    6: "يونيو",   7: "يوليو",   8: "أغسطس",
    9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر",
}

DAYS = list(DAYS_AR.keys())  # Monday … Sunday
HOURS = [f"{h:02d}:00" for h in range(7, 22)]  # 07:00 … 21:00


def format_date(date: datetime.date, lang: str) -> str:
    if lang == "ar":
        day_ar   = DAYS_AR[date.strftime("%A")]
        month_ar = MONTHS_AR[date.month]
        return f"{day_ar}، {date.day} {month_ar}"
    else:
        return date.strftime("%A, %B %-d") if os.name != "nt" else date.strftime("%A, %B %d").replace(" 0", " ")


def format_time(dt: datetime.datetime, lang: str) -> str:
    hour   = dt.hour
    minute = dt.strftime("%M")
    if lang == "ar":
        period  = "صباحاً" if hour < 12 else "مساءً"
        hour_12 = hour if hour <= 12 else hour - 12
        if hour_12 == 0:
            hour_12 = 12
        return f"{hour_12}:{minute} {period}"
    else:
        period  = "AM" if hour < 12 else "PM"
        hour_12 = hour % 12 or 12
        return f"{hour_12}:{minute} {period}"


def day_label(day_name: str, lang: str) -> str:
    """Day name in the right language."""
    return DAYS_AR.get(day_name, day_name) if lang == "ar" else day_name


def hour_label(h: str, lang: str) -> str:
    """Convert '14:00' → '2:00 PM' or '2:00 مساءً'."""
    hour = int(h.split(":")[0])
    if lang == "ar":
        period  = "صباحاً" if hour < 12 else "مساءً"
        hour_12 = hour if hour <= 12 else hour - 12
        if hour_12 == 0:
            hour_12 = 12
        return f"{hour_12}:00 {period}"
    else:
        period  = "AM" if hour < 12 else "PM"
        hour_12 = hour % 12 or 12
        return f"{hour_12}:00 {period}"


# ── Availability Storage ──────────────────────────────────

def load_availability() -> dict:
    if os.path.exists(AVAILABILITY_FILE):
        with open(AVAILABILITY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_availability(data: dict):
    with open(AVAILABILITY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_CHAT_ID


# ── Google Calendar ───────────────────────────────────────

def get_calendar_service():
    """Build an authorized Calendar API client, refreshing the token if needed."""
    creds = Credentials.from_authorized_user_file("token.json")
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def get_busy_slots(date: datetime.date) -> list:
    """Return busy time ranges for a given date from Google Calendar."""
    try:
        service = get_calendar_service()
        tz = ZoneInfo(TIMEZONE)
        day_start = datetime.datetime.combine(date, datetime.time(0, 0), tzinfo=tz)
        day_end   = datetime.datetime.combine(date, datetime.time(23, 59, 59), tzinfo=tz)

        result = service.freebusy().query(body={
            "timeMin":  day_start.isoformat(),
            "timeMax":  day_end.isoformat(),
            "timeZone": TIMEZONE,
            "items":    [{"id": "primary"}],
        }).execute()

        busy_raw = result["calendars"]["primary"]["busy"]
        logger.info("Busy slots for %s: %s", date.isoformat(), busy_raw)
        return busy_raw
    except Exception as e:
        logger.error("Error fetching busy slots: %s", e)
        return []


def _parse_gcal_datetime(dt_str: str) -> datetime.datetime:
    """Parse a Google Calendar datetime string into a naive local datetime."""
    dt_str = dt_str.replace("Z", "+00:00") if dt_str.endswith("Z") else dt_str
    dt = datetime.datetime.fromisoformat(dt_str)
    return dt.replace(tzinfo=None)


def get_free_slots(date: datetime.date) -> list:
    """Return list of available 1-hour datetime slots for a given date."""
    availability = load_availability()
    day_name = date.strftime("%A")

    if day_name not in availability:
        return []

    busy = get_busy_slots(date)
    busy_parsed = [
        (_parse_gcal_datetime(b["start"]), _parse_gcal_datetime(b["end"]))
        for b in busy
    ]
    slots = []

    for window in availability[day_name]:
        start_h, start_m = map(int, window["start"].split(":"))
        end_h,   end_m   = map(int, window["end"].split(":"))
        current  = datetime.datetime.combine(date, datetime.time(start_h, start_m))
        win_end  = datetime.datetime.combine(date, datetime.time(end_h, end_m))

        while current + datetime.timedelta(hours=1) <= win_end:
            slot_end = current + datetime.timedelta(hours=1)
            overlap = any(
                current < b_end and slot_end > b_start
                for b_start, b_end in busy_parsed
            )
            if not overlap:
                slots.append(current)
            current += datetime.timedelta(hours=1)

    return slots


def book_slot(slot: datetime.datetime, guest_name: str, guest_email: str = None):
    """Create a calendar event for the given slot."""
    try:
        service = get_calendar_service()
        event = {
            "summary": f"Meeting with {guest_name}",
            "start": {"dateTime": slot.isoformat(), "timeZone": TIMEZONE},
            "end":   {"dateTime": (slot + datetime.timedelta(hours=1)).isoformat(), "timeZone": TIMEZONE},
        }
        if guest_email:
            event["attendees"] = [{"email": guest_email}]
        service.events().insert(calendarId="primary", body=event, sendUpdates="all").execute()
        logger.info("Booked slot for %s at %s", guest_name, slot.isoformat())
    except Exception as e:
        logger.error("Error booking slot: %s", e)
        raise


# ══════════════════════════════════════════════════════════
#  Language Selection
# ══════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show language picker."""
    keyboard = [
        [
            InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        ]
    ]
    await update.message.reply_text(
        STRINGS["ar"]["choose_lang"],
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allow the user to switch language at any time."""
    keyboard = [
        [
            InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        ]
    ]
    msg = t(context, "language_cmd")
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))


async def lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save language choice and greet the user."""
    query = update.callback_query
    await query.answer()
    lang = query.data.replace("lang_", "")  # "ar" or "en"
    context.user_data["lang"] = lang

    # Confirm language, then send the start message
    await query.edit_message_text(STRINGS[lang]["lang_set"])
    await query.message.reply_text(STRINGS[lang]["start"])


# ══════════════════════════════════════════════════════════
#  Admin Handlers
# ══════════════════════════════════════════════════════════

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await update.message.reply_text(t(context, "admin_denied"))

    lang = context.user_data.get("lang", "ar")
    keyboard = [
        [InlineKeyboardButton(t(context, "admin_set"),   callback_data="adm_set")],
        [InlineKeyboardButton(t(context, "admin_view"),  callback_data="adm_view")],
        [InlineKeyboardButton(t(context, "admin_clear"), callback_data="adm_clear")],
    ]
    await update.message.reply_text(
        t(context, "admin_menu"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def adm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update):
        return

    lang = context.user_data.get("lang", "ar")
    data = query.data

    # ── View ──
    if data == "adm_view":
        availability = load_availability()
        if not availability:
            return await query.edit_message_text(t(context, "admin_no_slots"))
        text = t(context, "admin_schedule")
        for day, windows in availability.items():
            dl = day_label(day, lang)
            for w in windows:
                text += f"• {dl}: {hour_label(w['start'], lang)} – {hour_label(w['end'], lang)}\n"
        await query.edit_message_text(text, parse_mode="Markdown")

    # ── Set: pick day ──
    elif data == "adm_set":
        keyboard = [
            [InlineKeyboardButton(day_label(d, lang), callback_data=f"adm_day_{d}")]
            for d in DAYS
        ]
        await query.edit_message_text(
            t(context, "admin_pick_day"),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ── Set: picked day → pick start ──
    elif data.startswith("adm_day_"):
        day = data.replace("adm_day_", "")
        context.user_data["adm_day"] = day
        keyboard = [
            [InlineKeyboardButton(hour_label(h, lang), callback_data=f"adm_start_{h}") for h in HOURS[i:i + 3]]
            for i in range(0, len(HOURS), 3)
        ]
        await query.edit_message_text(
            t(context, "admin_pick_start", day=day_label(day, lang)),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ── Set: picked start → pick end ──
    elif data.startswith("adm_start_"):
        start = data.replace("adm_start_", "")
        context.user_data["adm_start"] = start
        day = context.user_data.get("adm_day")
        valid_ends = [h for h in HOURS if h > start]
        keyboard = [
            [InlineKeyboardButton(hour_label(h, lang), callback_data=f"adm_end_{h}") for h in valid_ends[i:i + 3]]
            for i in range(0, len(valid_ends), 3)
        ]
        await query.edit_message_text(
            t(context, "admin_pick_end", day=day_label(day, lang), start=hour_label(start, lang)),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ── Set: save ──
    elif data.startswith("adm_end_"):
        end   = data.replace("adm_end_", "")
        day   = context.user_data.pop("adm_day", None)
        start = context.user_data.pop("adm_start", None)

        availability = load_availability()
        if day not in availability:
            availability[day] = []
        availability[day].append({"start": start, "end": end})
        save_availability(availability)

        await query.edit_message_text(
            t(context, "admin_saved",
              day=day_label(day, lang),
              start=hour_label(start, lang),
              end=hour_label(end, lang)),
            parse_mode="Markdown",
        )

    # ── Clear: pick day ──
    elif data == "adm_clear":
        availability = load_availability()
        if not availability:
            return await query.edit_message_text(t(context, "admin_nothing"))
        keyboard = [
            [InlineKeyboardButton(day_label(d, lang), callback_data=f"adm_clearday_{d}")]
            for d in availability
        ]
        await query.edit_message_text(
            t(context, "admin_pick_clear"),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("adm_clearday_"):
        day = data.replace("adm_clearday_", "")
        availability = load_availability()
        availability.pop(day, None)
        save_availability(availability)
        await query.edit_message_text(
            t(context, "admin_cleared", day=day_label(day, lang)),
            parse_mode="Markdown",
        )


# ══════════════════════════════════════════════════════════
#  User Handlers
# ══════════════════════════════════════════════════════════

async def availability_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang  = context.user_data.get("lang", "ar")
    today = datetime.date.today()
    keyboard = []
    for i in range(7):
        day = today + datetime.timedelta(days=i)
        slots = get_free_slots(day)
        if slots:
            keyboard.append([InlineKeyboardButton(
                f"{format_date(day, lang)}  ·  {t(context, 'slots_available', n=len(slots))}",
                callback_data=f"day_{day.isoformat()}",
            )])

    if keyboard:
        await update.message.reply_text(
            t(context, "pick_day"),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update.message.reply_text(t(context, "no_slots_week"))


async def show_day_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("lang", "ar")
    date = datetime.date.fromisoformat(query.data.replace("day_", ""))
    slots = get_free_slots(date)

    if not slots:
        return await query.edit_message_text(t(context, "no_slots_day"))

    keyboard = [
        [InlineKeyboardButton(format_time(s, lang), callback_data=f"book_{s.isoformat()}")]
        for s in slots
    ]
    await query.edit_message_text(
        t(context, "pick_time", date=format_date(date, lang)),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("lang", "ar")
    slot = datetime.datetime.fromisoformat(query.data.replace("book_", ""))
    context.user_data["pending_slot"] = slot
    await query.edit_message_text(
        t(context, "slot_chosen",
          date=format_date(slot.date(), lang),
          time=format_time(slot, lang)),
        parse_mode="Markdown",
    )


async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "pending_slot" not in context.user_data:
        return

    lang     = context.user_data.get("lang", "ar")
    slot     = context.user_data.pop("pending_slot")
    name     = update.message.text
    date_str = format_date(slot.date(), lang)
    time_str = format_time(slot, lang)

    try:
        book_slot(slot, name)
    except Exception:
        return await update.message.reply_text(t(context, "book_error"))

    # Notify admin (always in admin's language — default Arabic)
    admin_lang = "ar"  # Admin gets Arabic notifications
    await context.bot.send_message(
        ADMIN_CHAT_ID,
        STRINGS[admin_lang]["new_booking"].format(
            name=name,
            date=format_date(slot.date(), admin_lang),
            time=format_time(slot, admin_lang),
        ),
        parse_mode="Markdown",
    )

    await update.message.reply_text(
        t(context, "book_success", date=date_str, time=time_str, name=name),
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════

def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is not set. Create a .env file or set the environment variable.")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Language selection (must be before other callbacks)
    app.add_handler(CallbackQueryHandler(lang_callback, pattern="^lang_"))

    # User commands
    app.add_handler(CommandHandler("start",        start))
    app.add_handler(CommandHandler("language",     language_cmd))
    app.add_handler(CommandHandler("availability", availability_cmd))

    # Admin
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(adm_callback, pattern="^adm_"))

    # Booking flow
    app.add_handler(CallbackQueryHandler(show_day_slots,  pattern="^day_"))
    app.add_handler(CallbackQueryHandler(confirm_booking, pattern="^book_"))

    # Free-text (name capture)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name))

    logger.info("Bot is starting…")
    app.run_polling()


if __name__ == "__main__":
    main()
