from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime

import httpx
from telegram import Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut
from telegram.request import HTTPXRequest
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from bot_app.config import Settings, configure_logging, ensure_directories, load_settings
from bot_app.images import ImageService
from bot_app.quotes import QuoteService
from bot_app.state import RuntimeState, StateStore


LOGGER = logging.getLogger(__name__)
RANDOM_DAY_START_MINUTE = 9 * 60
RANDOM_DAY_END_MINUTE = 21 * 60


@dataclass
class Services:
    settings: Settings
    state_store: StateStore
    quote_service: QuoteService
    image_service: ImageService


def run() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    ensure_directories()

    services = Services(
        settings=settings,
        state_store=StateStore(settings),
        quote_service=QuoteService(
            provider=settings.quote_provider,
            api_url=settings.quote_api_url,
            tone_tags=settings.message_tone_tags,
            cohere_api_key=settings.cohere_api_key,
            cohere_model=settings.cohere_model,
            cohere_api_url=settings.cohere_api_url,
        ),
        image_service=ImageService(
            url_template=settings.image_api_url_template,
            tags=settings.image_tags,
            width=settings.image_width,
            height=settings.image_height,
        ),
    )

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .job_queue(None)
        .request(build_telegram_request(settings))
        .get_updates_request(build_telegram_request(settings))
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data["services"] = services

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("chat_id", chat_id_command))
    application.add_handler(CommandHandler("send_quote", send_quote_command))
    application.add_handler(CommandHandler("send_custom", send_custom_command))
    application.add_handler(CommandHandler("schedule_on", schedule_on_command))
    application.add_handler(CommandHandler("schedule_off", schedule_off_command))
    application.add_handler(CommandHandler("set_time", set_time_command))
    application.add_handler(CommandHandler("set_interval", set_interval_command))
    application.add_handler(CommandHandler("set_daily_count", set_daily_count_command))
    application.add_handler(CommandHandler("set_random_time", set_random_time_command))
    application.add_handler(CommandHandler("set_source", set_source_command))
    application.add_handler(CommandHandler("set_custom_schedule", set_custom_schedule_command))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    application.add_error_handler(error_handler)

    LOGGER.info("Bot is starting")
    asyncio.set_event_loop(asyncio.new_event_loop())
    try:
        application.run_polling(drop_pending_updates=True)
    except (TimedOut, NetworkError) as exc:
        raise SystemExit(
            "Could not connect to Telegram. Check internet access to api.telegram.org, "
            "firewall/VPN settings, and bot token."
        ) from exc


def services_from(context: ContextTypes.DEFAULT_TYPE) -> Services:
    return context.application.bot_data["services"]


def services_from_application(application: Application) -> Services:
    return application.bot_data["services"]


def admin_only(update: Update, settings: Settings) -> bool:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or chat.id != settings.admin_chat_id:
        if chat and message and message.text:
            LOGGER.info("Ignoring update from non-admin chat %s: %s", chat.id, message.text)
        return False
    return True


def log_incoming(update: Update) -> None:
    chat = update.effective_chat
    message = update.effective_message
    if not chat or not message:
        return
    if message.text:
        LOGGER.info("Received message from chat %s: %s", chat.id, message.text)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    await update.effective_message.reply_text(_help_text())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    await update.effective_message.reply_text(_help_text())


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    state = services.state_store.load()
    await update.effective_message.reply_text(_format_status(state, services))


async def send_quote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    try:
        await _send_message_to_partner(
            context,
            services,
            delivery_mode="api",
            custom_message=None,
        )
    except Exception as exc:
        LOGGER.exception("Manual quote send failed")
        await update.effective_message.reply_text(f"Could not send the quote: {_friendly_send_error(exc)}")
        return
    await update.effective_message.reply_text("Lovely message with image sent.")


async def send_custom_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    message_text = " ".join(context.args).strip()
    if not message_text:
        await update.effective_message.reply_text("Usage: /send_custom Your custom message here")
        return
    try:
        await _send_message_to_partner(
            context,
            services,
            delivery_mode="custom",
            custom_message=message_text,
        )
    except Exception as exc:
        LOGGER.exception("Manual custom send failed")
        await update.effective_message.reply_text(
            f"Could not send the custom message: {_friendly_send_error(exc)}"
        )
        return
    await update.effective_message.reply_text("Custom message with image sent.")


async def schedule_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    state = services.state_store.load()
    state.auto_mode = True
    services.state_store.save(state)
    await update.effective_message.reply_text("Automatic scheduled sending is now ON.")


