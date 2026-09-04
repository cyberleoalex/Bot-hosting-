# -*- coding: utf-8 -*-

"""
========================================================
        PROFESSIONAL TELEGRAM BOT HOSTING PANEL
========================================================

FEATURES
--------
👑 Admin Panel
💳 Credit System
➕ Add Credit
➖ Remove Credit
👤 User Management
📊 Statistics
📤 Upload Python Bot
📦 requirements.txt support
▶️ Start
⛔ Stop
🔄 Restart
📜 Logs
📊 Status
🗑 Delete Bot
💾 JSON Database
🐳 Docker = OFF
🐘 PostgreSQL = OFF

UPLOAD
------
/upload
   ↓
Send .py
   ↓
Send .txt requirements
   ↓
/finish
   ↓
Install requirements
   ↓
Start bot
   ↓
1 credit deducted ONLY after successful start

========================================================
"""

import asyncio
import html
import json
import logging
import os
import shutil
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ========================================================
# CONFIG
# ========================================================

BOT_TOKEN = "8853668764:AAG7AOd3kPSDxeImjDaK4sYybDsgVfXeuCA"

ADMIN_ID = 6776571573

ADMIN_USERNAME = "@alexhuntercct"

# প্রতি bot hosting এর জন্য কত credit কাটবে
BOT_CREDIT_COST = 1

# Requirements installation timeout
PIP_TIMEOUT = 1800

# Log maximum characters
MAX_LOG_CHARS = 7000


# ========================================================
# DIRECTORIES
# ========================================================

BASE_DIR = Path(__file__).resolve().parent

HOSTING_DIR = BASE_DIR / "hosted_bots"

LOG_DIR = BASE_DIR / "bot_logs"

TEMP_DIR = BASE_DIR / "temp_uploads"

DATA_FILE = BASE_DIR / "hosting_data.json"


HOSTING_DIR.mkdir(
    parents=True,
    exist_ok=True
)

LOG_DIR.mkdir(
    parents=True,
    exist_ok=True
)

TEMP_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ========================================================
# RUNTIME
# ========================================================

processes = {}

upload_sessions = {}

data_lock = asyncio.Lock()


# ========================================================
# LOGGING
# ========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("HostingPanel")


# ========================================================
# DATABASE
# ========================================================

def default_database():

    return {
        "users": {},
        "bots": {},
        "settings": {
            "bot_credit_cost": BOT_CREDIT_COST
        }
    }


def load_data():

    if not DATA_FILE.exists():

        return default_database()

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            result = json.load(f)

        if not isinstance(result, dict):
            return default_database()

        result.setdefault("users", {})
        result.setdefault("bots", {})
        result.setdefault(
            "settings",
            {
                "bot_credit_cost": BOT_CREDIT_COST
            }
        )

        return result

    except Exception as e:

        logger.error(
            "Database load error: %s",
            e
        )

        return default_database()


data = load_data()


def save_data():

    temp = DATA_FILE.with_suffix(".tmp")

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        temp,
        DATA_FILE
    )


# ========================================================
# BASIC HELPERS
# ========================================================

def now():

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def is_admin(user_id):

    return int(user_id) == int(ADMIN_ID)


def get_cost():

    try:

        return int(
            data.get(
                "settings",
                {}
            ).get(
                "bot_credit_cost",
                BOT_CREDIT_COST
            )
        )

    except Exception:

        return BOT_CREDIT_COST


def safe_filename(filename):

    filename = os.path.basename(
        filename or "file"
    )

    allowed = []

    for char in filename:

        if (
            char.isalnum()
            or char in "._-"
        ):
            allowed.append(char)

    result = "".join(allowed)

    return result or "file"


def bot_folder(bot_id):

    return HOSTING_DIR / str(bot_id)


def bot_log(bot_id):

    return LOG_DIR / f"{bot_id}.log"


def get_bot(bot_id):

    return data["bots"].get(
        str(bot_id)
    )


def get_user(user_id):

    return data["users"].get(
        str(user_id)
    )


# ========================================================
# USER SYSTEM
# ========================================================

def register_user(user):

    uid = str(user.id)

    if uid not in data["users"]:

        data["users"][uid] = {

            "id": user.id,

            "username":
                user.username,

            "first_name":
                user.first_name or "",

            "credits":
                0,

            "created_at":
                now()

        }

    else:

        data["users"][uid][
            "username"
        ] = user.username

        data["users"][uid][
            "first_name"
        ] = user.first_name or ""

    save_data()


def user_credits(user_id):

    user = get_user(user_id)

    if not user:
        return 0

    return int(
        user.get(
            "credits",
            0
        )
    )


def add_credit(user_id, amount):

    user_id = str(user_id)

    if user_id not in data["users"]:

        data["users"][user_id] = {

            "id": int(user_id),

            "username": "",

            "first_name": "",

            "credits": 0,

            "created_at": now()
        }

    data["users"][user_id][
        "credits"
    ] = max(
        0,
        int(
            data["users"][user_id].get(
                "credits",
                0
            )
        ) + int(amount)
    )

    save_data()


def remove_credit(user_id, amount):

    user_id = str(user_id)

    if user_id not in data["users"]:
        return False

    current = user_credits(
        user_id
    )

    if current < amount:
        return False

    data["users"][user_id][
        "credits"
    ] = current - amount

    save_data()

    return True


# ========================================================
# PROCESS
# ========================================================

def is_running(bot_id):

    process = processes.get(
        str(bot_id)
    )

    if not process:
        return False

    return process.returncode is None


# ========================================================
# LOCAL LOG
# ========================================================

def write_log(bot_id, message):

    try:

        with open(
            bot_log(bot_id),
            "a",
            encoding="utf-8",
            errors="replace",
            buffering=1
        ) as f:

            f.write(
                f"[{now()}] {message}\n"
            )

            f.flush()

    except Exception as e:

        logger.error(
            "Write log error: %s",
            e
        )


def read_logs(bot_id):

    path = bot_log(
        bot_id
    )

    if not path.exists():

        return "📭 কোনো log পাওয়া যায়নি।"

    try:

        with open(
            path,
            "r",
            encoding="utf-8",
            errors="replace"
        ) as f:

            content = f.read()

        if not content.strip():

            return "📭 Log এখনো খালি।"

        if len(content) > MAX_LOG_CHARS:

            content = (
                "...\n"
                "[Old logs trimmed]\n\n"
                + content[-MAX_LOG_CHARS:]
            )

        return content

    except Exception as e:

        return f"❌ Log error: {e}"


# ========================================================
# REQUIREMENTS
# ========================================================

