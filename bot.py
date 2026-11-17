import asyncio
import logging
import random
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from openai import OpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 1. Ваш токен от @BotFather
TELEGRAM_TOKEN = "9151646088:AAHcAlVs1sHnFpTiGUzAcju1mszmQZ5f9UM"

# 2. Ваш ключ от Berget AI
BERGET_API_KEY = "sk_ber_FR7icIBqDw3KtOHcad8bPCLqZc57dauQOmwz3L_b9c94196424a8067"

ADMIN_CHAT_ID = None

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Инициализация клиента Berget AI
client = OpenAI(
    api_key=BERGET_API_KEY,
    base_url="https://api.berget.ai/v1"
)

# Состояния для машины состояний (FSM)
class PostEditStates(StatesGroup):
    waiting_for_user_feedback = State()

def get_post_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Взять в работу", callback_data="accept_post"),
            InlineKeyboardButton(text="✍️ Уточнить / Доработать", callback_data="edit_post")
        ],
        [
            InlineKeyboardButton(text="🔄 Сгенерировать еще", callback_data="regen_post")
        ]
    ])

# Генерация базового поста
async def generate_music_post(user_prompt: str = None) -> str:
    system_prompt = (
        "Ты — креативный соавтор музыкального Telegram-канала. "
        "Твоя задача — писать короткие, увлекательные посты (факты, истории, байки) о рок-музыке, панке, фолке и околомузыкальной эстетике "
        "(ориентир на плейлист: AnnenMayKantereit, The Hatters, Король и Шут, Rammstein, Марлины и др.). "
        "Стиль: дружелюбный, живой, без излишнего пафоса и 'душной' теории. "
        "СТРОГОЕ ОГРАНИЧЕНИЕ: текст должен быть короче 1024 символов, чтобы помещаться под картинку в Telegram."
    )
    
    topics = [
        "Расскажи неожиданный факт о записи культового рок-альбома 90-х.",
        "Вспомни интересную закулисную историю про панк- или фолк-группу.",
        "Опиши забавный или необычный случай с концерта рок-музыкантов.",
        "Расскажи историю создания необычного инструмента, который используют в рок-музыке.",
        "Поделись интересной байкой про то, как рождался известный музыкальный хит.",
        "Напиши короткий и увлекательный факт про эстетику уличных музыкантов и фолк-рока."
    ]
    
    # Если пользователь дал конкретное уточнение — используем его, иначе случайную тему
    current_task = user_prompt if user_prompt else random.choice(topics)

    try:
        response = client.chat.completions.create(
            model="moonshotai/Kimi-K3.1-Pro",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": current_task}
            ],
            temperature=1.3
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"ОШИБКА ИИ: {e}")
        return f"⚠️ Ошибка генерации от ИИ: {e}"

# Автоматическая рассылка
async def scheduled_post_job():
    if not ADMIN_CHAT_ID:
        return 
    
    post_text = await generate_music_post()
    await bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"⏰ **Автоматическая подборка (раз в 3 дня):**\n\n{post_text}",
        reply_markup=get_post_keyboard()
    )

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = message.from_user.id
    await state.clear()
    
    await message.answer(
        f"🎸 Привет! Твой ID (`{ADMIN_CHAT_ID}`) сохранен.\n"
        "Бот настроен на редкий режим (раз в 3 дня). Можешь протестировать генерацию прямо сейчас:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Сгенерировать пост с ИИ", callback_data="regen_post")]
        ])
    )

@dp.callback_query(F.data == "regen_post")
async def process_regen(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("🎸 ИИ думает над инфоповодом...")
    post_text = await generate_music_post()
    await callback.message.answer(post_text, reply_markup=get_post_keyboard())

@dp.callback_query(F.data == "accept_post")
async def process_accept(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("✅ Готово!")
    await callback.message.answer("✅ Пост зафиксирован. Можешь копировать и отправлять в канал.")

# Шаг 1: Нажали кнопку «Уточнить / Доработать»
@dp.callback_query(F.data == "edit_post")
async def process_edit_click(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    
    # Сохраняем текст текущего сообщения, чтобы ИИ знал, что дорабатывать
    await state.update_data(last_post_text=callback.message.text)
    await state.set_state(PostEditStates.waiting_for_user_feedback)
    
    await callback.message.answer(
        "✏️ **Режим доработки:**\n"
        "Напиши ответным сообщением, что именно нужно изменить или добавить (например: *'Сделай акцент на вокалисте'* или *'Добавь больше юмора'*)."
    )

# Шаг 2: Получаем текст уточнения от пользователя и отправляем в ИИ
@dp.message(PostEditStates.waiting_for_user_feedback)
async def process_user_feedback(message: types.Message, state: FSMContext):
    data = await state.get_data()
    previous_text = data.get("last_post_text", "")
    user_instruction = message.text

    await message.answer("🔄 Перерабатываю текст с учетом твоих пожеланий...")

    # Формируем запрос для ИИ на основе старого текста и нового пожелания
    refine_prompt = (
        f"Вот предыдущий вариант поста:\n{previous_text}\n\n"
        f"Пожелание автора по доработке: {user_instruction}\n"
        "Перепиши пост с учетом этого пожелания, сохранив стиль и лимит до 1024 символов."
    )

    new_post_text = await generate_music_post(user_prompt=refine_prompt)
    
    # Сбрасываем состояние
    await state.clear()
    
    await message.answer(new_post_text, reply_markup=get_post_keyboard())

async def main():
    scheduler = AsyncIOScheduler()
    # Установлен редкий режим: раз в 3 дня
    scheduler.add_job(scheduled_post_job, 'interval', days=3)
    scheduler.start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())