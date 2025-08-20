#!/usr/bin/env python3
"""
Script to add Slack bot to specified channels from environment variables.
This script reads channel IDs from environment variables and joins the bot to those channels.
"""

import os
import sys
import time
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def get_channel_env_vars():
    """Get all Slack channel environment variables."""
    channel_vars = {
        'SLACK_CHANNEL_DATA_ENGINEERING': os.getenv('SLACK_CHANNEL_DATA_ENGINEERING'),
        'SLACK_CHANNEL_LLM_ZOOMCAMP': os.getenv('SLACK_CHANNEL_LLM_ZOOMCAMP'),
        'SLACK_CHANNEL_MLOPS_ZOOMCAMP': os.getenv('SLACK_CHANNEL_MLOPS_ZOOMCAMP'),
        'SLACK_CHANNEL_ML_ZOOMCAMP': os.getenv('SLACK_CHANNEL_ML_ZOOMCAMP'),
        'SLACK_CHANNEL_STOCKS_ANALYTICS': os.getenv('SLACK_CHANNEL_STOCKS_ANALYTICS')
    }
    
    # Filter out None values
    return {k: v for k, v in channel_vars.items() if v}


def join_channel(client, channel_id, channel_name):
    """Join bot to a specific channel."""
    try:
        # Try to join the channel
        response = client.conversations_join(channel=channel_id)
        
        if response['ok']:
            print(f"✓ Successfully joined channel {channel_name} ({channel_id})")
            return True
        else:
            print(f"✗ Failed to join channel {channel_name} ({channel_id})")
            return False
            
    except SlackApiError as e:
        error_code = e.response['error']
        
        # Handle specific error cases
        if error_code == 'already_in_channel':
            print(f"ℹ Already in channel {channel_name} ({channel_id})")
            return True
        elif error_code == 'channel_not_found':
            print(f"✗ Channel not found: {channel_name} ({channel_id})")
            return False
        elif error_code == 'is_archived':
            print(f"✗ Channel is archived: {channel_name} ({channel_id})")
            return False
        else:
            print(f"✗ Error joining {channel_name} ({channel_id}): {error_code}")
            return False
    except Exception as e:
        print(f"✗ Unexpected error joining {channel_name} ({channel_id}): {str(e)}")
        return False


def main():
    """Main function to join bot to all configured channels."""
    
    # Get Slack bot token
    slack_token = os.getenv('SLACK_BOT_TOKEN')
    if not slack_token:
        print("Error: SLACK_BOT_TOKEN environment variable not set")
        sys.exit(1)
    
    # Initialize Slack client
    client = WebClient(token=slack_token)
    
    # Verify bot authentication
    try:
        auth_response = client.auth_test()
        bot_name = auth_response['user']
        bot_id = auth_response['user_id']
        team_name = auth_response['team']
        print(f"Authenticated as bot '{bot_name}' (ID: {bot_id}) in workspace '{team_name}'")
        print("-" * 60)
    except SlackApiError as e:
        print(f"Authentication failed: {e.response['error']}")
        sys.exit(1)
    
    # Get channel environment variables
    channels = get_channel_env_vars()
    
    if not channels:
        print("Warning: No channel environment variables found")
        print("Expected variables:")
        print("  - SLACK_CHANNEL_DATA_ENGINEERING")
        print("  - SLACK_CHANNEL_LLM_ZOOMCAMP")
        print("  - SLACK_CHANNEL_MLOPS_ZOOMCAMP")
        print("  - SLACK_CHANNEL_ML_ZOOMCAMP")
        print("  - SLACK_CHANNEL_STOCKS_ANALYTICS")
        sys.exit(0)
    
    print(f"Found {len(channels)} channel(s) to join:")
    for var_name, channel_id in channels.items():
        print(f"  - {var_name}: {channel_id}")
    print("-" * 60)
    
    # Join each channel
    success_count = 0
    failed_count = 0
    
    for var_name, channel_id in channels.items():
        # Extract course name from variable name for display
        course_name = var_name.replace('SLACK_CHANNEL_', '').replace('_', ' ').title()
        
        if join_channel(client, channel_id, course_name):
            success_count += 1
        else:
            failed_count += 1
        
        # Small delay between API calls to avoid rate limiting
        time.sleep(1)
    
    # Summary
    print("-" * 60)
    print(f"Summary: {success_count} successful, {failed_count} failed")
    
    # Exit with error code if any failures
    if failed_count > 0:
        sys.exit(1)
    
    print("Bot successfully joined all specified channels!")


if __name__ == "__main__":
    main()