async def install_requirements(bot_id):

    bot = get_bot(
        bot_id
    )

    if not bot:
        return False, "Bot পাওয়া যায়নি।"

    requirements = bot.get(
        "requirements"
    )

    if not requirements:

        write_log(
            bot_id,
            "No requirements.txt."
        )

        return True, "No requirements."

    req = (
        bot_folder(bot_id)
        / requirements
    )

    if not req.exists():

        write_log(
            bot_id,
            "requirements file missing."
        )

        return False, (
            "requirements file পাওয়া যায়নি।"
        )

    write_log(
        bot_id,
        "Installing requirements..."
    )

    try:

        process = await asyncio.create_subprocess_exec(

            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(req),
            "--disable-pip-version-check",

            cwd=str(
                bot_folder(bot_id)
            ),

            stdout=asyncio.subprocess.PIPE,

            stderr=asyncio.subprocess.STDOUT
        )

        async def reader():

            while True:

                line = await process.stdout.readline()

                if not line:
                    break

                text = line.decode(
                    "utf-8",
                    errors="replace"
                ).rstrip()

                write_log(
                    bot_id,
                    "[PIP] " + text
                )

        try:

            await asyncio.wait_for(
                reader(),
                timeout=PIP_TIMEOUT
            )

        except asyncio.TimeoutError:

            try:
                process.kill()
            except Exception:
                pass

            await process.wait()

            write_log(
                bot_id,
                "Requirements installation timeout."
            )

            return False, (
                "Requirements installation timeout."
            )

        code = await process.wait()

        if code != 0:

            write_log(
                bot_id,
                f"PIP failed. Exit code: {code}"
            )

            return False, (
                f"Requirements install failed.\n"
                f"Exit code: {code}"
            )

        write_log(
            bot_id,
            "Requirements installed successfully."
        )

        return True, (
            "Requirements installed successfully."
        )

    except Exception as e:

        write_log(
            bot_id,
            f"PIP error: {e}"
        )

        return False, str(e)


# ========================================================
# START BOT
# ========================================================

async def start_bot(
    bot_id,
    deduct_credit=False
):

    bot_id = str(bot_id)

    bot = get_bot(
        bot_id
    )

    if not bot:

        return False, (
            "❌ Bot পাওয়া যায়নি।"
        )

    owner_id = bot.get(
        "owner_id"
    )

    # ----------------------------------------------------
    # Running check
    # ----------------------------------------------------

    if is_running(bot_id):

        return False, (
            "⚠️ Bot ইতোমধ্যে running আছে।"
        )

    folder = bot_folder(
        bot_id
    )

    script_name = bot.get(
        "script"
    )

    if not script_name:

        return False, (
            "❌ Python file পাওয়া যায়নি।"
        )

    script = folder / script_name

    if not script.exists():

        bot["status"] = "error"

        bot["error"] = (
            "Python file missing."
        )

        save_data()

        return False, (
            "❌ Python file পাওয়া যায়নি।"
        )

    # ----------------------------------------------------
    # Credit check
    # ----------------------------------------------------

    cost = get_cost()

    if deduct_credit:

        if user_credits(owner_id) < cost:

            return False, (
                "❌ পর্যাপ্ত credit নেই।\n\n"
                f"💳 প্রয়োজন: {cost}\n"
                f"💰 আপনার credit: "
                f"{user_credits(owner_id)}"
            )

    # ----------------------------------------------------
    # Requirements
    # ----------------------------------------------------

    if bot.get("requirements"):

        bot["status"] = "installing"

        save_data()

        ok, message = await install_requirements(
            bot_id
        )

        if not ok:

            bot["status"] = "error"
            bot["error"] = message

            save_data()

            return False, (
                "❌ Requirements install failed.\n\n"
                + message
            )

    # ----------------------------------------------------
    # Log
    # ----------------------------------------------------

    write_log(
        bot_id,
        "========================================"
    )

    write_log(
        bot_id,
        "Starting bot..."
    )

    write_log(
        bot_id,
        f"Python: {sys.executable}"
    )

    write_log(
        bot_id,
        f"Script: {script_name}"
    )

    write_log(
        bot_id,
        "Docker: DISABLED"
    )

    # ----------------------------------------------------
    # Environment
    # ----------------------------------------------------

    env = os.environ.copy()

    env["PYTHONUNBUFFERED"] = "1"

    env["PYTHONIOENCODING"] = "utf-8"

    # ----------------------------------------------------
    # Log file
    # ----------------------------------------------------

    try:

        log_file = open(
            bot_log(bot_id),
            "a",
            encoding="utf-8",
            buffering=1
        )

    except Exception as e:

        return False, (
            f"❌ Log file error: {e}"
        )

    # ----------------------------------------------------
    # Start subprocess
    # ----------------------------------------------------

    try:

        process = await asyncio.create_subprocess_exec(

            sys.executable,

            "-u",

            str(script),

            cwd=str(folder),

            stdin=asyncio.subprocess.DEVNULL,

            stdout=log_file,

            stderr=log_file,

            env=env

        )

    except Exception as e:

        log_file.close()

        write_log(
            bot_id,
            f"Process start failed: {e}"
        )

        bot["status"] = "error"
        bot["error"] = str(e)

        save_data()

        return False, (
            f"❌ Bot start failed:\n{e}"
        )

    processes[bot_id] = process

    # ----------------------------------------------------
    # Save running
    # ----------------------------------------------------

    bot["status"] = "running"

    bot["pid"] = process.pid

    bot["started_at"] = now()

    bot["stopped_at"] = None

    bot["error"] = None

    save_data()

    write_log(
        bot_id,
        f"Bot started. PID={process.pid}"
    )

    # ----------------------------------------------------
    # CREDIT DEDUCT
    # ----------------------------------------------------

    if deduct_credit:

        current = user_credits(
            owner_id
        )

        if current < cost:

            # Extremely unlikely because checked before.
            # Stop bot to avoid unpaid hosting.

            await stop_bot(
                bot_id
            )

            return False, (
                "❌ Credit কম থাকায় bot বন্ধ করা হয়েছে।"
            )

        data["users"][
            str(owner_id)
        ]["credits"] = current - cost

        bot["credit_charged"] = cost

        bot["credit_charged_at"] = now()

        save_data()

        write_log(
            bot_id,
            f"Credit deducted: {cost}"
        )

    # ----------------------------------------------------
    # Monitor
    # ----------------------------------------------------

    asyncio.create_task(
        monitor_bot(
            bot_id,
            process,
            log_file
        )
    )

    return True, (
        "✅ <b>Bot Started Successfully!</b>\n\n"
        f"🆔 Bot ID: <code>{bot_id}</code>\n"
        f"📄 File: <code>{html.escape(script_name)}</code>\n"
        f"🟢 PID: <code>{process.pid}</code>"
    )


