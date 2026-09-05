"""Focused live S3 acceptance; preserve fixtures to verify reads across service restarts."""
import hashlib
import json
import os
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

runtime = Path(os.environ['FINAI_RUNTIME_ROOT'])
config = json.loads((runtime / 'local.json').read_text(encoding='utf-8-sig'))
client = boto3.client('s3', endpoint_url=config['FINAI_S3_ENDPOINT'],
                      aws_access_key_id=config['FINAI_S3_ACCESS_KEY'],
                      aws_secret_access_key=config['FINAI_S3_SECRET_KEY'],
                      region_name=config['FINAI_S3_REGION'])
bucket = config['FINAI_S3_BUCKET']
client.head_bucket(Bucket=bucket)
assert client.get_bucket_versioning(Bucket=bucket)['Status'] == 'Enabled'
fixture = runtime / 'artifacts' / 'minio-lifecycle-fixture.json'
if not fixture.exists():
    payload = ('G8 local immutable evidence storage smoke ' + str(uuid.uuid4())).encode()
    key = 'runtime-verification/' + hashlib.sha256(payload).hexdigest()
    uploaded = client.put_object(Bucket=bucket, Key=key, Body=payload, IfNoneMatch='*')
    assert uploaded.get('VersionId') not in (None, '', 'null')
    fixture.write_text(json.dumps({'key': key, 'sha256': hashlib.sha256(payload).hexdigest(),
                                   'version_id': uploaded['VersionId']}), encoding='utf-8')
record = json.loads(fixture.read_text(encoding='utf-8'))
read = client.get_object(Bucket=bucket, Key=record['key'], VersionId=record['version_id'])
assert hashlib.sha256(read['Body'].read()).hexdigest() == record['sha256']
try:
    client.put_object(Bucket=bucket, Key=record['key'], Body=b'replacement must fail', IfNoneMatch='*')
    raise AssertionError('Conditional overwrite was accepted')
except ClientError as error:
    assert error.response['ResponseMetadata']['HTTPStatusCode'] == 412
try:
    client.delete_object(Bucket=bucket, Key=record['key'], VersionId=record['version_id'])
    raise AssertionError('Runtime credentials were allowed to delete evidence')
except ClientError as error:
    assert error.response['ResponseMetadata']['HTTPStatusCode'] == 403
print('PASS: versioned read/hash, conditional overwrite rejection, and runtime delete denial; retained fixture supports restart verification.')
