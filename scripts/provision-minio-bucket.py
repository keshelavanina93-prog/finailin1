"""Provision only the local versioned evidence bucket using isolated admin credentials."""
import json
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

runtime = Path(os.environ['FINAI_RUNTIME_ROOT'])
admin = json.loads((runtime / 'minio-admin.json').read_text(encoding='utf-8-sig'))
client = boto3.client('s3', endpoint_url='http://127.0.0.1:9061',
                      aws_access_key_id=admin['accessKey'], aws_secret_access_key=admin['secretKey'],
                      region_name='us-east-1')
bucket = 'g8-evidence'
try:
    client.head_bucket(Bucket=bucket)
except ClientError as error:
    if error.response['ResponseMetadata']['HTTPStatusCode'] != 404:
        raise
    client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={'Status': 'Enabled'})
# No default deletion/expiration lifecycle. Application credentials cannot delete versions.
assert client.get_bucket_versioning(Bucket=bucket)['Status'] == 'Enabled'
assert client.get_object_lock_configuration(Bucket=bucket)['ObjectLockConfiguration']['ObjectLockEnabled'] == 'Enabled'
print('Local evidence bucket verified: versioning and object-lock capability enabled.')
