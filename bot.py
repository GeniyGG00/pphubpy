import os
import sys
import signal
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from copy import deepcopy

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# Load environment variables
load_dotenv()

# Bot token and chat IDs from environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')
GROUP_CHAT_ID = os.getenv('GROUP_CHAT_ID')

# Validate environment variables
if not TOKEN:
    print('❌ ОШИБКА: TELEGRAM_BOT_TOKEN не найден в .env файле!')
    sys.exit(1)

if not ADMIN_CHAT_ID:
    print('⚠️ ПРЕДУПРЕЖДЕНИЕ: ADMIN_CHAT_ID не найден в .env файле!')

if not GROUP_CHAT_ID:
    print('⚠️ ПРЕДУПРЕЖДЕНИЕ: GROUP_CHAT_ID не найден в .env файле!')

print('✅ Переменные окружения загружены успешно')
print(f'📱 Admin Chat ID: {ADMIN_CHAT_ID}')
print(f'👥 Group Chat ID: {GROUP_CHAT_ID}')

# Admin usernames
ADMIN_USERS = [
    'Promezytkina1',
    'Promezytkina',
    'Belui2807'
]

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


@dataclass
class Product:
    id: str
    name: str
    price: int
    quantity: int


@dataclass
class CartItem:
    name: str
    price: int
    quantity: int


@dataclass
class User:
    user_id: int
    username: str
    cart: List[CartItem] = field(default_factory=list)
    comment: str = ''
    waiting_for_comment: bool = False
    waiting_for_product_add: bool = False
    waiting_for_new_category: bool = False
    waiting_for_quantity_input: bool = False
    selected_category: str = ''
    selected_product_id: str = ''


@dataclass
class Order:
    user_id: int
    username: str
    items: List[CartItem]
    comment: str
    status: str
    created_at: datetime


# In-memory storage
users: Dict[int, User] = {}
orders: List[Order] = []

# Product catalog
catalog: Dict[str, List[Product]] = {
    'Одноразки': [
        Product(id='disposable1', name='HQD 2500', price=1000, quantity=10),
        Product(id='disposable2', name='Ivy', price=1200, quantity=5),
        Product(id='disposable3', name='Maskking', price=1500, quantity=0)
    ],
    'Подсистемы': [
        Product(id='pod1', name='Voopoo', price=2500, quantity=3),
        Product(id='pod2', name='Uwell', price=3000, quantity=7),
        Product(id='pod3', name='спизженный хиро 3 в ахуитительном состоянии', price=5000, quantity=1)
    ],
    'Снюс': [
        Product(id='snus1', name='EPOK', price=500, quantity=15),
        Product(id='snus2', name='Siberia', price=600, quantity=8),
        Product(id='snus3', name='Odens', price=550, quantity=0)
    ],
    'Жидкости': [
        Product(id='liquid1', name='Honey Cream 3mg', price=800, quantity=20),
        Product(id='liquid2', name='Mango Ice 3mg', price=800, quantity=12),
        Product(id='liquid3', name='Strawberry 6mg', price=800, quantity=6),
        Product(id='liquid4', name='Tobacco 6mg', price=800, quantity=9),
        Product(id='liquid5', name='Menthol 0mg', price=800, quantity=4),
        Product(id='liquid6', name='Blueberry 3mg', price=800, quantity=11)
    ]
}


def get_user(chat_id: int, username: str = 'User') -> User:
    """Get or create user."""
    if chat_id not in users:
        users[chat_id] = User(user_id=chat_id, username=username)
    return users[chat_id]


def is_admin(username: Optional[str]) -> bool:
    """Check if user is admin."""
    return username is not None and username in ADMIN_USERS


def has_available_products() -> bool:
    """Check if any products are available."""
    for category in catalog.values():
        for product in category:
            if product.quantity > 0:
                return True
    return False


