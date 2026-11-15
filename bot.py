import os
import sqlite3
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")
DB = "truck_manager.db"

if not TOKEN or not OWNER_ID:
    raise RuntimeError("Set BOT_TOKEN and OWNER_ID in Render environment variables")

OWNER_ID = int(OWNER_ID)

def init_db():
    with sqlite3.connect(DB) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, origin TEXT, destination TEXT,
            miles REAL, deadhead REAL, revenue REAL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, category TEXT, amount REAL,
            note TEXT, receipt_id TEXT
        )""")

def menu():
    return ReplyKeyboardMarkup([
        ["🚛 Add Trip", "💵 Add Expense"],
        ["📊 Reports", "📋 Trips"],
        ["🧾 Expenses", "❌ Cancel"]
    ], resize_keyboard=True)

def allowed(update):
    return update.effective_user and update.effective_user.id == OWNER_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await update.message.reply_text(
        "🚛 Welcome to Truck CPM Manager!\n\nChoose an action:",
        reply_markup=menu()
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    context.user_data.clear()
    await update.message.reply_text("Cancelled.", reply_markup=menu())

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return

    text = update.message.text.strip()
    state = context.user_data.get("state")

    if text == "❌ Cancel":
        return await cancel(update, context)

    if text == "🚛 Add Trip":
        context.user_data.clear()
        context.user_data["state"] = "origin"
        await update.message.reply_text("Enter pickup city:")
        return

    if text == "💵 Add Expense":
        context.user_data.clear()
        context.user_data["state"] = "expense_category"
        await update.message.reply_text(
            "Enter expense category (Fuel, Repair, Insurance, Tolls, Other):"
        )
        return

    if text == "📊 Reports":
        return await report(update, context)

    if text == "📋 Trips":
        return await show_trips(update, context)

    if text == "🧾 Expenses":
        return await show_expenses(update, context)

    if state == "origin":
        context.user_data["origin"] = text
        context.user_data["state"] = "destination"
        await update.message.reply_text("Enter delivery city:")
    elif state == "destination":
        context.user_data["destination"] = text
        context.user_data["state"] = "miles"
        await update.message.reply_text("Enter total miles:")
    elif state == "miles":
        try:
            context.user_data["miles"] = float(text)
            context.user_data["state"] = "deadhead"
            await update.message.reply_text("Enter deadhead miles:")
        except ValueError:
            await update.message.reply_text("Please enter a number.")
    elif state == "deadhead":
        try:
            context.user_data["deadhead"] = float(text)
            context.user_data["state"] = "revenue"
            await update.message.reply_text("Enter trip revenue in dollars:")
        except ValueError:
            await update.message.reply_text("Please enter a number.")
    elif state == "revenue":
        try:
            revenue = float(text)
            d = context.user_data
            with sqlite3.connect(DB) as con:
                con.execute(
                    """INSERT INTO trips
                    (date,origin,destination,miles,deadhead,revenue)
                    VALUES (?,?,?,?,?,?)""",
                    (datetime.now().strftime("%Y-%m-%d"),
                     d["origin"], d["destination"],
                     d["miles"], d["deadhead"], revenue)
                )
            context.user_data.clear()
            await update.message.reply_text(
                "✅ Trip saved!\n"
                f"{d['origin']} → {d['destination']}\n"
                f"Miles: {d['miles']:,.0f}\n"
                f"Deadhead: {d['deadhead']:,.0f}\n"
                f"Revenue: ${revenue:,.2f}",
                reply_markup=menu()
            )
        except ValueError:
            await update.message.reply_text("Please enter a valid amount.")
    elif state == "expense_category":
        context.user_data["category"] = text
        context.user_data["state"] = "expense_amount"
        await update.message.reply_text("Enter expense amount in dollars:")
    elif state == "expense_amount":
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
            context.user_data["amount"] = amount
            context.user_data["state"] = "expense_note"
            await update.message.reply_text(
                "Add a note (vendor, fuel stop, etc.) or type - to skip:"
            )
        except ValueError:
            await update.message.reply_text("Enter a valid positive amount.")
    elif state == "expense_note":
        d = context.user_data
        with sqlite3.connect(DB) as con:
            con.execute(
                """INSERT INTO expenses
                (date,category,amount,note,receipt_id)
                VALUES (?,?,?,?,?)""",
                (datetime.now().strftime("%Y-%m-%d"),
                 d["category"], d["amount"],
                 "" if text == "-" else text,
                 d.get("receipt_id"))
            )
        amount = d["amount"]
        category = d["category"]
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ Expense saved!\n{category}: ${amount:,.2f}",
            reply_markup=menu()
        )
    else:
        await update.message.reply_text("Choose an option from the menu.", reply_markup=menu())

async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    if not update.message.photo:
        return
    file = await update.message.photo[-1].get_file()
    context.user_data["receipt_id"] = file.file_id
    context.user_data["state"] = "expense_category"
    await update.message.reply_text(
        "🧾 Receipt received!\nNow enter its category (Fuel, Repair, etc.):"
    )

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with sqlite3.connect(DB) as con:
        trips = con.execute(
            "SELECT COALESCE(SUM(revenue),0), COALESCE(SUM(miles),0) FROM trips"
        ).fetchone()
        expenses = con.execute(
            "SELECT COALESCE(SUM(amount),0) FROM expenses"
        ).fetchone()[0]

    revenue, miles = trips
    net = revenue - expenses
    cpm = expenses / miles if miles else 0
    rpm = revenue / miles if miles else 0

    await update.message.reply_text(
        "📊 TRUCK REPORT\n\n"
        f"Revenue: ${revenue:,.2f}\n"
        f"Expenses: ${expenses:,.2f}\n"
        f"NET PROFIT: ${net:,.2f}\n\n"
        f"Total miles: {miles:,.0f}\n"
        f"CPM: ${cpm:.3f}\n"
        f"RPM: ${rpm:.3f}",
        reply_markup=menu()
    )

async def show_trips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with sqlite3.connect(DB) as con:
        rows = con.execute(
            "SELECT id,origin,destination,miles,revenue FROM trips ORDER BY id DESC LIMIT 15"
        ).fetchall()
    if not rows:
        return await update.message.reply_text("No trips yet.", reply_markup=menu())
    msg = "🚛 RECENT TRIPS\n\n"
    for r in rows:
        msg += f"#{r[0]} {r[1]} → {r[2]}\n{r[3]:,.0f} miles | ${r[4]:,.2f}\n\n"
    await update.message.reply_text(msg, reply_markup=menu())

async def show_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with sqlite3.connect(DB) as con:
        rows = con.execute(
            "SELECT id,category,amount,note FROM expenses ORDER BY id DESC LIMIT 15"
        ).fetchall()
    if not rows:
        return await update.message.reply_text("No expenses yet.", reply_markup=menu())
    msg = "🧾 RECENT EXPENSES\n\n"
    for r in rows:
        msg += f"#{r[0]} {r[1]}: ${r[2]:,.2f}\n{r[3]}\n\n"
    await update.message.reply_text(msg, reply_markup=menu())

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.PHOTO, photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    print("Truck CPM Manager bot is running")
    app.run_polling()

if __name__ == "__main__":
    main()
