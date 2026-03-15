from __future__ import annotations

from aiogram import Dispatcher

from app.bot.handlers.advice import build_advice_router
from app.bot.handlers.deadlines import build_deadlines_router
from app.bot.handlers.help import build_help_router
from app.bot.handlers.profile import build_profile_router
from app.bot.handlers.sources import build_sources_router
from app.bot.handlers.start import build_start_router
from app.bot.handlers.subjects import build_subject_router
from app.bot.handlers.summary import build_summary_router
from app.bot.services.contracts import StudyBotService
from app.bot.services.session_service import SessionService


def register_routers(
    dispatcher: Dispatcher,
    service: StudyBotService,
    sessions: SessionService,
) -> None:
    dispatcher.include_router(build_start_router(service, sessions))
    dispatcher.include_router(build_profile_router(service))
    dispatcher.include_router(build_sources_router(service, sessions))
    dispatcher.include_router(build_summary_router(service))
    dispatcher.include_router(build_subject_router(service, sessions))
    dispatcher.include_router(build_deadlines_router(service))
    dispatcher.include_router(build_advice_router(service))
    dispatcher.include_router(build_help_router())
