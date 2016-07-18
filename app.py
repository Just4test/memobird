import os
import sys
from flask import Flask, redirect, request, g, url_for, render_template, send_file, jsonify
import requests
import base64
import sqlite3
from uuid import uuid1
from util import *
from random import random
from datetime import datetime
import json
from PIL import Image
import cloudconvert

####################处理参数################

ak = os.environ.get('MEMOBIRD_AK')
if ak:
    print('Read access key from env.')
cloudconvert_key = os.environ.get('CLOUDCONVERT_KEY')
if cloudconvert_key:
    print('Read cloudconvert key from env.')

arg = None
argi = 0
def next_arg():
    global argi, arg
    argi = argi + 1
    if argi >= len(sys.argv):
        arg = None
        return None
    arg = sys.argv[argi]
    return arg
    
while next_arg() is not None:
    if '--ak' == arg:
        ak = next_arg()
        print('Set access key by args.')
    elif '--cloudconvert' == arg:
        cloudconvert_key = next_arg()
        print('Set cloudconvert key by args.')
    else:
        print('Unknown argument {}'.format(arg))
        exit(1)
        
if not ak:
    print('Haven`t give access key.')
    exit(1)
if not cloudconvert_key:
    print('Haven`t give cloudconvert key.')
    exit(1)
cloudconvert_api = cloudconvert.Api(cloudconvert_key)

AUTH_TIMEOUT = 60

def create_db_connection():
    return sqlite3.connect('data.db')

print('Check database...')
conn = create_db_connection()
c = conn.cursor()
result = c.execute('SELECT name FROM sqlite_master WHERE type="table" ORDER BY name').fetchall()
    
if ('device',) not in result:
    print('Creat table "device"...')
    sql = 'create table device (device_id varchar(32) primary key not null,' + \
    'bind_id integer not null,' + \
    'auth integer not null, auth_time real not null)'
    c.execute(sql)

if ('token',) not in result:
    print('Creat table "token"...')
    
    sql = 'create table token (token varchar(36) primary key not null,' + \
    'device_id varchar(32) not null,' + \
    'passwd varchar(32))'
    c.execute(sql)
    
conn.commit()    
conn.close()

print('Start server...')
app = Flask(__name__)
app.debug = True
app.config.update(
    conn = conn
)

@app.route('/')
def index():
    info = {
        'info': 'Welecome. You can create device by post /device, and create an token, and print by token.',
        'create_device_url': url_for('create_device')
    }
    return jsonify(info)
    
def update_device_auth(device_id, conn):
    c = conn.cursor()
    auth = int(random() * 100000)
    auth_time = datetime.now()
    c.execute('update device set auth = ?, auth_time = ? where device_id = ?', (auth, auth_time.timestamp(), device_id))
    conn.commit()
    return auth, auth_time
    
@app.route('/device', methods = ['POST'])
def create_device():
    '将一个设备添加到系统中'
    device_id = request.values.get('device_id')
    if not device_id:
        info = {
            'info':'Can`t find device_id in form'
        }
        return jsonify(info), 400
        
    paper = Paper()
    conn = create_db_connection()
    c = conn.cursor()
    result = c.execute('select bind_id, auth, auth_time from device where device_id = ?', (device_id,)).fetchall()
    
    if len(result) == 1:
        bind_id = result[0][0]
        auth = result[0][1]
        print(result[0][2])
        auth_time = datetime.fromtimestamp(result[0][2])
        print(auth_time)
        paper.append_txt('Your device is already bound.')
        # 如果auth的更新时间超过AUTH_TIMEOUT，则更新auth
        if (datetime.now() - auth_time).total_seconds() > AUTH_TIMEOUT:
            auth, auth_time = update_device_auth(device_id, conn)
            paper.append_txt('Auth updated.')
    else:
        bind_id, r = bind_device(ak, device_id)
        if not bind_id:
            if r.status_code == 200 and r.json().get('showapi_res_code') == 2:
                info = {
                    'info': 'device_id invalid.'
                }
                return jsonify(info), 400
            elif r.status_code >= 500:
                info = {
                    'info': 'Can`t bind device. Memobird API status code {}. AccessKey may invalid.'.format(r.status_code)
                }
                return jsonify(info), 500
            else:
                info = {
                    'info': 'Can`t bind device. Memobird API status code {}.'.format(r.status_code),
                    'api_result': r.text
                }
                return jsonify(info), 400
                
        
        auth = int(random() * 100000)
        c.execute('insert into device(device_id, bind_id, auth, auth_time) values(?, ?, 0, 0)', (device_id, bind_id))
        auth, auth_time = update_device_auth(device_id, conn)
        paper.append_txt('Bind device success.')
    
    paper.append_txt('Your auth is {}, will timeout in {} seconds.'.format(auth, AUTH_TIMEOUT - int((datetime.now() - auth_time).total_seconds())))
    paper.append_txt('Scan QR code to manage your device:')
    manage_url = url_for('manage_device', device_id = device_id, auth = auth, _external=True)
    paper.append_qrcode(manage_url)
    print_paper(ak, device_id, bind_id, paper)
    info = {
        'info': 'Bind success. Manage URL has sent to your divice.'
    }
    return jsonify(info)
    
def check_device_auth(request, device_id, c):
    '检查auth是否匹配。如果正确匹配，不返回值。否则返回错误响应。'
    auth = request.values.get('auth')
    
    if not auth:
        info = {
            'info':'auth is not given'
        }
        return jsonify(info), 400
        
    result = c.execute('select * from device where device_id = ? and auth = ?', (device_id, auth)).fetchall()
    
    if len(result) != 1:
        info = {
            'info': 'Device_id do not match auth.'
        }
        return jsonify(info), 400

