import os
import asyncio
import logging
import aiosqlite
import pyotp
from aiogram.filters import CommandStart, Command
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from security import IsAdminFilter, ThrottlingMiddleware
from locations import LOCATIONS_DB, REGION_TIPS, REGION_ROUTES
dp.message.middleware(ThrottlingMiddleware(limit=1.0))
dp.callback_query.middleware(ThrottlingMiddleware(limit=1.0))
class RouteSelection(StatesGroup):
    choosing_car = State()  
    choosing_days = State()
class AdminBroadcasting(StatesGroup):
    waiting_for_post = State()   
    waiting_for_confirm = State() 
    waiting_for_2fa = State()     
logging.basicConfig(level=logging.INFO)
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID_STR = os.getenv("CHANNEL_ID")
FEEDBACK_BOT_URL = os.getenv("FEEDBACK_BOT_URL")
DB_NAME = os.getenv("DB_NAME", "travel_bot.db")
ADMIN_ID_STR = os.getenv("ADMIN_ID")
ADMIN_2FA_SECRET = os.getenv("ADMIN_2FA_SECRET")
if not ADMIN_ID_STR or not ADMIN_2FA_SECRET:
    raise ValueError("ОШИБКА: Проверьте ADMIN_ID или ADMIN_2FA_SECRET в .env!")
ADMIN_ID = int(ADMIN_ID_STR)
totp = pyotp.TOTP(ADMIN_2FA_SECRET)
if not BOT_TOKEN or not CHANNEL_ID_STR or not FEEDBACK_BOT_URL:
    raise ValueError("ОШИБКА: Проверьте файл .env! Заполнены не все переменные.")
CHANNEL_ID = int(CHANNEL_ID_STR)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
READY_REGIONS = [
    "Дагестан",
    "Алтай",
    "Камчатка",
    "Калининград",
    "Карелия"
]
async def init_db():
    """Инициализация БД и создание таблиц пользователей и избранного"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id BIGINT,
                location_id INTEGER,
                UNIQUE(user_id, location_id) -- Защита от дублей
            )
        """)
        await db.commit()
async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        return False
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False
def get_sub_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/metikh_hq"))
    builder.row(types.InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_sub"))
    return builder.as_markup()
def get_main_reply_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text="🔍 Найти регион"))
    builder.row(
        types.KeyboardButton(text="📁 Мои поездки"),
        types.KeyboardButton(text="✍️ Обратная связь и Идеи")
    )
    return builder.as_markup(resize_keyboard=True)
def get_regions_inline_keyboard():
    builder = InlineKeyboardBuilder()
    for region in READY_REGIONS:
        builder.row(types.InlineKeyboardButton(text=f"🗺 {region}", callback_data=f"region_{region}"))
    return builder.as_markup()
def get_region_menu_keyboard(region_name: str):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🗺 Все локации", callback_data=f"menu_locs_{region_name}"))
    builder.row(types.InlineKeyboardButton(text="🚗 Готовые маршруты", callback_data=f"menu_routes_{region_name}"))
    builder.row(types.InlineKeyboardButton(text="💡 Лайфхаки и правила", callback_data=f"menu_tips_{region_name}"))
    builder.row(types.InlineKeyboardButton(text="🔙 К выбору региона", callback_data="back_to_regions"))
    return builder.as_markup()
