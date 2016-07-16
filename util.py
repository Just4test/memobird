from PIL import Image
from io import BytesIO, StringIO
import requests
import base64
import qrcode
from flask import jsonify
from inspect import isgenerator, isfunction

DEVICE_WIDTH = 384 #设备能打印的宽度

def convert_txt(txt):
    return 'T:' + base64.b64encode(txt.encode('gbk')).decode('ascii')

def convert_img(img):
    # 图片宽度最大支持384。支持黑白图（色深1位），并且这个傻逼玩意打出来的图片是上下颠倒的。
    img = img.transpose(Image.FLIP_TOP_BOTTOM)
    width, height = img.size
    if width > DEVICE_WIDTH:
        new_height = int(height * DEVICE_WIDTH / width)
        print('图片的当前尺寸是{},{} 调整为{},{}'.format(width, height, DEVICE_WIDTH, new_height))
        img = img.resize((DEVICE_WIDTH, new_height), Image.BILINEAR)
    img = img.convert('1')
    bmp_data = BytesIO()
    img.save(bmp_data, 'BMP')
    return 'P:' + base64.b64encode(bmp_data.getvalue()).decode('ascii')
    
class Paper:
    
    def __init__(self):
        self.contents = []
        
    def append_txt(self, txt):
        txt += '\n' #咕咕机排版有bug，图文混排的时候如果不加换行符会出现问题
        self.contents.append(convert_txt(txt))

            
    def append_img(self, img):
        # img = Image.open(StringIO(imgdata))
        self.contents.append(convert_img(img))
            
    def append_qrcode(self, txt):
        img = qrcode.make(txt)
        self.contents.append(convert_img(img))
        
    def encode(self):
        return '|'.join(self.contents)

def bind_device(ak, device_id):
    '''
    return:
        bind_id: bind_id if success else None
        r: response
    '''
    data = {
        'ak': ak,
        'memobirdID': device_id,
    }
    r = requests.post('http://open.memobird.cn/home/setuserbind', data = data)
    json = r.json()
    if r.status_code == 200 and json['showapi_res_code'] == 1:
        return json['showapi_userid'], r
    return None, r
    
def print_paper(ak, device_id, bind_id, paper):
    '''
    return:
        print_id: print_id if success else None
        r: response
    '''
    data = {
        'ak': ak,
        'memobirdID': device_id,
        'userID': bind_id,
        'printcontent': paper.encode(),
    }
    r = requests.post('http://open.memobird.cn/home/printpaper', data = data)
    json = r.json()
    if r.status_code == 200 and json['showapi_res_code'] == 1 and json['result'] in (1, 2):
        return json['printcontentid'], r
    return None, r
    
def print_state(ak, print_id):
    '''
    return:
        state:  state int if success else None
        r: response
    '''
    data = {
        'ak': ak,
        'printcontentid': print_id,
    }
    r = requests.post('http://open.memobird.cn/home/printpaper', data = data)
    json = r.json()
    if r.status_code == 200 and json['showapi_res_code'] == 1:
        return json['printflag'], r
    return None, r
    
# class ConverterBase:
#     def __init__(self, data):
#         self.data = data
#         self.generator = None
#         self.result = None
#         self.response = None
        
#     def convert(self, cloudconvert_key):
#         '''
#         执行转换操作。该操作可以是同步的，也可以是异步的。
#         yield or return:
#             如果正在执行，yield None（可选）
#             如果已经转换成功，return 结果
#             如果转换失败，return False，并设置self.response
#         '''
        
def is_func_or_generator(obj):
    return isfunction(obj) or isgenerator(obj)
    
def download_convert_image(process):
    if process['step'] == 'error':
        return False
    url = 'https:' + process['output']['url']
    r = requests.get(url)
    if r.status_code == 200:
        return Image.open(BytesIO(r.content))
    return False
    
