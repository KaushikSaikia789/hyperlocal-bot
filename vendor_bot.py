import asyncio
import json
import os
from uuid import uuid4
import requests
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove, KeyboardButton, ReplyKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, CallbackQueryHandler, filters,
)

VENDOR_FILE = "vendors.json"
BOT_TOKEN = "7596760249:AAHpjQOqD2Ga_yNVnymo4T4D-_2yzupOe38"
PHOTO_DIR = "product_photos"
CUSTOMER_BOT_TOKEN = "8041211807:AAGtsTQrLcNRICMZJie_GwSzOF0aovyEpok"
ORDER_FILE = "orders.json"
os.makedirs(PHOTO_DIR, exist_ok=True)

# State Identifiers
ASK_NAME, ASK_LOCATION = range(2)
ADD_NAME, ADD_PRICE, ADD_STOCK, ADD_PHOTO = range(10, 14)
EDIT_SELECT, EDIT_NAME, EDIT_PRICE, EDIT_STOCK, EDIT_PHOTO = range(20, 25)
DELETE_SELECT = 30
CB_CANCEL = "cancel_add_product"
CB_SKIP_PHOTO = "skip_product_photo"
CB_SKIP_EDIT = "skip_edit_step"

# ------------ DATA UTILITIES ------------

def load_vendors():
    if os.path.exists(VENDOR_FILE):
        try:
            with open(VENDOR_FILE, "r") as f:
                vendors = json.load(f)
                return [v for v in vendors if "chat_id" in v]
        except Exception:
            return []
    return []

def save_vendors(vendors):
    with open(VENDOR_FILE, "w") as f:
        json.dump(vendors, f, indent=2)