# ========================================================
# MONITOR
# ========================================================

async def monitor_bot(
    bot_id,
    process,
    log_file
):

    bot_id = str(bot_id)

    try:

        code = await process.wait()

        write_log(
            bot_id,
            f"Bot stopped. Exit code: {code}"
        )

        bot = get_bot(
            bot_id
        )

        if bot:

            bot["status"] = "stopped"

            bot["pid"] = None

            bot["last_exit_code"] = code

            bot["stopped_at"] = now()

            save_data()

    except Exception as e:

        write_log(
            bot_id,
            f"Monitor error: {e}"
        )

    finally:

        try:
            log_file.close()
        except Exception:
            pass

        processes.pop(
            bot_id,
            None
        )


# ========================================================
# STOP
# ========================================================

async def stop_bot(bot_id):

    bot_id = str(bot_id)

    process = processes.get(
        bot_id
    )

    if not process:

        bot = get_bot(
            bot_id
        )

        if bot:

            bot["status"] = "stopped"

            bot["pid"] = None

            save_data()

        return False, (
            "⚠️ Bot running নেই।"
        )

    write_log(
        bot_id,
        "Stopping bot..."
    )

    try:

        if os.name == "nt":

            process.terminate()

        else:

            process.send_signal(
                signal.SIGTERM
            )

    except Exception:

        try:
            process.terminate()
        except Exception:
            pass

    try:

        await asyncio.wait_for(
            process.wait(),
            timeout=10
        )

    except asyncio.TimeoutError:

        write_log(
            bot_id,
            "Force killing process..."
        )

        try:
            process.kill()
        except Exception:
            pass

        try:
            await process.wait()
        except Exception:
            pass

    bot = get_bot(
        bot_id
    )

    if bot:

        bot["status"] = "stopped"

        bot["pid"] = None

        bot["stopped_at"] = now()

        save_data()

    processes.pop(
        bot_id,
        None
    )

    write_log(
        bot_id,
        "Bot stopped successfully."
    )

    return True, (
        "🛑 Bot stopped successfully."
    )


# ========================================================
# RESTART
# ========================================================

async def restart_bot(bot_id):

    await stop_bot(
        bot_id
    )

    await asyncio.sleep(1)

    return await start_bot(
        bot_id,
        deduct_credit=False
    )


# ========================================================
# MAIN MENU
# ========================================================

def main_menu(user_id):

    buttons = [

        [
            InlineKeyboardButton(
                "📤 Upload Bot",
                callback_data="upload"
            )
        ],

        [
            InlineKeyboardButton(
                "🤖 My Bots",
                callback_data="mybots"
            )
        ],

        [
            InlineKeyboardButton(
                "💳 My Credit",
                callback_data="credit"
            )
        ],

        [
            InlineKeyboardButton(
                "📊 Panel Status",
                callback_data="panel_status"
            )
        ]

    ]

    if is_admin(user_id):

        buttons.append([

            InlineKeyboardButton(
                "👑 Admin Panel",
                callback_data="admin"
            )

        ])

    return InlineKeyboardMarkup(
        buttons
    )


# ========================================================
# BOT BUTTONS
# ========================================================

def bot_buttons(bot_id):

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "▶️ Start",
                callback_data=f"start:{bot_id}"
            ),

            InlineKeyboardButton(
                "⛔ Stop",
                callback_data=f"stop:{bot_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "🔄 Restart",
                callback_data=f"restart:{bot_id}"
            ),

            InlineKeyboardButton(
                "📊 Status",
                callback_data=f"status:{bot_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "📜 Logs",
                callback_data=f"logs:{bot_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "🗑 Delete",
                callback_data=f"delete:{bot_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 My Bots",
                callback_data="mybots"
            )
        ]

    ])


# ========================================================
# ADMIN MENU
# ========================================================

def admin_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📊 Statistics",
                callback_data="admin_stats"
            )
        ],

        [
            InlineKeyboardButton(
                "➕ Add Credit",
                callback_data="admin_add"
            ),

            InlineKeyboardButton(
                "➖ Remove Credit",
                callback_data="admin_remove"
            )
        ],

        [
            InlineKeyboardButton(
                "👥 Users",
                callback_data="admin_users"
            )
        ],

        [
            InlineKeyboardButton(
                "🤖 All Bots",
                callback_data="admin_bots"
            )
        ],

        [
            InlineKeyboardButton(
                "💰 Hosting Cost",
                callback_data="admin_cost"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 Main Menu",
                callback_data="home"
            )
        ]

    ])


# ========================================================
# START COMMAND
# ========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    register_user(
        user
    )

    text = (
        "🚀 <b>Professional Bot Hosting Panel</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🐍 Python Bot Hosting\n"
        "📦 Requirements Support\n"
        "▶️ Start / Stop / Restart\n"
        "📜 Local Logs\n"
        "💳 Credit System\n"
        "💾 JSON Database\n"
        "🐳 Docker: OFF\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💳 আপনার Credit: "
        f"<b>{user_credits(user.id)}</b>\n\n"
        "নিচের menu থেকে option নির্বাচন করুন।"
    )

    await update.message.reply_text(

        text,

        parse_mode="HTML",

        reply_markup=main_menu(
            user.id
        )
    )


# ========================================================
# UPLOAD
# ========================================================

async def upload_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    register_user(
        user
    )

    cost = get_cost()

    if user_credits(user.id) < cost:

        await update.message.reply_text(

            "❌ <b>Insufficient Credit</b>\n\n"

            f"💰 আপনার credit: "
            f"<b>{user_credits(user.id)}</b>\n"

            f"💳 প্রয়োজন: "
            f"<b>{cost}</b>\n\n"

            "Admin-এর সাথে যোগাযোগ করুন।",

            parse_mode="HTML"
        )

        return

    upload_sessions[user.id] = {

        "py_file": None,

        "requirements": None

    }

    await update.message.reply_text(

        "📤 <b>Upload Session Started</b>\n\n"

        "1️⃣ এখন আপনার <code>.py</code> file পাঠান।\n\n"

        "2️⃣ এরপর requirements-এর জন্য "
        "<code>.txt</code> file পাঠান।\n\n"

        "3️⃣ requirements না থাকলে "
        "<code>/finish</code> দিন।\n\n"

        f"💳 Hosting Cost: <b>{cost} credit</b>\n\n"

        "⚠️ Bot successfully start হওয়ার পরই credit কাটবে।",

        parse_mode="HTML"
    )


# ========================================================
# DOCUMENT
# ========================================================

