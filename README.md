# LanShare · 局域网文件共享

把电脑上的一个文件夹，通过 Wi-Fi 共享给手机、平板或另一台电脑——**手机端零安装，扫码即用**。

![界面截图](docs/screenshot.png)

单文件 Python 程序，只用到 `qrcode`（生成二维码）和 `Pillow`（截屏）两个第三方库，不做任何外网穿透，只在你自己的局域网内监听。

---

## 功能

| 功能 | 说明 |
|:--|:--|
| 扫码访问 | 窗口里直接显示二维码，手机扫一下就进来 |
| 网址免端口 | 默认监听 80，手机上直接输 `http://192.168.1.100`，不用打冒号 |
| 浏览与下载 | 目录列表带文件类型图标、大小、修改时间，点开即看 |
| 断点续传 | 支持 HTTP `Range`，手机上拖视频进度条不会失败 |
| 双向传输 | 打开「允许上传」后，手机可多选文件传到电脑，重名自动加序号 |
| 大文件不爆内存 | 上传用 `mmap` + boundary 流式切分，传几个 G 也不会把内存吃满 |
| 路径穿越防护 | 访问共享目录之外的路径一律 403 |
| 深色科幻界面 | 桌面端与手机端共用同一套配色 |
| 手机控制电源 | v1.1 新增：手机远程**关机 / 睡眠**，默认关闭，开启后需输 4 位访问码 |
| 手机查看屏幕 | v1.2 新增：手机浏览器里实时看电脑主屏，默认关闭，只看不控 |

## 快速开始

### 方式一：下载 exe（推荐，不需要装 Python）

1. 到 [Releases](../../releases) 下载 `LanShare.exe`
2. 放到任意文件夹，双击打开
3. 选一个要共享的文件夹 → 点「启动共享」
4. 手机连上同一个 Wi-Fi，扫窗口里的二维码，或直接输入窗口显示的网址

### 方式二：从源码运行

```bash
pip install qrcode
python LanShare.pyw
```

需要 Python 3.8+。界面在 Windows 上验证最充分，macOS / Linux 也可运行。

## 手机打不开？先放行防火墙

Windows 防火墙默认拦截入站连接，这是最常见的原因。

- 双击 **`fix-firewall.bat`**（会弹 UAC，点「是」），它会放行程序需要的 TCP 端口
- 或手动执行：

```bat
netsh advfirewall firewall add rule name="LanShare File Share (LAN)" dir=in action=allow protocol=TCP localport=80,8080,8888,6666,9999,8000-8100 profile=any enable=yes
```

同时确认两件事：手机和电脑连的是**同一个路由器**（IP 前三段一致），且路由器没有开启「AP 隔离 / 客户端隔离」——开了的话两台设备之间根本无法互访。

## 打包成单文件 exe

双击 **`build.bat`**，产物在 `dist\LanShare.exe`（约 30 MB，自带 Python 运行时，拷走就能用）。

手动打包：

```bash
pip install pyinstaller qrcode pillow
pyinstaller --noconfirm --clean --onefile --noconsole --name LanShare ^
  --icon LanShare.ico --add-data "LanShare.ico;." ^
  --hidden-import qrcode ^
  --hidden-import PIL --hidden-import PIL.Image ^
  --hidden-import PIL.ImageGrab --hidden-import PIL.JpegImagePlugin ^
  LanShare.pyw
```

`PIL` 那几行不能省：截屏是**函数内延迟导入**的（`ScreenStream._loop` 里），PyInstaller 的静态分析对这类导入不总是可靠，漏了就会打出一个"能跑但一看屏就报错"的 exe。

## 常见问题