async def schedule_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    state = services.state_store.load()
    state.auto_mode = False
    services.state_store.save(state)
    await update.effective_message.reply_text("Automatic scheduled sending is now OFF.")


async def set_time_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /set_time HH:MM")
        return
    send_time = context.args[0].strip()
    if not _is_valid_time(send_time):
        await update.effective_message.reply_text("Time must look like 20:00")
        return
    state = services.state_store.load()
    state.send_time = send_time
    state.scheduled_times_date = None
    state.scheduled_times_today = []
    services.state_store.save(state)
    await update.effective_message.reply_text(f"Scheduled send time updated to {send_time}.")


async def set_interval_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /set_interval 2")
        return
    try:
        interval_days = max(1, int(context.args[0]))
    except ValueError:
        await update.effective_message.reply_text("Interval must be a whole number of days.")
        return
    state = services.state_store.load()
    state.interval_days = interval_days
    services.state_store.save(state)
    await update.effective_message.reply_text(f"Interval updated to every {interval_days} day(s).")


async def set_daily_count_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /set_daily_count 3")
        return
    try:
        sends_per_day = max(1, min(24, int(context.args[0])))
    except ValueError:
        await update.effective_message.reply_text("Daily count must be a whole number from 1 to 24.")
        return
    state = services.state_store.load()
    state.sends_per_day = sends_per_day
    state.scheduled_times_date = None
    state.scheduled_times_today = []
    services.state_store.save(state)
    await update.effective_message.reply_text(
        f"Bot will now send {sends_per_day} time(s) on each schedule day."
    )


async def set_random_time_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    if not context.args or context.args[0].lower() not in {"on", "off"}:
        await update.effective_message.reply_text("Usage: /set_random_time on OR /set_random_time off")
        return
    enabled = context.args[0].lower() == "on"
    state = services.state_store.load()
    state.random_time_mode = enabled
    state.scheduled_times_date = None
    state.scheduled_times_today = []
    services.state_store.save(state)
    if enabled:
        await update.effective_message.reply_text(
            "Random time mode is now ON. Scheduled sends will use random times between 09:00 and 21:00."
        )
        return
    await update.effective_message.reply_text("Random time mode is now OFF. Fixed schedule times will be used.")


async def set_source_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    if not context.args or context.args[0].lower() not in {"api", "custom"}:
        await update.effective_message.reply_text("Usage: /set_source api OR /set_source custom")
        return
    new_source = context.args[0].lower()
    state = services.state_store.load()
    state.schedule_source = new_source
    services.state_store.save(state)
    await update.effective_message.reply_text(f"Scheduled message source is now {new_source}.")


async def set_custom_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    message_text = " ".join(context.args).strip()
    if not message_text:
        await update.effective_message.reply_text(
            "Usage: /set_custom_schedule Your lovely scheduled message"
        )
        return
    state = services.state_store.load()
    state.scheduled_custom_message = message_text
    state.schedule_source = "custom"
    services.state_store.save(state)
    await update.effective_message.reply_text("Scheduled custom message saved and source switched to custom.")


async def chat_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_incoming(update)
    chat = update.effective_chat
    if chat is None:
        await update.effective_message.reply_text("Could not read the current chat information.")
        return
    await update.effective_message.reply_text(
        f"Current chat ID: {chat.id}\n"
        f"Chat type: {chat.type}"
    )


async def _send_message_to_partner(
    context: ContextTypes.DEFAULT_TYPE,
    services: Services,
    delivery_mode: str,
    custom_message: str | None,
) -> None:
    caption_text = _build_delivery_texts(
        services,
        delivery_mode=delivery_mode,
        custom_message=custom_message,
    )
    image_url = services.image_service.random_image_url()

    await context.bot.send_chat_action(
        chat_id=services.settings.partner_chat_id,
        action=ChatAction.UPLOAD_PHOTO,
    )
    try:
        await context.bot.send_photo(
            chat_id=services.settings.partner_chat_id,
            photo=image_url,
            caption=caption_text,
        )
    except Exception as exc:
        LOGGER.warning("Image send failed, falling back to text only: %s", exc)
        await context.bot.send_message(chat_id=services.settings.partner_chat_id, text=caption_text)


