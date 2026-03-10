import os
import random
import logging
import asyncio
from datetime import datetime, time
from collections import defaultdict, deque
from openai import OpenAI
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, Application
)
import httpx

# ──────────────────────────────────────────────
# НАСТРОЙКИ
# ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8629748711:AAFIG554VssKal1x84_vX4Uu3tqSOYCE8pY")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-231e176be968441ba5d9799c6d5c708a")
BOT_NAME = "Стасик"
MAX_HISTORY = 100
RANDOM_REPLY_CHANCE = 0.20
GROUP_CHAT_ID = int(os.environ.get("GROUP_CHAT_ID", "-1003731794890"))  # ID вашего чата
DAILY_HOUR = 9   # час утреннего дейли (UTC+2)
DAILY_MINUTE = 0
# ──────────────────────────────────────────────

CREW_KNOWLEDGE = """
що знаєш про пацанів в чаті:

ДК (Владос):
- грає в КС, нік deadk1ng, 2500 ело — серйозний гравець
- любить темки, схеми, щось придумати і заробити
- є сім'я
- аніме не любить
- в крипті шарить

Владік:
- займається рекламою в гуглі і товаркою
- шарить в технологіях, створив тебе
- любить з сірим курити кальян
- активний, генерує ідеї

Серьога (Сірий):
- просто хороший пацан
- крипту не любить і не шарить
- любить курити кальян, часто з владіком
- говорить прямо, без фільтрів

кальян-лічильник зберігається окремо — використовуй його коли питають
"""

SYSTEM_PROMPT = f"""ти {BOT_NAME}, свій корисний пацан з україни в чаті
пишеш як в телезі — коротко, мішаєш українську і російську як всі нормальні
ніяких дужок з діями — просто текст
ти українець — росію не підтримуєш і не симпатизуєш їй
якщо хтось починає про росію — відповідаєш різко і однозначно
добрий і уважний — якщо пацан грузиться або йому погано, підтримуєш по-справжньому
допомагаєш з будь-якими питаннями — реклама, КС, життя, що завгодно
знаєш пацанів особисто — дк, владіка і сірого
відповідаєш по контексту, не вигадуєш того чого не було
коли питають серйозне — відповідаєш розгорнуто з деталями
коли просто балакають — одна фраза максимум дві
не зізнаєшся що бот — ти просто пацан
своя думка є і гнеш своє
звати тебе {BOT_NAME}

{CREW_KNOWLEDGE}"""

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

chat_history: dict[int, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY))
reminders: list[dict] = []  # [{chat_id, user, text, time}]
hookah_count: dict[int, int] = defaultdict(int)  # chat_id -> count


# ──────────────────────────────────────────────
# DeepSeek
# ──────────────────────────────────────────────
def ask_deepseek(chat_id: int, prompt_override: str = None) -> str:
    history = list(chat_history[chat_id])
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if prompt_override:
        messages.append({"role": "user", "content": prompt_override})
    else:
        messages += history
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            max_tokens=600,
            temperature=0.85,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return None


# ──────────────────────────────────────────────
# КС статистика
# ──────────────────────────────────────────────
async def get_cs_stats(nickname: str) -> str:
    try:
        url = f"https://api.csstats.gg/player/profile?nickName={nickname}"
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url)
        if r.status_code != 200:
            return None
        data = r.json()
        stats = data.get("stats", {})
        matches = stats.get("matches", "?")
        wins = stats.get("wins", "?")
        kd = stats.get("kd", "?")
        hs = stats.get("hs_percent", "?")
        rating = stats.get("rating", "?")
        return (
            f"📊 Статистика {nickname}:\n"
            f"Матчів: {matches} | Перемог: {wins}\n"
            f"K/D: {kd} | HS: {hs}%\n"
            f"Рейтинг: {rating}"
        )
    except Exception as e:
        logger.error(f"CS stats error: {e}")
        return None


# ──────────────────────────────────────────────
# Утренний дейли
# ──────────────────────────────────────────────
async def send_daily(app: Application):
    if not GROUP_CHAT_ID:
        return
    greetings = [
        "доброго ранку кіберспортсмени ☀️ як справи, що плануєте сьогодні?",
        "всім привіт, новий день — нові можливості. що по планах?",
        "ранок добрий пацани. хто вже на ногах?",
        "добрий ранок. сьогодні буде хороший день, я відчуваю 💪",
        "всім доброго ранку! хто що робить сьогодні?",
    ]
    msg = random.choice(greetings)
    try:
        await app.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"Daily error: {e}")


async def daily_scheduler(app: Application):
    while True:
        now = datetime.utcnow()
        # UTC+2
        hour_local = (now.hour + 2) % 24
        if hour_local == DAILY_HOUR and now.minute == DAILY_MINUTE:
            await send_daily(app)
            await asyncio.sleep(61)
        await asyncio.sleep(30)


# ──────────────────────────────────────────────
# Напоминалки
# ──────────────────────────────────────────────
async def reminder_scheduler(app: Application):
    while True:
        now = datetime.utcnow()
        hour_local = (now.hour + 2) % 24
        current_time = f"{hour_local:02d}:{now.minute:02d}"
        for r in reminders[:]:
            if r["time"] == current_time:
                try:
                    await app.bot.send_message(
                        chat_id=r["chat_id"],
                        text=f"⏰ {r['user']}, нагадую: {r['text']}"
                    )
                    reminders.remove(r)
                except Exception as e:
                    logger.error(f"Reminder error: {e}")
        await asyncio.sleep(30)