def load_orders():
    if os.path.exists(ORDER_FILE):
        try:
            with open(ORDER_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_orders(orders):
    with open(ORDER_FILE, "w") as f:
        json.dump(orders, f, indent=2)

async def accept_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    # Format: order_accept_{order_id}_{customer_id} or order_reject_{order_id}_{customer_id}
    if data.startswith("order_accept_") or data.startswith("order_reject_"):
        try:
            _, act, order_id, customer_id = data.split("_", 3)
        except ValueError:
            await query.answer("Invalid button!")
            return
        orders = load_orders()
        order = orders.get(order_id)
        if not order:
            await query.answer("Order not found.")
            return
        if order.get("status") != "pending":
            await query.answer("Order already responded to.")
            try:
                await query.edit_message_text("Order already accepted/rejected.")
            except:
                pass
            return
        accept = (act == "accept")
        order["status"] = "accepted" if accept else "rejected"
        save_orders(orders)
        await query.answer("Order updated.")
        try:
            await query.edit_message_text(
                f"✅ Order *ACCEPTED*." if accept else "❌ Order *REJECTED*.",
                parse_mode="Markdown"
            )
        except Exception as e:
            print("Error editing message:", e)
        # Notify the customer via customer bot
        customer_msg = (
            f"🎉 Your order (ID: `{order_id}`) has been *ACCEPTED* by the vendor!" if accept
            else f"🙁 Sorry, your order (ID: `{order_id}`) was *REJECTED* by the vendor."
        )
        try:
            url = f"https://api.telegram.org/bot{CUSTOMER_BOT_TOKEN}/sendMessage"
            resp = requests.post(url, json={
                "chat_id": customer_id,
                "text": customer_msg,
                "parse_mode": "Markdown"
            })
            if not resp.ok:
                print("Customer notify failed:", resp.text)
        except Exception as e:
            print(f"Could not notify customer: {e}")
    else:
        await query.answer("Unknown action.")

def get_vendor(chat_id):
    vendors = load_vendors()
    for v in vendors:
        if v["chat_id"] == chat_id:
            return v
    return None

def upsert_vendor(vendor_data):
    vendors = load_vendors()
    for i, v in enumerate(vendors):
        if v["chat_id"] == vendor_data["chat_id"]:
            vendors[i] = vendor_data
            break
    else:
        vendors.append(vendor_data)
    save_vendors(vendors)

async def cleanup_msgs(context, chat_id, msg_ids):
    tasks = [context.bot.delete_message(chat_id=chat_id, message_id=msg_id) for msg_id in msg_ids]
    await asyncio.gather(*tasks, return_exceptions=True)

# ------------ MAIN MENU (INLINE) ------------

def get_main_menu_markup():
    keyboard = [
        [
            InlineKeyboardButton("➕ Add Product", callback_data="add_product"),
            InlineKeyboardButton("✏️ Edit Product", callback_data="edit_product"),
        ],
        [
            InlineKeyboardButton("❌ Delete Product", callback_data="delete_product"),
            InlineKeyboardButton("📦 Order History", callback_data="order_history"),
        ],
        [
            InlineKeyboardButton("💰 My Earnings", callback_data="my_earnings"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    markup = get_main_menu_markup()
    if hasattr(update, "message") and update.message:
        await update.message.reply_text("📋 *Main Menu*", parse_mode='Markdown', reply_markup=markup)
    elif hasattr(update, "callback_query") and update.callback_query:
        try:
            await update.callback_query.edit_message_text("📋 *Main Menu*", parse_mode='Markdown', reply_markup=markup)
        except Exception:
            await context.bot.send_message(update.effective_chat.id, "📋 *Main Menu*", parse_mode='Markdown', reply_markup=markup)
    return ConversationHandler.END

# ------------ REGISTRATION ------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    vendor = get_vendor(chat_id)
    if vendor:
        await update.message.reply_text(f"👋 Welcome back, *{vendor['name']}*!", parse_mode='Markdown')
        return await show_main_menu(update, context)
    msg = await update.message.reply_text("👋 Welcome! Let's register your shop.\nPlease enter your shop name:")
    context.user_data["messages_to_delete"] = [update.message.message_id, msg.message_id]
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    chat_id = update.effective_chat.id
    context.user_data["name"] = name
    context.user_data.setdefault("messages_to_delete", []).append(update.message.message_id)
    button = [[KeyboardButton("📍 Share Location", request_location=True)]]
    reply_markup = ReplyKeyboardMarkup(button, one_time_keyboard=True, resize_keyboard=True)
    msg = await update.message.reply_text("Please share your shop location:", reply_markup=reply_markup)
    context.user_data["messages_to_delete"].append(msg.message_id)
    return ASK_LOCATION

async def ask_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    location = update.message.location
    chat_id = update.effective_chat.id
    if not location:
        msg = await update.message.reply_text("❌ Please send a valid location.")
        context.user_data.setdefault("messages_to_delete", []).append(msg.message_id)
        return ASK_LOCATION
    vendor = {
        "chat_id": chat_id,
        "name": context.user_data["name"],
        "location": {"lat": location.latitude, "lon": location.longitude},
        "products": []
    }
    upsert_vendor(vendor)
    context.user_data["messages_to_delete"].append(update.message.message_id)
    await cleanup_msgs(context, chat_id, context.user_data.get("messages_to_delete", []))
    confirmation = await context.bot.send_message(
        chat_id=chat_id,
        text=f"✅ Shop *{vendor['name']}* registered successfully! \n🛍️ You're now live.",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data["messages_to_delete"] = [confirmation.message_id]
    return await show_main_menu(update, context)

# ------------- ADD PRODUCT -------------

async def add_product_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id if hasattr(update, 'effective_chat') else update.callback_query.message.chat_id
    context.user_data["add_product_msgs"] = []
    if hasattr(update, 'message') and update.message:
        context.user_data["add_product_msgs"].append(update.message.message_id)
    elif hasattr(update, 'callback_query'):
        try:
            await update.callback_query.delete_message()
        except Exception:
            pass
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL)]])
    prompt = (await context.bot.send_message(
        chat_id=chat_id,
        text="📝 Enter the *product name*:",
        parse_mode='Markdown',
        reply_markup=markup
    ))
    context.user_data["add_product_msgs"].append(prompt.message_id)
    return ADD_NAME

async def add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["product_name"] = text
    context.user_data["add_product_msgs"].append(update.message.message_id)
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL)]])
    prompt = await update.message.reply_text(
        "💰 Enter the *product price* (in ₹):",
        parse_mode='Markdown',
        reply_markup=markup
    )
    context.user_data["add_product_msgs"].append(prompt.message_id)
    return ADD_PRICE

