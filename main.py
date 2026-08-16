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
from locations import LOCATIONS_DB
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
        types.InlineKeyboardButton(text="🚙 На машине", callback_data=f"rcar_{region_name}_yes"),
        types.InlineKeyboardButton(text="🚶‍♂️ Без машины", callback_data=f"rcar_{region_name}_no")
    )
    builder.row(types.InlineKeyboardButton(text="❌ Отмена", callback_data=f"region_{region_name}"))
    return builder.as_markup()
def get_route_days_keyboard(region_name: str):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="2 дня (Экспресс)", callback_data=f"rdays_{region_name}_2"),
        types.InlineKeyboardButton(text="3 дня", callback_data=f"rdays_{region_name}_3")
    )
    builder.row(
        types.InlineKeyboardButton(text="5 дней", callback_data=f"rdays_{region_name}_5"),
        types.InlineKeyboardButton(text="7 дней (Неделя)", callback_data=f"rdays_{region_name}_7")
    )
    builder.row(
        types.InlineKeyboardButton(text="🗺 10 дней (Гранд-тур)", callback_data=f"rdays_{region_name}_10")
    )
    builder.row(types.InlineKeyboardButton(text="❌ Отмена", callback_data=f"region_{region_name}"))
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
    if not await check_subscription(user_id):
        await message.answer(
            "👋 Привет! Чтобы пользоваться этим travel-ботом, пожалуйста, подпишись на наш официальный канал.",
            reply_markup=get_sub_keyboard()
        )
    else:
        await add_user(user_id, username)
        await message.answer(
            f"🌟 Добро пожаловать, {message.from_user.first_name}! Куда отправимся?\n\n"
            "Нажмите кнопку «🔍 Найти регион» внизу экрана, чтобы выбрать интересующее вас направление.",
            reply_markup=get_main_reply_keyboard()
        )
