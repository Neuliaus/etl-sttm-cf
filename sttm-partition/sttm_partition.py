# @Author: foamdino
# @Email: foamdino@gmail.com
# Modified by Dex
"""
This lambda handles the CREATE TABLE command, the initial MSCK command
and the ALTER TABLE ADD PARTITION command.
"""
import time
import boto3
import botocore
import os
from datetime import datetime, timedelta


s3 = boto3.client('s3')
athena = boto3.client('athena', region_name='ap-southeast-2')


def check_partition(func):
    def _decorator(stack_name, database_name, from_bucket, file_key):
        file_path = '/'.join(file_key.split('/')[0:-1])
        result = client.list_objects(Bucket=from_bucket, Prefix=file_path)
        file_nums = len(result['Contents'])
        print(f"Amount of files under {file_path}: {file_nums}")
        if file_nums == 1:
            partition(stack_name, database_name, from_bucket, file_key)
        else:
            print("No need for partition")

    return _decorator


@check_partition
def partition(stack_name, database_name, from_bucket, file_key):
    """
    Run ALTER TABLE command
    Args:
      stack_name (string): name of the cloud formation stack to differentiate between test and production
      database_name (string): name of the athena database
      from_bucket (string): name of the bucket which the input file originated from
      parsed_time (datetime): datetime created by parsing the input filename, used in the partition command

    Returns:
      nothing
    """
    print("Adding partition...")
    key_parts = file_key.split("/")
    table_name = key_parts[1]
    day = key_parts[-2]
    month = key_parts[-3]
    year = key_parts[-4]

    logbucket_name = from_bucket.replace("_", "-") + '.log'
    print("using: " + logbucket_name)

    config = {
        'OutputLocation': 's3://' + logbucket_name + '/' + database_name.replace('_', '-'), ,
        'EncryptionConfiguration': {'EncryptionOption': 'SSE_S3'}
    }

    # Query Execution Parameters
    sql = f"ALTER TABLE {database_name}.{table_name}_{stack_name.replace('-','_')} ADD PARTITION ({year},{month},{day})"
    print(f'Partition sql: {sql}')
    context = {'Database': database_name}
    s3.start_query_execution(QueryString=sql,
                             QueryExecutionContext=context,
                             ResultConfiguration=config)
    print("Partition added")


def handler(event, context):
    """
    Standard aws lambda handler function

    Args:
      event (dict): the aws event that triggered the lambda
      context (dict): the aws context the lambda runs under
    """
    print(event['Records'][0]['s3']['object']['key'])
    stack_name = os.environ['StackName']
    database_name = os.environ['DatabaseName'].replace('-', '_')
    print("stack_name: %s" % (stack_name),)
    from_bucket = event['Records'][0]['s3']['bucket']['name']
    print("from_bucket: %s" % (from_bucket,))
    filekey = event['Records'][0]['s3']['object']['key'].replace("%3D", "=")
    print("filekey: %s" % (filekey,))
    filename = filekey.split('/')[-1]
    print("filename: %s" % (filename,))

    # need to add partition no matter it's the first input file or not
    partition(stack_name, database_name, from_bucket, filekey)