async def document_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    register_user(
        user
    )

    session = upload_sessions.get(
        user.id
    )

    if not session:

        await update.message.reply_text(

            "❌ কোনো upload session নেই।\n\n"

            "প্রথমে /upload দিন।"
        )

        return

    document = update.message.document

    filename = safe_filename(
        document.file_name
    )

    # ----------------------------------------------------
    # PYTHON
    # ----------------------------------------------------

    if filename.lower().endswith(".py"):

        if session["py_file"]:

            await update.message.reply_text(
                "⚠️ একটি .py file ইতোমধ্যে দেওয়া হয়েছে।"
            )

            return

        path = TEMP_DIR / (
            f"{user.id}_{int(time.time())}_{filename}"
        )

        try:

            tg_file = await document.get_file()

            await tg_file.download_to_drive(
                custom_path=str(path)
            )

            session["py_file"] = {

                "filename": filename,

                "path": str(path)

            }

            await update.message.reply_text(

                "✅ <b>Python file received!</b>\n\n"

                f"📄 <code>{html.escape(filename)}</code>\n\n"

                "এখন requirements.txt পাঠান।\n"

                "Requirements না থাকলে:\n"
                "<code>/finish</code>",

                parse_mode="HTML"
            )

        except Exception as e:

            await update.message.reply_text(
                f"❌ Download error:\n{e}"
            )

        return

    # ----------------------------------------------------
    # TXT
    # ----------------------------------------------------

    if filename.lower().endswith(".txt"):

        if not session["py_file"]:

            await update.message.reply_text(
                "⚠️ আগে .py file পাঠান।"
            )

            return

        if session["requirements"]:

            await update.message.reply_text(
                "⚠️ Requirements file ইতোমধ্যে দেওয়া হয়েছে।"
            )

            return

        path = TEMP_DIR / (
            f"{user.id}_{int(time.time())}_{filename}"
        )

        try:

            tg_file = await document.get_file()

            await tg_file.download_to_drive(
                custom_path=str(path)
            )

            session["requirements"] = {

                "filename": filename,

                "path": str(path)

            }

            await update.message.reply_text(

                "✅ <b>Requirements received!</b>\n\n"

                f"📦 <code>{html.escape(filename)}</code>\n\n"

                "এখন <code>/finish</code> দিন।",

                parse_mode="HTML"
            )

        except Exception as e:

            await update.message.reply_text(
                f"❌ Download error:\n{e}"
            )

        return

    await update.message.reply_text(

        "❌ শুধু <b>.py</b> অথবা <b>.txt</b> file পাঠান।",

        parse_mode="HTML"
    )


# ========================================================
# FINISH
# ========================================================

async def finish_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    register_user(
        user
    )

    session = upload_sessions.get(
        user.id
    )

    if not session:

        await update.message.reply_text(
            "❌ কোনো upload session নেই।"
        )

        return

    if not session["py_file"]:

        await update.message.reply_text(
            "❌ আগে .py file পাঠান।"
        )

        return

    cost = get_cost()

    # ----------------------------------------------------
    # CREDIT RECHECK
    # ----------------------------------------------------

    if user_credits(user.id) < cost:

        await update.message.reply_text(

            "❌ Credit কম।\n\n"

            f"💰 আপনার credit: "
            f"{user_credits(user.id)}\n"

            f"💳 প্রয়োজন: {cost}"
        )

        return

    # ----------------------------------------------------
    # BOT ID
    # ----------------------------------------------------

    bot_id = str(
        int(time.time() * 1000)
    )

    folder = bot_folder(
        bot_id
    )

    folder.mkdir(
        parents=True,
        exist_ok=True
    )

    py = session["py_file"]

    requirements = session.get(
        "requirements"
    )

    script_name = safe_filename(
        py["filename"]
    )

    # ----------------------------------------------------
    # Copy Python
    # ----------------------------------------------------

    try:

        shutil.copy2(
            py["path"],
            folder / script_name
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ Python file copy failed:\n{e}"
        )

        return

    # ----------------------------------------------------
    # Copy requirements
    # ----------------------------------------------------

    requirements_name = None

    if requirements:

        requirements_name = safe_filename(
            requirements["filename"]
        )

        try:

            shutil.copy2(
                requirements["path"],
                folder / requirements_name
            )

        except Exception as e:

            await update.message.reply_text(
                f"❌ Requirements copy failed:\n{e}"
            )

            return

    # ----------------------------------------------------
    # Save record
    # ----------------------------------------------------

    data["bots"][bot_id] = {

        "id":
            bot_id,

        "owner_id":
            user.id,

        "owner_username":
            user.username,

        "script":
            script_name,

        "requirements":
            requirements_name,

        "status":
            "created",

        "pid":
            None,

        "created_at":
            now(),

        "started_at":
            None,

        "stopped_at":
            None,

        "error":
            None,

        "credit_charged":
            0

    }

    save_data()

    # ----------------------------------------------------
    # Remove temp
    # ----------------------------------------------------

    for item in [
        py,
        requirements
    ]:

        if item:

            try:

                os.remove(
                    item["path"]
                )

            except Exception:
                pass

    upload_sessions.pop(
        user.id,
        None
    )

    await update.message.reply_text(

        "⏳ <b>Bot processing...</b>\n\n"

        "📦 Requirements install হচ্ছে।\n"
        "🚀 তারপর bot start হবে।\n\n"

        "💳 Bot successfully start হলে "
        f"<b>{cost} credit</b> কাটা হবে।",

        parse_mode="HTML"
    )

    # ----------------------------------------------------
    # START + CREDIT
    # ----------------------------------------------------

    ok, message = await start_bot(

        bot_id,

        deduct_credit=True
    )

    if ok:

        await update.message.reply_text(

            message

            + "\n\n"

            f"💳 Credit charged: <b>{cost}</b>\n"

            f"💰 Remaining credit: "
            f"<b>{user_credits(user.id)}</b>",

            parse_mode="HTML",

            reply_markup=bot_buttons(
                bot_id
            )
        )

    else:

        await update.message.reply_text(

            "❌ <b>Bot Start Failed</b>\n\n"

            f"<code>{html.escape(str(message))}</code>\n\n"

            "💳 আপনার credit কাটা হয়নি।\n"

            "📜 Logs দেখতে নিচের button ব্যবহার করুন।",

            parse_mode="HTML",

            reply_markup=bot_buttons(
                bot_id
            )
        )


# ========================================================
# MY BOTS
# ========================================================

