import logging
import requests
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import re

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен  бота (получить у @BotFather)
BOT_TOKEN = "8175173195:AAHt1cQCbLhz0LC9lv2XGv46SJbKwHoJ_3o"

class DataMatrixBot:
    def __init__(self):
        self.api_url = "https://mobile.api.crpt.ru/mobile/check"
        # Словарь для перевода статусов
        self.status_translations = {
            'EMITTED': 'Эмитирован. Выпущен',
            'APPLIED': 'Эмитирован. Получен',
            'INTRODUCED': 'В обороте',
            'RETIRED': 'Выбыл',
            'WRITTEN_OFF': 'Списан',
            'DISAGGREGATION': 'Расформирован',
            'APPLIED_NOT_PAID': 'Нанесён, не оплачен',
            'APPLIED_PAID': 'Нанесен. Оплачен',
            'WITHDRAWN': 'Выбыл',
            'INTRODUCED_RETURNED': 'Возвращён в оборот',
            'DISAGGREGATED': 'Расформирован'
        }
        
        # Детальные описания статусов
        self.status_descriptions = {
            'EMITTED': 'Код получен участником оборота, но еще не нанесен на товар (упаковку товара)',
            'APPLIED': 'Код получен участником оборота и нанесен на товар (упаковку товара)',
            'INTRODUCED': 'Код введен в оборот и может быть отгружен контрагенту или продан по кассе',
            'RETIRED': 'Код выведен из оборота по какой-то причине (продан по кассе, отгружен за пределы страны)',
            'WRITTEN_OFF': 'Код списан в системе мониторинга (утерян, поврежден, уничтожен и т.п.)',
            'DISAGGREGATION': 'Только для КИТУ (транспортная упаковка), АТК (агрегированный таможенный код) и набора (групповая упаковка)',
            'APPLIED_NOT_PAID': 'Нанесён, не оплачен (только для табачной продукции)',
            'APPLIED_PAID': 'Нанесен. Оплачен (только для табачной продукции)',
            'WITHDRAWN': 'Выбыл (только для табачной продукции)',
            'INTRODUCED_RETURNED': 'Возвращён в оборот',
            'DISAGGREGATED': 'Расформирован'
        }
    
    def clean_datamatrix_code(self, code):
        """
        Очищает Data Matrix код от пробелов и других ненужных символов
        """
        # Убираем все пробелы
        cleaned_code = re.sub(r'\s+', '', code.strip())
        return cleaned_code
    
    def process_datamatrix_code(self, code):
        """
        Обрабатывает Data Matrix код, убирая криптохвост после 93, 92, 91
        """
        # очищаем код от пробелов
        cleaned_code = self.clean_datamatrix_code(code)
        
        # Ищем разделитель групп (символ с ASCII кодом 29, который может быть представлен как \x1D)
        # В некоторых случаях он может быть заменен на другие символы
        group_separator_pos = -1
        
        # Ищем возможные разделители
        separators = ['\x1D', chr(29), '|', '\x1E', chr(30)]
        for sep in separators:
            pos = cleaned_code.find(sep)
            if pos != -1:
                group_separator_pos = pos
                logger.info(f"Найден разделитель групп на позиции {pos}")
                break
        
        # Если разделитель не найден, пытаемся найти паттерны после определенной позиции
        # Обычно основная часть DataMatrix занимает первые 20-30 символов
        if group_separator_pos == -1:
            # Ищем паттерны начиная с позиции 20 (это примерная граница)
            search_start = min(20, len(cleaned_code) // 2)
            logger.info(f"Разделитель групп не найден, ищем паттерны начиная с позиции {search_start}")
        else:
            # Ищем паттерны после разделителя
            search_start = group_separator_pos + 1
            logger.info(f"Ищем паттерны после разделителя с позиции {search_start}")
        
        # Ищем позицию "93", "92" или "91" начиная с определенной позиции
        earliest_pos = len(cleaned_code)
        found_pattern = None
        
        for pattern in ['91', '92', '93']:
            pos = cleaned_code.find(pattern, search_start)
            if pos != -1 and pos < earliest_pos:
                earliest_pos = pos
                found_pattern = pattern
        
        # Если нашли хотя бы один паттерн, обрезаем до него
        if found_pattern:
            processed_code = cleaned_code[:earliest_pos]
            logger.info(f"Найден паттерн '{found_pattern}' на позиции {earliest_pos}, код обрезан до: {processed_code}")
            return processed_code
        
        # Если ни один из паттернов не найден, возвращаем очищенный код как есть
        logger.info(f"Паттерны 91/92/93 не найдены после позиции {search_start}, код остается без изменений")
        return cleaned_code
    
    async def get_product_info(self, code):
        """
        Получает информацию о товаре через мобильное апи Честного знака
        """
        try:
            processed_code = self.process_datamatrix_code(code)
            url = f"{self.api_url}?code={processed_code}"
            
            logger.info(f"Отправляем запрос: {url}")
            
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при запросе к API: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при обработке кода: {e}")
            return None
    
    def find_value_recursive(self, data, target_keys):
        """
        Рекурсивно ищет значение по ключам в JSON структуре
        """
        if isinstance(data, dict):
            for key, value in data.items():
                if key in target_keys:
                    return value
                if isinstance(value, (dict, list)):
                    result = self.find_value_recursive(value, target_keys)
                    if result is not None:
                        return result
        elif isinstance(data, list):
            for item in data:
                result = self.find_value_recursive(item, target_keys)
                if result is not None:
                    return result
        return None
    
    def find_tnvd_by_attr(self, data):
        """
        Ищет ТНВЭД по attr_name = "Код ТНВЭД" если tnvd нет (по личным наблюдениям)
        """
        if isinstance(data, dict):
            # Проверяем текущий уровень
            if data.get('attr_name') == 'Код ТНВЭД':
                return data.get('attr_value')
            
            # Рекурсивно ищем в дочерних элементах
            for value in data.values():
                if isinstance(value, (dict, list)):
                    result = self.find_tnvd_by_attr(value)
                    if result:
                        return result
        elif isinstance(data, list):
            for item in data:
                result = self.find_tnvd_by_attr(item)
                if result:
                    return result
        return None
    
    def find_status_deep(self, data):
        """
        Ищет статус глубоко в структуре JSON (не в корне) т.к статус обычно 
        """
        if isinstance(data, dict):
            for key, value in data.items():
                if key == 'status' and isinstance(value, (str, int)):
                    # Пропускаем статус в корне, ищем глубже
                    continue
                if isinstance(value, (dict, list)):
                    result = self.find_status_in_nested(value)
                    if result is not None:
                        return result
        elif isinstance(data, list):
            for item in data:
                result = self.find_status_in_nested(item)
                if result is not None:
                    return result
        return None
    
    def find_status_in_nested(self, data):
        """
        Вспомогательная функция для поиска статуса в вложенных структурах
        """
        if isinstance(data, dict):
            if 'status' in data:
                return data['status']
            for value in data.values():
                if isinstance(value, (dict, list)):
                    result = self.find_status_in_nested(value)
                    if result is not None:
                        return result
        elif isinstance(data, list):
            for item in data:
                result = self.find_status_in_nested(item)
                if result is not None:
                    return result
        return None

    def format_status(self, status):
        """
        Форматирует статус с переводом и описанием
        """
        if not status:
            return "Неизвестен"
        
        # Переводим статус
        translated_status = self.status_translations.get(status, status)
        
        # Добавляем описание если есть
        description = self.status_descriptions.get(status, "")
        
        if description:
            return f"**{translated_status}**\n_{description}_"
        else:
            return f"**{translated_status}**"

    def format_response(self, data):
        """
        Форматирует ответ для пользователя
        """
        if not data:
            return "❌ Не удалось получить информацию о товаре"
        
        try:
            # Ищем поля по всей структуре JSON
            producer_inn = self.find_value_recursive(data, ['producer_inn'])
            importer_name = self.find_value_recursive(data, ['importerName'])
            
            # Для tnvd сначала ищем обычным способом, потом через attr_name
            tnvd = self.find_value_recursive(data, ['tnvd'])
            if not tnvd:
                tnvd = self.find_tnvd_by_attr(data)
            
            gtin = self.find_value_recursive(data, ['gtin'])
            product_name = self.find_value_recursive(data, ['productName'])
            cis = self.find_value_recursive(data, ['cis'])
            
            # Статус ищем глубже, не в корне
            status = self.find_status_deep(data)
            if not status:
                # Если не нашли глубже, берем из корня как fallback
                status = data.get('status')
            
            # Формируем ответ
            response_parts = ["📦 **Информация о товаре:**\n"]
            
            if importer_name:
                response_parts.append(f"🏢 **Импортер:** {importer_name}")
            elif producer_inn:
                response_parts.append(f"🏭 **ИНН производителя:** `{producer_inn}`")
            
            if tnvd:
                response_parts.append(f"📋 **ТНВЭД:** `{tnvd}`")
            
            if gtin:
                response_parts.append(f"🔢 **GTIN:** `{gtin}`")
            
            if product_name:
                response_parts.append(f"📝 **Наименование:** {product_name}")
            
            if cis:
                response_parts.append(f"🆔 **CIS:** `{cis}`")
            
            # Форматируем статус с переводом и описанием
            if status:
                formatted_status = self.format_status(status)
                response_parts.append(f"📊 **Статус:** {formatted_status}")
            
            if len(response_parts) == 1:  # Только заголовок
                return "❌ Не удалось извлечь информацию из ответа API"
                
            return "\n\n".join(response_parts)
            
        except Exception as e:
            logger.error(f"Ошибка при форматировании ответа: {e}")
            return "❌ Ошибка при обработке данных"

# Создаем экземпляр бота
bot_instance = DataMatrixBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    welcome_message = """
🤖 **Добро пожаловать в бот проверки Data Matrix кодов!**

📱 Отправьте мне Data Matrix код, и я получу информацию о товаре через систему ЦРПТ.

🔍 **Как использовать:**
1. Отправьте Data Matrix код как текстовое сообщение (пробелы будут автоматически удалены)
2. Бот обработает код и запросит информацию
3. Получите данные о товаре с переводом статусов

⚡ Попробуйте прямо сейчас!
    """
    
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_message = update.message.text
    user_id = update.effective_user.id
    
    logger.info(f"Получен код от пользователя {user_id}: {user_message[:50]}...")
    
    # Отправляем сообщение о начале обработки
    processing_message = await update.message.reply_text("🔄 Обрабатываю код...")
    
    try:
        # Получаем информацию о товаре
        product_data = await bot_instance.get_product_info(user_message)
        
        # Форматируем и отправляем ответ
        response = bot_instance.format_response(product_data)
        
        # Редактируем сообщение с результатом
        await processing_message.edit_text(response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")
        await processing_message.edit_text(
            "❌ Произошла ошибка при обработке кода. Попробуйте еще раз."
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = """
🆘 **Помощь по использованию бота:**

**Команды:**
• `/start` - Запуск бота
• `/help` - Показать эту справку

**Как пользоваться:**
1. Отправьте Data Matrix код как текст (с пробелами или без)
2. Бот автоматически очистит код от пробелов и обработает его
3. Получите информацию о товаре с переводом статусов

**Что показывает бот:**
• ИНН производителя / Импортер
• ТНВЭД код
• GTIN
• Наименование товара
• CIS код
• Статус товара (с переводом и описанием)

**Статусы товаров:**
• **EMITTED** - Эмитирован. Выпущен
• **APPLIED** - Эмитирован. Получен
• **INTRODUCED** - В обороте
• **RETIRED** - Выбыл
• **WRITTEN_OFF** - Списан
• **DISAGGREGATION** - Расформирован


    """
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

def main():
    """Основная функция запуска бота"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем бота
    logger.info("Бот запускается...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()