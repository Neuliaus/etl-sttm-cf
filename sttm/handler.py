import urllib.parse

import boto3
from dateutil.parser import parse


s3 = boto3.client('s3')


STTM_BUCKET = "aemo.sttm"
INPUT_FOLDER = "input"
PROCESSING_FOLDER = "processing"
DONE_FOLDER = "done"
ERROR_FOLDER = "error"
ATHENA_FOLDER = "athena"

FILE_TYPES = {
    "INT651": "STTM_INT651_ExAnteMarketPrice",
    "INT652": "STTM_INT652_ExAnteScheduleQuantity",
    "INT654": "STTM_INT654_ProvisionalMarketPrice",
    "INT690": "STTM_INT690_DeviationPriceData"
}


def move_file(src_bucket, src_key, dst_bucket, dst_key):
    print("Copying [%s] from [%s]" % (src_key, src_bucket))
    s3.copy({'Bucket': src_bucket, 'Key': src_key}, dst_bucket, dst_key)
    s3.delete_object(Bucket=src_bucket, Key=src_key)


def copy_file(src_bucket, src_key, dst_bucket, dst_key):
    print("Copying [%s] to [%s]" % (src_key, dst_key))
    s3.copy({'Bucket': src_bucket, 'Key': src_key}, dst_bucket, dst_key)


def s3_key_partition(file_type, year, month, day, file_name):
    key = "%s/%s/year=%s/month=%s/day=%s/%s" % (ATHENA_FOLDER, file_type, year, month, day, file_name)
    return key


def get_s3_key(state, file_type, file_name):
    key = "%s/%s/%s" % (state, file_type, file_name)
    return key


def parse_date(s, text=True, format="%Y-%m-%d"):
    """Convert text to date, if not found date return "".
    Args:
        s (string): text to parse date
        text (boolean): return datetime type or datetime in format text
        format (string): format text to return for date
    Returns:
        type: string or datetime
    """
    try:
        date_parsed = parse(s)
        if text:
            return date_parsed.strftime(format)
        else:
            return date_parsed
    except Exception as e:
        return ""


def process_file(input_key, file_type, file_name):
    """
    1. Move to processing_bucket
    2. Find date in the first line and copy file to correct key
    3. Move to done_bucket with partition
    """
    try:
        processing_key = get_s3_key(PROCESSING_FOLDER, file_type, file_name)
        done_key = get_s3_key(DONE_FOLDER, file_type, file_name)
        error_key = get_s3_key(ERROR_FOLDER, file_type, file_name)

        # move file to processing
        move_file(STTM_BUCKET, input_key, STTM_BUCKET, processing_key)
        obj = s3.get_object(Bucket=STTM_BUCKET, Key=processing_key)
        data = obj['Body'].read().decode('utf-8')

        # check first line for: gas_date
        lines = data.splitlines()

        if lines[0].startswith("gas_date"):
            line = lines[1]
            fields = line.split(",")
            date = parse_date(fields[0])
            if date:
                year, month, day = date.split("-")
                athena_key = s3_key_partition(file_type, year, month, day, file_name)
                copy_file(STTM_BUCKET, processing_key, STTM_BUCKET, athena_key)
                move_file(STTM_BUCKET, processing_key, STTM_BUCKET, done_key)
                return

        move_file(STTM_BUCKET, processing_key, STTM_BUCKET, error_key)
    except Exception as e:
        print (e)
        move_file(STTM_BUCKET, processing_key, STTM_BUCKET, error_key)


def handler(event, context):
    try:
        print("Object added to: [%s]" % (event['Records'][0]['s3']['bucket']['name'],))
        key = event['Records'][0]['s3']['object']['key']
        key = urllib.parse.unquote_plus(key, encoding='utf-8', errors='replace')

        keys = key.split("/")
        file_name = keys[-1]
        file_type = key[-2]
        if file_name[:6].upper() not in FILE_TYPES.keys():
            move_file(STTM_BUCKET, key, STTM_BUCKET, ERROR_FOLDER+"/wrong_format/"+key)
            return
        else:
            if file_type not in FILE_TYPES.values():
                file_type = FILE_TYPES[file_name[:6].upper()]

    except Exception as e:
        print(e)
        # error_key = get_s3_key(ERROR_FOLDER, file_type, file_name)
        move_file(STTM_BUCKET, key, STTM_BUCKET, ERROR_FOLDER+"/"+key)
        return

    print("Processing: ", key)
    process_file(key, file_type, file_name)





# key = "input/STTM_INT651_ExAnteMarketPrice/int651_v1_ex_ante_market_price_rpt_1~20150622120102.csv"
# key = "input/STTM_INT690_DeviationPriceData/int690_v1_deviation_price_data_rpt_1~20150622133826.csv"
#
# event = {
#     "Records": [
#         {
#             "s3": {
#                 "object": {
#                     "key": key
#                 },
#                 "bucket": {
#                     "name": STTM_BUCKET
#                 }
#             }
#         }
#     ]
# }
#
#
# handler(event, None)