| 现象 | 处理 |
|:--|:--|
| 手机打不开网页 | 先按上面放行防火墙；再确认同一网段、路由器未开 AP 隔离 |
| 网址里带 `:8080` 这类端口号 | 说明 80 被别的软件占用了，程序会自动退到备用端口，以窗口显示的地址为准 |
| 换了共享文件夹但内容没变 | 现在的版本是即时生效的，手机刷新一下页面即可；若仍不变请提 issue |
| 想开机自动启动 | 给 exe 建个快捷方式放进启动文件夹（`Win+R` 输入 `shell:startup`），启动参数加 `--autostart` |
| 想改成默认共享某个目录 | 第一次在界面里选好即可，设置会记在 `config.json` 里 |
| 手机点了关机后网页就打不开了 | 正常——电脑都关了，服务自然也不在了。想再唤醒得靠手机 WOL App 或路由器，网页做不到 |
| 点了「睡眠」但感觉像休眠 | 系统启用了休眠时的正常表现，见下一节 |
| 手机看屏一片黑 | 多半是锁屏或 UAC 弹窗挡着——**安全桌面拍不到**，见下文说明 |
| 手机看屏很卡 | 先看 Wi-Fi 信号；10 fps 是刻意限的，调大 `SCREEN_FPS` 可以提速，但 CPU 占用同步上升 |
| 看屏时电脑变卡 | 抓屏要占约三分之一单核，打游戏或跑渲染时建议把这个开关关掉 |

## 手机远程关机 / 睡眠（v1.1）

电脑端在「端口与权限」面板勾选 **允许手机控制电源**，手机页面右下角就会出现一个电源按钮，点开可以关机或睡眠。开启时会自动生成 4 位访问码，手机端需输入才能操作（可勾选记住）。

**这个开关默认是关的，也建议你只在自家人用的网络里开**——局域网内任何能打开这个网页的设备，只要拿到访问码就能关掉你的电脑。

三件需要知道的事：

- **「睡眠」在你的机器上可能实际是「休眠」。** 只要系统启用了休眠（Windows 默认如此），`SetSuspendState` 就会走休眠——内存写盘、唤醒慢几秒，但断电也不丢数据。这是系统自带行为，程序没有绕开它。
- **这是单向操作。** 电脑一关，服务随之消失，你没办法再用这个网页把电脑唤醒。远程唤醒（Wake-on-LAN）需要发送 UDP 魔术包，浏览器发不出来，而且关机后本机也没有任何服务在跑。想唤觉得靠手机上的 WOL App 或路由器。
- **访问码连错 5 次会锁定 60 秒**，防止有人在局域网里慢慢试。

实现上，电源指令走保留路径 `__power__`，只接受 POST；关机用 `shutdown /s /t 0`，睡眠用 `rundll32 powrprof.dll,SetSuspendState`，两者都**不需要管理员权限**。

## 手机查看屏幕（v1.2）

电脑端勾选 **允许手机查看屏幕**，手机页面右下角就会出现一个眼睛图标。点进去输一次访问码，就能看到电脑主屏的实时画面。

技术上就是一个 MJPEG 流（`multipart/x-mixed-replace`）——浏览器拿 `<img>` 标签直接就能播，手机端不需要装任何东西。默认 **1280×720 / 10 fps / 单帧约 105 KB**，局域网里肉眼延迟约 200 毫秒：够看清文字和进度，但别指望拿它看电影。

**只能看，不能操作。** 想远程控制（点鼠标、敲键盘），请用 RustDesk 这类专门的软件——自制方案要多做输入注入，工作量翻倍，可靠性还不如现成的。

### 几个设计上的取舍

- **没人看的时候不抓屏。** 抓屏线程只在真有客户端取帧时活着；手机关掉页面 6 秒后线程自己退场，挂机不烧 CPU。
- **只跑一个抓屏线程。** 几台手机同时看，共享同一帧缓冲、各取"最新一帧"——看的人变多不会让 CPU 成倍涨，只是每台手机的帧率被摊薄。
- **同时看屏上限 4 人**，超出直接 503。
- **凭证走 Cookie，不走 URL。** 访问码校验通过后发一张随机凭证（12 小时有效），存在 `HttpOnly` cookie 里，不会留在浏览器历史或访问日志中。
- **访问码和电源控制共用**——一个码管两件事，少记一个。

### 拍不到的东西

Windows 的**安全桌面**——UAC 弹窗、`Ctrl+Alt+Del` 界面、锁屏登录界面——普通截屏 API 拍不到，这些时候手机上会看到一片黑。想越过这道墙，程序得以 SYSTEM 权限注册成 Windows 服务（RustDesk、VNC 就是这么干的）。本程序是普通桌面程序，不越这条线。

## 技术说明