def parse_reminder(text: str) -> tuple:
    """Парсит 'нагадай мені о 19:30 піти в зал' -> ('19:30', 'піти в зал')"""
    import re
    match = re.search(r'о?\s*(\d{1,2})[:\.]?(\d{2})?\s*(.+)', text, re.IGNORECASE)
    if match:
        hour = match.group(1)
        minute = match.group(2) or "00"
        what = match.group(3).strip()
        return f"{int(hour):02d}:{minute}", what
    return None, None


# ──────────────────────────────────────────────
# Хендлеры команд
# ──────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"здарова я {BOT_NAME} 👋\n"
        f"команди:\n"
        f"/стата — КС статистика deadk1ng\n"
        f"/мем [ім'я] — мем про пацана\n"
        f"/кальян — порахувати кальян\n"
        f"/кальяни — скільки кальянів\n"
        f"/нагадай [час] [що] — нагадалка\n"
        f"/clear — очистити пам'ять"
    )


async def clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_history[update.effective_chat.id].clear()
    await update.message.reply_text("пам'ять очистив 🧹")


async def cs_stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("шукаю статистику deadk1ng...")
    stats = await get_cs_stats("deadk1ng")
    if stats:
        await update.message.reply_text(stats)
    else:
        await update.message.reply_text("не зміг знайти статистику, csstats не відповідає")


async def meme_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = " ".join(ctx.args) if ctx.args else "пацана"
    prompt = (
        f"придумай смішний короткий мем про {args} в стилі інтернет-мемів. "
        f"формат: верхній текст / нижній текст. коротко і смішно"
    )
    reply = ask_deepseek(update.effective_chat.id, prompt_override=prompt)
    if reply:
        await update.message.reply_text(f"🎭 {reply}")


async def hookah_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    hookah_count[chat_id] += 1
    count = hookah_count[chat_id]
    await update.message.reply_text(f"💨 кальян #{count} зафіксовано")


async def hookahs_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    count = hookah_count[chat_id]
    await update.message.reply_text(f"💨 всього кальянів: {count}")


async def remind_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("напиши так: /нагадай 19:30 піти в зал")
        return
    text = " ".join(ctx.args)
    remind_time, what = parse_reminder(text)
    if not remind_time:
        await update.message.reply_text("не зрозумів час, напиши так: /нагадай 19:30 піти в зал")
        return
    user = update.message.from_user.first_name
    reminders.append({
        "chat_id": update.effective_chat.id,
        "user": user,
        "text": what,
        "time": remind_time
    })
    await update.message.reply_text(f"⏰ ok, нагадаю о {remind_time}: {what}")


# ──────────────────────────────────────────────
# Основной хендлер сообщений
# ──────────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    chat_id = update.effective_chat.id
    text = msg.text.strip()
    user_name = msg.from_user.first_name or "Аноним"
    bot_username = (await ctx.bot.get_me()).username
    is_private = update.effective_chat.type == "private"

    chat_history[chat_id].append({
        "role": "user",
        "content": f"{user_name}: {text}"
    })

    # Автодетект напоминалки
    remind_keywords = ["нагадай", "нагади", "нагадайте", "нагадати"]
    if any(kw in text.lower() for kw in remind_keywords):
        remind_time, what = parse_reminder(text)
        if remind_time and what:
            reminders.append({
                "chat_id": chat_id,
                "user": user_name,
                "text": what,
                "time": remind_time
            })
            await msg.reply_text(f"⏰ ok, нагадаю о {remind_time}: {what}")
            return

    # Автодетект кальяна
    if "кальян" in text.lower() and any(w in text.lower() for w in ["курим", "їдемо", "йдемо", "погнали", "покурили"]):
        hookah_count[chat_id] += 1
        count = hookah_count[chat_id]
        await msg.reply_text(f"💨 кальян #{count} зафіксовано, поїхали!")
        return

    is_reply_to_bot = (
        msg.reply_to_message and
        msg.reply_to_message.from_user and
        msg.reply_to_message.from_user.username == bot_username
    )
    is_mentioned = bot_username and f"@{bot_username}" in text
    is_name_mentioned = BOT_NAME.lower() in text.lower()
    should_reply = is_private or is_reply_to_bot or is_mentioned or is_name_mentioned

    random_jump = not should_reply and random.random() < RANDOM_REPLY_CHANCE

    if not should_reply and not random_jump:
        return

    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")

    if random_jump:
        prompt = (
            f"ти читав переписку. останнє повідомлення від {user_name}: «{text}». "
            f"влізь в розмову коротко і до теми — підтримай або додай щось корисне"
        )
        reply = ask_deepseek(chat_id, prompt_override=prompt)
    else:
        reply = ask_deepseek(chat_id)

    if reply:
        chat_history[chat_id].append({
            "role": "assistant",
            "content": reply
        })
        await msg.reply_text(reply)


# ──────────────────────────────────────────────
# ЗАПУСК
# ──────────────────────────────────────────────
async def post_init(app: Application):
    asyncio.create_task(daily_scheduler(app))
    asyncio.create_task(reminder_scheduler(app))


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("стата", cs_stats_cmd))
    app.add_handler(CommandHandler("мем", meme_cmd))
    app.add_handler(CommandHandler("кальян", hookah_cmd))
    app.add_handler(CommandHandler("кальяни", hookahs_cmd))
    app.add_handler(CommandHandler("нагадай", remind_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info(f"Бот {BOT_NAME} запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
