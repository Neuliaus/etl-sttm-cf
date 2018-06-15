# -*- coding: utf-8 -*-
# @Author: foamdino
# @Email: foamdino@gmail.com
# Modified by: Dex
import json
import boto3
import botocore
from botocore.vendored import requests

s3 = boto3.resource('s3')
client = boto3.client('s3')


def can_access_bucket(bucket):
    """
    Check if the bucket exists and if it is accessible by this account
    returns:
      - True when bucket exists and is accessible
      - False when bucket doesn't exist or cannot be accessed
    """
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


def createfolders(bucketName):
    """
    Create folders under a bucket
    Args:
      bucketName (string): the name of the main bucket
      sourceName (string): the name of the retailer
    """
    client.put_object(Bucket=bucketName, Key=f'in/')
    client.put_object(Bucket=bucketName, Key=f'processing/')
    client.put_object(Bucket=bucketName, Key=f'done/')
    client.put_object(Bucket=bucketName, Key=f'athena/STTM_INT651_ExAnteMarketPrice/')
    client.put_object(Bucket=bucketName, Key=f'athena/STTM_INT652_ExAnteScheduleQuantity/')
    client.put_object(Bucket=bucketName, Key=f'athena/STTM_INT654_ProvisionalMarketPrice/')
    client.put_object(Bucket=bucketName, Key=f'athena/STTM_INT690_DeviationPriceData/')
    client.put_object(Bucket=bucketName, Key=f'error/')


def sendResponseCfn(event, context, responseStatus):
    """
    Send the correctly formatted response_data for cloudformation to know that this lambda has succeeded or failed.

    Args:
      event (dict): the aws event that triggered the lambda
      context (dict): the aws context the lambda runs under
      responseStatus (string): SUCCESS or FAILED
    Returns:
      nothing
    """
    response_body = {'Status': responseStatus,
                     'Reason': 'Log stream name: ' + context.log_stream_name,
                     'PhysicalResourceId': context.log_stream_name,
                     'StackId': event['StackId'],
                     'RequestId': event['RequestId'],
                     'LogicalResourceId': event['LogicalResourceId'],
                     'Data': json.loads("{}")}

    requests.put(event['ResponseURL'], data=json.dumps(
        response_body).encode("utf8"))


def handler(event, context):
    """
    This handler:
      1. Checks the S3 bucket name
      2. If s3 bucket already exists, logs + returns quickly
         Else Creates the S3 bucket with the correct configuration
      3. Creates folders

    Args:
      event (dict): the aws event that triggered the lambda
      context (dict): the aws context the lambda runs under
    """
    try:
        print(f"Request Type: {event['RequestType']}")
        # if this lambda is trigger in the cloudformation at the purpose of
        # create
        if event['RequestType'] == "Create":
            bucketName = event['ResourceProperties']['BucketName']
            logbucketName = bucketName + ".log"
            bucket = s3.Bucket(bucketName)
            print("bucketName: " + bucketName)

            log_bucket = s3.Bucket(logbucketName)
            print("log bucket: " + logbucketName)

            if not log_bucket or not can_access_bucket(log_bucket):
                # create the bucket for storing athena logs
                s3.create_bucket(Bucket=logbucketName, CreateBucketConfiguration={
                    'LocationConstraint': 'ap-southeast-2'})

            if bucket and can_access_bucket(bucket):
                print("Bucket %s already exists, skipping creation" %
                      (bucketName,))
                sendResponseCfn(event, context, "SUCCESS")
                return

            print("start creating bucket")
            # create the main bucket
            s3.create_bucket(Bucket=bucketName, CreateBucketConfiguration={
                             'LocationConstraint': 'ap-southeast-2'})

            # set lambda NotificationConfiguration
            config = {
                'LambdaFunctionConfigurations': [
                    {
                        'LambdaFunctionArn': event['ResourceProperties']['InputFn1'],
                        'Events': [
                            's3:ObjectCreated:*',
                        ],
                        'Filter': {
                            'Key': {
                                'FilterRules': [
                                    {
                                        'Name': 'prefix',
                                        'Value': 'in'
                                    },
                                ]
                            }
                        }
                    },
                    {
                        'LambdaFunctionArn': event['ResourceProperties']['DoneFn'],
                        'Events': [
                            's3:ObjectCreated:*',
                        ],
                        'Filter': {
                            'Key': {
                                'FilterRules': [
                                    {
                                        'Name': 'prefix',
                                        'Value': 'athena'
                                    },
                                ]
                            }
                        }
                    }
                ]
            }

            client.put_bucket_notification_configuration(
                Bucket=bucketName, NotificationConfiguration=config)

            # create folders, please set the directories accordingly
            createfolders(bucketName)

        # this lambda will be triggered when it's deleted in the cloudformation
        sendResponseCfn(event, context, "SUCCESS")
    except Exception as e:
        print(e)
        sendResponseCfn(event, context, "FAILED")