- **HTTP 服务**：标准库 `http.server.ThreadingHTTPServer`，实现 `Range`（206）、流式上传、MJPEG 推流、目录穿越防护
- **界面**：`tkinter` 手绘深色主题（刻意不用 `ttk` 的分隔符与 `LabelFrame`——它们在深色下样式不可控）
- **二维码**：取 `qrcode` 的 `get_matrix()` 直接画到 `tkinter.Canvas` 上，不经过图片文件
- **截屏**：`PIL.ImageGrab` 抓主屏 → `Image.resize` 缩放 → JPEG 编码。实测 1080p 下单帧约 40 ms，**瓶颈在抓屏（25 ms）而不在编码（14 ms）**——所以降分辨率救不了帧率，只能省带宽
- **保留路径**：`__power__`（电源）、`__screen__`（看屏），都用双下划线包夹，几乎不可能和真实文件夹撞名
- **配置**：`config.json` 与程序同目录，记录共享路径、端口、上传开关、电源与看屏开关、访问码

### 三个踩过的坑

**1. 隐藏控制台窗口要用 `CREATE_NO_WINDOW`**

程序启动时会用 `netsh` 查防火墙规则。GUI 程序自己没有控制台，用 `subprocess` 拉起控制台子进程时，Windows 会给子进程**新开一个控制台窗口**——用户看到的就是"程序一打开闪一下黑框"。所有外部命令统一走一个 helper：

```python
def run_hidden(cmd, timeout=20):
    kw = {"capture_output": True, "timeout": timeout}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(cmd, **kw)
```

验收方法（比肉眼看可靠）：启动后查有没有"父进程是本程序的控制台进程"，应当是 0。

```powershell
$pids = @(Get-CimInstance Win32_Process -Filter "Name='LanShare.exe'") | ForEach-Object { $_.ProcessId }
@(Get-CimInstance Win32_Process -Filter "Name='conhost.exe'" |
  Where-Object { $pids -contains $_.ParentProcessId }).Count    # 必须为 0
```

**2. 打包后配置文件路径会漂移**

PyInstaller 的 onefile 模式会把程序解压到 `%TEMP%`，此时 `__file__` 指向临时目录——如果配置按 `__file__` 定位，每次启动都会"忘记"上次的文件夹和端口。要改成跟着可执行文件本身走：

```python
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
```

**3. 没读完请求体就返回，会让下一个请求莫名 501**

HTTP/1.1 是 keep-alive 的，一个 TCP 连接会连着跑好几个请求。如果服务端在某个分支提前返回（比如「这个功能没开放」直接 403）而请求体还没读，那些字节就会赖在 socket 里，把下一个请求的报文头顶歪——对端收到畸形的请求行，标准库只能回 `501 Not Implemented`。

这个 bug 单发一次请求测不出来，必须复用同一个连接连发三次：

```python
c = http.client.HTTPConnection("127.0.0.1", port)
for _ in range(3):
    c.request("POST", "/__power__", body="action=x&pin=1",
              headers={"Content-Type": "application/x-www-form-urlencoded"})
    print(c.getresponse().status)   # 三次必须一致
```

规矩很简单：**先把 `Content-Length` 指定的字节读干净，再做任何判断。**

**4. 一个没做干净的「退场」，会让后来的人黑屏**

抓屏线程的存活最初按"有几个人在看"来管：`viewers` 减到 0 就 `_stop()`。看着天经地义，实际有个时序洞——**上一个连接的 `finally` 可能跑在下一个客户端 `attach()` 之后**。于是它那次迟到的 `detach()` 把计数减到 0，反手就把刚起来的抓屏线程掐了，后连上来的手机对着黑屏干瞪眼。手机刷新得越快越容易撞上。

改法是让线程存活和人数**解耦**：线程自己看 `last_pull`（最近一次有人取帧的时刻），空闲超过 6 秒才退场；`viewers` 只用来算并发上限。这样迟到的 `detach()` 顶多让计数短暂偏一下，伤不到线程。

同一个坑还有第二半：线程自己退场时**必须把 `running` 标志复位**，否则下次 `attach()` 看到它还是 `True`，就不起新线程了——照样黑屏。

两处都是单元测试抓出来的（看 `断流后立刻重连` 那条用例）。

教训：**只要存在迟到的回调，用「外部计数」控制「内部线程」的生命周期就一定有窗口。**

## 许可

[MIT](LICENSE)
