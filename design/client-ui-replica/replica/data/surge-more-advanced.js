window.REPLICA={
 "app": "surge",
 "screen": "more-advanced",
 "theme": "ios26",
 "reference": "../screens/surge/more-advanced_1.png",
 "nav": {
  "left": "close",
  "title": "高级",
  "right": "check",
  "center_y": 100.3,
  "material": null
 },
 "sheet": {
  "top": 62,
  "radius": 38
 },
 "status": {
  "time": "01:55",
  "battery": "80"
 },
 "content_top": 187.4,
 "row_h": 53.0,
 "header_offset": 16,
 "footer_offset": 8.6,
 "groups": [
  {
   "header": "通用",
   "footer": null,
   "rows": [
    {
     "label": "网络优化",
     "subhub": "不写",
     "maps_to": null,
     "accessory": "chevron"
    },
    {
     "label": "延迟测试",
     "subhub": "只写一部分",
     "maps_to": null,
     "accessory": "chevron"
    },
    {
     "label": "子网设置覆盖",
     "subhub": "不写",
     "maps_to": null,
     "accessory": "chevron"
    },
    {
     "label": "GeoIP 数据库",
     "subhub": "不写",
     "maps_to": null,
     "accessory": "chevron"
    },
    {
     "label": "IPv6",
     "subhub": "只写一部分",
     "maps_to": null,
     "accessory": "chevron"
    },
    {
     "label": "接管模式",
     "subhub": "还没核对",
     "maps_to": null,
     "accessory": "chevron"
    }
   ]
  },
  {
   "header": "Wi-Fi 访问",
   "footer": "Surge 可以作为一个标准的 HTTP/SOCKS5 代理服务器向 Wi-Fi 网络下的其他设备提供服务器。默认 HTTP 端口号：6152，SOCKS5 端口号：6153",
   "rows": [
    {
     "label": "允许 Wi-Fi 访问",
     "subhub": "不写",
     "maps_to": "[General] allow-wifi-access（app-guide 推测）",
     "accessory": "switch",
     "on": false,
     "sub": "当前 Wi-Fi IP: <局域网 IP>",
     "h": 61
    },
    {
     "label": "允许个人热点访问",
     "subhub": "不写",
     "maps_to": null,
     "accessory": "switch",
     "on": false
    },
    {
     "label": "HTTP 代理服务端口",
     "subhub": "不写",
     "maps_to": null,
     "accessory": "chevron",
     "detail": "6152"
    },
    {
     "label": "SOCKS5 代理服务端口",
     "subhub": "不写",
     "maps_to": null,
     "accessory": "chevron",
     "detail": "6153"
    }
   ],
   "gap_before": 63.0
  },
  {
   "header": "远程控制",
   "footer": "允许远程 Surge 面板或 Surge CLI 进行管理控制。",
   "rows": [
    {
     "label": "远端控制器",
     "subhub": "不写",
     "maps_to": null,
     "accessory": "chevron"
    },
    {
     "label": "HTTP API & Web 面板",
     "subhub": "写入",
     "maps_to": "intent surge_http_api",
     "accessory": "chevron"
    }
   ],
   "gap_before": 108.3
  },
  {
   "header": "高级",
   "footer": null,
   "rows": [
    {
     "label": "日志等级",
     "subhub": "写入",
     "maps_to": "intent surge_loglevel",
     "accessory": "updown",
     "detail": "notify"
    },
    {
     "label": "高级设置",
     "subhub": "只写一部分",
     "maps_to": null,
     "accessory": "chevron"
    }
   ],
   "gap_before": 68.3
  }
 ]
};