def remove_out_of_stock_products() -> List[str]:
    """Remove products with zero quantity."""
    removed_products = []
    
    categories_to_remove = []
    for category_name, category_products in catalog.items():
        products_to_keep = []
        for product in category_products:
            if product.quantity <= 0:
                removed_products.append(f'{product.name} из категории {category_name}')
            else:
                products_to_keep.append(product)
        
        if products_to_keep:
            catalog[category_name] = products_to_keep
        else:
            categories_to_remove.append(category_name)
    
    for category_name in categories_to_remove:
        del catalog[category_name]
    
    return removed_products


def add_product(category_name: str, name: str, price: int, quantity: int) -> Product:
    """Add a new product to catalog."""
    if category_name not in catalog:
        catalog[category_name] = []
    
    product_id = f'{category_name.lower().replace(" ", "_")}_{int(datetime.now().timestamp())}'
    new_product = Product(id=product_id, name=name, price=price, quantity=quantity)
    catalog[category_name].append(new_product)
    
    return new_product


def remove_product(category_name: str, product_id: str) -> bool:
    """Remove a product from catalog."""
    if category_name not in catalog:
        return False
    
    initial_length = len(catalog[category_name])
    catalog[category_name] = [p for p in catalog[category_name] if p.id != product_id]
    
    if len(catalog[category_name]) == 0:
        del catalog[category_name]
    
    return len(catalog[category_name]) < initial_length


def update_product_quantity(category_name: str, product_id: str, new_quantity: int) -> bool:
    """Update product quantity."""
    if category_name not in catalog:
        return False
    
    for product in catalog[category_name]:
        if product.id == product_id:
            product.quantity = new_quantity
            return True
    
    return False


def find_product_by_id(product_id: str) -> Optional[tuple]:
    """Find product by ID, returns (category_name, product) or None."""
    for category_name, products in catalog.items():
        for product in products:
            if product.id == product_id:
                return (category_name, product)
    return None


def get_main_menu_keyboard(username: Optional[str]) -> List[List[str]]:
    """Get main menu keyboard based on user role."""
    if is_admin(username):
        return [
            ['🛒 Каталог'],
            ['🛒 Корзина'],
            ['ℹ️ О нас'],
            ['👨‍💼 Админка']
        ]
    return [
        ['🛒 Каталог'],
        ['🛒 Корзина'],
        ['ℹ️ О нас']
    ]


async def safe_send_message(chat_id: Optional[str], text: str, **kwargs) -> bool:
    """Safely send message with error handling."""
    if not chat_id:
        logger.warning('⚠️ Попытка отправки сообщения без chatId')
        return False
    
    try:
        # This will be called from the bot context
        return True
    except Exception as e:
        logger.error(f'❌ Ошибка отправки сообщения в чат {chat_id}: {e}')
        return False