def get_content_from_request(request):
    '''
    从请求中提取要打印的内容
        - 请求附带一个文件，支持图片、html、markdown、文本
        - 请求中使用content和type属性指定内容和类型。
          使用content、content0、content1……content9来附加最多11个内容和类型对。
        - multipart请求，附带多个内容。会根据内容的名字判断类别。无法归类的内容会被忽略。
    return:
        contents 内容列表
            列表中要么是可以直接打印的对象（文本、图像），
            要么是转换函数/生成器。
            函数转换成功返回文本/图像，或者转换失败返回False
            生成器还可以返回None,表示转换尚未完成。
        need_convert: 如果结果需要转换，输出True。
        err_info: 如果发生了错误，返回一个错误信息。
    '''
    content_type = request.headers.get('Content-Type')
    def decode_data_to_str(data):
        print('解码', data)
        charset = 'utf8'
        if content_type:
            temp = content_type.split('charset=')
            if len(temp) > 1:
                charset = temp[1].split(';')[0]
        print('结果是', data.decode(charset))
        return data.decode(charset)
    
    def txt_converter(data):
        return decode_data_to_str(data)
    
    def html_converter(data):
        data = decode_data_to_str(data)
        def convert(cloudconvert_api):
            process = cloudconvert_api.convert({
                "inputformat": "html",
                "outputformat": "png",
                "input": "raw",
                "file": data,
                "filename": "a.html",
                "converteroptions": {
                    "screen_width": DEVICE_WIDTH
                },
                "timeout": 59,
                "save": True
            })
            
            process.wait()
            return download_convert_image(process)
            
        return convert
    
    def md_converter(data):
        data = decode_data_to_str(data)
        def convert(cloudconvert_api):
            # 先将markdown转换为html，再把html转换为png
            process = cloudconvert_api.convert({
                "inputformat": "md",
                "outputformat": "html",
                "input": "raw",
                "file": data,
                "filename": "a.md",
                "timeout": 59,
                "save": True
            })
            process.wait()
            if process['step'] == 'error':
                return False
            url = 'https:' + process['output']['url']
            
            process = cloudconvert_api.convert({
                "inputformat": "html",
                "outputformat": "png",
                "input": "download",
                "file": url,
                "filename": "a.html",
                "converteroptions": {
                    "screen_width": DEVICE_WIDTH
                },
                "timeout": 59,
                "save": True
            })
            
            process.wait()
            return download_convert_image(process)
            
        return convert
    
    def img_converter(data):
        return Image.open(BytesIO(data))
    
    def qr_converter(data):
        return qrcode.make(decode_data_to_str(data))
    
    print('内容类型是', content_type)
    if content_type:
        if content_type.find('image/') == 0:
            return [img_converter(request.get_data())], False, None
        if content_type == 'text/markdown':
            return [md_converter(request.get_data())], True, None
        if content_type == 'text/html':
            return [html_converter(request.get_data())], True, None
        if content_type.find('text/') == 0:
            return [txt_converter(request.get_data())], False, None
            
    convert_map = {
        'image': img_converter,
        'png': img_converter,
        'jpg': img_converter,
        'jpeg': img_converter,
        
        'md': md_converter,
        'markdown': md_converter,
        
        'htm': md_converter,
        'html': md_converter,
        
        'txt': txt_converter,
        'text': txt_converter,
        
        'qr': qr_converter,
        'qrcode': qr_converter,
        '二维码': qr_converter,
    }
            
    contents = []
    
    def find_content_from_value(suffix):
        content = request.values.get('content' + suffix)
        if content:
            tp = request.values.get('type' + suffix).lower()
            if not tp:
                return None, None, 'Need type for "content{}"'.format(suffix)
            converter = convert_map.get(tp)
            if not converter:
                return None, None, 'The giving type "{}" can`t be understand.'.format(tp)
            ct = converter(content)
            contents.append(ct)
    
    find_content_from_value('')
    for c in '0123456789':
        find_content_from_value(c)
    
    def find_content_from_multipart(name, data):
        tp = name.split('.')[-1]
        converter = convert_map.get(tp)
        if not converter:
            return None, None, 'File "{}" has extension name "{}", which can not be understand'.format(name, tp)
        ct = converter(data.read())
        contents.append(ct)
    
    for name, data in request.files.items():
        find_content_from_multipart(name, data)
    
    need_convert = False
    for c in contents:
        if is_func_or_generator(c):
            need_convert = True
            break
            
    return contents, need_convert, None
    
def contents2paper(contents):
    paper = Paper()
    for c in contents:
        if isinstance(c, str):
            paper.append_txt(c)
        elif isinstance(c, Image.Image):
            paper.append_img(c)
        else:
            raise Exception('Unknown data type!', c, contents)
    return paper
    
class ConvertAsync:
    def __init__(self, contents, cloudconvert_api):
        self.contents = contents
        self.cloudconvert_api = cloudconvert_api
        
    def run(self):
        while True:
            flag = True
            for i in range(len(self.contents)):
                c = self.contents[i]
                if isfunction(c):
                    temp = c(self.cloudconvert_api)
                    if temp == False:
                        info = {
                            'info': 'Convert Failed.'
                        }
                        self.response = (jsonify(info), 400)
                        return
                    else:
                        self.contents[i] = temp
                elif isgenerator(c):
                    temp = next(c)
                    if temp == None:
                        flag = False #还得继续循环，直到生成器返回非None值
                    elif temp == False:
                        info = {
                            'info': 'Convert Failed.'
                        }
                        self.response = (jsonify(info), 400)
                        return
                    else:
                        self.contents[i] = temp
            if flag:
                break
        
        paper = contents2paper(self.contents)
        
        return paper
        
        
        