async def my_bots_text(user_id):

    bots = [

        (bot_id, bot)

        for bot_id, bot
        in data["bots"].items()

        if (
            bot.get("owner_id")
            == user_id
        )

    ]

    if not bots:

        return (

            "🤖 <b>My Bots</b>\n\n"

            "আপনার কোনো hosted bot নেই।"

        ), InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "📤 Upload Bot",
                    callback_data="upload"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔙 Main Menu",
                    callback_data="home"
                )
            ]

        ])

    text = (
        "🤖 <b>My Hosted Bots</b>\n\n"
    )

    buttons = []

    for bot_id, bot in bots:

        if is_running(bot_id):

            status = "🟢 Running"

        elif bot.get("status") == "error":

            status = "❌ Error"

        elif bot.get("status") == "installing":

            status = "⏳ Installing"

        else:

            status = "🔴 Stopped"

        text += (

            f"🆔 <code>{bot_id}</code>\n"

            f"📄 "
            f"{html.escape(bot.get('script', ''))}\n"

            f"📊 {status}\n\n"

        )

        buttons.append([

            InlineKeyboardButton(

                f"🤖 {bot.get('script', 'Bot')}",

                callback_data=f"manage:{bot_id}"

            )

        ])

    buttons.append([

        InlineKeyboardButton(
            "📤 Upload New Bot",
            callback_data="upload"
        )

    ])

    buttons.append([

        InlineKeyboardButton(
            "🔙 Main Menu",
            callback_data="home"
        )

    ])

    return text, InlineKeyboardMarkup(
        buttons
    )


# ========================================================
# STATUS
# ========================================================

def status_text(bot_id):

    bot = get_bot(
        bot_id
    )

    if not bot:

        return "❌ Bot পাওয়া যায়নি।"

    if is_running(bot_id):

        status = "🟢 RUNNING"

        process = processes.get(
            bot_id
        )

        pid = (
            process.pid
            if process
            else bot.get("pid")
        )

    else:

        status = "🔴 STOPPED"

        pid = (
            bot.get("pid")
            or "N/A"
        )

    return (

        "📊 <b>Bot Status</b>\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"🆔 ID: <code>{bot_id}</code>\n"

        f"📄 Script: "
        f"<code>{html.escape(bot.get('script', ''))}</code>\n"

        f"📊 Status: <b>{status}</b>\n"

        f"🔢 PID: <code>{pid}</code>\n"

        f"📅 Created: "
        f"<code>{bot.get('created_at', '-')}</code>\n"

        f"🚀 Started: "
        f"<code>{bot.get('started_at', '-')}</code>\n"

        f"🛑 Stopped: "
        f"<code>{bot.get('stopped_at', '-')}</code>\n"

        f"💳 Charged: "
        f"<code>{bot.get('credit_charged', 0)}</code>\n"

        "━━━━━━━━━━━━━━━━━━━━"

    )


# ========================================================
# ADMIN CHECK
# ========================================================

def admin_only(user_id):

    return is_admin(
        user_id
    )


# ========================================================
# ADMIN STATS
# ========================================================

def admin_stats_text():

    total_users = len(
        data["users"]
    )

    total_bots = len(
        data["bots"]
    )

    running = sum(

        1

        for bot_id
        in data["bots"]

        if is_running(bot_id)

    )

    stopped = (
        total_bots
        - running
    )

    total_credit = sum(

        int(
            user.get(
                "credits",
                0
            )
        )

        for user
        in data["users"].values()

    )

    charged = sum(

        int(
            bot.get(
                "credit_charged",
                0
            )
        )

        for bot
        in data["bots"].values()

    )

    return (

        "👑 <b>ADMIN STATISTICS</b>\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"👥 Users: <b>{total_users}</b>\n"

        f"🤖 Total Bots: <b>{total_bots}</b>\n"

        f"🟢 Running: <b>{running}</b>\n"

        f"🔴 Stopped: <b>{stopped}</b>\n"

        f"💰 User Credits: <b>{total_credit}</b>\n"

        f"💳 Total Charged: <b>{charged}</b>\n"

        f"💵 Hosting Cost: "
        f"<b>{get_cost()}</b>\n"

        "🐳 Docker: <b>OFF</b>\n"

        "🐘 PostgreSQL: <b>OFF</b>\n"

        "💾 Database: <b>JSON</b>\n"

        "━━━━━━━━━━━━━━━━━━━━"

    )


# ========================================================
# ADMIN COMMAND
# ========================================================

