import json
import os
import requests
import asyncio
from geopy.distance import geodesic
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

# ---- BOT CONFIG ----
BOT_TOKEN = "8041211807:AAGtsTQrLcNRICMZJie_GwSzOF0aovyEpok"
VENDOR_BOT_TOKEN = "7596760249:AAHpjQOqD2Ga_yNVnymo4T4D-_2yzupOe38"
SEND_MSG_URL = f"https://api.telegram.org/bot{VENDOR_BOT_TOKEN}/sendMessage"

USER_FILE = "users.json"
VENDOR_FILE = "vendors.json"
ORDER_FILE = "orders.json"
PHOTO_DIR = "product_photos"
ASK_NAME, ASK_LOCATION, WAIT_LOCATION_TO_BROWSE = range(3)

def load_json(filename, fallback):
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except:
            return fallback
    return fallback

def save_json(filename, obj):
    with open(filename, "w") as f:
        json.dump(obj, f, indent=2)

def load_users(): return load_json(USER_FILE, {})
def save_users(users): save_json(USER_FILE, users)
def load_vendors(): return load_json(VENDOR_FILE, [])
def load_orders(): return load_json(ORDER_FILE, {})
def save_orders(orders): save_json(ORDER_FILE, orders)

def match_vendors(query, user_location):
    results = []
    query_words = query.lower().split()
    vendors = load_vendors()
    for vendor in vendors:
        vlat = vendor.get("location", {}).get("lat")
        vlon = vendor.get("location", {}).get("lon")
        if not vlat or not vlon:
            continue
        dist = geodesic((user_location["lat"], user_location["lon"]), (vlat, vlon)).km
        for product in vendor.get("products", []):
            keywords = [k.lower() for k in product.get("keywords", [])]
            if any(any(word in keyword for keyword in keywords) for word in query_words):
                results.append({
                    "vendor": vendor["name"],
                    "vendor_location": vendor["location"],
                    "vendor_chat_id": vendor.get("chat_id"),
                    "keywords": keywords,
                    "price": product["price"],
                    "stock": product["stock"],
                    "distance": round(dist, 2),
                    "photo": product.get("photo"),
                })
                break
    return sorted(results, key=lambda x: x["distance"])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_users()
    context.user_data.clear()
    context.user_data["messages_to_delete"] = []
    if user_id in users and users[user_id].get("name"):
        return await prompt_location(update, context, registered=True)
    msg = await update.message.reply_text("👋 Hi there! Welcome to our shopping bot.\n\nWhat's your name?")
    context.user_data["messages_to_delete"].extend([update.message.message_id, msg.message_id])
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    user_id = str(update.effective_user.id)
    users = load_users()
    users[user_id] = {"name": name, "tg_id": user_id}
    save_users(users)
    context.user_data["messages_to_delete"].append(update.message.message_id)
    return await prompt_location(update, context)

async def prompt_location(update, context, registered=False):
    btn = [[KeyboardButton("📍 Send Location", request_location=True)]]
    txt = ("Before browsing or ordering, please share your current location using the button below." if not registered else
           "Welcome back! For accurate service, please share your current location every time using the button below.")
    msg = await update.effective_chat.send_message(
        txt,
        reply_markup=ReplyKeyboardMarkup(btn, one_time_keyboard=True, resize_keyboard=True)
    )
    context.user_data["messages_to_delete"].append(msg.message_id)
    return WAIT_LOCATION_TO_BROWSE