async def add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        price = float(text)
        if price < 0: raise ValueError
    except Exception:
        msg = await update.message.reply_text("⚠️ Please enter a valid price (numeric value).")
        context.user_data["add_product_msgs"].append(update.message.message_id)
        context.user_data["add_product_msgs"].append(msg.message_id)
        return ADD_PRICE
    context.user_data["product_price"] = price
    context.user_data["add_product_msgs"].append(update.message.message_id)
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL)]])
    prompt = await update.message.reply_text(
        "📦 Enter *stock available* (e.g., 10kg or 5psc):",
        parse_mode='Markdown',
        reply_markup=markup
    )
    context.user_data["add_product_msgs"].append(prompt.message_id)
    return ADD_STOCK

async def add_product_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    t = text.lower()
    if not (t.endswith("kg") or t.endswith("psc")):
        msg = await update.message.reply_text("⚠️ Please specify units as 'kg' or 'psc'. E.g., '10kg'")
        context.user_data["add_product_msgs"].append(update.message.message_id)
        context.user_data["add_product_msgs"].append(msg.message_id)
        return ADD_STOCK
    context.user_data["product_stock"] = text
    context.user_data["add_product_msgs"].append(update.message.message_id)
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏭️ Skip", callback_data=CB_SKIP_PHOTO),
            InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL)
        ]
    ])
    prompt = await update.message.reply_text(
        "🖼️ *Optional:* Send a product photo now, or press Skip to continue without a photo.",
        parse_mode='Markdown',
        reply_markup=markup
    )
    context.user_data["add_product_msgs"].append(prompt.message_id)
    return ADD_PHOTO

async def add_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        msg = await update.message.reply_text(
            "⚠️ Please send a product photo or press *Skip*.",
            parse_mode='Markdown'
        )
        context.user_data["add_product_msgs"].append(update.message.message_id)
        context.user_data["add_product_msgs"].append(msg.message_id)
        return ADD_PHOTO
    photo_file = update.message.photo[-1].file_id
    photo = await context.bot.get_file(photo_file)
    photo_ext = ".jpg"
    filename = f"{uuid4().hex}{photo_ext}"
    local_path = os.path.join(PHOTO_DIR, filename)
    await photo.download_to_drive(local_path)
    context.user_data["product_photo"] = filename
    context.user_data["add_product_msgs"].append(update.message.message_id)
    return await finalize_product(update, context)

async def skip_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["product_photo"] = None
    if hasattr(update, 'callback_query'):
        await update.callback_query.answer()
    return await finalize_product(update, context)

