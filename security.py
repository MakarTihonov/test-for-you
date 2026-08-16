import asyncio
from typing import Any, Awaitable, Callable, Dict, Set
from aiogram import BaseMiddleware, types
from aiogram.filters import BaseFilter

class IsAdminFilter(BaseFilter):
    def __init__(self, admin_ids: Set[int]):
        self.admin_ids = admin_ids
    async def __call__(self, message_or_callback: types.Message | types.CallbackQuery) -> bool:
        return message_or_callback.from_user.id in self.admin_ids
class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 1.0):
        self.limit = limit
        self.storage: Dict[int, float] = {} 
    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.Message | types.CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        user_id = event.from_user.id
        current_time = asyncio.get_event_loop().time()
        if user_id in self.storage:
            last_time = self.storage[user_id]
            if current_time - last_time < self.limit:
                if isinstance(event, types.CallbackQuery):
                    await event.answer("⚠️ Не нажимайте на кнопки так часто!", show_alert=True)
                elif isinstance(event, types.Message):
                    if current_time - last_time > 0.5:
                        await event.reply("⚠️ Пожалуйста, не спамьте!")
                return 
        self.storage[user_id] = current_time
        if len(self.storage) > 5000:
            self.storage = {k: v for k, v in self.storage.items() if current_time - v < self.limit}
        return await handler(event, data)