async def ask_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.location:
        msg = await update.message.reply_text("❗ Location is required. Please tap the button to send your location.")
        context.user_data["messages_to_delete"].append(msg.message_id)
        return ASK_LOCATION
    user_id = str(update.effective_user.id)
    users = load_users()
    users[user_id]["location"] = {
        "lat": update.message.location.latitude,
        "lon": update.message.location.longitude
    }
    save_users(users)
    context.user_data["messages_to_delete"].append(update.message.message_id)
    for msg_id in context.user_data["messages_to_delete"]:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except:
            pass
    await update.message.reply_text(
        f"✅ *You're now registered!*\n👤 Name: *{users[user_id]['name']}*\n📍 Location saved.\n\nNow tell me what you'd like to order!",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def wait_location_to_browse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.location:
        msg = await update.message.reply_text("❗ Location is required. Please tap the button to send your location.")
        return WAIT_LOCATION_TO_BROWSE
    user_id = str(update.effective_user.id)
    users = load_users()
    users[user_id]["location"] = {
        "lat": update.message.location.latitude,
        "lon": update.message.location.longitude
    }
    save_users(users)
    context.user_data.clear()
    await update.message.reply_text(
        f"✅ Location received. Now tell me what you'd like to order!",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def require_location_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None: return
    user_id = str(update.effective_user.id)
    users = load_users()
    if user_id not in users or not users[user_id].get("location"):
        await prompt_location(update, context, registered=True)
        return
    await ask_product(update, context)

async def ask_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_users()
    user = users.get(user_id)
    if not user or "location" not in user:
        await prompt_location(update, context, registered=True)
        return
    query = update.message.text
    matches = match_vendors(query, user["location"])
    context.user_data.setdefault("messages_to_delete", []).append(update.message.message_id)
    if not matches:
        msg = await update.message.reply_text("❌ No vendors found with that product.")
        context.user_data["messages_to_delete"].append(msg.message_id)
        return
    context.user_data["search_results"] = matches
    context.user_data.setdefault("cart", [])
    for i, m in enumerate(matches):
        details = (
            f"{m['keywords'][0].title()} | "
            f"From: *{m['vendor']}*\n"
            f"Price: ₹{m['price']} | Stock: {m['stock']} | "
            f"Distance: {m['distance']} km"
        )
        add_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add to Cart", callback_data=f"add_{i}")],
            [InlineKeyboardButton("❌ Cancel Order", callback_data="cancel")]
        ])
        if m.get("photo"):
            photo_path = os.path.join(PHOTO_DIR, m["photo"])
            if os.path.isfile(photo_path):
                with open(photo_path, "rb") as imgfile:
                    msg = await update.message.reply_photo(
                        photo=imgfile, caption=details, parse_mode="Markdown", reply_markup=add_btn
                    )
                    context.user_data["messages_to_delete"].append(msg.message_id)
                continue
        msg = await update.message.reply_text(details, parse_mode="Markdown", reply_markup=add_btn)
        context.user_data["messages_to_delete"].append(msg.message_id)

async def vendor_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    index = int(query.data.split("_")[1])
    product = context.user_data["search_results"][index]
    context.user_data["cart"].append(product)
    context.user_data.setdefault("messages_to_delete", []).append(query.message.message_id)
    btns = [
        [
            InlineKeyboardButton("🧾 Checkout", callback_data="checkout"),
            InlineKeyboardButton("➕ Add to Cart", callback_data="add_more")
        ],
        [InlineKeyboardButton("❌ Cancel Order", callback_data="cancel")]
    ]
    msg = await query.message.reply_text(
        f"🛒 *Product added to cart:*\n{product['keywords'][0].title()} from {product['vendor']}",
        reply_markup=InlineKeyboardMarkup(btns),
        parse_mode="Markdown"
    )
    context.user_data["messages_to_delete"].append(msg.message_id)

async def handle_cart_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "add_more":
        msg = await query.message.reply_text("Please enter your next product:")
        context.user_data.setdefault("messages_to_delete", []).append(msg.message_id)
        return
    elif query.data == "checkout":
        btns = [
            [
                InlineKeyboardButton("🚚 Delivery", callback_data="delivery"),
                InlineKeyboardButton("🏪 Pickup", callback_data="pickup")
            ],
            [InlineKeyboardButton("❌ Cancel Order", callback_data="cancel")]
        ]
        msg = await query.message.reply_text("Select your delivery option:", reply_markup=InlineKeyboardMarkup(btns))
        context.user_data["messages_to_delete"].append(query.message.message_id)
        context.user_data["messages_to_delete"].append(msg.message_id)