async def finalize_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    vendor = get_vendor(chat_id)
    if vendor is None:
        await context.bot.send_message(chat_id, "❌ Could not find your vendor account. Please /start again.")
        return ConversationHandler.END
    new_product = {
        "name": context.user_data["product_name"],
        "price": context.user_data["product_price"],
        "stock": context.user_data["product_stock"],
        "keywords": [context.user_data["product_name"]],
        "photo": context.user_data.get("product_photo") or None,
    }
    vendor.setdefault("products", []).append(new_product)
    upsert_vendor(vendor)
    await cleanup_msgs(context, chat_id, context.user_data.get("add_product_msgs", []))
    msg_text = (
        f"✅ *Product Added Successfully!*\n\n"
        f"*Name*: {new_product['name']}\n"
        f"*Price*: ₹{new_product['price']}\n"
        f"*Stock*: {new_product['stock']}\n"
    )
    if new_product.get('photo'):
        photo_path = os.path.join(PHOTO_DIR, new_product['photo'])
        with open(photo_path, "rb") as photo_file:
            await context.bot.send_photo(chat_id, photo=photo_file, caption=msg_text, parse_mode='Markdown')
    else:
        await context.bot.send_message(chat_id, text=msg_text, parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
    return await show_main_menu(update, context)

# ---- (Edit product flow: for brevity, use your previous code block -- see prior answer) ----

# ------------- DELETE PRODUCT (with Fix for "Message to edit not found") -------------

async def delete_product_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id if hasattr(update, 'effective_chat') else update.callback_query.message.chat_id
    vendor = get_vendor(chat_id)
    context.user_data["delete_product_msgs"] = []
    context.user_data["delete_selected"] = set()
    if not vendor or not vendor.get("products"):
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text("You have no products to delete.")
        elif hasattr(update, 'message'):
            await update.message.reply_text("You have no products to delete.")
        return await show_main_menu(update, context)
    buttons = []
    for i, prod in enumerate(vendor["products"]):
        label = f"⬜ {prod['name']} ({prod['stock']}, ₹{prod['price']})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"delete_toggle_{i}")])
    buttons.append([
        InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL),
        InlineKeyboardButton("🗑️ Confirm Delete", callback_data="delete_confirm_disabled")
    ])
    markup = InlineKeyboardMarkup(buttons)
    if hasattr(update, 'callback_query') and update.callback_query:
        query = update.callback_query
        await query.answer()
        msg = await query.edit_message_text("Select product(s) to delete (toggle):", reply_markup=markup)
        context.user_data["delete_product_msgs"].append(msg.message_id)
    else:
        msg = await update.message.reply_text("Select product(s) to delete (toggle):", reply_markup=markup)
        context.user_data["delete_product_msgs"].append(msg.message_id)
    return DELETE_SELECT

async def delete_product_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data
    if data == CB_CANCEL:
        await cleanup_msgs(context, chat_id, context.user_data.get("delete_product_msgs", []))
        await query.edit_message_text("Delete product cancelled.")
        return await show_main_menu(update, context)
    if not data.startswith("delete_toggle_"):
        await query.answer("Unknown action.", show_alert=True)
        return
    idx = int(data.split("_")[-1])
    vendor = get_vendor(chat_id)
    products = vendor.get("products", [])
    if idx >= len(products):
        await query.answer("Product not found.", show_alert=True)
        return
    selected = context.user_data.setdefault("delete_selected", set())
    if idx in selected:
        selected.remove(idx)
    else:
        selected.add(idx)
    buttons = []
    for i, prod in enumerate(products):
        label = f"{'✅' if i in selected else '⬜'} {prod['name']} ({prod['stock']}, ₹{prod['price']})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"delete_toggle_{i}")])
    confirm_callback = "delete_confirm" if selected else "delete_confirm_disabled"
    buttons.append([
        InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL),
        InlineKeyboardButton("🗑️ Confirm Delete", callback_data=confirm_callback)
    ])
    markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_reply_markup(reply_markup=markup)
    return DELETE_SELECT

async def delete_product_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    selected = context.user_data.get("delete_selected", set())
    vendor = get_vendor(chat_id)
    products = vendor.get("products", [])
    if not selected:
        await query.answer("No products selected to delete.", show_alert=True)
        return DELETE_SELECT
    prod_list = '\n'.join([f"- {products[i]['name']}" for i in sorted(selected)])
    disclaimer = ("⚠️ The following products will be permanently deleted:\n\n"
                  f"{prod_list}\n\nAre you sure?")
    buttons = [
        [InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL),
        InlineKeyboardButton("⚡ Confirm", callback_data="delete_do")]
    ]
    markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(disclaimer, reply_markup=markup)
    return DELETE_SELECT