def _build_delivery_texts(
    services: Services,
    delivery_mode: str,
    custom_message: str | None,
) -> str:
    if delivery_mode == "custom":
        final_text = (custom_message or "").strip()
        if not final_text:
            raise RuntimeError(
                "Scheduled source is set to custom but there is no custom message saved yet."
            )
        return final_text

    quote = services.quote_service.random_quote()
    return quote.formatted


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    await update.effective_message.reply_text(
        "Unknown command. Use /help to see the supported commands."
    )


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = services_from(context)
    log_incoming(update)
    if not admin_only(update, services.settings):
        return
    await update.effective_message.reply_text(
        "Use a bot command like /send_quote, /send_custom, /status, or /help."
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    LOGGER.exception("Unhandled bot error", exc_info=context.error)


def _help_text() -> str:
    return (
        "Commands:\n"
        "/chat_id - show the current chat ID\n"
        "/send_quote - send a lovely encouraging message now\n"
        "/send_custom <message> - send your own message now\n"
        "/schedule_on - enable automatic sends\n"
        "/schedule_off - disable automatic sends\n"
        "/set_time <HH:MM> - choose the send time\n"
        "/set_interval <days> - choose how many days between sends\n"
        "/set_daily_count <count> - choose how many times to send on a schedule day\n"
        "/set_random_time <on|off> - use random daily send times\n"
        "/set_source <api|custom> - choose API messages or your custom text\n"
        "/set_custom_schedule <message> - save a scheduled custom message\n"
        "/status - show current settings"
    )


def _format_status(state: RuntimeState, services: Services) -> str:
    today = datetime.now(services.settings.timezone).date().isoformat()
    todays_times = (
        ", ".join(state.scheduled_times_today)
        if state.scheduled_times_date == today and state.scheduled_times_today
        else "Not prepared yet"
    )
    return (
        f"Auto mode: {'ON' if state.auto_mode else 'OFF'}\n"
        f"Send time: {state.send_time}\n"
        f"Interval days: {state.interval_days}\n"
        f"Sends per day: {state.sends_per_day}\n"
        f"Random time mode: {'ON' if state.random_time_mode else 'OFF'}\n"
        f"Today's planned times: {todays_times}\n"
        f"Admin chat ID: {services.settings.admin_chat_id}\n"
        f"Target chat ID: {services.settings.partner_chat_id}\n"
        f"Scheduled source: {state.schedule_source}\n"
        f"Custom scheduled message: {state.scheduled_custom_message or 'Not set'}\n"
        f"Last sent on: {state.last_sent_on or 'Never'}\n"
        f"Quote provider: {services.settings.quote_provider}\n"
        f"Cohere model: {services.settings.cohere_model}\n"
        f"Legacy quote API: {services.settings.quote_api_url}\n"
        f"Image API template: {services.settings.image_api_url_template}\n"
        f"Image tags: {services.settings.image_tags}"
    )


def _friendly_send_error(exc: Exception) -> str:
    if isinstance(exc, BadRequest):
        message = str(exc)
        if "Chat not found" in message:
            return (
                "Chat not found. Make sure TELEGRAM_CHAT_ID is the real numeric chat ID, "
                "the target user has started the bot at least once, or the bot has been added "
                "to the target group/channel."
            )
        return message
    if isinstance(exc, Forbidden):
        return "Telegram refused the message. The bot may be blocked or missing permission in that chat."
    return str(exc)


def _is_valid_time(value: str) -> bool:
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError:
        return False
    return True


async def post_init(application: Application) -> None:
    application.bot_data["schedule_task"] = asyncio.create_task(schedule_loop(application))


async def post_shutdown(application: Application) -> None:
    schedule_task = application.bot_data.get("schedule_task")
    if schedule_task is None:
        return
    schedule_task.cancel()
    try:
        await schedule_task
    except asyncio.CancelledError:
        pass


async def schedule_loop(application: Application) -> None:
    while True:
        try:
            await schedule_tick_from_application(application)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Schedule loop crashed during tick")
        await asyncio.sleep(60)


async def schedule_tick_from_application(application: Application) -> None:
    services = services_from_application(application)
    state = services.state_store.load()
    if not state.auto_mode:
        return

    now = datetime.now(services.settings.timezone)
    today = now.date()
    if not _is_schedule_day(state, today):
        return

    changed = _prepare_schedule_for_today(state, today)
    if changed:
        services.state_store.save(state)

    current_time = now.strftime("%H:%M")
    if current_time not in state.scheduled_times_today:
        return

    if state.sent_times_date == today.isoformat() and current_time in state.sent_times_today:
        return

    try:
        await _send_message_to_partner_from_application(
            application,
            services,
            delivery_mode=state.schedule_source,
            custom_message=state.scheduled_custom_message,
        )
    except Exception as exc:
        LOGGER.exception("Scheduled delivery failed")
        await application.bot.send_message(
            chat_id=services.settings.admin_chat_id,
            text=f"Scheduled send failed: {_friendly_send_error(exc)}",
        )
        return

    state.mark_sent(today, current_time)
    services.state_store.save(state)
    LOGGER.info("Scheduled message delivered for %s at %s", today.isoformat(), current_time)


async def _send_message_to_partner_from_application(
    application: Application,
    services: Services,
    delivery_mode: str,
    custom_message: str | None,
) -> None:
    caption_text = _build_delivery_texts(
        services,
        delivery_mode=delivery_mode,
        custom_message=custom_message,
    )
    image_url = services.image_service.random_image_url()

    await application.bot.send_chat_action(
        chat_id=services.settings.partner_chat_id,
        action=ChatAction.UPLOAD_PHOTO,
    )
    try:
        await application.bot.send_photo(
            chat_id=services.settings.partner_chat_id,
            photo=image_url,
            caption=caption_text,
        )
    except Exception as exc:
        LOGGER.warning("Image send failed, falling back to text only: %s", exc)
        await application.bot.send_message(chat_id=services.settings.partner_chat_id, text=caption_text)


def build_telegram_request(settings: Settings) -> HTTPXRequest:
    request_kwargs = {
        "connect_timeout": settings.telegram_connect_timeout,
        "read_timeout": settings.telegram_read_timeout,
        "http_version": settings.telegram_http_version,
    }
    if settings.telegram_force_ipv4:
        return IPv4HTTPXRequest(**request_kwargs)
    return HTTPXRequest(**request_kwargs)


class IPv4HTTPXRequest(HTTPXRequest):
    def _build_client(self) -> httpx.AsyncClient:
        client_kwargs = dict(self._client_kwargs)
        http1 = client_kwargs.pop("http1", True)
        http2 = client_kwargs.pop("http2", False)
        limits = client_kwargs.get("limits")
        proxy = client_kwargs.pop("proxies", None)
        client_kwargs["transport"] = httpx.AsyncHTTPTransport(
            local_address="0.0.0.0",
            http1=http1,
            http2=http2,
            limits=limits,
            proxy=proxy,
            retries=0,
        )
        return httpx.AsyncClient(**client_kwargs)


def _is_schedule_day(state: RuntimeState, today: date) -> bool:
    last_sent_date = state.last_sent_date
    if last_sent_date is None:
        return True
    if last_sent_date == today:
        if state.sent_times_date != today.isoformat():
            return True
        return len(state.sent_times_today) < state.sends_per_day
    return (today - last_sent_date).days >= state.interval_days


def _prepare_schedule_for_today(state: RuntimeState, today: date) -> bool:
    today_str = today.isoformat()
    changed = False

    if state.sent_times_date != today_str:
        state.sent_times_date = today_str
        state.sent_times_today = []
        changed = True

    if state.random_time_mode:
        if state.scheduled_times_date != today_str or len(state.scheduled_times_today) != state.sends_per_day:
            state.scheduled_times_date = today_str
            state.scheduled_times_today = _build_random_schedule(state.sends_per_day)
            changed = True
    else:
        desired_times = _build_fixed_schedule(state.send_time, state.sends_per_day)
        if state.scheduled_times_date != today_str or state.scheduled_times_today != desired_times:
            state.scheduled_times_date = today_str
            state.scheduled_times_today = desired_times
            changed = True

    return changed


def _build_fixed_schedule(base_time: str, sends_per_day: int) -> list[str]:
    if sends_per_day <= 1:
        return [base_time]

    base_minutes = _time_to_minutes(base_time)
    step_minutes = 1440 / sends_per_day
    times = {
        _minutes_to_time(int(round((base_minutes + (index * step_minutes)) % 1440)))
        for index in range(sends_per_day)
    }
    return sorted(times)


def _build_random_schedule(sends_per_day: int) -> list[str]:
    minute_pool = range(RANDOM_DAY_START_MINUTE, RANDOM_DAY_END_MINUTE + 1)
    chosen = sorted(random.sample(list(minute_pool), k=min(sends_per_day, len(minute_pool))))
    return [_minutes_to_time(minutes) for minutes in chosen]


def _time_to_minutes(value: str) -> int:
    hour_text, minute_text = value.split(":")
    return (int(hour_text) * 60) + int(minute_text)


def _minutes_to_time(value: int) -> str:
    hours, minutes = divmod(value, 60)
    return f"{hours:02d}:{minutes:02d}"
