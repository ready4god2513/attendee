# Bot Recreation with Transcription Copy Feature

## Overview
This feature enables graceful handling of bot terminations by automatically recreating the bot and preserving all existing transcriptions. When a bot receives a SIGTERM or SIGINT signal (graceful shutdown), it will now automatically spawn a replacement bot that rejoins the meeting with all previously captured transcriptions intact.

## Implementation Details

### Key Components

#### 1. New Task: `recreate_bot_with_transcriptions_task.py`
Location: `/bots/tasks/recreate_bot_with_transcriptions_task.py`

**Purpose**: Handles the recreation of a terminated bot while preserving transcription history.

**Key Features**:
- Creates a new bot with identical settings (meeting URL, name, settings, etc.)
- Copies all participants from the original bot
- Copies all utterances with successful transcriptions
- Filters out empty/failed transcriptions automatically
- Maintains proper recording structure
- Links original and new bots via metadata
- Launches the new bot automatically

**Metadata Tracking**:
- New bot includes: `recreated_from_bot`, `recreation_reason`
- Original bot updated with: `recreated_as_bot`

#### 2. Updated: `handle_glib_shutdown` in `bot_controller.py`
Location: `/bots/bot_controller/bot_controller.py`

**Changes**:
- Now schedules `recreate_bot_with_transcriptions` task with 30-second countdown
- Adds `will_recreate_bot: true` to the FATAL_ERROR event metadata
- Maintains existing cleanup behavior

#### 3. Updated: Task Registry
Location: `/bots/tasks/__init__.py`

**Changes**:
- Added `recreate_bot_with_transcriptions` to imports and `__all__` exports

### Workflow

```
1. Bot receives SIGTERM/SIGINT signal
   ↓
2. handle_glib_shutdown() is called
   ↓
3. FATAL_ERROR event created (with will_recreate_bot=true)
   ↓
4. recreate_bot_with_transcriptions task scheduled (30s delay)
   ↓
5. Bot cleanup() runs
   ↓
6. [30 seconds later]
   ↓
7. recreate_bot_with_transcriptions task executes:
   - Creates new bot with same settings
   - Copies participants
   - Copies all transcriptions/utterances
   - Copies bot-level webhook subscriptions
   - Links bots via metadata
   - Launches new bot
   ↓
8. New bot joins meeting with full transcript history
```

### Data Copied

**Bot Properties**:
- project
- meeting_url
- meeting_uuid
- name
- settings
- metadata (with additions)
- calendar_event

**Not Copied** (intentionally):
- deduplication_key (set to None)
- join_at (set to None - join immediately)
- heartbeat timestamps

**Participants**:
- uuid
- user_uuid
- full_name
- is_host

**Utterances** (only those with valid transcriptions):
- timestamp_ms
- duration_ms
- transcription (JSON with transcript and words)
- source
- participant (mapped to new participant)

**Webhook Subscriptions** (bot-level only):
- url
- triggers
- is_active
- project-level webhook subscriptions (remain at project level)
- webhook delivery attempts history

**Not Copied**:
- audio_blob (typically cleared after transcription)
- audio_chunk (only transcription text is preserved)
- utterances without transcriptions or empty transcripts

### Recording Handling

The task creates a new Recording object for the recreated bot that matches the original:
- recording_type
- transcription_type
- transcription_provider
- is_default_recording flag

If no original recording is found, a default recording is created with sensible defaults.

## Testing

### Test Suite
Location: `/bots/tests/test_recreate_bot_with_transcriptions_task.py`

**Test Cases**:
1. `test_recreate_bot_with_transcriptions` - Full recreation with multiple participants and transcriptions
4. `test_recreate_bot_copies_webhooks` - Verifies bot-level webhooks are copied correctly

**Coverage**:
- Bot creation with settings preservation
- Metadata tracking (bidirectional linking)
- Participant copying
- Utterance copying with filtering
- Webhook subscription copying (bot-level) linking)
- Participant copying
- Utterance copying with filtering
- Recording creation
- launch_bot invocation

## Usage Examples

### Scenario 1: Kubernetes Pod Eviction
When Kubernetes evicts a pod for resource rebalancing, the bot receives SIGTERM and automatically recreates itself in the same meeting with all transcriptions preserved.

### Scenario 2: Manual Restart
If an operator manually restarts a bot pod, the graceful shutdown will trigger bot recreation with transcript continuity.

### Scenario 3: Resource Constraints
If a node is being drained, bots on that node will gracefully shutdown and recreate on available nodes while maintaining transcript history.

## Configuration

No additional configuration required. The feature activates automatically when:
- Bot receives SIGTERM or SIGINT signal
- `handle_glib_shutdown()` is invoked

The 30-second countdown can be adjusted in `bot_controller.py`:
```python
recreate_bot_with_transcriptions.apply_async(args=[self.bot_in_db.id], countdown=30)
```

## Error Handling

The task includes comprehensive error handling:
- Returns `{"error": "Bot not found"}` if original bot doesn't exist
- Returns `{"error": <exception message>}` for other failures
- All errors are logged with full exception traces
- Warnings logged for missing participants or recordings

## Benefits

1. **Webhook Continuity**: Bot-level webhooks continue to receive events from the new bot
6. **Transcript Continuity**: Meeting participants experience no loss of transcript history
2. **Seamless Recovery**: Automatic bot recreation without manual intervention
3. **Meeting Continuity**: New bot rejoins with full context
4. **Participant Preservation**: All meeting participants are maintained in the new bot
5. **Audit Trail**: Metadata links allow tracking of bot lifecycles

## Limitations
5. Project-level webhook subscriptions are not affected (they remain at project level)
6. Webhook delivery history is not copied

1. Audio recordings are not preserved (only transcriptions)
2. Chat messages are not copied (would require additional logic)
3. Bot events from original bot are not transferred
4. Recording files (video/audio) are not carried over

## Future Enhancements

Potential improvements:
6. Copy participant events history
1. Copy chat messages from original bot
2. Preserve webhook delivery state
3. Add configuration option to disable recreation
4. Support partial transcript copying (e.g., last N minutes)
5. Add metrics for recreation success rate