def get_filters_keyboard(region_name: str):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🌿 Природные места", callback_data=f"filter_{region_name}_nature"),
        types.InlineKeyboardButton(text="🏛 История и Зодчество", callback_data=f"filter_{region_name}_history")
    )
    builder.row(
        types.InlineKeyboardButton(text="📸 Места для лучших фото", callback_data=f"filter_{region_name}_photo"),
        types.InlineKeyboardButton(text="🌆 Современные места", callback_data=f"filter_{region_name}_modern")
    )
    builder.row(
        types.InlineKeyboardButton(text="🏺 Этнография и ремесла", callback_data=f"filter_{region_name}_ethno"),
        types.InlineKeyboardButton(text="🚀 Будущие курорты (2026-2028)", callback_data=f"filter_{region_name}_future")
    )
    builder.row(
        types.InlineKeyboardButton(text="☀️ Лето", callback_data=f"filter_{region_name}_summer"),
        types.InlineKeyboardButton(text="🍂 Весна / Осень", callback_data=f"filter_{region_name}_autumn_spring"),
        types.InlineKeyboardButton(text="❄️ Зима", callback_data=f"filter_{region_name}_winter")
    )
    builder.row(types.InlineKeyboardButton(text="🌍 Показать абсолютно ВСЁ", callback_data=f"filter_{region_name}_all"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад в меню", callback_data=f"region_{region_name}"))
    return builder.as_markup()
def get_route_car_keyboard(region_name: str):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🚙 На машине", callback_data=f"rc_{region_name}_yes"),
        types.InlineKeyboardButton(text="🚶‍♂️ Без машины", callback_data=f"rc_{region_name}_no")
    )
    builder.row(types.InlineKeyboardButton(text="❌ Отмена", callback_data=f"routestop_{region_name}"))
    return builder.as_markup()
def get_route_days_keyboard(region_name: str):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="⏳ 2 дня (Экспресс)", callback_data=f"rd_{region_name}_2"),
        types.InlineKeyboardButton(text="📅 3 дня", callback_data=f"rd_{region_name}_3")
    )
    builder.row(
        types.InlineKeyboardButton(text="📆 5 дней", callback_data=f"rd_{region_name}_5"),
        types.InlineKeyboardButton(text="🍀 7 дней (Неделя)", callback_data=f"rd_{region_name}_7")
    )
    builder.row(
        types.InlineKeyboardButton(text="🗺 10 дней (Гранд-тур)", callback_data=f"rd_{region_name}_10")
    )
    builder.row(
        types.InlineKeyboardButton(text="❌ Отмена", callback_data=f"routestop_{region_name}")
    )
    return builder.as_markup()
def get_tips_menu_keyboard(region_name: str):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🧔 Для мужчин", callback_data=f"tips_{region_name}_men"),
        types.InlineKeyboardButton(text="👩 Для женщин (Важно!)", callback_data=f"tips_{region_name}_women")
    )
    builder.row(
        types.InlineKeyboardButton(text="🥟 Что попробовать из еды?", callback_data=f"tips_{region_name}_food")
    )
    builder.row(
        types.InlineKeyboardButton(text="💡 Топ-5 лайфхаков для всех", callback_data=f"tips_{region_name}_all")
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Назад в меню", callback_data=f"region_{region_name}"))
    return builder.as_markup()
def get_admin_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📢 Создать рассылку рекламы", callback_data="admin_broadcast"))
    builder.row(types.InlineKeyboardButton(text="📊 Посмотреть статистику бота", callback_data="admin_stats"))
    return builder.as_markup()
def get_admin_broadcast_confirm_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🚀 Да, запустить рассылку", callback_data="broadcast_confirm"),
        types.InlineKeyboardButton(text="❌ Сбросить и отменить", callback_data="broadcast_cancel")
    )
    return builder.as_markup()
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )
        await db.commit()
    is_subscribed = await check_subscription(user_id)
    if not is_subscribed:
        await message.answer(
            "👋 Привет! Чтобы пользоваться ботом-путеводителем, пожалуйста, подпишись на наш официальный канал.",
            reply_markup=get_sub_keyboard()
        )
        return
    await message.answer(
        f"🗺 Добро пожаловать в тревел-гид, {message.from_user.first_name}!\n"
        f"Выберите интересующий вас регион или действие в меню ниже 👇",
        reply_markup=get_main_reply_keyboard()
    )
@dp.callback_query(F.data == "check_sub")
async def callback_check_sub(callback: types.CallbackQuery):
    is_subscribed = await check_subscription(callback.from_user.id)
    if is_subscribed:
        await callback.message.delete() 
        await callback.message.answer(
            "✅ Подписка подтверждена! Добро пожаловать.",
            reply_markup=get_main_reply_keyboard()
        )
    else:
        await callback.answer("❌ Вы всё еще не подписались на канал!", show_alert=True)
def get_filtered_locations(region_name: str, filter_value: str) -> list:
    """Безопасная фильтрация локаций без дублирования кода"""
    all_locations = LOCATIONS_DB.get(region_name, [])
    if filter_value == "my_trips":
        return [] 
    filtered_locs = []
    for loc in all_locations:
        if filter_value == "all":
            filtered_locs.append(loc)
        elif filter_value in ["nature", "history", "photo", "modern", "ethno", "future"] and loc["category"] == filter_value:
            filtered_locs.append(loc)
        elif filter_value == "autumn_spring" and loc["season"] in ["autumn", "spring", "all"]:
            filtered_locs.append(loc)
        elif filter_value in ["summer", "winter"] and loc["season"] in [filter_value, "all"]:
            filtered_locs.append(loc)
    return filtered_locs