async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    register_user(
        user
    )

    if not admin_only(user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    await update.message.reply_text(

        "👑 <b>ADMIN PANEL</b>\n\n"

        "আপনার admin option নির্বাচন করুন।",

        parse_mode="HTML",

        reply_markup=admin_menu()
    )


# ========================================================
# ADD CREDIT COMMAND
# ========================================================

async def addcredit_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not admin_only(user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    if len(context.args) < 2:

        await update.message.reply_text(

            "Usage:\n"

            "<code>/addcredit USER_ID AMOUNT</code>\n\n"

            "Example:\n"

            "<code>/addcredit 123456789 10</code>",

            parse_mode="HTML"
        )

        return

    try:

        target = int(
            context.args[0]
        )

        amount = int(
            context.args[1]
        )

        if amount <= 0:

            raise ValueError

    except Exception:

        await update.message.reply_text(
            "❌ Invalid user ID বা amount."
        )

        return

    add_credit(
        target,
        amount
    )

    await update.message.reply_text(

        "✅ <b>Credit Added</b>\n\n"

        f"👤 User: <code>{target}</code>\n"

        f"➕ Added: <b>{amount}</b>\n"

        f"💰 Total: "
        f"<b>{user_credits(target)}</b>",

        parse_mode="HTML"
    )


# ========================================================
# REMOVE CREDIT COMMAND
# ========================================================

async def removecredit_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not admin_only(user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    if len(context.args) < 2:

        await update.message.reply_text(

            "Usage:\n"

            "<code>/removecredit USER_ID AMOUNT</code>",

            parse_mode="HTML"
        )

        return

    try:

        target = int(
            context.args[0]
        )

        amount = int(
            context.args[1]
        )

        if amount <= 0:
            raise ValueError

    except Exception:

        await update.message.reply_text(
            "❌ Invalid input."
        )

        return

    ok = remove_credit(
        target,
        amount
    )

    if not ok:

        await update.message.reply_text(

            "❌ Credit remove করা যায়নি।\n"

            "User-এর credit যথেষ্ট নেই।"

        )

        return

    await update.message.reply_text(

        "✅ <b>Credit Removed</b>\n\n"

        f"👤 User: <code>{target}</code>\n"

        f"➖ Removed: <b>{amount}</b>\n"

        f"💰 Remaining: "
        f"<b>{user_credits(target)}</b>",

        parse_mode="HTML"
    )


# ========================================================
# USERS ADMIN VIEW
# ========================================================

def admin_users_text():

    users = list(
        data["users"].items()
    )

    users.sort(
        key=lambda x:
        int(
            x[1].get(
                "credits",
                0
            )
        ),
        reverse=True
    )

    text = (
        "👥 <b>USERS</b>\n\n"
    )

    if not users:

        return "কোনো user নেই।"

    for uid, user in users[:50]:

        username = user.get(
            "username"
        )

        if username:

            name = "@"+username

        else:

            name = user.get(
                "first_name",
                "Unknown"
            )

        text += (

            f"👤 {html.escape(str(name))}\n"

            f"🆔 <code>{uid}</code>\n"

            f"💳 Credit: "
            f"<b>{user.get('credits', 0)}</b>\n\n"

        )

    return text


# ========================================================
# ADMIN BOT LIST
# ========================================================

def admin_bots_text():

    bots = list(
        data["bots"].items()
    )

    text = (
        "🤖 <b>ALL BOTS</b>\n\n"
    )

    if not bots:

        return "কোনো bot নেই।"

    for bot_id, bot in bots[-50:]:

        status = (
            "🟢 Running"
            if is_running(bot_id)
            else "🔴 Stopped"
        )

        text += (

            f"🆔 <code>{bot_id}</code>\n"

            f"📄 "
            f"{html.escape(bot.get('script', ''))}\n"

            f"👤 Owner: "
            f"<code>{bot.get('owner_id')}</code>\n"

            f"📊 {status}\n\n"

        )

    return text


# ========================================================
# CALLBACK HANDLER
# ========================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    action = query.data

    register_user(
        query.from_user
    )

    # ----------------------------------------------------
    # HOME
    # ----------------------------------------------------

    if action == "home":

        await query.edit_message_text(

            "🚀 <b>Professional Bot Hosting Panel</b>\n\n"

            f"💳 Credit: "
            f"<b>{user_credits(user_id)}</b>\n\n"

            "Option নির্বাচন করুন।",

            parse_mode="HTML",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    # ----------------------------------------------------
    # UPLOAD
    # ----------------------------------------------------

    if action == "upload":

        cost = get_cost()

        if user_credits(user_id) < cost:

            await query.answer(
                "❌ আপনার credit নেই!",
                show_alert=True
            )

            return

        upload_sessions[user_id] = {

            "py_file": None,

            "requirements": None

        }

        await query.edit_message_text(

            "📤 <b>Upload Started</b>\n\n"

            "এখন .py file পাঠান।\n\n"

            "Requirements.txt ফাইল দিতে হবে বাধ্যতামূলক"
            "<code>File</code> দিন।\n\n"

            f"💳 Cost: <b>{cost}</b> credit",

            parse_mode="HTML"
        )

        return

    # ----------------------------------------------------
    # CREDIT
    # ----------------------------------------------------

    if action == "credit":

        await query.edit_message_text(

            "💳 <b>My Credit</b>\n\n"

            f"💰 Available Credit: "
            f"<b>{user_credits(user_id)}</b>\n\n"

            f"🤖 Hosting Cost: "
            f"<b>{get_cost()} credit</b>\n\n"

            f"👑 Credit নিতে Admin: "
            f"<b>{ADMIN_USERNAME}</b>",

            parse_mode="HTML",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🔙 Main Menu",
                        callback_data="home"
                    )
                ]

            ])
        )

        return

    # ----------------------------------------------------
    # MY BOTS
    # ----------------------------------------------------

    if action == "mybots":

        text, keyboard = await my_bots_text(
            user_id
        )

        await query.edit_message_text(

            text,

            parse_mode="HTML",

            reply_markup=keyboard
        )

        return

    # ----------------------------------------------------
    # PANEL STATUS
    # ----------------------------------------------------

    if action == "panel_status":

        total = len(
            data["bots"]
        )

        running = sum(

            1

            for bot_id
            in data["bots"]

            if is_running(bot_id)

        )

        await query.edit_message_text(

            "📊 <b>Panel Status</b>\n\n"

            f"👥 Users: <b>{len(data['users'])}</b>\n"

            f"🤖 Bots: <b>{total}</b>\n"

            f"🟢 Running: <b>{running}</b>\n"

            f"🔴 Stopped: <b>{total-running}</b>\n"

            "🐳 Docker: <b>OFF</b>\n"

            "🐘 PostgreSQL: <b>OFF</b>\n"

            "💾 JSON: <b>ON</b>",

            parse_mode="HTML",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    # ====================================================
    # ADMIN
    # ====================================================

    if action == "admin":

        if not admin_only(user_id):

            await query.answer(
                "❌ Admin only!",
                show_alert=True
            )

            return

        await query.edit_message_text(

            "👑 <b>ADMIN PANEL</b>\n\n"

            "নিচের option নির্বাচন করুন।",

            parse_mode="HTML",

            reply_markup=admin_menu()
        )

        return

    # ----------------------------------------------------
    # ADMIN STATS
    # ----------------------------------------------------

    if action == "admin_stats":

        if not admin_only(user_id):
            return

        await query.edit_message_text(

            admin_stats_text(),

            parse_mode="HTML",

            reply_markup=admin_menu()
        )

        return

    # ----------------------------------------------------
    # ADMIN USERS
    # ----------------------------------------------------

    if action == "admin_users":

        if not admin_only(user_id):
            return

        await query.edit_message_text(

            admin_users_text(),

            parse_mode="HTML",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🔙 Admin Panel",
                        callback_data="admin"
                    )
                ]

            ])
        )

        return

    # ----------------------------------------------------
    # ADMIN BOTS
    # ----------------------------------------------------

    if action == "admin_bots":

        if not admin_only(user_id):
            return

        await query.edit_message_text(

            admin_bots_text(),

            parse_mode="HTML",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🔙 Admin Panel",
                        callback_data="admin"
                    )
                ]

            ])
        )

        return

    # ----------------------------------------------------
    # ADMIN ADD
    # ----------------------------------------------------

    if action == "admin_add":

        if not admin_only(user_id):
            return

        await query.edit_message_text(

            "➕ <b>ADD CREDIT</b>\n\n"

            "Command ব্যবহার করুন:\n\n"

            "<code>/addcredit USER_ID AMOUNT</code>\n\n"

            "Example:\n"

            "<code>/addcredit 123456789 10</code>",

            parse_mode="HTML",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🔙 Admin Panel",
                        callback_data="admin"
                    )
                ]

            ])
        )

        return

    # ----------------------------------------------------
    # ADMIN REMOVE
    # ----------------------------------------------------

    if action == "admin_remove":

        if not admin_only(user_id):
            return

        await query.edit_message_text(

            "➖ <b>REMOVE CREDIT</b>\n\n"

            "Command:\n\n"

            "<code>/removecredit USER_ID AMOUNT</code>\n\n"

            "Example:\n"

            "<code>/removecredit 123456789 5</code>",

            parse_mode="HTML",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🔙 Admin Panel",
                        callback_data="admin"
                    )
                ]

            ])
        )

        return

    # ----------------------------------------------------
    # ADMIN COST
    # ----------------------------------------------------

    if action == "admin_cost":

        if not admin_only(user_id):
            return

        await query.edit_message_text(

            "💰 <b>HOSTING COST</b>\n\n"

            f"বর্তমান cost: "
            f"<b>{get_cost()} credit</b>\n\n"

            "Code-এর CONFIG section থেকে "
            "BOT_CREDIT_COST পরিবর্তন করতে পারবেন।",

            parse_mode="HTML",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🔙 Admin Panel",
                        callback_data="admin"
                    )
                ]

            ])
        )

        return

    # ====================================================
    # MANAGE BOT
    # ====================================================

    if action.startswith("manage:"):

        bot_id = action.split(
            ":",
            1
        )[1]

        bot = get_bot(
            bot_id
        )

        if not bot:

            await query.edit_message_text(
                "❌ Bot পাওয়া যায়নি।"
            )

            return

        if (

            bot.get("owner_id")
            != user_id

            and not admin_only(user_id)

        ):

            await query.answer(
                "❌ Access denied!",
                show_alert=True
            )

            return

        await query.edit_message_text(

            status_text(
                bot_id
            ),

            parse_mode="HTML",

            reply_markup=bot_buttons(
                bot_id
            )
        )

        return

    # ====================================================
    # START BOT
    # ====================================================

    if action.startswith("start:"):

        bot_id = action.split(
            ":",
            1
        )[1]

        bot = get_bot(
            bot_id
        )

        if not bot:
            return

        if (

            bot.get("owner_id")
            != user_id

            and not admin_only(user_id)

        ):

            await query.answer(
                "❌ Access denied!",
                show_alert=True
            )

            return

        # Admin restart/start should not charge
        charge = not admin_only(
            user_id
        )

        if charge and user_credits(
            user_id
        ) < get_cost():

            await query.answer(
                "❌ Credit নেই!",
                show_alert=True
            )

            return

        await query.edit_message_text(
            "⏳ <b>Starting bot...</b>",
            parse_mode="HTML"
        )

        ok, message = await start_bot(

            bot_id,

            deduct_credit=charge

        )

        if ok and charge:

            message += (

                "\n\n💳 Charged: "
                f"<b>{get_cost()}</b>\n"

                "💰 Remaining: "
                f"<b>{user_credits(user_id)}</b>"

            )

        await query.edit_message_text(

            message,

            parse_mode="HTML",

            reply_markup=bot_buttons(
                bot_id
            )
        )

        return

    # ====================================================
    # STOP
    # ====================================================

    if action.startswith("stop:"):

        bot_id = action.split(
            ":",
            1
        )[1]

        bot = get_bot(
            bot_id
        )

        if not bot:
            return

        if (

            bot.get("owner_id")
            != user_id

            and not admin_only(user_id)

        ):

            await query.answer(
                "❌ Access denied!",
                show_alert=True
            )

            return

        ok, message = await stop_bot(
            bot_id
        )

        await query.edit_message_text(

            status_text(bot_id)

            + "\n\n"

            + message,

            parse_mode="HTML",

            reply_markup=bot_buttons(
                bot_id
            )
        )

        return

    # ====================================================
    # RESTART
    # ====================================================

    if action.startswith("restart:"):

        bot_id = action.split(
            ":",
            1
        )[1]

        bot = get_bot(
            bot_id
        )

        if not bot:
            return

        if (

            bot.get("owner_id")
            != user_id

            and not admin_only(user_id)

        ):

            await query.answer(
                "❌ Access denied!",
                show_alert=True
            )

            return

        await query.edit_message_text(

            "🔄 <b>Restarting...</b>",

            parse_mode="HTML"
        )

        ok, message = await restart_bot(
            bot_id
        )

        await query.edit_message_text(

            message,

            parse_mode="HTML",

            reply_markup=bot_buttons(
                bot_id
            )
        )

        return

    # ====================================================
    # STATUS
    # ====================================================

    if action.startswith("status:"):

        bot_id = action.split(
            ":",
            1
        )[1]

        bot = get_bot(
            bot_id
        )

        if not bot:
            return

        if (

            bot.get("owner_id")
            != user_id

            and not admin_only(user_id)

        ):

            await query.answer(
                "❌ Access denied!",
                show_alert=True
            )

            return

        await query.edit_message_text(

            status_text(
                bot_id
            ),

            parse_mode="HTML",

            reply_markup=bot_buttons(
                bot_id
            )
        )

        return

    # ====================================================
    # LOGS
    # ====================================================

    if action.startswith("logs:"):

        bot_id = action.split(
            ":",
            1
        )[1]

        bot = get_bot(
            bot_id
        )

        if not bot:
            return

        if (

            bot.get("owner_id")
            != user_id

            and not admin_only(user_id)

        ):

            await query.answer(
                "❌ Access denied!",
                show_alert=True
            )

            return

        logs = html.escape(
            read_logs(bot_id)
        )

        await query.edit_message_text(

            "📜 <b>Bot Logs</b>\n\n"

            f"<pre>{logs}</pre>",

            parse_mode="HTML",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🔄 Refresh",
                        callback_data=f"logs:{bot_id}"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "🔙 Back",
                        callback_data=f"manage:{bot_id}"
                    )
                ]

            ])
        )

        return

    # ====================================================
    # DELETE
    # ====================================================

    if action.startswith("delete:"):

        bot_id = action.split(
            ":",
            1
        )[1]

        bot = get_bot(
            bot_id
        )

        if not bot:
            return

        if (

            bot.get("owner_id")
            != user_id

            and not admin_only(user_id)

        ):

            await query.answer(
                "❌ Access denied!",
                show_alert=True
            )

            return

        await query.edit_message_text(

            "⚠️ <b>Delete Bot?</b>\n\n"

            f"🆔 <code>{bot_id}</code>\n\n"

            "Bot files এবং logs delete হবে।",

            parse_mode="HTML",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "❌ Confirm Delete",
                        callback_data=f"confirmdelete:{bot_id}"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "🔙 Cancel",
                        callback_data=f"manage:{bot_id}"
                    )
                ]

            ])
        )

        return

    # ====================================================
    # CONFIRM DELETE
    # ====================================================

    if action.startswith("confirmdelete:"):

        bot_id = action.split(
            ":",
            1
        )[1]

        bot = get_bot(
            bot_id
        )

        if not bot:
            return

        if (

            bot.get("owner_id")
            != user_id

            and not admin_only(user_id)

        ):

            await query.answer(
                "❌ Access denied!",
                show_alert=True
            )

            return

        await stop_bot(
            bot_id
        )

        try:

            folder = bot_folder(
                bot_id
            )

            if folder.exists():

                shutil.rmtree(
                    folder
                )

        except Exception:
            pass

        try:

            logfile = bot_log(
                bot_id
            )

            if logfile.exists():

                logfile.unlink()

        except Exception:
            pass

        data["bots"].pop(
            bot_id,
            None
        )

        save_data()

        await query.edit_message_text(

            "🗑 <b>Bot Deleted Successfully!</b>",

            parse_mode="HTML",

            reply_markup=main_menu(
                user_id
            )
        )

        return


