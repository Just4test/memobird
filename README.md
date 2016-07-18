# REST-Memobird
##简介
[Memobird](http://memobird.cn/) 是一个类似Little Printer的智能打印机。

Memobird的[API](http://open.memobird.cn/)仅能打印无格式文本和图片，并且需要以特殊的方式编码。

此项目对Memobird的API进行封装，试图提供一个更优雅易用的REST API，并支持Markdown等多种格式。
##用法
####首先
你需要向Memobird官方[申请](http://open.memobird.cn/upload/webapi.pdf)一个Access Key。为了支持格式转换，还需要在[CloudConvert](https://cloudconvert.com/)注册一个账号。

可以使用两种方式传入参数:环境变量和命令行参数。

使用命令行参数 app.py --ak [Access Key] --cloudconvert [CloudConvert Key]

或者使用环境变量MEMOBIRD_AK传入Access Key，并使用CLOUDCONVERT_KEY传入CloudConvert API Key。

####其次
打印需要三个步骤:
1. 注册设备，这需要你的设备id。
2. 创建token
3. 拿着token打印
##API
####/device POST
附带device_id，以创建一个新设备。

这也会同时创建一个设备密码，访问设备信息需要附带设备密码。
####/device/{device_id} GET
返回设备的状态，列出设备的所有token
####/device/{device_id} DELETE
删除设备及关联的所有token。
####/device/{device_id}/token GET
列出指定设备的所有token
####/device/{device_id}/token POST
为设备创建新token。可以附带参数token以指定token，以及参数passwd以使用密码保护改token。如果不指定token，则会生成一个uuid token。
####/token/{token} POST
向token绑定的设备打印。可以打印文本、图片、html、markdown。

你可以使用三种方式打印:
1. 将文件附加到请求体。
2. 使用“content”和“type”参数对，前者指定数据，后者指定格式。你还可以使用content0，type0到content9，type9指定最多11个内容。这些内容会依序打印。
3. 使用multipart。每个部分需要使用name指定该部分的数据格式。name可以是文件名。
####/token/{token} DELETE
删除一个token。