# Command handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    
    # Debug log
    logger.info(f'User: {username}, isAdmin: {is_admin(update.effective_user.username)}')
    
    # Get or create user
    user = get_user(chat_id, username)
    
    # Send welcome message
    welcome_message = (
        f'👋 Привет, {username}! Добро пожаловать в PPHUB!\n\n'
        'Выберите категорию товаров:'
    )
    
    keyboard = get_main_menu_keyboard(update.effective_user.username)
    reply_markup = {'keyboard': keyboard, 'resize_keyboard': True}
    
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin command."""
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    
    if not is_admin(username):
        await update.message.reply_text('🚫 У вас нет прав для выполнения этой команды.')
        return
    
    admin_menu = {
        'keyboard': [
            ['📊 Товары в наличии'],
            ['➕ Добавить товар'],
            ['🗑️ Удалить товар'],
            ['📦 Изменить количество'],
            ['🧹 Очистить отсутствующие'],
            ['🔙 Назад']
        ],
        'resize_keyboard': True
    }
    
    await update.message.reply_text(
        '👨‍💼 <b>Панель администратора</b>\n\nВыберите действие:',
        parse_mode='HTML',
        reply_markup=admin_menu
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages."""
    if not update.message or not update.message.text:
        return
    
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    username = update.effective_user.username
    user = get_user(chat_id, update.effective_user.username or update.effective_user.first_name)
    
    # Handle main menu buttons
    if text == '🔙 Назад':
        keyboard = get_main_menu_keyboard(username)
        reply_markup = {'keyboard': keyboard, 'resize_keyboard': True}
        await update.message.reply_text('Главное меню:', reply_markup=reply_markup)
        return
    
    if text == '👨‍💼 Админка':
        if not is_admin(username):
            await update.message.reply_text('🚫 У вас нет прав для выполнения этой команды.')
            return
        
        admin_menu = {
            'keyboard': [
                ['📊 Товары в наличии'],
                ['➕ Добавить товар'],
                ['🗑️ Удалить товар'],
                ['📦 Изменить количество'],
                ['🧹 Очистить отсутствующие'],
                ['🔙 Назад']
            ],
            'resize_keyboard': True
        }
        
        await update.message.reply_text(
            '👨‍💼 <b>Панель администратора</b>\n\nВыберите действие:',
            parse_mode='HTML',
            reply_markup=admin_menu
        )
        return
    
    if text == '📊 Товары в наличии':
        if not is_admin(username):
            await update.message.reply_text('🚫 У вас нет прав для выполнения этой команды.')
            return
        
        catalog_text = '📊 <b>Товары в наличии:</b>\n\n'
        
        for category_name, category_products in catalog.items():
            catalog_text += f'📦 <b>{category_name}:</b>\n'
            for product in category_products:
                status = '✅' if product.quantity > 0 else '❌'
                catalog_text += f'{status} {product.name} - {product.price}₽ (В наличии: {product.quantity} шт.)\n'
            catalog_text += '\n'
        
        if not catalog:
            catalog_text = '📊 <b>Товары в наличии:</b>\n\n❌ Каталог пуст!'
        
        await update.message.reply_text(catalog_text, parse_mode='HTML')
        return
    
    if text == '➕ Добавить товар':
        if not is_admin(username):
            await update.message.reply_text('🚫 У вас нет прав для выполнения этой команды.')
            return
        
        user.waiting_for_product_add = True
        
        # Create inline keyboard with categories
        keyboard = []
        for category_name in catalog.keys():
            keyboard.append([InlineKeyboardButton(f'📦 {category_name}', callback_data=f'addcat_{category_name}')])
        
        # Add option to create new category
        keyboard.append([InlineKeyboardButton('➕ Новая категория', callback_data='addcat_new')])
        keyboard.append([InlineKeyboardButton('🔙 Отмена', callback_data='addcat_cancel')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            '➕ <b>Добавление товара</b>\n\nВыберите категорию:',
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        return
    
    if text == '🗑️ Удалить товар':
        if not is_admin(username):
            await update.message.reply_text('🚫 У вас нет прав для выполнения этой команды.')
            return
        
        if not catalog:
            await update.message.reply_text('❌ Каталог пуст! Нечего удалять.')
            return
        
        # Create inline keyboard with products
        keyboard = []
        for category_name, category_products in catalog.items():
            for product in category_products:
                keyboard.append([
                    InlineKeyboardButton(
                        f'🗑 {product.name} ({product.quantity} шт.)',
                        callback_data=f'del_{product.id}'
                    )
                ])
        
        keyboard.append([InlineKeyboardButton('🔙 Отмена', callback_data='del_cancel')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            '🗑️ <b>Удаление товара</b>\n\nВыберите товар для удаления:',
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        return
    
    if text == '📦 Изменить количество':
        if not is_admin(username):
            await update.message.reply_text('🚫 У вас нет прав для выполнения этой команды.')
            return
        
        if not catalog:
            await update.message.reply_text('❌ Каталог пуст! Нечего изменять.')
            return
        
        # Create inline keyboard with products
        keyboard = []
        for category_name, category_products in catalog.items():
            for product in category_products:
                keyboard.append([
                    InlineKeyboardButton(
                        f'📦 {product.name} (сейчас: {product.quantity} шт.)',
                        callback_data=f'qty_{product.id}'
                    )
                ])
        
        keyboard.append([InlineKeyboardButton('🔙 Отмена', callback_data='qty_cancel')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            '📦 <b>Изменение количества</b>\n\nВыберите товар:',
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        return
    
    if text == '🧹 Очистить отсутствующие':
        if not is_admin(username):
            await update.message.reply_text('🚫 У вас нет прав для выполнения этой команды.')
            return
        
        removed_products = remove_out_of_stock_products()
        
        if not removed_products:
            await update.message.reply_text(
                '🧹 <b>Очистка отсутствующих товаров</b>\n\n✅ Все товары в наличии!',
                parse_mode='HTML'
            )
        else:
            message = (
                '🧹 <b>Очистка отсутствующих товаров</b>\n\n'
                '🗑️ Удаленные товары:\n' +
                '\n'.join(f'• {p}' for p in removed_products) +
                f'\n\n✅ Удалено {len(removed_products)} товаров!'
            )
            await update.message.reply_text(message, parse_mode='HTML')
        return
    
    # Handle catalog button
    if text in ['🛒 Каталог', '🔙 Назад в каталог']:
        if not has_available_products():
            out_of_stock_menu = {
                'keyboard': [
                    ['🛒 Корзина'],
                    ['ℹ️ О нас']
                ],
                'resize_keyboard': True
            }
            
            await update.message.reply_text(
                '❌ <b>К сожалению, все товары закончились!</b>\n\n'
                'Попробуйте зайти позже или свяжитесь с менеджером @Ferb_manger02',
                parse_mode='HTML',
                reply_markup=out_of_stock_menu
            )
            return
        
        category_buttons = [[cat] for cat in catalog.keys()]
        
        keyboard = {
            'keyboard': [
                *category_buttons,
                ['🔙 Назад']
            ],
            'resize_keyboard': True
        }
        
        await update.message.reply_text('Выберите категорию товаров:', reply_markup=keyboard)
        return
    
    # Handle category selection
    if text in catalog:
        category = text
        products = catalog[category]
        
        # Filter available products
        available_products = [p for p in products if p.quantity > 0]
        
        if not available_products:
            if not products:
                await update.message.reply_text(
                    f'❌ В данной вкладке товаров пока что нету!\n\nВыберите другую категорию:'
                )
            else:
                await update.message.reply_text(
                    f'❌ В категории "{category}" все товары закончились!\n\nВыберите другую категорию:'
                )
            return
        
        # Create inline keyboard
        keyboard = []
        for product in available_products:
            keyboard.append([
                InlineKeyboardButton(
                    f'➕ {product.name} - {product.price}₽ ({product.quantity} шт.)',
                    callback_data=f'add_{product.id}'
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f'📦 *{category}*:\nВыберите товар:',
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    # Handle cart button
    if text == '🛒 Корзина':
        if not user.cart:
            await update.message.reply_text('Ваша корзина пуста!')
            return
        
        cart_items = '\n'.join(
            f'{i + 1}. {item.name} - {item.quantity} x {item.price}₽ = {item.quantity * item.price}₽'
            for i, item in enumerate(user.cart)
        )
        
        total = sum(item.price * item.quantity for item in user.cart)
        
        message = f'🛒 *Ваша корзина:*\n\n{cart_items}\n\n*Итого: {total}₽*'
        
        keyboard = {
            'keyboard': [
                ['✅ Оформить заказ'],
                ['❌ Очистить корзину'],
                ['🔙 Назад в каталог']
            ],
            'resize_keyboard': True
        }
        
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=keyboard)
        return
    
    # Handle order placement
    if text == '✅ Оформить заказ':
        if not user.cart:
            await update.message.reply_text('Ваша корзина пуста!')
            return
        
        user.waiting_for_comment = True
        
        keyboard = {
            'keyboard': [['Пропустить']],
            'resize_keyboard': True
        }
        
        await update.message.reply_text(
            '💬 Введите комментарий к заказу (или нажмите "Пропустить"):',
            reply_markup=keyboard
        )
        return
    
    # Handle clear cart
    if text == '❌ Очистить корзину':
        user.cart = []
        await update.message.reply_text('Корзина очищена!')
        return
    
    # Handle about
    if text == 'ℹ️ О нас':
        about_text = (
            '🌟 <b>О PPHUB</b>\n\n'
            '🛍 <b>Наш магазин предлагает:</b>\n'
            '• Качественные товары для вейпинга\n'
            '• Широкий ассортимент\n'
            '• Доступные цены\n'
            '• Гарантия качества\n\n'
            '💳 <b>Способы оплаты</b>\n'
            '💰 Наличными при встрече с менеджером\n\n'
            '📍 <b>Наши контакты</b>\n'
            '📢 Официальный канал: https://t.me/FerbshopPP\n\n'
            '👨‍💼 <b>Менеджер:</b>\n'
            '• @Ferb_manger02\n\n'
            '💬 По всем вопросам обращайтесь к менеджеру\n'
            '⏰ Работаем круглосуточно\n\n'
            '💯 <b>Мы работаем для вас!</b>'
        )
        
        keyboard = {
            'keyboard': [
                ['🛒 Каталог'],
                ['🔙 Назад']
            ],
            'resize_keyboard': True
        }
        
        await update.message.reply_text(about_text, parse_mode='HTML', reply_markup=keyboard)
        return
    
    # Handle admin states
    if is_admin(username):
        # Handle new category creation
        if hasattr(user, 'waiting_for_new_category') and user.waiting_for_new_category:
            user.waiting_for_new_category = False
            user.selected_category = text
            await update.message.reply_text(
                f'✅ Категория "{text}" создана!\n\n'
                f'➕ <b>Добавление товара в категорию: {text}</b>\n\n'
                'Введите данные товара в формате:\n'
                '<code>название|цена|количество</code>\n\n'
                'Пример: <code>HQD 3000|1200|15</code>',
                parse_mode='HTML'
            )
            return
        
        # Handle product addition
        if user.waiting_for_product_add:
            user.waiting_for_product_add = False
            
            parts = text.split('|')
            if len(parts) == 3:
                try:
                    name, price, quantity = parts
                    category = getattr(user, 'selected_category', 'Разное')
                    new_product = add_product(
                        category,
                        name.strip(),
                        int(price),
                        int(quantity)
                    )
                    
                    await update.message.reply_text(
                        f'✅ <b>Товар добавлен!</b>\n\n'
                        f'📦 Категория: {category}\n'
                        f'📝 Название: {name}\n'
                        f'💰 Цена: {price}₽\n'
                        f'📊 Количество: {quantity} шт.',
                        parse_mode='HTML'
                    )
                except ValueError:
                    await update.message.reply_text(
                        '❌ <b>Неверный формат!</b>\n\n'
                        'Цена и количество должны быть числами.',
                        parse_mode='HTML'
                    )
            else:
                await update.message.reply_text(
                    '❌ <b>Неверный формат!</b>\n\n'
                    'Используйте формат: <code>название|цена|количество</code>',
                    parse_mode='HTML'
                )
            return
        
        # Handle quantity input
        if hasattr(user, 'waiting_for_quantity_input') and user.waiting_for_quantity_input:
            user.waiting_for_quantity_input = False
            
            try:
                new_quantity = int(text)
                product_id = getattr(user, 'selected_product_id', None)
                
                if product_id:
                    result = find_product_by_id(product_id)
                    if result:
                        category_name, product = result
                        product.quantity = new_quantity
                        await update.message.reply_text(
                            f'✅ <b>Количество обновлено!</b>\n\n'
                            f'📝 Товар: {product.name}\n'
                            f'📊 Новое количество: {new_quantity} шт.',
                            parse_mode='HTML'
                        )
                        return
                
                await update.message.reply_text('❌ Товар не найден!', parse_mode='HTML')
            except ValueError:
                await update.message.reply_text(
                    '❌ Количество должно быть числом!',
                    parse_mode='HTML'
                )
            return
    
    # Handle comment input
    if user.waiting_for_comment:
        user.waiting_for_comment = False
        
        # Process comment
        if text == 'Пропустить':
            user.comment = 'Без комментария'
        elif not text.startswith('/'):
            user.comment = text
        else:
            user.comment = 'Без комментария'
        
        # Check if all items in cart are still available
        unavailable_items = []
        for cart_item in user.cart:
            found = False
            for category_products in catalog.values():
                for product in category_products:
                    if product.name == cart_item.name:
                        found = True
                        if product.quantity < cart_item.quantity:
                            unavailable_items.append(cart_item.name)
                        break
                if found:
                    break
            
            if not found:
                unavailable_items.append(cart_item.name)
        
        if unavailable_items:
            await update.message.reply_text(
                '❌ <b>Некоторые товары в корзине закончились!</b>\n\n'
                'Товары, которые больше недоступны:\n' +
                '\n'.join(f'• {item}' for item in unavailable_items) +
                '\n\nПожалуйста, удалите их из корзины и оформите заказ заново.',
                parse_mode='HTML'
            )
            return
        
        # Create order
        order = Order(
            user_id=user.user_id,
            username=user.username,
            items=deepcopy(user.cart),
            comment=user.comment,
            status='new',
            created_at=datetime.now()
        )
        orders.append(order)
        
        # Reduce product quantities
        for order_item in order.items:
            result = find_product_by_id(order_item.name)
            if result:
                category_name, product = result
                # Find by name since cart items don't have IDs
                for cat_products in catalog.values():
                    for p in cat_products:
                        if p.name == order_item.name:
                            p.quantity -= order_item.quantity
                            break
        
        # Check for products that reached zero
        removed_products = remove_out_of_stock_products()
        if removed_products and ADMIN_CHAT_ID:
            admin_notification = (
                '🧹 <b>Автоматическое удаление товаров</b>\n\n'
                'Следующие товары закончились и были удалены:\n' +
                '\n'.join(f'• {p}' for p in removed_products)
            )
            
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=admin_notification,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f'❌ Ошибка отправки уведомления админу: {e}')
        
        # Notify admin
        order_items = '\n'.join(
            f'• {item.name} - {item.quantity} x {item.price}₽ = {item.quantity * item.price}₽'
            for item in order.items
        )
        
        total = sum(item.price * item.quantity for item in order.items)
        
        user_info = (
            f'👤 <b>Информация о заказчике:</b>\n'
            f'├ Имя: {update.effective_user.first_name or "Не указано"}\n'
            f'├ Фамилия: {update.effective_user.last_name or "Не указана"}\n'
            f'├ Username: @{update.effective_user.username or "отсутствует"}\n'
            f'└ ID: <code>{order.user_id}</code>'
        )
        
        # Escape HTML in user content
        order_items_escaped = order_items.replace('<', '&lt;').replace('>', '&gt;')
        comment_escaped = order.comment.replace('<', '&lt;').replace('>', '&gt;')
        
        admin_message = (
            '🛍 <b>НОВЫЙ ЗАКАЗ</b> 🛍\n\n'
            f'{user_info}\n\n'
            '📦 <b>Состав заказа:</b>\n'
            f'{order_items_escaped}\n\n'
            f'💬 <b>Комментарий:</b> {comment_escaped}\n\n'
            f'💰 <b>Итого к оплате:</b> <code>{total}₽</code>\n\n'
            f'⏰ {order.created_at.strftime("%d.%m.%Y %H:%M")}'
        )
        
        if ADMIN_CHAT_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=admin_message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.warning(f'⚠️ ADMIN_CHAT_ID не настроен или ошибка отправки: {e}')
        
        if GROUP_CHAT_ID:
            try:
                await context.bot.send_message(
                    chat_id=GROUP_CHAT_ID,
                    text=admin_message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.warning(f'⚠️ GROUP_CHAT_ID не настроен или ошибка отправки: {e}')
        
        # Confirm to user
        keyboard = {
            'keyboard': [
                ['🛒 Каталог'],
                ['ℹ️ О нас']
            ],
            'resize_keyboard': True
        }
        
        user_message = (
            f'✅ <b>Спасибо за заказ, {update.effective_user.first_name or "друг"}!</b>\n\n'
            'Ваш заказ принят в обработку. Наш менеджер свяжется с вами в ближайшее время.\n\n'
            f'📦 <b>Номер вашего заказа:</b> #{len(orders)}\n'
            f'💬 <b>Ваш комментарий:</b> {"не указан" if user.comment == "Без комментария" else user.comment}\n\n'
            'Для уточнения деталей заказа вы всегда можете обратиться к менеджеру @Ferb_manger02'
        )
        
        await update.message.reply_text(user_message, parse_mode='HTML', reply_markup=keyboard)
        
        # Clear cart
        user.cart = []
        return


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries (inline buttons)."""
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    data = query.data
    user = get_user(chat_id)
    
    # Handle adding to cart
    if data.startswith('add_'):
        product_id = data.replace('add_', '')
        
        # Find product
        result = find_product_by_id(product_id)
        
        if result:
            category_name, product = result
            
            # Check availability
            if product.quantity <= 0:
                await query.answer('❌ Товар закончился!', show_alert=True)
                return
            
            # Check if already in cart
            existing_item = None
            for item in user.cart:
                if item.name == product.name:
                    existing_item = item
                    break
            
            current_quantity = existing_item.quantity if existing_item else 0
            
            if current_quantity >= product.quantity:
                await query.answer(
                    f'❌ В наличии только {product.quantity} шт.!',
                    show_alert=True
                )
                return
            
            if existing_item:
                existing_item.quantity += 1
            else:
                user.cart.append(CartItem(
                    name=product.name,
                    price=product.price,
                    quantity=1
                ))
            
            await query.answer(
                f'Добавлено: {product.name} (осталось {product.quantity - 1} шт.)',
                show_alert=False
            )
        else:
            await query.answer('❌ Товар не найден!', show_alert=True)
        return
    
    # Handle category selection for adding product
    if data.startswith('addcat_'):
        category = data.replace('addcat_', '')
        
        if category == 'cancel':
            await query.message.delete()
            return
        
        if category == 'new':
            user.waiting_for_new_category = True
            user.waiting_for_product_add = True
            await query.message.edit_text(
                '➕ <b>Создание новой категории</b>\n\n'
                'Введите название новой категории:',
                parse_mode='HTML'
            )
            return
        
        user.selected_category = category
        user.waiting_for_product_add = True
        await query.message.edit_text(
            f'➕ <b>Добавление товара в категорию: {category}</b>\n\n'
            'Введите данные товара в формате:\n'
            '<code>название|цена|количество</code>\n\n'
            'Пример: <code>HQD 3000|1200|15</code>',
            parse_mode='HTML'
        )
        return
    
    # Handle product deletion
    if data.startswith('del_'):
        product_id = data.replace('del_', '')
        
        if product_id == 'cancel':
            await query.message.delete()
            return
        
        # Find and delete product
        for category_name in list(catalog.keys()):
            if remove_product(category_name, product_id):
                await query.message.edit_text(
                    f'✅ <b>Товар удалён!</b>',
                    parse_mode='HTML'
                )
                return
        
        await query.answer('❌ Товар не найден!', show_alert=True)
        return
    
    # Handle quantity update
    if data.startswith('qty_'):
        product_id = data.replace('qty_', '')
        
        if product_id == 'cancel':
            await query.message.delete()
            return
        
        result = find_product_by_id(product_id)
        if result:
            category_name, product = result
            user.selected_product_id = product_id
            user.waiting_for_quantity_input = True
            await query.message.edit_text(
                f'📦 <b>Изменение количества</b>\n\n'
                f'Товар: {product.name}\n'
                f'Текущее количество: {product.quantity} шт.\n\n'
                'Введите новое количество:',
                parse_mode='HTML'
            )
        return


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    print('🛑 Получен сигнал остановки. Завершаю работу...')
    sys.exit(0)


def main():
    """Start the bot."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CommandHandler('admin', admin_command))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    print('✅ Бот запущен и готов к работе!')
    print('📊 Токен загружен')
    print(f'👤 Админов в списке: {len(ADMIN_USERS)}')
    
    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
    