@dp.message(F.text == "🔍 Найти регион")
async def menu_find_region(message: types.Message):
    if not await check_subscription(message.from_user.id):
        return await message.answer("⚠️ Доступ заблокирован. Пожалуйста, подпишитесь.", reply_markup=get_sub_keyboard())
    
    await message.answer(
        "🗺 *Выберите регион России, который хотите посетить:*", 
        reply_markup=get_regions_inline_keyboard(),
        parse_mode="Markdown"
    )
@dp.message(F.text == "📁 Мои поездки")
async def menu_my_trips(message: types.Message):
    if not await check_subscription(message.from_user.id):
        return await message.answer("⚠️ Доступ заблокирован. Пожалуйста, подпишитесь.", reply_markup=get_sub_keyboard())
    await send_location_card(message.chat.id, "Дагестан", 0, "my_trips")
@dp.message(F.text == "✍️ Обратная связь и Идеи")
async def menu_feedback(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🚀 Написать отзыв / идею", url=FEEDBACK_BOT_URL))
    await message.answer(
        "У вас есть крутая идея, предложение или вы заметили ошибку в описании места?\n\n"
        "Нажмите кнопку ниже, чтобы отправить сообщение в наш единый центр поддержки. Мы обязательно его прочитаем!",
        reply_markup=builder.as_markup()
    )
@dp.callback_query(F.data.startswith("region_"))
async def callback_region_select(callback: types.CallbackQuery):
    region_name = callback.data.split("_")[1] 
    await callback.message.edit_text(
        f"🏖 *Добро пожаловать в путеводитель по региону: {region_name}!*\n\n"
        "Мы собрали для вас лучшие локации, проверенные маршруты и важные правила. "
        "Выберите, что вас интересует, с помощью кнопок ниже 👇",
        reply_markup=get_region_menu_keyboard(region_name),
        parse_mode="Markdown"
    )
    await callback.answer()
@dp.callback_query(F.data == "back_to_regions")
async def callback_back_to_regions(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🗺 *Выберите регион России, который хотите посетить:*",
        reply_markup=get_regions_inline_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()
@dp.callback_query(F.data.startswith("menu_locs_"))
async def callback_menu_locations(callback: types.CallbackQuery):
    region_name = callback.data.split("_")[2]
    await callback.message.edit_text(
        f"🧭 *Настройка фильтров для региона {region_name}*\n\n"
        "Куда вы хотите отправиться или в какое время года планируете поездку? "
        "Выберите нужную категорию, чтобы сузить поиск локаций 👇",
        reply_markup=get_filters_keyboard(region_name),
        parse_mode="Markdown"
    )
    await callback.answer()
@dp.callback_query(F.data.startswith("filter_"))
async def callback_filter_select(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    region_name = data_parts[1]
    filter_value = "_".join(data_parts[2:])
    filtered_locs = get_filtered_locations(region_name, filter_value)
    if not filtered_locs:
        await callback.answer("😔 Подходящих мест по вашему фильтру пока не найдено!", show_alert=True)
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await send_location_card(callback.message.chat.id, region_name, 0, filter_value)
    await callback.answer()
@dp.callback_query(F.data.startswith("page_"))
async def callback_pagination(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    region_name = data_parts[1]
    next_index = int(data_parts[2])
    filter_value = "_".join(data_parts[3:])
    await callback.message.delete()
    await send_location_card(callback.message.chat.id, region_name, next_index, filter_value)
    await callback.answer()
async def send_location_card(chat_id: int, region_name: str, index: int, filter_value: str):
    filtered_locs = get_filtered_locations(region_name, filter_value)
    if not filtered_locs:
        await bot.send_message(
            chat_id=chat_id, 
            text="📁 <b>Список пуст</b>\n\nЗдесь будут отображаться ваши сохраненные места, когда эта функция будет полностью подключена к базе данных."
        )
        return
    loc = filtered_locs[index]
    total_count = len(filtered_locs)
    caption = f"📍 <b>{loc['title']}</b>\n\n{loc['description']}\n\n"
    if loc.get('promo_text'):
        caption += f"{loc['promo_text']}\n\n" 
    builder = InlineKeyboardBuilder()
    prev_idx = total_count - 1 if index == 0 else index - 1
    next_idx = 0 if index == total_count - 1 else index + 1
    builder.row(
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"pg_{region_name}_{prev_idx}_{filter_value}"),
        types.InlineKeyboardButton(text=f"📄 {index + 1} / {total_count}", callback_data="dont_click"),
        types.InlineKeyboardButton(text="Вперед ➡️", callback_data=f"pg_{region_name}_{next_idx}_{filter_value}")
    )
    builder.row(
        types.InlineKeyboardButton(text="⭐️ В Избранное", callback_data=f"fav_{region_name}_{loc['id']}_{index}_{filter_value}")
    )
    builder.row(types.InlineKeyboardButton(text="🏠 В меню региона", callback_data=f"region_{region_name}"))
    try:
        await bot.send_photo(chat_id=chat_id, photo=loc['photo'], caption=caption, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        text_message = f"🖼 <b>[Фото недоступно]</b>\n\n{caption}"
        await bot.send_message(chat_id=chat_id, text=text_message, reply_markup=builder.as_markup(), parse_mode="HTML")
@dp.callback_query(F.data.startswith("pg_"))
async def callback_pagination(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    region_name = data_parts[1]
    next_index = int(data_parts[2])
    filter_value = "_".join(data_parts[3:])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await send_location_card(callback.message.chat.id, region_name, next_index, filter_value)
    await callback.answer()
@dp.callback_query(F.data.startswith("menu_tips_"))
async def callback_menu_tips(callback: types.CallbackQuery):
    region_name = callback.data.split("_")[2]
    await callback.message.edit_text(
        f"💡 *Правила поведения и полезные лайфхаки для региона {region_name}*\n\n"
        f"Каждый регион России уникален, обладает богатой культурой и своими традициями. "
        "Пожалуйста, выберите интересующий раздел, чтобы ваше путешествие прошло максимально комфортно и безопасно:",
        reply_markup=get_tips_menu_keyboard(region_name),
        parse_mode="Markdown"
    )
    await callback.answer()
@dp.callback_query(F.data.startswith("tips_"))
async def callback_show_specific_tips(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    region_name = data_parts[1]
    tip_category = data_parts[2]
    region_data = REGION_TIPS.get(region_name, {})
    text = region_data.get(tip_category)
    if not text:
        text = f"💡 Лайфхаки и полезная информация для региона {region_name} сейчас находятся в процессе активного наполнения контентом."
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Назад к разделам", callback_data=f"menu_tips_{region_name}"))
    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Ошибка вывода лайфхаков: {e}")
        await callback.answer("⚠️ Не удалось обновить текст.", show_alert=True)
    await callback.answer()
@dp.callback_query(F.data.startswith("menu_routes_"))
async def callback_menu_routes(callback: types.CallbackQuery, state: FSMContext):
    region_name = callback.data.split("_")[2]
    await state.set_state(RouteSelection.choosing_car)
    await callback.message.edit_text(
        f"🚗 *Планирование маршрута по региону {region_name}*\n\n"
        "Шаг 1: Подскажите, вы планируете путешествовать на машине (своей/арендованной) или без неё?",
        reply_markup=get_route_car_keyboard(region_name),
        parse_mode="Markdown"
    )
    await callback.answer()
@dp.callback_query(RouteSelection.choosing_car, F.data.startswith("rc_"))
async def callback_route_car_select(callback: types.CallbackQuery, state: FSMContext):
    data_parts = callback.data.split("_")
    region_name = data_parts[1]
    has_car = data_parts[2]
    await state.update_data(has_car=has_car)
    await state.set_state(RouteSelection.choosing_days) 
    await callback.message.edit_text(
        f"📅 *Отлично!*\n\nШаг 2: На какое количество дней вы планируете поездку?",
        reply_markup=get_route_days_keyboard(region_name),
        parse_mode="Markdown"
    )
    await callback.answer()
@dp.callback_query(F.data.startswith("routestop_"))
async def callback_route_cancel(callback: types.CallbackQuery, state: FSMContext):
    region_name = callback.data.split("_")[1]
    await state.clear()
    await callback.message.edit_text(
        f"🏖 *Добро пожаловать в путеводитель по региону: {region_name}!*\n\n"
        "Мы собрали для вас лучшие локации, проверенные маршруты и важные правила. "
        "Выберите, что вас интересует, с помощью кнопок ниже 👇",
        reply_markup=get_region_menu_keyboard(region_name),
        parse_mode="Markdown"
    )
    await callback.answer("Маршрутизатор закрыт")
@dp.callback_query(RouteSelection.choosing_days, F.data.startswith("rd_")) 
async def callback_route_final(callback: types.CallbackQuery, state: FSMContext):
    data_parts = callback.data.split("_")
    region_name = data_parts[1]
    days = data_parts[2] 
    user_data = await state.get_data()
    has_car = user_data.get("has_car", "no")
    await state.clear()
    if has_car == "yes":
        transport_tip = "🚙 _Маршрут оптимизирован для самостоятельной поездки на авто._"
    else:
        transport_tip = "🚶‍♂️ _Маршрут составлен с учетом общественного транспорта. Рекомендуется нанять местного гида для выездов в дикие горы._"
    route_text = REGION_ROUTES.get(region_name, {}).get(has_car, {}).get(days)
    if not route_text:
        if region_name == "Дагестан" and has_car == "no":
            route_text = (
                f"🗺 *Маршрут на {days} дней без машины по региону {region_name}*\n\n"
                "😔 К сожалению, готовых пеших программ на это количество дней пока нет (в отдаленные горные аулы общественный транспорт ходит крайне редко).\n\n"
                "Рекомендуем выбрать программы на *3 или 5 дней* без авто, либо вернуться назад и переключить опрос на вариант '🚙 На машине'!"
            )
        else:
            route_text = f"🗺 *Маршрут по региону {region_name} на {days} дней в процессе наполнения контентом!*"
    else:
        route_text = f"{route_text}\n\n{transport_tip}"
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🏠 В меню региона", callback_data=f"region_{region_name}"))
    try:
        await callback.message.edit_text(route_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Ошибка вывода финального маршрута: {e}")
        await callback.answer("⚠️ Не удалось отобразить путеводитель.", show_alert=True)
    await callback.answer()
async def run_bg_broadcast(photo_id: str | None, text_content: str, message_to_reply: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users_rows = await cursor.fetchall()         
    success_count = 0
    failed_count = 0  
    for row in users_rows:
        target_user_id = row[0]
        try:
            if photo_id:
                await bot.send_photo(chat_id=target_user_id, photo=photo_id, caption=text_content, parse_mode="HTML")
            else:
                await bot.send_message(chat_id=target_user_id, text=text_content, parse_mode="HTML")
            success_count += 1
            await asyncio.sleep(0.05) 
        except Exception:
            failed_count += 1
    await message_to_reply.answer(
        "📊 *Фоновая рассылка успешно завершена!*\n\n"
        f"✅ Доставлено сообщений: *{success_count}*\n"
        f"❌ Не доставлено (бот в бане): *{failed_count}*",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="Markdown"
    )
@dp.callback_query(F.data.startswith("fav_"))
async def callback_add_to_favorites(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    region_name = data_parts[1]
    location_id = int(data_parts[2])
    current_index = int(data_parts[3])
    filter_value = "_".join(data_parts[4:])
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO favorites (user_id, location_id) VALUES (?, ?)", (user_id, location_id))
        await db.commit()
    await callback.answer("⭐️ Место успешно сохранено в 'Мои поездки'!", show_alert=False)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await send_location_card(callback.message.chat.id, region_name, current_index, filter_value)
@dp.callback_query(F.data.startswith("unfav_"))
async def callback_remove_from_favorites(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    region_name = data_parts[1]
    location_id = int(data_parts[2])
    current_index = int(data_parts[3])
    filter_value = "_".join(data_parts[4:])
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM favorites WHERE user_id = ? AND location_id = ?", (user_id, location_id))
        await db.commit()  
    await callback.answer("❌ Место удалено из ваших поездок.", show_alert=False) 
    if filter_value == "my_trips":
        current_index = max(0, current_index - 1)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await send_location_card(callback.message.chat.id, region_name, current_index, filter_value)
@dp.message(Command("admin"), IsAdminFilter(admin_id=ADMIN_ID))
async def cmd_admin_panel(message: types.Message):
    await message.answer(
        "🛠 *Добро пожаловать в админ-панель!*\n\n"
        "Выберите необходимое действие:",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="Markdown"
    )
@dp.callback_query(F.data == "admin_stats", IsAdminFilter(admin_id=ADMIN_ID))
async def callback_admin_stats(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
    await callback.message.edit_text(
        "📊 *Текущая статистика:*\n\n"
        f"🔹 Всего пользователей в базе: *{total_users}* чел.\n\n"
        "ℹ️ _Данные собираются автоматически при первой успешной проверке подписки._",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()
@dp.callback_query(F.data == "admin_broadcast", IsAdminFilter(admin_id=ADMIN_ID))
async def callback_admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminBroadcasting.waiting_for_post)
    await callback.message.edit_text(
        "📢 *Режим создания рассылки*\n\n"
        "Пожалуйста, пришлите в чат пост (можно с фото).",
        parse_mode="Markdown"
    )
    await callback.answer()
@dp.message(AdminBroadcasting.waiting_for_post, IsAdminFilter(admin_id=ADMIN_ID))
async def process_admin_post_preview(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id if message.photo else None
    text_content = message.html_text
    await state.update_data(photo_id=photo_id, text_content=text_content)
    await state.set_state(AdminBroadcasting.waiting_for_confirm)
    await message.answer("👀 *Превью рекламного сообщения:*", parse_mode="Markdown")
    if photo_id:
        await bot.send_photo(chat_id=ADMIN_ID, photo=photo_id, caption=text_content, parse_mode="HTML")
    else:
        await bot.send_message(chat_id=ADMIN_ID, text=text_content, parse_mode="HTML")
    await message.answer(
        "⚠️ *Вы уверены, что хотите разослать этот пост всем пользователям бота?*",
        reply_markup=get_admin_broadcast_confirm_keyboard(),
        parse_mode="Markdown"
    )
@dp.callback_query(AdminBroadcasting.waiting_for_confirm, F.data == "broadcast_confirm", IsAdminFilter(admin_id=ADMIN_ID))
async def callback_broadcast_confirm(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminBroadcasting.waiting_for_2fa)
    await callback.message.edit_text(
        "🔐 *ДОП ЗАЩИТА (2FA)*\n\n"
        "Откройте приложение Authenticator и отправьте текущий 6-значный код подтверждения:",
        parse_mode="Markdown"
    )
    await callback.answer()
@dp.callback_query(AdminBroadcasting.waiting_for_confirm, F.data == "broadcast_cancel", IsAdminFilter(admin_id=ADMIN_ID))
async def callback_broadcast_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена и сброшена.", reply_markup=get_admin_main_keyboard())
    await callback.answer()
@dp.message(AdminBroadcasting.waiting_for_2fa, IsAdminFilter(admin_id=ADMIN_ID))
async def process_admin_2fa_verification(message: types.Message, state: FSMContext):
    user_code = message.text.strip().replace(" ", "")
    state_data = await state.get_data()
    failed_attempts = state_data.get("failed_attempts", 0)
    if not totp.verify(user_code):
        failed_attempts += 1
        if failed_attempts >= 3:
            await state.clear() 
            await message.answer("🚨 *3 неверных ввода кода подряд!* Сессия рассылки аннулирована.", parse_mode="Markdown")
            return
        await state.update_data(failed_attempts=failed_attempts)
        await message.answer(
            f"❌ *Неверный код безопасности!* Попробуйте еще раз.\n"
            f"⚠️ У вас осталось попыток: *{3 - failed_attempts}*",
            parse_mode="Markdown"
        )
        return
    photo_id = state_data.get("photo_id")
    text_content = state_data.get("text_content")
    await state.clear()
    await message.answer("🚀 *Код подтвержден! Рассылка запущена в фоновом режиме. Бот продолжает стабильно отвечать пользователям...*")
    asyncio.create_task(run_bg_broadcast(photo_id, text_content, message))
async def main():
    await init_db()
    dp.message.middleware(ThrottlingMiddleware(limit=0.8))
    dp.callback_query.middleware(ThrottlingMiddleware(limit=0.5))
    print("MT GROUP | MT SECURITY | Бот успешно запущен")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