# ========================================================
# /BOTS
# ========================================================

async def bots_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    register_user(
        update.effective_user
    )

    text, keyboard = await my_bots_text(

        update.effective_user.id

    )

    await update.message.reply_text(

        text,

        parse_mode="HTML",

        reply_markup=keyboard
    )


# ========================================================
# /CREDIT
# ========================================================

async def credit_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    register_user(
        update.effective_user
    )

    await update.message.reply_text(

        "💳 <b>Your Credit</b>\n\n"

        f"💰 Credit: "
        f"<b>{user_credits(update.effective_user.id)}</b>\n\n"

        f"🤖 Hosting Cost: "
        f"<b>{get_cost()}</b>\n\n"

        f"👑 Admin: "
        f"<b>{ADMIN_USERNAME}</b>",

        parse_mode="HTML"
    )


# ========================================================
# /STATUS
# ========================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(

            "Usage:\n"

            "<code>/status BOT_ID</code>",

            parse_mode="HTML"
        )

        return

    bot_id = context.args[0]

    bot = get_bot(
        bot_id
    )

    if not bot:

        await update.message.reply_text(
            "❌ Bot পাওয়া যায়নি।"
        )

        return

    user_id = update.effective_user.id

    if (

        bot.get("owner_id")
        != user_id

        and not admin_only(user_id)

    ):

        await update.message.reply_text(
            "❌ Access denied."
        )

        return

    await update.message.reply_text(

        status_text(bot_id),

        parse_mode="HTML",

        reply_markup=bot_buttons(
            bot_id
        )
    )