def get_device_token(device_id, c):
    result = c.execute('select token, passwd from token where device_id = ?', (device_id,)).fetchall()
    print(result)
    token = result[0][0]
    passwd = result[0][1]
    print('token, passwd', token, passwd)
    return [{
        'token': token,
        'passwd_protect': bool(passwd),
        'url': url_for('print_by_token', token = token, passwd = passwd and '{passwd}', _external=True)
    } for token, passwd in result]

@app.route('/device/<device_id>', methods = ['GET'])
def manage_device(device_id):
    '返回设备的状态'
    conn = create_db_connection()
    c = conn.cursor()
    
    temp = check_device_auth(request, device_id, c)
    if temp:
        return temp
    
    url_base = request.base_url.split('/device')
    info = {
        'tokens': get_device_token(device_id, c)
    }
    return jsonify(info)

@app.route('/device/<device_id>', methods = ['DELETE'])
def delete_device(device_id):
    '删除设备和所有token'
    conn = create_db_connection()
    c = conn.cursor()
    
    temp = check_device_auth(request, device_id, c)
    if temp:
        return temp
    
    c.execute('delete from token where device_id = ?', (device_id,))
    c.execute('delete from device where device_id = ?', (device_id,))
    conn.commit()
    return '', 204

@app.route('/device/<device_id>/token', methods = ['GET'])
def list_token(device_id):
    '返回设备的token列表'
    conn = create_db_connection()
    c = conn.cursor()
    
    temp = check_device_auth(request, device_id, c)
    if temp:
        return temp
    
    return jsonify(get_device_token(device_id, c))

@app.route('/device/<device_id>/token', methods = ['POST'])
def create_token(device_id):
    '创建token'
    conn = create_db_connection()
    c = conn.cursor()
    
    temp = check_device_auth(request, device_id, c)
    if temp:
        return temp
    
    token = request.values.get('token')
    passwd = request.values.get('passwd')
    if token:
        if len(token) > 36 or not token.isalnum():
            info = {
                'info': 'Token is illegal. Token can only contain num and letter'
            }
            return jsonify(info), 400
    else:
        token = str(uuid1())
        
    result = c.execute('select * from token where token = ?', (token,) ).fetchall()
    
    if len(result) != 0:
        info = {
            'info': 'Token already in use.'
        }
        return jsonify(info), 409
        
    c.execute('insert into token(token, device_id, passwd) values(?, ?, ?)', (token, device_id, passwd))
    conn.commit()
    
    print('token, device_id, passwd', token, device_id, passwd)
    
    info = {
        'info': 'Create token successd.',
        'token': token,
        'passwd': passwd,
        'url': url_for('print_by_token', token = token, passwd = passwd, _external=True)
    }
    return jsonify(info)
    
def print_paper_to_device(device_id, paper, c):
    result = c.execute('select bind_id from device where device_id = ?', (device_id,) ).fetchall()
    bind_id = result[0][0]
    print_id, r = print_paper(ak, device_id, bind_id, paper)
    obj = r.json()
    if not print_id:
        if r.status_code == 200 and obj['showapi_res_code'] == 1:
            FAIL_REASON = {
                '-1': '插入数据库失败',
                '-3': '用户设备绑定关系不正确',
                '-4': '获取打印机异常',
            }
            result = obj.get('result')
            info = {
                'info': 'Print failed. Memobird api said "{}", result {}'.format(FAIL_REASON.get(result), result)
            }
            return jsonify(info), 500
        elif r.status_code >= 500:
            info = {
                'info': 'Print failed. Memobird API status code {}. AccessKey may invalid.'.format(r.status_code)
            }
            return jsonify(info), 500
        else:
            info = {
                'info': 'Print failed. Memobird API status code {}.'.format(r.status_code),
                'api_result': r.text
            }
            return jsonify(info), 400
                
    info = {
        'print_id': print_id,
        'url': url_for('print_state', print_id = print_id, _external=True)
    }
    if obj['result'] == 2:
        info['info'] = 'Paper printing...'
        return jsonify(info), 200
    else:
        info['info'] = 'Printing request has sent to Memobird API, But API can`t print rightnow. Device may offline.'
        return jsonify(info), 202


@app.route('/token/<token>', methods = ['POST', 'DELETE'])
def print_by_token(token):
    conn = create_db_connection()
    c = conn.cursor()
    result = c.execute('select device_id, passwd from token where token = ?', (token,) ).fetchall()
    if len(result) == 0:
        info = {
            'info':'Token not exist.'
        }
        return jsonify(info), 404
        
    device_id = result[0][0]
    passwd = result[0][1]
    
    if passwd:
        if passwd != request.values.get('passwd'):
            info = {
                'info': 'This token need correct passwd'
            }
            return jsonify(info), 401
    
    if request.method == 'DELETE':
        c.execute('delete from token where token = ?', (token,))
        conn.commit()
        return '', 204
    
    contents, need_convert, err_info = get_content_from_request(request)
    if err_info:
        info = {
            'info': err_info
        }
        return jsonify(info), 400
    
    if not need_convert:
        paper = contents2paper(contents)
        return print_paper_to_device(device_id, paper, c)
    
    print('异步转换！')
    convert_async = ConvertAsync(contents, cloudconvert_api)
    paper = convert_async.run()
    return print_paper_to_device(device_id, paper, c)
    

    
    
    
@app.route('/print_state/<print_id>', methods = ['GET'])
def print_state(print_id):
    return ''

app.run(host='0.0.0.0', port=8080)