async def delete_product_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    selected = context.user_data.get("delete_selected", set())
    vendor = get_vendor(chat_id)
    products = vendor.get("products", [])
    for idx in sorted(selected, reverse=True):
        if idx < len(products):
            prod = products.pop(idx)
            if prod.get("photo"):
                try:
                    os.remove(os.path.join(PHOTO_DIR, prod["photo"]))
                except Exception:
                    pass
    upsert_vendor(vendor)

    # ---- Fix! Cleanup before sending new message ----
    await cleanup_msgs(context, chat_id, context.user_data.get("delete_product_msgs", []))
    await context.bot.send_message(chat_id, f"🗑️ Deleted {len(selected)} product(s) successfully.")

    context.user_data["delete_selected"] = set()
    context.user_data["delete_product_msgs"] = []
    return await show_main_menu(update, context)

# ------------- CANCEL / MENU CALLBACKS -------------

async def inline_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    for key in ["add_product_msgs", "edit_product_msgs", "delete_product_msgs"]:
        if context.user_data.get(key):
            await cleanup_msgs(context, chat_id, context.user_data.get(key, []))
    await context.bot.send_message(chat_id, "❌ Operation cancelled.", reply_markup=ReplyKeyboardRemove())
    return await show_main_menu(update, context)

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "add_product":
        return await add_product_entry(update, context)
    elif data == "edit_product":
        await update.callback_query.answer("Edit product not implemented yet.")
        await show_main_menu(update, context)

    elif data == "delete_product":
        return await delete_product_entry(update, context)
    elif data == "order_history":
        await query.edit_message_text("📦 Order History (not implemented yet)", parse_mode='Markdown')
    elif data == "my_earnings":
        await query.edit_message_text("💰 My Earnings (not implemented yet)", parse_mode='Markdown')
    else:
        await query.edit_message_text("Unknown action.")

# ---- Include your Edit Product handler block above run_vendor_bot ----

def run_vendor_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    registration_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), ask_name)],
            ASK_LOCATION: [MessageHandler(filters.LOCATION, ask_location)],
        },
        fallbacks=[],
        name="vendor_registration",
        persistent=False,
    )
    app.add_handler(registration_handler)
    add_product_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_product_entry, pattern="^add_product$")],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), add_product_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & (~filters.COMMAND), add_product_price)],
            ADD_STOCK: [MessageHandler(filters.TEXT & (~filters.COMMAND), add_product_stock)],
            ADD_PHOTO: [
                MessageHandler(filters.PHOTO, add_product_photo),
                CallbackQueryHandler(skip_product_photo, pattern=f"^{CB_SKIP_PHOTO}$"),
                CallbackQueryHandler(inline_cancel_callback, pattern=f"^{CB_CANCEL}$"),
                MessageHandler(filters.ALL, add_product_photo),
            ],
        },
        fallbacks=[CallbackQueryHandler(inline_cancel_callback, pattern=f"^{CB_CANCEL}$")],
        name="add_product",
        persistent=False,
    )
    app.add_handler(add_product_handler)
    # --- Edit product handler block goes here ---
    # ... (paste your EDIT product handler here from your last code)
    delete_product_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(delete_product_entry, pattern="^delete_product$")],
        states={
            DELETE_SELECT: [
                CallbackQueryHandler(delete_product_toggle, pattern="^delete_toggle_\\d+$"),
                CallbackQueryHandler(delete_product_confirm, pattern="^delete_confirm$"),
                CallbackQueryHandler(delete_product_do, pattern="^delete_do$"),
                CallbackQueryHandler(inline_cancel_callback, pattern=f"^{CB_CANCEL}$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(inline_cancel_callback, pattern=f"^{CB_CANCEL}$")],
        name="delete_product",
        persistent=False,
    )
    app.add_handler(CallbackQueryHandler(accept_reject_callback, pattern=r"^order_(accept|reject)_"))
    app.add_handler(delete_product_handler)
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^(add_product|edit_product|delete_product|order_history|my_earnings)$"))
    print("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    run_vendor_bot()
