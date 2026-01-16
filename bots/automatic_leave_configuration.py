import os
from dataclasses import dataclass


def _get_env_int(env_var: str, default: int) -> int:
    """Get an integer from environment variable with a default value."""
    value = os.getenv(env_var)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_int_optional(env_var: str) -> int | None:
    """Get an optional integer from environment variable."""
    value = os.getenv(env_var)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class AutomaticLeaveConfiguration:
    """Specifies conditions under which the bot will automatically leave a meeting.

    Attributes:
        silence_timeout_seconds: Number of seconds of continuous silence after which the bot should leave
        only_participant_in_meeting_timeout_seconds: Number of seconds to wait before leaving if bot is the only participant
        wait_for_host_to_start_meeting_timeout_seconds: Number of seconds to wait for the host to start the meeting
        silence_activate_after_seconds: Number of seconds to wait before activating the silence timeout
        waiting_room_timeout_seconds: Number of seconds to wait before leaving if the bot is in the waiting room
        max_uptime_seconds: Maximum number of seconds that the bot should be running before automatically leaving (infinite by default)

    Environment Variables:
        BOT_SILENCE_TIMEOUT_SECONDS: Override default for silence_timeout_seconds (default: 600)
        BOT_SILENCE_ACTIVATE_AFTER_SECONDS: Override default for silence_activate_after_seconds (default: 1200)
        BOT_ONLY_PARTICIPANT_TIMEOUT_SECONDS: Override default for only_participant_in_meeting_timeout_seconds (default: 60)
        BOT_WAIT_FOR_HOST_TIMEOUT_SECONDS: Override default for wait_for_host_to_start_meeting_timeout_seconds (default: 600)
        BOT_WAITING_ROOM_TIMEOUT_SECONDS: Override default for waiting_room_timeout_seconds (default: 900)
        BOT_MAX_UPTIME_SECONDS: Override default for max_uptime_seconds (default: None/infinite)
    """

    silence_timeout_seconds: int = _get_env_int("BOT_SILENCE_TIMEOUT_SECONDS", 600)
    silence_activate_after_seconds: int = _get_env_int("BOT_SILENCE_ACTIVATE_AFTER_SECONDS", 1200)
    only_participant_in_meeting_timeout_seconds: int = _get_env_int("BOT_ONLY_PARTICIPANT_TIMEOUT_SECONDS", 60)
    wait_for_host_to_start_meeting_timeout_seconds: int = _get_env_int("BOT_WAIT_FOR_HOST_TIMEOUT_SECONDS", 600)
    waiting_room_timeout_seconds: int = _get_env_int("BOT_WAITING_ROOM_TIMEOUT_SECONDS", 900)
    max_uptime_seconds: int | None = _get_env_int_optional("BOT_MAX_UPTIME_SECONDS")