# ========================================================
# /LOGS
# ========================================================

async def logs_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(

            "Usage:\n"

            "<code>/logs BOT_ID</code>",

            parse_mode="HTML"
        )

        return

    bot_id = context.args[0]

    bot = get_bot(
        bot_id
    )

    if not bot:

        await update.message.reply_text(
            "❌ Bot পাওয়া যায়নি।"
        )

        return

    user_id = update.effective_user.id

    if (

        bot.get("owner_id")
        != user_id

        and not admin_only(user_id)

    ):

        await update.message.reply_text(
            "❌ Access denied."
        )

        return

    logs = html.escape(
        read_logs(bot_id)
    )

    await update.message.reply_text(

        "📜 <b>Bot Logs</b>\n\n"

        f"<pre>{logs}</pre>",

        parse_mode="HTML",

        reply_markup=bot_buttons(
            bot_id
        )
    )


# ========================================================
# /CANCEL
# ========================================================

async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    session = upload_sessions.pop(
        user_id,
        None
    )

    if not session:

        await update.message.reply_text(
            "ℹ️ কোনো upload session নেই।"
        )

        return

    for key in [
        "py_file",
        "requirements"
    ]:

        item = session.get(
            key
        )

        if item:

            try:

                os.remove(
                    item["path"]
                )

            except Exception:
                pass

    await update.message.reply_text(
        "❌ Upload cancelled."
    )


# ========================================================
# ERROR
# ========================================================

async def error_handler(
    update,
    context
):

    logger.exception(
        "Telegram error: %s",
        context.error
    )


# ========================================================
# AUTO START
# ========================================================

async def auto_start():

    await asyncio.sleep(
        2
    )

    logger.info(
        "Checking saved bots..."
    )

    for bot_id, bot in list(
        data["bots"].items()
    ):

        try:

            if bot.get("status") == "running":

                # Auto restart MUST NOT charge again.

                logger.info(
                    "Auto starting %s",
                    bot_id
                )

                await start_bot(
                    bot_id,
                    deduct_credit=False
                )

                await asyncio.sleep(
                    1
                )

        except Exception as e:

            logger.error(
                "Auto start %s: %s",
                bot_id,
                e
            )


# ========================================================
# POST INIT
# ========================================================

async def post_init(
    application
):

    logger.info(
        "===================================="
    )

    logger.info(
        "Professional Hosting Panel Started"
    )

    logger.info(
        "Docker: DISABLED"
    )

    logger.info(
        "PostgreSQL: DISABLED"
    )

    logger.info(
        "Database: JSON"
    )

    logger.info(
        "Credit System: ENABLED"
    )

    logger.info(
        "Hosting Cost: %s",
        get_cost()
    )

    logger.info(
        "===================================="
    )

    asyncio.create_task(
        auto_start()
    )


# ========================================================
# MAIN
# ========================================================

def main():

    if (

        not BOT_TOKEN

        or
        BOT_TOKEN
        == "PUT_YOUR_NEW_BOT_TOKEN_HERE"

    ):

        print(
            "\n"
            "❌ BOT_TOKEN সেট করুন!\n"
            "Panel.py-এর CONFIG section-এ নতুন token দিন.\n"
        )

        return

    app = (

        Application

        .builder()

        .token(
            BOT_TOKEN
        )

        .post_init(
            post_init
        )

        .build()

    )

    # Commands

    app.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    app.add_handler(
        CommandHandler(
            "upload",
            upload_command
        )
    )

    app.add_handler(
        CommandHandler(
            "finish",
            finish_command
        )
    )

    app.add_handler(
        CommandHandler(
            "bots",
            bots_command
        )
    )

    app.add_handler(
        CommandHandler(
            "credit",
            credit_command
        )
    )

    app.add_handler(
        CommandHandler(
            "status",
            status_command
        )
    )

    app.add_handler(
        CommandHandler(
            "logs",
            logs_command
        )
    )

    app.add_handler(
        CommandHandler(
            "cancel",
            cancel_command
        )
    )

    # Admin

    app.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    app.add_handler(
        CommandHandler(
            "addcredit",
            addcredit_command
        )
    )

    app.add_handler(
        CommandHandler(
            "removecredit",
            removecredit_command
        )
    )

    # Buttons

    app.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # Documents

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            document_handler
        )
    )

    # Errors

    app.add_error_handler(
        error_handler
    )

    print(
        "Professional Hosting Panel started..."
    )

    print(
        "Docker: DISABLED"
    )

    print(
        "PostgreSQL: DISABLED"
    )

    print(
        "Credit System: ENABLED"
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ========================================================
# RUN
# ========================================================

if __name__ == "__main__":

    main()