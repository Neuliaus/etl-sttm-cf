import re
import sys
if sys.version_info[0] < 3:
    from StringIO import StringIO
else:
    from io import StringIO

import csv
import datetime
import urllib.parse

import boto3
import pandas as pd
from dateutil.parser import parse



s3 = boto3.client('s3')

INPUT_FOLDER = "input"
PROCESSING_FOLDER = "processing"
DONE_FOLDER = "done"
ERROR_FOLDER = "error"
ATHENA_FOLDER = "athena"


FILE_TYPES = {
    "INT651": {
        "table_name": "STTM_INT651_ExAnteMarketPrice",
        "params": {
            "parse_dates": ["gas_date", "approval_datetime", "report_datetime"],
            "dayfirst": True
        }
    },
    "INT652": {
        "table_name": "STTM_INT652_ExAnteScheduleQuantity",
        "params": {
            "parse_dates": ["gas_date", "approval_datetime", "report_datetime"],
            "dayfirst": True
        }
    },
    "INT654": {
        "table_name": "STTM_INT654_ProvisionalMarketPrice",
        "params": {
            "parse_dates": ["gas_date", "report_datetime"],
            "dayfirst": True
        }
    },
    "INT690": {
        "table_name": "STTM_INT690_DeviationPriceData",
        "params": {
            "parse_dates": ["gas_date", "last_update_datetime", "report_datetime"],
            "dayfirst": True
        }
    },
}

TABLES_NAME = [FILE_TYPES[key]["table_name"] for key in FILE_TYPES]




def move_file(src_bucket, src_key, dst_bucket, dst_key):
    print("Copying [%s] from [%s]" % (src_key, src_bucket))
    s3.copy({'Bucket': src_bucket, 'Key': src_key}, dst_bucket, dst_key)
    s3.delete_object(Bucket=src_bucket, Key=src_key)


def copy_file(src_bucket, src_key, dst_bucket, dst_key):
    print("Copying [%s] to [%s]" % (src_key, dst_key))
    s3.copy({'Bucket': src_bucket, 'Key': src_key}, dst_bucket, dst_key)


def get_object(bucket, key):
    return s3.get_object(Bucket=bucket, Key=key)


def put_file(bucket, key, body):
    print("Put file [%s] to [%s]" % (key, bucket))
    return s3.put_object(Bucket=bucket, Key=key, Body=body)
    print("Finish put file [%s] to [%s]" % (key, bucket))


def s3_key_partition(file_type, year, month, day, file_name):
    key = "%s/%s/year=%s/month=%s/day=%s/%s" % (ATHENA_FOLDER, file_type, year, month, day, file_name)
    return key


def get_s3_key(state, file_type, file_name):
    key = "%s/%s/%s" % (state, file_type, file_name)
    return key


def parse_date(s, text=True, format="%Y-%m-%d"):
    """
    112	 yyyymmdd
    103	 dd/mm/yyyy
    """
    s = s.strip()

    if len(s) < 8:
        return date.split("-")
    try:
        s_num = float(s)
        if s_num < 0:
            return ""
    except:
        pass

    if re.search("^\d{8}$", s):
        return (s[:4], s[4:6], s[6:])
    if re.search("^\d{2}/\d{2}/\d{4}$", s):
        return (s[6:], s[3:5], s[:2])

    date = datetime.datetime.now().strftime(format)

    return date.split("-")


def process_file(file_name, data, params):
    """
    """
    try:
        df = pd.read_csv(data, **params)
        df["source_file_id"] = file_name
        df["added_dttm"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return df.to_csv(index=False)
    except Exception as e:
        print (e)
        return False


def handler(event, context):
    try:
        print("Object added to: [%s]" % (event['Records'][0]['s3']['bucket']['name'],))
        key = event['Records'][0]['s3']['object']['key']
        bucket = event['Records'][0]['s3']['bucket']['name']

        key = urllib.parse.unquote_plus(key, encoding='utf-8', errors='replace')

        keys = key.split("/")
        file_name = keys[-1]
        if file_name == "":
            return

        file_type = key[-2]

        if file_name[:6].upper() not in FILE_TYPES.keys():
            print ("wrong_format")
            move_file(bucket, key, bucket, bucket+"/wrong_format/"+key)
            return
        else:
            if file_type not in TABLES_NAME:
                file_type = FILE_TYPES[file_name[:6].upper()]["table_name"]

        params = FILE_TYPES[file_name[:6].upper()]["params"]

        print("Processing: ", key)

        input_key = key
        processing_key = get_s3_key(PROCESSING_FOLDER, file_type, file_name)
        done_key = get_s3_key(DONE_FOLDER, file_type, file_name)
        error_key = get_s3_key(ERROR_FOLDER, file_type, file_name)

        # move file to processing
        move_file(bucket, input_key, bucket, processing_key)

        # get file from processing bucket
        obj = get_object(bucket, processing_key)
        data = obj['Body'].read().decode('utf-8', 'ignore')
        data = StringIO(data)

        output = process_file(file_name, data, params)

        if not output:
            move_file(bucket, processing_key, bucket, error_key)
            print ("Error empty output ", (file_name))
            return
        try:
            date_filename = re.findall("\d{14}", file_name)
            date_found = date_filename[0][:8]
        except:
            date_found = ""
        year, month, day = parse_date(date_found)

        athena_key = s3_key_partition(file_type, year, month, day, file_name)

        put_file(bucket, athena_key, output)
        move_file(bucket, processing_key, bucket, done_key)

        print ("Finish ", (file_name))

    except Exception as e:
        print (e)
