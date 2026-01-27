import logging
import os
import signal

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from celery.signals import worker_shutting_down
from django.conf import settings

from bots.bot_controller import BotController
from bots.models import Bot, BotEventManager, BotEventSubTypes, BotEventTypes

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=settings.BOT_TASK_SOFT_TIME_LIMIT_SECONDS)
def run_bot(self, bot_id):
    logger.info(f"Running bot {bot_id}")
    bot_controller = BotController(bot_id)

    try:
        bot_controller.run()
    except SoftTimeLimitExceeded:
        logger.warning(f"Bot {bot_id} exceeded soft time limit ({settings.BOT_TASK_SOFT_TIME_LIMIT_SECONDS}s)")
        try:
            bot = Bot.objects.get(id=bot_id)
            BotEventManager.create_event(
                bot=bot,
                event_type=BotEventTypes.FATAL_ERROR,
                event_sub_type=BotEventSubTypes.FATAL_ERROR_SOFT_TIME_LIMIT_EXCEEDED,
            )
        except Exception as e:
            logger.error(f"Failed to create FATAL_ERROR event for bot {bot_id}: {e}")
        finally:
            bot_controller.cleanup()
        return


def kill_child_processes():
    # Get the process group ID (PGID) of the current process
    pgid = os.getpgid(os.getpid())

    try:
        # Send SIGTERM to all processes in the process group
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # Process group may no longer exist


@worker_shutting_down.connect
def shutting_down_handler(sig, how, exitcode, **kwargs):
    # Just adding this code so we can see how to shut down all the tasks
    # when the main process is terminated.
    # It's likely overkill.
    logger.info("Celery worker shutting down, sending SIGTERM to all child processes")
    kill_child_processes()