async def finalize_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import uuid
    query = update.callback_query
    await query.answer()
    users = load_users()
    user_id = str(query.from_user.id)
    location = users[user_id]["location"]
    cart = context.user_data.get("cart", [])
    total = sum(item["price"] for item in cart)
    delivery_mode = query.data
    delivery_charge = 0
    if delivery_mode == "delivery":
        max_distance = max(item["distance"] for item in cart)
        delivery_charge = 10 + int(round(max_distance)) * 5
        delivery_text = f"🚚 Delivery: ₹{delivery_charge}"
    else:
        delivery_text = "🏪 Pickup: ₹0"
    grand_total = total + delivery_charge
    for msg_id in context.user_data.get("messages_to_delete", []):
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=msg_id)
        except:
            pass
    lines = ["🧾 *Order Summary:*", ""]
    for i, item in enumerate(cart, 1):
        lines.append(f"{i}. {item['keywords'][0].title()} from *{item['vendor']}* - ₹{item['price']}")
    lines.append("")
    lines.append(delivery_text)
    lines.append(f"💰 *Total: ₹{grand_total}*")
    buttons = [
        [
            InlineKeyboardButton("✅ Confirm Order", callback_data="confirm"),
            InlineKeyboardButton("❌ Cancel Order", callback_data="cancel")
        ]
    ]
    await query.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    context.user_data["order_summary"] = "\n".join(lines)
    context.user_data["order_details"] = {
        "cart": cart,
        "user": {**users[user_id], "tg_id": user_id},
        "delivery_option": delivery_mode,
        "delivery_charge": delivery_charge,
        "grand_total": grand_total,
    }

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import uuid
    query = update.callback_query
    await query.answer()
    order = context.user_data.get("order_details", {})
    cart = order.get("cart", [])
    user = order.get("user", {})
    delivery_option = order.get("delivery_option", "pickup")
    delivery_charge = order.get("delivery_charge", 0)
    grand_total = order.get("grand_total", 0)
    order_id = str(uuid.uuid4())[:8]
    vendor_msgs = {}
    for item in cart:
        vendor_id = item.get("vendor_chat_id")
        if not vendor_id:
            continue
        if vendor_id not in vendor_msgs:
            vendor_msgs[vendor_id] = []
        vendor_msgs[vendor_id].append(item)
    for vendor_id, products in vendor_msgs.items():
        prod_lines = [f"{i+1}. {p['keywords'][0].title()} – ₹{p['price']} ({p['stock']})" for i, p in enumerate(products)]
        msg = (
            f"🚨🚨🚨 *NEW ORDER RECEIVED!* 🚨🚨🚨\n\n"
            f"*Order ID*: `{order_id}`\n"
            f"Products:\n" +
            "\n".join(prod_lines) +
            f"\n\nCustomer: *{user.get('name', 'Unknown')}*"
            f"\nLocation: [{user['location']['lat']}, {user['location']['lon']}]"
            f"\n[Open in Maps](https://maps.google.com/?q={user['location']['lat']},{user['location']['lon']})"
            f"\nDelivery Option: {'Delivery' if delivery_option=='delivery' else 'Pickup'}"
            f"\nDelivery Charge: ₹{delivery_charge}\nTotal: ₹{grand_total}"
            "\n\nPlease *Accept* or *Reject* this order:"
        )
        kb = {
            "inline_keyboard": [[
                {"text":"✅ Accept", "callback_data":f"order_accept_{order_id}_{user['tg_id']}"},
                {"text":"❌ Reject", "callback_data":f"order_reject_{order_id}_{user['tg_id']}"}
            ]]
        }
        payload = {
            "chat_id": vendor_id,
            "text": msg,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
            "reply_markup": kb
        }
        try:
            requests.post(SEND_MSG_URL, json=payload)
        except Exception as e:
            print(f"Could not notify vendor {vendor_id}: {e}")
        # Save order for accept/reject/reminder in shared orders.json
        orders = load_orders()
        now = int(asyncio.get_event_loop().time()) if hasattr(asyncio, "get_event_loop") else 0
        orders[order_id] = {
            "user_id": user["tg_id"],
            "vendor_id": vendor_id,
            "status": "pending",
            "cart": products,
            "user": user,
            "created_time": now,
            "reminder_sent": False
        }
        save_orders(orders)
    await query.message.reply_text("🎉 Thank you so much for your order!\nYou're awesome 😄🛍️\nWe'll notify you once your order is accepted.")
    context.user_data.clear()

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    for msg_id in context.user_data.get("messages_to_delete", []):
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=msg_id)
        except:
            pass
    await query.message.reply_text("❌ Order cancelled. You can start again anytime.")
    context.user_data.clear()

def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            WAIT_LOCATION_TO_BROWSE: [MessageHandler(filters.LOCATION, wait_location_to_browse)],
            ASK_LOCATION: [MessageHandler(filters.LOCATION, ask_location)],
        },
        fallbacks=[],
    )
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, require_location_middleware))
    app.add_handler(CallbackQueryHandler(vendor_selected, pattern=r"^add_\d+$"))
    app.add_handler(CallbackQueryHandler(handle_cart_options, pattern="^(checkout|add_more)$"))
    app.add_handler(CallbackQueryHandler(finalize_order, pattern="^(delivery|pickup)$"))
    app.add_handler(CallbackQueryHandler(confirm_order, pattern="^confirm$"))
    app.add_handler(CallbackQueryHandler(cancel_order, pattern="^cancel$"))
    app.run_polling()

if __name__ == "__main__":
    run_bot()
