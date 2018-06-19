# -*- coding: utf-8 -*-
# @Author: foamdino
# @Email: foamdino@gmail.com
# Modified by: Dex

import boto3
import os
import json
import cfnresponse3
import cfnresponse
import botocore
from botocore.vendored import requests
import time

s3 = boto3.client('s3')
athena = boto3.client('athena', region_name='ap-southeast-2')

json_file = "schemas.json"


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


def check_msck_file(stack_name, db_bucket, msck_key):
    """
    Check if the msck_file for this bucket already exists
    returns:
      - ('ok', True) when file exists
      - ('ok', False) when file doesn't exist
      - ('fail', None) when there is an error
    """
    try:
        print(f"Checking: {db_bucket}, {msck_key}")
        s3.head_object(Bucket=db_bucket, Key=msck_key)
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == "404":
            print("msck file does not exist")
            return ('ok', False)
        else:
            print(e)
            return ('fail', None)
    else:
        print("msck file exists")
        return ('ok', True)


def msck_repair(db_bucket, table_name, database_name, msck_key, config):
    """
    Load partition
    Args:
      db_bucket (string): the name of the database that stores athena logs
      table_name (string): the name of the table that needs partition
      stack_name (string): the name of the cloudformation stack
      msck_key (string): the key of the msck file
      config (dict): athena config
    """

    sql = 'MSCK REPAIR TABLE ' + table_name
    context = {'Database': database_name}
    print(f"MSCK: {sql}")
    queryid = athena.start_query_execution(
        QueryString=sql, QueryExecutionContext=context, ResultConfiguration=config)['QueryExecutionId']
    check_result(queryid)
    print("msck finished")
    # write msck file to db bucket
    try:
        s3.put_object(Bucket=db_bucket, Key=msck_key,
                      Body="MSCK completed for %s" % (db_bucket,))
    except Exception as e:
        print(f"Error: {e} Unable to write msck file - msck command will run again")


def create_table(database_name, from_bucket, stack_name, pre, schemas, config):
    """
    Use athena to create tables, then check if the msck_file exits, if not, load partition
    Args:
      database_name (string): the name of the database
      from_bucket (string): the name of the main bucket
      stack_name (string): the name of the cloudformation stack
      pre (string): one of the four output names
      schemas (list): schemas and their types
      config (dict): athena config
    """

    db_bucket = from_bucket + ".log"
    print(f"Creating table in {database_name}")

    schemas_type = [" ".join((schema['name'], schema['type']))
                    for schema in schemas]
    sql_schemas_type = ", ".join(schemas_type)
    table_name = f"{pre}_{stack_name.replace('-','_')}"
    sql = f"CREATE EXTERNAL TABLE IF NOT EXISTS {database_name}.{table_name} ({sql_schemas_type}) PARTITIONED BY (retailer string) ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe'WITH SERDEPROPERTIES ('serialization.format' = ',','field.delim' = ',' , 'quoteChar' = '\"')LOCATION 's3://{from_bucket}/athena/{pre}/'TBLPROPERTIES ('has_encrypted_data'='false','skip.header.line.count'='1', )"
    print(f"sql: {sql}")
    queryid = athena.start_query_execution(QueryString=sql,
                                           ResultConfiguration=config)['QueryExecutionId']
 
    check_result(queryid)
    print(f"Table created: {database_name}.{table_name}")

    msck_key = f"msck-completed-files/{stack_name}-msck-completed-{table_name}.txt"
    # check if msck file exists
    msck_result = check_msck_file(stack_name, db_bucket, msck_key)
    if msck_result[0] == 'ok' and not msck_result[1]:
        # do the partition
        msck_repair(db_bucket, table_name,
                    database_name, msck_key, config)
    elif msck_result[0] == 'ok' and msck_result[1]:
        print("Msck file exists")
    elif msck_result[0] == 'fail':
        print(
            "unable to msck/partition due to error checking if msck file exists")


def create_db(from_bucket, database_name, stack_name):
    """
    Use athena to create database and triggers the function to create tables
    Args:
      from_bucket (string): the name of the main bucket
      database_name (string): the name of the database
      stack_name (string): the name of the cloudformation stack
    """
    db_bucket = from_bucket + ".log"
    config = {
        'OutputLocation': 's3://' + db_bucket + '/' + database_name.replace('_', '-'),
        'EncryptionConfiguration': {'EncryptionOption': 'SSE_S3'}
    }
    sql = 'CREATE DATABASE IF NOT EXISTS ' + database_name
    queryid = athena.start_query_execution(QueryString=sql,
                                           ResultConfiguration=config)['QueryExecutionId']
    check_result(queryid)
    print("DATABASE created, start creating TABLES")

    # load the schemas and the schema types from a json config file
    with open(json_file) as f:
        data = json.load(f)
    # create tables based on json info
    for pre in data:
        create_table(database_name, from_bucket, stack_name, pre, data[pre], config)
    print("All TABLES created")


def handler(event, context):
    """
    This handler:
      1. Creates a database and tables within the database.
      2. Checks if the msck files of the tables exist, if not, loads partition.

    Args:
      event (dict): the aws event that triggered the lambda
      context (dict): the aws context the lambda runs under
    """
    # the data send back to the cloudformation
    response_data = {}
    stack_name = os.environ['StackName']
    try:
        print(f"Request Type: {event['RequestType']}")
        stack_name = os.environ['StackName']
        # athena db name cannot contain hyphens
        database_name = os.environ['DatabaseName'].replace('-', '_')
        print("stack_name: " + stack_name)
        print("database_name: " + database_name)
        print(event)
        from_bucket = os.environ['FromBucketName']
        # if this lambda is trigger in the cloudformation at the purpose of
        # create
        if event['RequestType'] == "Create":
            create_db(from_bucket, database_name, stack_name)
            response_data['Success'] = 'Create database and tables complete'
            cfnresponse3.send(event, context, cfnresponse3.SUCCESS,
                              None, response_data, stack_name)
        else:
            # this lambda will be triggered when it's deleted in the
            # cloudformation
            sendResponseCfn(event, context, "SUCCESS")
    except Exception as e:
        print(e)
        response_data['Failure'] = 'Create database or table failed'
        cfnresponse3.send(event, context, cfnresponse3.FAILED,
                          None, response_data, stack_name)
