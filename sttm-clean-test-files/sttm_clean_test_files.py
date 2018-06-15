# -*- coding: utf-8 -*-
# https://stackoverflow.com/questions/40383470/can-i-force-cloudformation-to-delete-non-empty-s3-bucket
# @Author: foamdino
# @Email: foamdino@gmail.com
# Modified by: Dex

import json
import boto3
import botocore
from botocore.vendored import requests
import time

s3 = boto3.resource('s3')
athena = boto3.client('athena')


def check_result(queryid):
    """
    Make sure an athena query finishes
    Args:
        ueryid (string): the id of a query
    """
    while True:
        response = athena.get_query_execution(QueryExecutionId=queryid)
        state = response['QueryExecution']['Status']['State']
        if state in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
            return
        else:
            print('wait...')
            time.sleep(0.5)


def can_access_bucket(bucket):
    try:
        s3.meta.client.head_bucket(Bucket=bucket.name)
        return True
    except botocore.exceptions.ClientError as e:
        # If a client error is thrown, then check that it was a 404 error.
        # If it was a 404 error, then the bucket does not exist.
        error_code = int(e.response['Error']['Code'])
        if error_code == 403:
            print("Private Bucket. Forbidden Access!")
        elif error_code == 404:
            print("Bucket Does Not Exist!")
        return False


def delete_bucket(bucket_del):
    """
    Deletes a bucket
    Args:
        bucket_del(object): the bucket to be deleted
    """
    if bucket_del and can_access_bucket(bucket_del):
        print("Start deleting test bucket")
        bucket_del.objects.all().delete()
        bucket_del.delete()
        print("Bucket cleaned")


def delete_db(database_name, bucketName):
    """
    Deletes a db and all of its tabels if any
    Args:
        database_name(string): the name of the database to be deleted
        bucketName(string): the name of the bucket that stores athena log
    """

    sql_show = f'SHOW TABLES IN {database_name}'
    config = {'OutputLocation': f's3://{bucketName}/cleanDB', 'EncryptionConfiguration': {'EncryptionOption': 'SSE_S3'}}
    queryid = athena.start_query_execution(
        QueryString=sql_show, ResultConfiguration=config)['QueryExecutionId']
    check_result(queryid)

    try:
        # show the tables in the database
        results = athena.get_query_results(QueryExecutionId=queryid)
    except Exception as e:
        print(f"Cannot find the db: {e}")
    else:
        # if the database contains tables, delete all of them
        if 'ResultSet' in results:
            if 'Rows' in results['ResultSet']:
                print(f"Start cleaning DB {database_name}")
                for i in results['ResultSet']['Rows']:
                    tablename = i['Data'][0]['VarCharValue']
                    sql_table = f"DROP TABLE {database_name}.{tablename}"
                    queryid_table = athena.start_query_execution(
                        QueryString=sql_table, ResultConfiguration=config)['QueryExecutionId']
                    check_result(queryid_table)
                    print(f"TABLE {tablename} cleaned")

    sql_db = f"DROP DATABASE IF EXISTS {database_name}"
    queryid_db = athena.start_query_execution(
        QueryString=sql_db, ResultConfiguration=config)['QueryExecutionId']
    check_result(queryid_db)
    print(f"Database {database_name} cleaned")


def handler(event, context):
    """
    This handler deletes the bucket and database generated in the test stage
   
    Args:
      event (dict): the aws event that triggered the lambda
      context (dict): the aws context the lambda runs under
    """
    try:
        print(f"Request Type: {event['RequestType']}")
        # if this lambda is trigger in the cloudformation at the purpose of create
        if event['RequestType'] == "Create":
            bucketName = event['ResourceProperties']['BucketName']
            logbucketName = bucketName + ".log"
            bucket = s3.Bucket(bucketName)
            logbucket = s3.Bucket(logbucketName)

            database_name = event['ResourceProperties']['DatabaseName']
            print("Start cleaning test files")

            delete_db(database_name.replace("-", "_"), bucketName)

            # delete the main test bucket
            print("bucketName: " + bucketName)
            delete_bucket(bucket)

            # delete the test bucket for stroing athena logs
            print("logbucketName: " + logbucketName)
            delete_bucket(logbucket)
        # this lambda will be triggered when it's deleted in the cloudformation
        sendResponseCfn(event, context, "SUCCESS")
    except Exception as e:
        print(e)
        sendResponseCfn(event, context, "FAILED")


def sendResponseCfn(event, context, responseStatus):
    response_body = {'Status': responseStatus,
                     'Reason': 'Log stream name: ' + context.log_stream_name,
                     'PhysicalResourceId': context.log_stream_name,
                     'StackId': event['StackId'],
                     'RequestId': event['RequestId'],
                     'LogicalResourceId': event['LogicalResourceId'],
                     'Data': json.loads("{}")}

    requests.put(event['ResponseURL'], data=json.dumps(
        response_body).encode("utf8"))