@dp.callback_query(F.data == "check_sub")
async def callback_check_sub(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username
    if await check_subscription(user_id):
        await add_user(user_id, username)
        await callback.message.delete()
        await callback.message.answer(
            "✅ Подписка подтверждена! Добро пожаловать в мир путешествий.\n"
            "Используйте меню внизу экрана для выбора региона.",
            reply_markup=get_main_reply_keyboard()
        )
    else:
        await callback.answer("❌ Вы всё еще не подписались на канал!", show_alert=True)
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
    all_locations = LOCATIONS_DB.get(region_name, [])
    filtered_locs = []
    for loc in all_locations:
        if filter_value == "all":
            filtered_locs.append(loc)
        elif filter_value in ["nature", "history", "photo", "modern", "ethno", "future"] and loc["category"] == filter_value:
            filtered_locs.append(loc)
        elif filter_value in ["summer", "winter", "autumn_spring"] and (loc["season"] == filter_value or loc["season"] == "all"):
            filtered_locs.append(loc)
    if not filtered_locs:
        await callback.answer("😔 Подходящих мест по вашему фильтру пока не найдено!", show_alert=True)
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await send_location_card(callback.message.chat.id, region_name, 0, filter_value)
    await callback.answer()
async def send_location_card(chat_id: int, region_name: str, index: int, filter_value: str):
    """Генерация и безопасная отправка карточки места с динамическим Избранным"""
    all_locations = LOCATIONS_DB.get(region_name, [])
    filtered_locs = []
    if filter_value == "my_trips":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT location_id FROM favorites WHERE user_id = ?", (chat_id,)) as cursor:
                fav_rows = await cursor.fetchall()
        fav_ids = [row[0] for row in fav_rows]
        for r_name in LOCATIONS_DB:
            for loc in LOCATIONS_DB[r_name]:
                if loc["id"] in fav_ids:
                    filtered_locs.append(loc)
    else:
        for loc in all_locations:
            if filter_value == "all":
                filtered_locs.append(loc)
            elif filter_value in ["nature", "history", "photo", "modern", "ethno", "future"] and loc["category"] == filter_value:
                filtered_locs.append(loc)
            elif filter_value in ["summer", "winter", "autumn_spring"] and (loc["season"] == filter_value or loc["season"] == "all"):
                filtered_locs.append(loc)
    if not filtered_locs:
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_regions"))
        await bot.send_message(chat_id, "📁 Ваше Избранное пока пусто! Добавляйте места кнопкой '⭐ В Избранное' во время просмотра.", reply_markup=builder.as_markup())
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
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page_{region_name}_{prev_idx}_{filter_value}"),
        types.InlineKeyboardButton(text=f"📄 {index + 1} / {total_count}", callback_data="dont_click"),
        types.InlineKeyboardButton(text="Вперед ➡️", callback_data=f"page_{region_name}_{next_idx}_{filter_value}")
    )
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM favorites WHERE user_id = ? AND location_id = ?", (chat_id, loc['id'])) as cursor:
            is_fav = await cursor.fetchone()
    if is_fav:
        builder.row(types.InlineKeyboardButton(text="❌ Удалить из Избранного", callback_data=f"unfav_{region_name}_{loc['id']}_{index}_{filter_value}"))
    else:
        builder.row(types.InlineKeyboardButton(text="⭐️ В Избранное", callback_data=f"fav_{region_name}_{loc['id']}_{index}_{filter_value}"))
    builder.row(types.InlineKeyboardButton(text="🏠 В меню региона", callback_data=f"region_{region_name}"))
    try:
        await bot.send_photo(chat_id=chat_id, photo=loc['photo'], caption=caption, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        text_message = f"🖼 <b>[Фото недоступно]</b>\n\n{caption}"
        await bot.send_message(chat_id=chat_id, text=text_message, reply_markup=builder.as_markup(), parse_mode="HTML")
@dp.callback_query(F.data.startswith("page_"))
async def callback_pagination(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    region_name = data_parts[1]
    next_index = int(data_parts[2])
    filter_value = "_".join(data_parts[3:])
    await callback.message.delete()
    await send_location_card(callback.message.chat.id, region_name, next_index, filter_value)
    await callback.answer()
@dp.callback_query(F.data.startswith("menu_tips_"))
async def callback_menu_tips(callback: types.CallbackQuery):
    region_name = callback.data.split("_")[2]
    
    await callback.message.edit_text(
        f"💡 *Правила поведения и полезные лайфхаки для региона {region_name}*\n\n"
        "Дагестан — регион с богатой культурой и глубокими традициями. "
        "Пожалуйста, выберите интересующий раздел, чтобы ваше путешествие прошло комфортно и безопасно:",
        reply_markup=get_tips_menu_keyboard(region_name),
        parse_mode="Markdown"
    )
    await callback.answer()
@dp.callback_query(F.data.startswith("tips_"))
async def callback_show_specific_tips(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    region_name = data_parts[1]
    tip_category = data_parts[2]
    if region_name == "Дагестан":
        if tip_category == "women":
            text = (
                "👩 *Рекомендации для женщин (Важно!)*\n\n"
                "Дагестан — преимущественно мусульманская республика, поэтому одежда здесь играет ключевую роль в проявлении уважения к местным традициям.\n\n"
                "• *Забудьте про мини и декольте:* Шорты, короткие юбки, облегающие майки и платья с открытыми плечами/животом лучше оставить для других курортов.\n"
                "• *Идеальный гардероб:* Свободные платья в пол, юбки ниже колена, легкие брюки (кюлоты или палаццо) и оверсайз-рубашки, закрывающие плечи и локти.\n"
                "• *Головной убор:* Носить платок на улице туристам не нужно. Он понадобится только при входе в мечети (там его часто выдают на входе, но лучше иметь свой красивый палантин).\n"
                "• *Для купания:* На общественных пляжах Махачкалы и Дербента женщинам-туристкам можно быть в обычных закрытых (слитных) купальниках. Раздельные бикини допустимы только на закрытых базах отдыха или совсем диких, безлюдных пляжах."
            )
        elif tip_category == "men":
            text = (
                "🧔 *Рекомендации для мужчин*\n\n"
                "• *Шорты под запретом:* Это главное правило. Даже в сильную жару мужчинам в Дагестане не принято ходить в шортах (особенно в горах и религиозных местах). Местные мужчины носят легкие брюки, джинсы или спортивные штаны. Относитесь к этому с уважением, чтобы избежать замечаний.\n"
                "• *Майки-алкоголички:* Мужские майки без рукавов на улицах городов и сел также вызовут недоумение. Носите классические футболки или легкие рубашки."
            )
        elif tip_category == "food":
            text = (
                "🥟 *Гид по национальной кухне Дагестана*\n"
                "Вот список главных блюд, которые обязан попробовать каждый турист:\n\n"
                "1️⃣ *Хинкал (Главное блюдо республики)*\n"
                "Не путайте с грузинскими хинкали. Дагестанский хинкал — это не цельное блюдо, а целый «конструктор». Вам подадут отдельно сваренные в мясном бульоне кусочки теста, отдельно куски отварного мяса (говядина, баранина или сушеное мясо), пиалу с наваристым бульоном и острый соус (томатный с чесноком или сметанный).\n"
                "• _Лезгинский хинкал:_ Тесто раскатывается тонко и режется на небольшие квадратики.\n"
                "• _Аварский хинкал:_ Пышные, толстые кусочки теста, приготовленные на кефире или соде.\n"
                "• _Даргинский хинкал:_ Тесто раскатывают, посыпают ореховой травой, сворачивают в рулет и готовят на пару (в виде слоеных рулетиков).\n"
                "• _Лакский хинкал:_ Тесто скатывают в мелкие аккуратные «ракушки» или «ушки».\n\n"
                "2️⃣ *Чуду (Тонкие и толстые пироги)*\n"
                "Это тончайшие (или, наоборот, пышные слоеные) лепешки с самыми разными начинками, которые жарятся на сухой сковороде, а перед подачей обильно смазываются топленым маслом.\n"
                "• _С мясом и зеленью:_ Классический зимний или весенний вариант.\n"
                "• _С творогом и зеленью:_ Легкий и очень нежный вариант.\n"
                "• _С тыквой:_ Удивительное сочетание сладковатой тыквы, лука и грецких орехов (очень популярно у даргинцев).\n"
                "• _Ботищал:_ Особый аварский вид чуду с начинкой из творога и картофеля. Правильный ботищал тянется, как расплавленный сыр, когда его отламывают.\n\n"
                "3️⃣ *Сушеное мясо и колбаса*\n"
                "Настоящий горский деликатес со специфическим вкусом и ароматом. Мясо и домашнюю колбасу со специями вялят на открытом горном воздухе в тени. Горцы часто добавляют его в хинкал или варят фасолевый суп.\n\n"
                "4️⃣ *Курзе (Дагестанские пельмени)*\n"
                "Дагестанский аналог пельменей или вареников, но их плетут красивой «косичкой», а начинка может быть жидкой.\n"
                "• _С мясом:_ Острая мясная начинка со специями, луком и курдюком.\n"
                "• _С яйцом:_ Уникальное блюдо. В мешочек из теста заливают сырое яйцо, взбитое с зеленым луком и молоком, и мгновенно бросают в кипяток.\n\n"
                "5️⃣ *Урбеч (Дагестанская «нутелла»)*\n"
                "Паста из перетертых на каменных жерновах семян или орехов. Из него делают десерт, смешивая со сливочным маслом и медом.\n"
                "• _Льняной (темный):_ Классический, слегка вяжущий. Самый полезный.\n"
                "• _Абрикосовый (из косточек):_ Нежный, с легкой кислинкой и ароматом марципана.\n"
                "• _Ореховый:_ Из миндаля, фундука или грецкого ореха — идеальный топпинг к каше.\n\n"
                "6️⃣ *Каша из кураги (Абрикосовая каша)*\n"
                "Традиционный нежный десерт из разваренной кураги, который перед едой обязательно поливают сладким урбечем."
            )
        elif tip_category == "all":
            text = (
                "💡 *Топ-5 главных лайфхаков для всех туристов*\n\n"
                "1️⃣ *Всегда имейте наличные деньги:* В Махачкале и Дербенте во многих местах можно расплатиться картой или переводом по СБП. Но в горах, на заправках, в аулах и на рынках интернет часто не ловит, а терминалов нет вообще. Наличные рубли (желательно мелкими купюрами) — ваш главный спаситель.\n\n"
                "2️⃣ *Скачайте офлайн-карты заранее:* В горах Дагестана мобильная связь и интернет отключаются полностью. Заранее скачайте офлайн-карты в «Яндекс Навигатор» или Maps.me, чтобы не заблудиться на серпантинах.\n\n"
                "3️⃣ *Берите кроссовки с хорошим протектором:* Дойти до Гамсутля, Карадахской теснины или Языка Тролля придется пешком по грунту, камням и глине. Никаких шлепанцев, кед на плоской подошве или каблуков. Только треккинговые кроссовки.\n\n"
                "4️⃣ *Не стесняйтесь просить о помощи:* Дагестанское гостеприимство — это не миф. Если вы заблудились в горах или у вас сломалась машина, смело обращайтесь к местным. Вас не просто направят, а скорее всего, довезут, напоят чаем и накормят чуду.\n\n"
                "5️⃣ *Дресс-код для автомобиля:* Если вы арендуете машину, помните, что в горах на узких серпантинах принято сигналить перед закрытыми поворотами, чтобы предупредить встречные машины."
            )
    else:
        text = f"💡 Лайфхаки для региона {region_name} находятся в процессе наполнения контентом."
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Назад к разделам", callback_data=f"menu_tips_{region_name}"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()
@dp.callback_query(F.data.startswith("menu_routes_"))
async def callback_menu_routes(callback: types.CallbackQuery, state: FSMContext):
    region_name = callback.data.split("_")[2]
    await state.set_state(RouteSelection.choosing_car) # Включаем режим опроса
    await callback.message.edit_text(
        f"🚗 *Планирование маршрута по региону {region_name}*\n\n"
        "Шаг 1: Подскажите, вы планируете путешествовать на машине (своей/арендованной) или без неё?",
        reply_markup=get_route_car_keyboard(region_name),
        parse_mode="Markdown"
    )
    await callback.answer()
@dp.callback_query(RouteSelection.choosing_car, F.data.startswith("rcar_"))
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
@dp.callback_query(RouteSelection.choosing_days, F.data.startswith("rdays_"))
async def callback_route_final(callback: types.CallbackQuery, state: FSMContext):
    data_parts = callback.data.split("_")
    region_name = data_parts[1]
    days = data_parts[2] 
    user_data = await state.get_data()
    has_car = user_data.get("has_car")
    await state.clear()
    transport_tip = "🚙 _Маршрут оптимизирован для поездки на авто._" if has_car == "yes" else "🚶‍♂️ _Рекомендуется заказать экскурсию или нанять местного гида с машиной._"
    if region_name == "Дагестан":
        if has_car == "yes":
            if days == "2":
                route_text = (
                    "🗺 *Маршрут на 2 дня: Экспресс-тур (На автомобиле)*\n"
                    f"{transport_tip}\n\n"
                    "Идеальный план для первых выходных, который знакомит с визитными карточками республики:\n\n"
                    "🔹 *День 1: Величие каньона*\n"
                    "• *Сулакский каньон* — Главный бренд Дагестана с невероятной бирюзовой водой.\n"
                    "• *Смотровая площадка Дубки* — Лучшая точка для панорамных фотографий каньона.\n"
                    "• *Экотуркомплекс «Главрыба»* — Комфортное место для обеда форелью и отдыха у реки.\n\n"
                    "🔹 *День 2: Пески пустыни*\n"
                    "• *Бархан Сарыкум* — Огромная пустынная дюна посреди горного ландшафта."
                )
            elif days == "3":
                route_text = (
                    "🗺 *Маршрут на 3 дня: Древний Дербент и Каспий (На автомобиле)*\n"
                    f"{transport_tip}\n\n"
                    "Программа выходного дня дополняется поездкой в самый южный и древний город России:\n\n"
                    "🔹 *Дни 1-2: Каньон и Сарыкум* (Повторяют Экспресс-программу).\n\n"
                    "🔹 *День 3: Погружение в историю*\n"
                    "• *Крепость Нарын-Кала* — Великая цитадель, защищавшая Каспийские ворота.\n"
                    "• *Старый город Магал* — Лабиринты старинных кварталов и Джума-мечеть VIII века.\n"
                    "• *Экраноплан «Лунь»* — Огромный советский корабль-самолет на берегу моря.\n"
                    "• *Дербентский мультимедийный фонтан* — Вечернее светомузыкальное шоу в парке Низами Гянджеви."
                )
            elif days == "5":
                route_text = (
                    "🗺 *Маршрут на 5 дней: Сердце горного Дагестана (На автомобиле)*\n"
                    f"{transport_tip}\n\n"
                    "Глубокое погружение в Нагорный Дагестан — Хунзах и Гуниб:\n\n"
                    "🔹 *День 1-3: Главные визитки и Дербент.*\n\n"
                    "🔹 *День 4: Водопады и теснины*\n"
                    "• *Хунзахское плато и водопад Тобот* — Мощный 70-метровый водопад, срывающийся в каньон.\n"
                    "• *Салтинский подземный водопад* — Уникальный пещерный водопад в узкой теснине.\n"
                    "• *Карадахская теснина* — Природный скальный коридор шириной всего несколько метров.\n\n"
                    "🔹 *День 5: Заброшенные цитадели и озера*\n"
                    "• *Село-призрак Гамсутль* — Покинутый высокогорный аул, кавказский «Мачу-Пикчу».\n"
                    "• *Ирганайское водохранилище* — Живописное изумрудное озеро в окружении массивных скал."
                )
            elif days == "7":
                route_text = (
                    "🗺 *Маршрут на 7 дней (Неделя): Максимальное этно-погружение (На авто)*\n"
                    f"{transport_tip}\n\n"
                    "Полноценное путешествие, включающее дикие горные башни, секретные локации и центры ремесел:\n\n"
                    "🔹 *Дни 1-5: Полный горный и прибрежный кластер.*\n\n"
                    "🔹 *День 6: Экстрим и боевые башни*\n"
                    "• *Старый Кахиб и Гоор* — Оборонительные башни и знаменитый скальный выступ «Язык Тролля».\n"
                    "• *Плато Матлас и Каменная чаша* — Теснины, пещеры и экстремальные качели над пропастью.\n"
                    "• *Комплекс пещер «Нохъо»* — Подвесные мостов и тарзанки над Сулакским каньоном.\n\n"
                    "🔹 *День 7: Ремёсла и традиции предков*\n"
                    "• *Аул Кубачи* — Высокогорное село легендарных мастеров по серебру и ювелиров.\n"
                    "• *Село Чох* — Живой памятник потрясающей террасной архитектуры горцев."
                )
            elif days == "10":
                route_text = (
                    "🗺 *Оптимальный маршрут на 10 дней (На автомобиле)*\n"
                    "⚠️ _Для этого маршрута строго необходим автомобиль (лучше кроссовер или внедорожник)._\n\n"
                    "💡 *Где именно нужна машина?*\n"
                    "Машина критически необходима с 3 по 9 дни 10-дневного маршрута. В Кубачи, Чох, Гоор и Хунзах общественные автобусы либо не ходят вообще, либо ездят один раз в день (утром из аула в город, вечером обратно), что делает туризм невозможным. Дороги к Гамсутлю, Карадахской теснине и Матласу включают грунтовые горные серпантины, где передвигаться можно только на авто или заказывая дорогое местное джип-такси.\n\n"
                    "🧗‍♂️ *Программа гранд-тура по дням:*\n\n"
                    "📍 *День 1: Прилет и Каспийский берег*\n"
                    "• _Махачкала (аэропорт) → Избербаш → Дербент._ Озеро Ак-Гёль, песчаные пляжи Избербаша, заселение в Дербенте.\n\n"
                    "📍 *День 2: Древности Дербента*\n"
                    "• Цитадель Нарын-Кала, древние кварталы Магалы, Джума-мечеть VIII века. Вечером — мультимединный фонтан в парке Низами Гянджеви.\n\n"
                    "📍 *День 3: Каспийский монстр и мастера серебра*\n"
                    "• _Дербент → Экраноплан «Лунь» → Аул Кубачи._ Экраноплан на побережье, переезд в туманный аул Кубачи, сторожевая башня и домашние музеи серебра.\n\n"
                    "📍 *День 4: Въезд в горный Дагестан*\n"
                    "• _Кубачи → Гергебиль → Ирганайское водохранилище → Село Чох._ Проезд через Гимринский тоннель, изумрудные виды Ирганайского водохранилища. Ночевка в атмосферном горном селе Чох.\n\n"
                    "📍 *День 5: Кавказский «Мачу-Пикчу» и подземный водопад*\n"
                    "• _Чох → Гамсутль → Салтинский водопад → Гуниб._ Утреннее восхождение к заброшенному аулу Гамсутль (пешком около 1,5–2 часов в гору), после обеда — прогулка по Салтинской теснине к подземному водопаду.\n\n"
                    "📍 *День 6: Сердце гор — Гуниб*\n"
                    "• Гунибская крепость, ворота Шамиля, царская поляна, природный парк «Верхний Гуниб».\n\n"
                    "📍 *День 7: Край водопадов и башен*\n"
                    "• _Гуниб → Карадахская теснина → Хунзах (плато)._ Проход между узкими скалами Карадахской теснины, переезд на Хунзахское плато, каньон Цолотль и ревущий водопад Тобот.\n\n"
                    "📍 *День 8: Экстрим на плато Матлас*\n"
                    "• _Хунзах → Матлас → Каменная чаша → Старый Гоор._ Живописные теснины «Каменная чаша», экстрим-парк в Матласе. Ближе к закату — древние башни Гоора и фото на «Языке Тролля».\n\n"
                    "📍 *День 9: Главный каньон Дагестана*\n"
                    "• _Гоор → Чиркейское водохранилище → Дубки (Сулакский каньон)._ Смотровая площадка на каньон в Дубках, комплекс пещер и подвесных мостов «Нохъо», катание на скоростных катерах.\n\n"
                    "📍 *День 10: Пустыня и вылет*\n"
                    "• _Дубки → Бархан Сарыкум → Махачкала (аэропорт)._ Экотуркомплекс «Главрыба», подъем на вершины песчаного бархана Сарыкум, покупка сувениров и вылет."
                )
        else:
            if days == "3":
                route_text = (
                    "🗺 *Этно-экспресс на 3 дня (Без машины)*\n"
                    f"{transport_tip}\n\n"
                    "• *День 1: Махачкала.* Прилетаете, берете такси до города. Пешеходная прогулка по улице Буйнакского, осмотр Центральной Джума-мечети. Вечером — подъем на смотровую площадку Тарки-Тау (на городском такси).\n\n"
                    "• День 2: Дербент. Утром садитесь на скоростную электричку Махачкала — Дербент (идет около 2 часов). В Дербенте передвигаетесь пешком по старым Магалам и берете местное такси до крепости Нарын-Кала. Вечером — пешком до фонтана в парке Низами.\n\n"
                    "• День 3: Каспийский монстр. На городском такси Дербента едете за город к экраноплану «Лунь» (около 20 минут). Возвращаетесь на электричке в Махачкалу и уезжаете в аэропорт.")
            elif days == "5":
                route_text = ("🗺 Природа и каньоны на 5 дней (Без машины)\n"
                f"{transport_tip}\n\n"
                "• День 1: Махачкала — Дубки. Из Махачкалы (от автостанции Северная) садитесь на маршрутку до поселка Дубки. Пешком доходите до главной смотровой площадки Сулакского каньона. Ночуете в Дубках.\n\n"
                "• День 2: Каньоны и катера. Из Дубков берете местное такси до экотуркомплекса «Главрыба» или поселка Зубутли. Там садитесь на туристический катер и отправляетесь на водную прогулку по бирюзовым водам Сулакского каньона.\n\n"
                "• День 3: Из гор к морю. На утренней маршрутке возвращаетесь из Дубков в Махачкалу, на автостанции пересаживаетесь на маршрутку или электричку до Дербента. Заселение, прогулка по обновленной Набережной Дербента.\n\n"
                "• День 4: История Дербента. Полностью пешеходный день внутри Дербента: подъем к Нарын-Кала, прогулка по лабиринтам старого города, посещение старинных бань и дегустация национальных чуду в местных кафе.\n\n"
                "• День 5: Экраноплан и сувениры. Утром на такси доезжаете до экраноплана «Лунь». Возвращаетесь в город, покупаете на рынке сувениры, серебро и берете электричку до аэропорта.")
            else:
                route_text = (f"🗺 Маршрут на {days} дней без машины по региону {region_name}\n\n"
                "😔 К сожалению, готовых пеших программ на это количество дней пока нет (в отдаленные горные аулы транспорт ходит крайне редко).\n\n"
                "Рекомендуем выбрать программы на 3 или 5 дней без авто, либо вернуться назад и переключить опрос на вариант '🚙 На машине'!")
    else:route_text = f"🗺 Маршрут по региону {region_name} на {days} дней в процессе наполнения контентом!"
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🏠 В меню региона", callback_data=f"region_{region_name}"))
    await callback.message.edit_text(route_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()
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
    await callback.message.delete()
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
    await callback.message.delete()
    await send_location_card(callback.message.chat.id, region_name, current_index, filter_value)
@dp.message(Command("admin"), IsAdminFilter(admin_id=ADMIN_ID))
async def cmd_admin_panel(message: types.Message):
    await message.answer(
        "🛠 *Добро пожаловать в защищенную панель администратора!*\n\n"
        "Выберите необходимое действие с помощью инлайн-кнопок:",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="Markdown"
    )
@dp.callback_query(F.data == "admin_stats", IsAdminFilter(admin_id=ADMIN_ID))
async def callback_admin_stats(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
    await callback.message.edit_text(
        "📊 *Текущая статистика travel-бота:*\n\n"
        f"🔹 Всего уникальных пользователей в базе: *{total_users}* чел.\n\n"
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
        "Пожалуйста, пришлите в чат пост, который увидят все пользователи.",
        parse_mode="Markdown"
    )
    await callback.answer()
@dp.message(AdminBroadcasting.waiting_for_post, IsAdminFilter(admin_id=ADMIN_ID))
async def process_admin_post_preview(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id if message.photo else None
    text_content = message.html_text if message.photo else message.html_text
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
        "🔐 *ДОП ЗАЩИТА*\n\n"
        "Отправьте код для подтверждения операции:",
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
    if not totp.verify(user_code):
        await message.answer("❌ *Неверный код безопасности или срок его действия истек!* Попробуйте еще раз:")
        return
    data = await state.get_data()
    photo_id = data.get("photo_id")
    text_content = data.get("text_content")
    await state.clear()
    await message.answer("🚀 *Код подтвержден! Начинаю массовую рассылку рекламы...*")
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
    await message.answer(
        "📊 *Рассылка успешно завершена!*\n\n"
        f"✅ Доставлено сообщений: *{success_count}*\n"
        f"❌ Не доставлено (бот в бане у юзера): *{failed_count}*",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="Markdown"
    )
async def main():
    await init_db()
    dp.message.middleware(ThrottlingMiddleware(limit=0.8))
    dp.callback_query.middleware(ThrottlingMiddleware(limit=0.5))
    print("MT GROUP | MT SECURITY")
    await dp.start_polling(bot)