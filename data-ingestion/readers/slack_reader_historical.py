"""Slack historical reader for slackdump files."""
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from llama_index.core.readers.base import BasePydanticReader
from llama_index.core.schema import Document

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)
EXCLUDED_METADATA_FIELDS = ['channel', 'thread_ts']


class SlackHistoricalReader(BasePydanticReader):
    """Slack historical reader for slackdump files.
    
    Reads conversations from local JSON files created by slackdump tool.
    Applies the same filtering logic as SlackReader for consistency.
    
    Args:
        slackdump_path (str): Path to the slackdump directory containing JSON files
        earliest_date (Optional[datetime]): Earliest date from which to read conversations
        latest_date (Optional[datetime]): Latest date from which to read conversations  
        bot_user_id (Optional[str]): Bot user ID to filter messages
        not_ignore_users (Optional[list[str]]): Users whose messages should always be indexed
    """
    
    is_remote: bool = False
    slackdump_path: str
    earliest_date_timestamp: Optional[float]
    latest_date_timestamp: Optional[float] 
    bot_user_id: Optional[str]
    not_ignore_users: Optional[list[str]] = []
    
    def __init__(
        self,
        slackdump_path: str,
        earliest_date: Optional[datetime] = None,
        latest_date: Optional[datetime] = None,
        earliest_date_timestamp: Optional[float] = None,
        latest_date_timestamp: Optional[float] = None,
        bot_user_id: Optional[str] = None,
        not_ignore_users: Optional[list[str]] = None
    ) -> None:
        """Initialize with parameters."""
        if not os.path.exists(slackdump_path):
            raise ValueError(f"Slackdump path does not exist: {slackdump_path}")
            
        if latest_date is not None and earliest_date is None:
            raise ValueError("Must specify `earliest_date` if `latest_date` is specified.")
            
        if not_ignore_users is None:
            not_ignore_users = []
            
        if earliest_date is not None:
            earliest_date_timestamp = earliest_date.timestamp()
        else:
            earliest_date_timestamp = earliest_date_timestamp
            
        if latest_date is not None:
            latest_date_timestamp = latest_date.timestamp()
        else:
            latest_date_timestamp = latest_date_timestamp or datetime.now().timestamp()
            
        super().__init__(
            slackdump_path=slackdump_path,
            earliest_date_timestamp=earliest_date_timestamp,
            latest_date_timestamp=latest_date_timestamp,
            bot_user_id=bot_user_id,
            not_ignore_users=not_ignore_users,
        )
    
    @classmethod
    def class_name(cls) -> str:
        """Get the name identifier of the class."""
        return "SlackHistoricalReader"
    
    def _load_json_file(self, file_path: str) -> list[dict]:
        """Load messages from a JSON file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                messages = json.load(f)
            return messages if isinstance(messages, list) else []
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.warning(f"Failed to load {file_path}: {e}")
            return []
    
    def _get_json_files(self) -> list[str]:
        """Get all JSON files in the slackdump directory within date range."""
        path = Path(self.slackdump_path)
        json_files = []
        
        for file_path in path.glob("*.json"):
            try:
                # Extract date from filename (YYYY-MM-DD.json)
                date_str = file_path.stem
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                file_timestamp = file_date.timestamp()
                
                # Check if file is within date range
                if self.earliest_date_timestamp and file_timestamp < self.earliest_date_timestamp:
                    continue
                if self.latest_date_timestamp and file_timestamp > self.latest_date_timestamp:
                    continue
                    
                json_files.append(str(file_path))
            except ValueError:
                # Skip files that don't match date format
                logger.warning(f"Skipping file with invalid date format: {file_path}")
                continue
                
        return sorted(json_files)
    
    def _build_thread_from_messages(self, thread_messages: list[dict], channel_id: str, thread_ts: str) -> Document:
        """Build a document from thread messages."""
        messages_text: list[str] = []
        
        for message in thread_messages:
            # Skip bot messages unless they're from users we don't want to ignore
            if (message.get('user') == self.bot_user_id and 
                message.get('user') not in self.not_ignore_users):
                continue
                
            # Skip messages from ignored users unless they have attachments we want
            if (message.get('user') not in self.not_ignore_users and 
                message.get('user') != self.bot_user_id):
                messages_text.append(message.get('text', ''))
            elif (message.get('user') in self.not_ignore_users and 
                  'attachments' in message and 
                  message['attachments'] and 
                  'text' in message['attachments'][0]):
                messages_text.append(message['attachments'][0]['text'])
                
        return Document(
            text="\n\n".join(filter(None, messages_text)),
            metadata={"channel": channel_id, "thread_ts": float(thread_ts)},
            excluded_embed_metadata_keys=EXCLUDED_METADATA_FIELDS,
            excluded_llm_metadata_keys=EXCLUDED_METADATA_FIELDS
        )
    
    def _is_message_in_timeframe(self, message: dict) -> bool:
        """Check if message timestamp is within the specified timeframe."""
        try:
            msg_timestamp = float(message.get('ts', 0))
            if self.earliest_date_timestamp and msg_timestamp < self.earliest_date_timestamp:
                return False
            if self.latest_date_timestamp and msg_timestamp > self.latest_date_timestamp:
                return False
            return True
        except (ValueError, TypeError):
            return False
    
    def is_for_indexing(self, message: dict) -> bool:
        """Determine if a message should be indexed (same logic as SlackReader)."""
        # ignore unanswered messages
        if 'reply_count' in message:
            # if bot user id isn't specified or bot hasn't replied the message
            if not self.bot_user_id or self.bot_user_id not in message.get('reply_users', []):
                return True
            if message.get('reply_users_count', 0) > 1:
                return True
        # even if it's a single message but from a user in un-ignore list, index it
        elif message.get('user') in self.not_ignore_users:
            return True
        return False
    
    def _process_messages_from_files(self) -> list[Document]:
        """Process all messages from JSON files and group them by threads."""
        json_files = self._get_json_files()
        logger.info(f"Processing {len(json_files)} JSON files from {self.slackdump_path}")
        
        # Dictionary to group messages by thread_ts
        threads: dict[str, list[dict]] = {}
        standalone_messages: list[dict] = []
        
        for file_path in json_files:
            messages = self._load_json_file(file_path)
            logger.info(f"Loaded {len(messages)} messages from {os.path.basename(file_path)}")
            
            for message in messages:
                # Skip messages outside timeframe
                if not self._is_message_in_timeframe(message):
                    continue
                    
                # Skip non-message types (like channel_join)
                if message.get('type') != 'message' or message.get('subtype') == 'channel_join':
                    continue
                
                thread_ts = message.get('thread_ts')
                if thread_ts:
                    # This is a thread reply
                    if thread_ts not in threads:
                        threads[thread_ts] = []
                    threads[thread_ts].append(message)
                else:
                    # Check if this is a root message that has replies
                    if 'reply_count' in message:
                        thread_ts = message.get('ts')
                        if thread_ts not in threads:
                            threads[thread_ts] = []
                        threads[thread_ts].append(message)
                    else:
                        standalone_messages.append(message)
        
        # Process threads
        documents = []
        channel_id = os.path.basename(self.slackdump_path)  # Use directory name as channel ID
        
        for thread_ts, thread_messages in threads.items():
            # Sort messages by timestamp
            thread_messages.sort(key=lambda x: float(x.get('ts', 0)))
            
            # Check if the root message should be indexed
            root_message = thread_messages[0] if thread_messages else None
            if root_message and self.is_for_indexing(root_message):
                doc = self._build_thread_from_messages(thread_messages, channel_id, thread_ts)
                if doc.text.strip():
                    documents.append(doc)
                    
        # Process standalone messages from not_ignore_users
        for message in standalone_messages:
            if self.is_for_indexing(message):
                doc = self._build_thread_from_messages([message], channel_id, message.get('ts'))
                if doc.text.strip():
                    documents.append(doc)
        
        logger.info(f"Created {len(documents)} documents from {len(threads)} threads and {len(standalone_messages)} standalone messages")
        return documents
    
    def load_data(self, **kwargs) -> list[Document]:
        """Load data from slackdump JSON files.
        
        Returns:
            List[Document]: List of documents created from Slack messages.
        """
        return self._process_messages_from_files()


if __name__ == "__main__":
    # Example usage
    reader = SlackHistoricalReader(
        slackdump_path="../slack_dumps/course-llm-zoomcamp",
        earliest_date=datetime(2024, 4, 1),
        latest_date=datetime(2024, 5, 1),
        bot_user_id='U05DM3PEJA2',
        not_ignore_users=['U01S08W6Z9T']
    )
    
    docs = reader.load_data()
    logger.info(f"Total documents loaded: {len(docs)}")

    for i, thread in enumerate(docs[:3]):  # Show first 3 documents
        logger.info(f'Document {i+1}:')
        logger.info(f'Text (first 200 chars): {thread.text[:200]}...')
        logger.info(f'Metadata: {thread.metadata}')
        logger.info('----------------------------')