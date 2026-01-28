import logging

from celery import shared_task
from django.db import transaction

from bots.launch_bot_utils import launch_bot
from bots.models import Bot, BotEventManager, BotEventTypes, Recording, Participant, Utterance, AudioChunk, BotStates, TranscriptionTypes, WebhookSubscription

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=3600)
def recreate_bot_with_transcriptions(self, original_bot_id):
    """
    Re-create a bot that was terminated, copying over existing transcriptions and participants.
    This is useful when a bot is gracefully shutdown (SIGTERM/SIGINT) and needs to be restarted
    in the same meeting with the context preserved.
    """
    logger.info(f"Recreating bot {original_bot_id} with transcriptions")

    try:
        original_bot = Bot.objects.get(id=original_bot_id)

        # Create a new bot with the same settings
        with transaction.atomic():
            new_bot = Bot.objects.create(
                project=original_bot.project,
                meeting_url=original_bot.meeting_url,
                meeting_uuid=original_bot.meeting_uuid,
                name=original_bot.name,
                settings=original_bot.settings,
                metadata={
                    **(original_bot.metadata or {}),
                    "recreated_from_bot": original_bot.object_id,
                    "recreation_reason": "graceful_shutdown",
                },
                join_at=None,  # Join immediately
                deduplication_key=None,  # Don't use deduplication key for recreated bots
                calendar_event=original_bot.calendar_event,
                state=BotStates.READY,
            )

            logger.info(f"Created new bot {new_bot.object_id} from original bot {original_bot.object_id}")

            # Get the default recording from the original bot
            original_recording = original_bot.recordings.filter(is_default_recording=True).first()
            if not original_recording:
                logger.warning(f"No default recording found for original bot {original_bot.object_id}")
                # Create a basic recording even if we don't have an original
                # Determine transcription provider from bot settings or use a default
                from bots.models import TranscriptionProviders
                transcription_provider = TranscriptionProviders.DEEPGRAM  # Default fallback
                
                Recording.objects.create(
                    bot=new_bot,
                    recording_type=new_bot.recording_type(),
                    transcription_type=TranscriptionTypes.NON_REALTIME,
                    transcription_provider=transcription_provider,
                    is_default_recording=True,
                )
            else:
                # Create new recording for the new bot
                new_recording = Recording.objects.create(
                    bot=new_bot,
                    recording_type=original_recording.recording_type,
                    transcription_type=original_recording.transcription_type,
                    transcription_provider=original_recording.transcription_provider,
                    is_default_recording=True,
                )

                logger.info(f"Created new recording {new_recording.id} for new bot {new_bot.object_id}")

                # Copy participants from original bot to new bot
                participant_mapping = {}  # Map old participant ID to new participant ID
                for old_participant in original_bot.participants.all():
                    new_participant = Participant.objects.create(
                        bot=new_bot,
                        uuid=old_participant.uuid,
                        user_uuid=old_participant.user_uuid,
                        full_name=old_participant.full_name,
                        is_host=old_participant.is_host,
                    )
                    participant_mapping[old_participant.id] = new_participant
                    logger.info(f"Copied participant {old_participant.uuid} ({old_participant.full_name})")

                # Copy utterances (transcriptions) from original recording to new recording
                utterances_copied = 0
                for old_utterance in original_recording.utterances.filter(transcription__isnull=False).order_by('timestamp_ms'):
                    # Only copy utterances that have successful transcriptions
                    if not old_utterance.transcription or not old_utterance.transcription.get("transcript"):
                        continue

                    new_participant = participant_mapping.get(old_utterance.participant.id)
                    if not new_participant:
                        logger.warning(f"Could not find new participant for utterance {old_utterance.id}")
                        continue

                    # Create new utterance with the transcription data
                    # Note: We're not copying the audio_blob since that's typically cleared after transcription
                    Utterance.objects.create(
                        recording=new_recording,
                        participant=new_participant,
                        timestamp_ms=old_utterance.timestamp_ms,
                        duration_ms=old_utterance.duration_ms,
                        transcription=old_utterance.transcription,
                        source=old_utterance.source,
                        # Don't copy audio_chunk as we're only preserving the transcription text
                        audio_chunk=None,
                    )
                    utterances_copied += 1

                logger.info(f"Copied {utterances_copied} utterances with transcriptions to new bot {new_bot.object_id}")

            # Copy bot-level webhook subscriptions from original bot to new bot
            webhooks_copied = 0
            for old_webhook in original_bot.bot_webhook_subscriptions.all():
                WebhookSubscription.objects.create(
                    project=new_bot.project,
                    bot=new_bot,
                    url=old_webhook.url,
                    triggers=old_webhook.triggers,
                    is_active=old_webhook.is_active,
                )
                webhooks_copied += 1
                logger.info(f"Copied webhook subscription {old_webhook.url}")

            logger.info(f"Copied {webhooks_copied} webhook subscriptions to new bot {new_bot.object_id}")

            # Create JOIN_REQUESTED event for the new bot
            BotEventManager.create_event(
                bot=new_bot,
                event_type=BotEventTypes.JOIN_REQUESTED,
                event_metadata={
                    "source": "recreate_after_shutdown",
                    "original_bot": original_bot.object_id,
                },
            )

            # Add metadata to original bot indicating it was recreated
            original_bot.metadata = original_bot.metadata or {}
            original_bot.metadata["recreated_as_bot"] = new_bot.object_id
            original_bot.save()

        # Launch the new bot
        logger.info(f"Launching recreated bot {new_bot.object_id}")
        launch_bot(new_bot)

        logger.info(f"Successfully recreated bot {original_bot.object_id} as {new_bot.object_id}")
        return {"original_bot_id": original_bot.object_id, "new_bot_id": new_bot.object_id}

    except Bot.DoesNotExist:
        logger.error(f"Bot {original_bot_id} not found")
        return {"error": "Bot not found"}
    except Exception as e:
        logger.error(f"Error recreating bot {original_bot_id}: {e}")
        logger.exception(e)
        return {"error": str(e)}
