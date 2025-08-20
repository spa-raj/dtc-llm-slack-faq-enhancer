#!/usr/bin/env python3
"""
Local script to upload historical Slack dump files to S3 with date-based partitioning.
Run this from your local machine after configuring AWS credentials.

This script establishes the partition key pattern that will be used for:
1. Historical data upload (this script)
2. Daily Slack API data fetching (slack_pipeline.py)

Partition structure:
s3://bucket/raw/slack/{course_id}/year={YYYY}/month={MM}/day={DD}/{YYYY-MM-DD}.json

Usage:
    python data-ingestion/upload_historical_dumps.py --bucket dtc-slack-data-prod
    
    Or to upload a specific course:
    python data-ingestion/upload_historical_dumps.py --bucket dtc-slack-data-prod --course course-data-engineering
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple
import boto3
from botocore.exceptions import ClientError, NoCredentialsError


def parse_args():
    parser = argparse.ArgumentParser(description='Upload historical Slack dumps to S3 with partitioning')
    parser.add_argument('--bucket', type=str, required=True,
                        help='S3 bucket name (e.g., dtc-slack-data-prod)')
    parser.add_argument('--course', type=str, default=None,
                        help='Specific course to upload (optional, uploads all if not specified)')
    parser.add_argument('--region', type=str, default='ap-south-1',
                        help='AWS region (default: ap-south-1)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be uploaded without actually uploading')
    parser.add_argument('--profile', type=str, default=None,
                        help='AWS profile to use (optional)')
    return parser.parse_args()


def setup_aws_client(region: str, profile: str = None):
    """Setup AWS S3 client with credentials."""
    try:
        if profile:
            session = boto3.Session(profile_name=profile)
            s3_client = session.client('s3', region_name=region)
        else:
            s3_client = boto3.client('s3', region_name=region)
        
        # Test credentials
        s3_client.list_buckets()
        return s3_client
    except NoCredentialsError:
        print("❌ AWS credentials not found. Please configure your AWS credentials:")
        print("   Option 1: aws configure")
        print("   Option 2: Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables")
        print("   Option 3: Use --profile flag with a configured AWS profile")
        sys.exit(1)
    except ClientError as e:
        print(f"❌ Error connecting to AWS: {e}")
        sys.exit(1)


def find_slack_dumps(base_path: Path, specific_course: str = None) -> Dict[str, List[Path]]:
    """Find all Slack dump files organized by course."""
    slack_dumps_dir = base_path / 'data-ingestion' / 'slack_dumps'
    
    if not slack_dumps_dir.exists():
        print(f"❌ Slack dumps directory not found: {slack_dumps_dir}")
        sys.exit(1)
    
    courses = {}
    
    # Get all course directories
    if specific_course:
        course_dirs = [slack_dumps_dir / specific_course]
        if not course_dirs[0].exists():
            print(f"❌ Course directory not found: {course_dirs[0]}")
            sys.exit(1)
    else:
        course_dirs = [d for d in slack_dumps_dir.iterdir() if d.is_dir()]
    
    for course_dir in course_dirs:
        course_name = course_dir.name
        json_files = sorted(course_dir.glob('*.json'))
        if json_files:
            courses[course_name] = json_files
            print(f"📁 Found {len(json_files)} files for {course_name}")
    
    return courses


def parse_date_from_filename(filename: str) -> Tuple[str, str, str]:
    """
    Extract year, month, day from filename (format: YYYY-MM-DD.json).
    
    This function defines the standard date parsing that should be consistent
    across all data ingestion pipelines.
    """
    date_part = filename.replace('.json', '')
    try:
        date_obj = datetime.strptime(date_part, '%Y-%m-%d')
        return date_obj.strftime('%Y'), date_obj.strftime('%m'), date_obj.strftime('%d')
    except ValueError:
        print(f"⚠️  Warning: Could not parse date from filename: {filename}")
        return None, None, None


def generate_s3_key(course_id: str, year: str, month: str, day: str, filename: str) -> str:
    """
    Generate S3 key with standard partitioning scheme.
    
    This function defines the canonical S3 path structure that should be used
    consistently across all data pipelines:
    - Historical data upload (this script)
    - Daily Slack API fetching (slack_pipeline.py)
    - DLT ingestion pipeline
    
    Pattern: raw/slack/{course_id}/year={YYYY}/month={MM}/day={DD}/{YYYY-MM-DD}.json
    """
    return f"raw/slack/{course_id}/year={year}/month={month}/day={day}/{filename}"


def upload_file_to_s3(s3_client, local_path: Path, bucket: str, s3_key: str, dry_run: bool = False) -> bool:
    """Upload a single file to S3."""
    if dry_run:
        print(f"  [DRY RUN] Would upload: {local_path.name} → s3://{bucket}/{s3_key}")
        return True
    
    try:
        s3_client.upload_file(str(local_path), bucket, s3_key)
        return True
    except ClientError as e:
        print(f"  ❌ Failed to upload {local_path.name}: {e}")
        return False


def verify_bucket_exists(s3_client, bucket: str) -> bool:
    """Verify that the S3 bucket exists and is accessible."""
    try:
        s3_client.head_bucket(Bucket=bucket)
        return True
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            print(f"❌ Bucket '{bucket}' does not exist")
        elif error_code == '403':
            print(f"❌ Access denied to bucket '{bucket}'. Check your IAM permissions.")
        else:
            print(f"❌ Error accessing bucket '{bucket}': {e}")
        return False


def main():
    args = parse_args()
    
    print(f"🚀 Historical Slack Dumps S3 Uploader")
    print(f"=" * 50)
    print(f"Bucket: {args.bucket}")
    print(f"Region: {args.region}")
    print(f"Dry run: {args.dry_run}")
    if args.course:
        print(f"Course filter: {args.course}")
    print(f"=" * 50)
    print()
    
    # Setup AWS client
    print("🔑 Setting up AWS client...")
    s3_client = setup_aws_client(args.region, args.profile)
    
    # Verify bucket exists
    if not args.dry_run:
        print(f"✓ Verifying bucket '{args.bucket}' exists...")
        if not verify_bucket_exists(s3_client, args.bucket):
            sys.exit(1)
        print("✓ Bucket verified")
    
    # Find Slack dump files
    print("\n📂 Scanning for Slack dump files...")
    base_path = Path.cwd()
    courses = find_slack_dumps(base_path, args.course)
    
    if not courses:
        print("❌ No Slack dump files found")
        sys.exit(1)
    
    # Upload files
    total_files = sum(len(files) for files in courses.values())
    print(f"\n📤 Starting upload of {total_files} files...")
    
    uploaded = 0
    failed = 0
    skipped = 0
    
    for course_name, files in courses.items():
        print(f"\n📚 Processing course: {course_name}")
        print(f"   Files to upload: {len(files)}")
        
        for file_path in files:
            filename = file_path.name
            year, month, day = parse_date_from_filename(filename)
            
            if not year:
                print(f"  ⚠️  Skipping {filename} (invalid date format)")
                skipped += 1
                continue
            
            # Generate S3 key using standard function
            s3_key = generate_s3_key(course_name, year, month, day, filename)
            
            # Upload file
            if upload_file_to_s3(s3_client, file_path, args.bucket, s3_key, args.dry_run):
                uploaded += 1
                if not args.dry_run:
                    print(f"  ✓ Uploaded: {filename}")
            else:
                failed += 1
    
    # Summary
    print(f"\n{'=' * 50}")
    print(f"📊 Upload Summary:")
    print(f"   Total files: {total_files}")
    print(f"   Uploaded: {uploaded}")
    print(f"   Failed: {failed}")
    print(f"   Skipped: {skipped}")
    
    if args.dry_run:
        print(f"\n⚠️  This was a DRY RUN. No files were actually uploaded.")
        print(f"   Remove --dry-run flag to perform actual upload.")
    
    if not args.dry_run and failed == 0 and skipped == 0:
        print(f"\n✅ All files uploaded successfully!")
        
        # Show the partition key structure for reference
        print(f"\n📍 Partition Key Structure:")
        print(f"   Pattern: raw/slack/{{course_id}}/year={{YYYY}}/month={{MM}}/day={{DD}}/{{YYYY-MM-DD}}.json")
        print(f"\n   Example paths created:")
        for course_name in list(courses.keys())[:2]:  # Show first 2 courses
            print(f"   s3://{args.bucket}/raw/slack/{course_name}/year=2023/month=06/day=15/2023-06-15.json")
        
        print(f"\n📝 This same partition structure will be used by:")
        print(f"   • Daily Slack API ingestion (slack_pipeline.py)")
        print(f"   • DLT bronze layer processing")
        print(f"   • Downstream analytics and ML pipelines")
    
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()