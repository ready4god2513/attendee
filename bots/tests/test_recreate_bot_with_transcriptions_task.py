"""
Unit tests for recreate_bot_with_transcriptions_task
"""
from django.test import TransactionTestCase
from unittest import mock

from accounts.models import Organization, Project
from bots.models import (
    Bot,
    BotStates,
    Participant,
    Recording,
    RecordingTypes,
    TranscriptionTypes,
    TranscriptionProviders,
    Utterance,
    AudioChunk,
)
from bots.tasks.recreate_bot_with_transcriptions_task import recreate_bot_with_transcriptions


class RecreateBotsWithTranscriptionsTaskTest(TransactionTestCase):
    """Tests for the bot recreation task"""

    def setUp(self):
        """Set up test data"""
        self.organization = Organization.objects.create(name="Test Org")
        self.project = Project.objects.create(name="Test Project", organization=self.organization)

    def test_recreate_bot_with_transcriptions(self):
        """Test that a bot can be recreated with transcriptions copied over"""
        # Create original bot
        original_bot = Bot.objects.create(
            project=self.project,
            meeting_url="https://zoom.us/j/123456789",
            name="Test Bot",
            settings={"test_setting": "value"},
            metadata={"original": "metadata"},
        )

        # Create recording for original bot
        original_recording = Recording.objects.create(
            bot=original_bot,
            recording_type=RecordingTypes.AUDIO_AND_VIDEO,
            transcription_type=TranscriptionTypes.NON_REALTIME,
            transcription_provider=TranscriptionProviders.DEEPGRAM,
            is_default_recording=True,
        )

        # Create participants
        participant1 = Participant.objects.create(
            bot=original_bot,
            uuid="participant-1",
            user_uuid="user-1",
            full_name="Alice",
            is_host=True,
        )
        participant2 = Participant.objects.create(
            bot=original_bot,
            uuid="participant-2",
            user_uuid="user-2",
            full_name="Bob",
            is_host=False,
        )

        # Create utterances with transcriptions
        Utterance.objects.create(
            recording=original_recording,
            participant=participant1,
            timestamp_ms=1000,
            duration_ms=2000,
            transcription={"transcript": "Hello everyone", "words": []},
            source=Utterance.Sources.PER_PARTICIPANT_AUDIO,
        )
        Utterance.objects.create(
            recording=original_recording,
            participant=participant2,
            timestamp_ms=3000,
            duration_ms=1500,
            transcription={"transcript": "Hi Alice", "words": []},
            source=Utterance.Sources.PER_PARTICIPANT_AUDIO,
        )

        # Mock launch_bot to prevent actual bot launching during test
        with mock.patch("bots.tasks.recreate_bot_with_transcriptions_task.launch_bot") as mock_launch:
            # Call the task
            result = recreate_bot_with_transcriptions(original_bot.id)

        # Verify result
        self.assertIsNotNone(result)
        self.assertIn("new_bot_id", result)
        self.assertEqual(result["original_bot_id"], original_bot.object_id)

        # Get the new bot
        new_bot_object_id = result["new_bot_id"]
        new_bot = Bot.objects.get(object_id=new_bot_object_id)

        # Verify new bot has same settings
        self.assertEqual(new_bot.meeting_url, original_bot.meeting_url)
        self.assertEqual(new_bot.name, original_bot.name)
        self.assertEqual(new_bot.settings, original_bot.settings)
        self.assertEqual(new_bot.project, original_bot.project)

        # Verify metadata includes recreation info
        self.assertIn("recreated_from_bot", new_bot.metadata)
        self.assertEqual(new_bot.metadata["recreated_from_bot"], original_bot.object_id)
        self.assertEqual(new_bot.metadata["recreation_reason"], "graceful_shutdown")
        self.assertEqual(new_bot.metadata["original"], "metadata")

        # Verify new bot has a recording
        new_recording = new_bot.recordings.filter(is_default_recording=True).first()
        self.assertIsNotNone(new_recording)

        # Verify participants were copied
        self.assertEqual(new_bot.participants.count(), 2)
        new_participant1 = new_bot.participants.get(uuid="participant-1")
        self.assertEqual(new_participant1.full_name, "Alice")
        self.assertEqual(new_participant1.is_host, True)
        new_participant2 = new_bot.participants.get(uuid="participant-2")
        self.assertEqual(new_participant2.full_name, "Bob")

        # Verify utterances were copied
        new_utterances = new_recording.utterances.all().order_by("timestamp_ms")
        self.assertEqual(new_utterances.count(), 2)
        
        first_utterance = new_utterances[0]
        self.assertEqual(first_utterance.transcription["transcript"], "Hello everyone")
        self.assertEqual(first_utterance.participant.uuid, "participant-1")
        self.assertEqual(first_utterance.timestamp_ms, 1000)
        self.assertEqual(first_utterance.duration_ms, 2000)

        second_utterance = new_utterances[1]
        self.assertEqual(second_utterance.transcription["transcript"], "Hi Alice")
        self.assertEqual(second_utterance.participant.uuid, "participant-2")
        self.assertEqual(second_utterance.timestamp_ms, 3000)

        # Verify original bot was updated with recreation info
        original_bot.refresh_from_db()
        self.assertIn("recreated_as_bot", original_bot.metadata)
        self.assertEqual(original_bot.metadata["recreated_as_bot"], new_bot.object_id)

        # Verify launch_bot was called
        mock_launch.assert_called_once_with(new_bot)

    def test_recreate_bot_without_transcriptions(self):
        """Test that a bot can be recreated even without existing transcriptions"""
        # Create original bot without transcriptions
        original_bot = Bot.objects.create(
            project=self.project,
            meeting_url="https://meet.google.com/abc-defg-hij",
            name="Empty Bot",
        )

        Recording.objects.create(
            bot=original_bot,
            recording_type=RecordingTypes.AUDIO_ONLY,
            transcription_type=TranscriptionTypes.NON_REALTIME,
            transcription_provider=TranscriptionProviders.DEEPGRAM,
            is_default_recording=True,
        )

        with mock.patch("bots.tasks.recreate_bot_with_transcriptions_task.launch_bot"):
            result = recreate_bot_with_transcriptions(original_bot.id)

        # Verify bot was created
        self.assertIsNotNone(result)
        self.assertIn("new_bot_id", result)
        new_bot = Bot.objects.get(object_id=result["new_bot_id"])
        self.assertIsNotNone(new_bot)

        # Verify recording exists
        new_recording = new_bot.recordings.filter(is_default_recording=True).first()
        self.assertIsNotNone(new_recording)

    def test_recreate_bot_filters_empty_transcriptions(self):
        """Test that utterances without transcriptions are not copied"""
        original_bot = Bot.objects.create(
            project=self.project,
            meeting_url="https://zoom.us/j/987654321",
            name="Filter Test Bot",
        )

        original_recording = Recording.objects.create(
            bot=original_bot,
            recording_type=RecordingTypes.AUDIO_AND_VIDEO,
            transcription_type=TranscriptionTypes.NON_REALTIME,
            transcription_provider=TranscriptionProviders.DEEPGRAM,
            is_default_recording=True,
        )

        participant = Participant.objects.create(
            bot=original_bot,
            uuid="participant-1",
            full_name="Test User",
        )

        # Create utterances - some with transcriptions, some without
        Utterance.objects.create(
            recording=original_recording,
            participant=participant,
            timestamp_ms=1000,
            duration_ms=1000,
            transcription={"transcript": "Valid text", "words": []},
        )
        Utterance.objects.create(
            recording=original_recording,
            participant=participant,
            timestamp_ms=2000,
            duration_ms=1000,
            transcription=None,  # No transcription
        )
        Utterance.objects.create(
            recording=original_recording,
            participant=participant,
            timestamp_ms=3000,
            duration_ms=1000,
            transcription={"transcript": "", "words": []},  # Empty transcript
        )
        Utterance.objects.create(
            recording=original_recording,
            participant=participant,
            timestamp_ms=4000,
            duration_ms=1000,
            transcription={"transcript": "Another valid text", "words": []},
        )

        with mock.patch("bots.tasks.recreate_bot_with_transcriptions_task.launch_bot"):
            result = recreate_bot_with_transcriptions(original_bot.id)

        new_bot = Bot.objects.get(object_id=result["new_bot_id"])
        new_recording = new_bot.recordings.filter(is_default_recording=True).first()

        # Only 2 utterances should be copied (the ones with valid transcripts)
        new_utterances = new_recording.utterances.all()
        self.assertEqual(new_utterances.count(), 2)
        self.assertEqual(new_utterances[0].transcription["transcript"], "Valid text")
        self.assertEqual(new_utterances[1].transcription["transcript"], "Another valid text")
