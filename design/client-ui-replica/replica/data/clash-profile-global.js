window.REPLICA={
 "app": "clash",
 "screen": "profile-global",
 "theme": "ios26 theme-clash",
 "reference": "../screens/clash/profile-global_1.png",
 "nav": {
  "left": "back",
  "title": "全局配置",
  "center_y": 110
 },
 "sheet": {
  "top": 72,
  "radius": 38,
  "back": {
   "top": 62,
   "x": [
    16,
    386
   ],
   "radius": 34,
   "color": "#D5D5D9"
  }
 },
 "status": {
  "time": "02:15",
  "battery": "80"
 },
 "content_top": 182.7,
 "row_h": 52.3,
 "group_gap": 56.6,
 "header_offset": 20,
 "footer_offset": 8.6,
 "groups": [
  {
   "header": "出站",
   "footer": null,
   "rows": [
    {
     "label": "运行模式",
     "subhub": "还没核对",
     "maps_to": "mode",
     "accessory": "updown",
     "detail": "规则分流"
    }
   ]
  },
  {
   "header": "日志",
   "footer": null,
   "rows": [
    {
     "label": "日志级别",
     "subhub": "写入",
     "maps_to": "intent clash_log_level",
     "accessory": "updown",
     "detail": "信息"
    }
   ]
  },
  {
   "header": "连接",
   "footer": null,
   "rows": [
    {
     "label": "IPv6",
     "subhub": "写入",
     "maps_to": "intent clash_ipv6",
     "accessory": "switch",
     "on": false
    },
    {
     "label": "统一延迟",
     "subhub": "不写",
     "maps_to": "unified-delay",
     "accessory": "switch",
     "on": true
    },
    {
     "label": "TCP 并发连接",
     "subhub": "写入",
     "maps_to": "intent clash_tcp_concurrent",
     "accessory": "switch",
     "on": false
    },
    {
     "label": "关闭 TCP 保活",
     "subhub": "不写",
     "maps_to": "disable-keep-alive",
     "accessory": "switch",
     "on": false
    },
    {
     "label": "TCP 保活空闲时间",
     "subhub": "不写",
     "maps_to": "keep-alive-idle",
     "accessory": "updown",
     "detail": "默认 · 5 分钟"
    },
    {
     "label": "TCP 保活间隔",
     "subhub": "不写",
     "maps_to": "keep-alive-interval",
     "accessory": "updown",
     "detail": "默认 · 75 秒"
    },
    {
     "label": "GeoSite 匹配方式",
     "subhub": "不写",
     "maps_to": "geosite-matcher",
     "accessory": "updown",
     "detail": "默认（紧凑）"
    }
   ]
  },
  {
   "header": "其余字段",
   "footer": null,
   "rows": [
    {
     "label": "控制接口",
     "subhub": "写入",
     "maps_to": "intent clash_external_controller",
     "accessory": "updown",
     "detail": "关闭"
    },
    {
     "label": "控制接口套接字",
     "subhub": "不写",
     "maps_to": "external-controller-unix",
     "accessory": "chevron",
     "detail": "关闭"
    },
    {
     "label": "控制接口（HTTPS）",
     "subhub": "不写",
     "maps_to": "external-controller-tls",
     "accessory": "updown",
     "detail": "关闭"
    },
    {
     "label": "面板文件夹",
     "subhub": "写入",
     "maps_to": "intent clash_external_ui",
     "accessory": "chevron",
     "detail": "无"
    },
    {
     "label": "面板下载地址",
     "subhub": "写入",
     "maps_to": "intent clash_external_ui_url",
     "accessory": "chevron",
     "detail": "默认"
    },
    {
     "label": "面板子文件夹",
     "subhub": "写入",
     "maps_to": "intent clash_external_ui_name",
     "accessory": "chevron",
     "detail": "直接放在面板文件夹"
    },
    {
     "label": "控制接口上的 DoH",
     "subhub": "不写",
     "maps_to": "external-doh-server",
     "accessory": "chevron",
     "detail": "关闭"
    },
    {
     "label": "访问密钥",
     "subhub": "写入",
     "maps_to": "intent clash_secret",
     "accessory": "chevron",
     "detail": "无"
    },
    {
     "label": "dat 版 GeoIP",
     "subhub": "不写",
     "maps_to": "geodata-mode",
     "accessory": "switch",
     "on": false
    },
    {
     "label": "全局 TLS 指纹",
     "subhub": "不写",
     "maps_to": "global-client-fingerprint",
     "accessory": "chevron",
     "detail": "无"
    },
    {
     "label": "下载时的 UA",
     "subhub": "不写",
     "maps_to": "global-ua",
     "accessory": "chevron",
     "detail": "clash.meta"
    },
    {
     "label": "ETag 缓存",
     "subhub": "不写",
     "maps_to": "etag-support",
     "accessory": "switch",
     "on": true
    },
    {
     "label": "多网络策略",
     "subhub": "不写",
     "maps_to": null,
     "accessory": "updown",
     "detail": "默认（只用当前网络）"
    },
    {
     "label": "优先使用的网络",
     "subhub": "不写",
     "maps_to": null,
     "accessory": "chevron",
     "detail": "按策略决定"
    },
    {
     "label": "备用网络",
     "subhub": "不写",
     "maps_to": null,
     "accessory": "chevron",
     "detail": "其他所有网络"
    },
    {
     "label": "TLS 证书",
     "subhub": "不写",
     "maps_to": null,
     "accessory": "chevron",
     "detail": "未设置；副标题「在『证书与信任』里改」"
    }
   ]
  },
  {
   "header": "控制接口跨域",
   "footer": "哪些网页可以在浏览器里调用控制接口。",
   "rows": [
    {
     "label": "允许的网页来源",
     "subhub": "不写",
     "maps_to": "external-controller-cors.allow-origins",
     "accessory": "chevron",
     "detail": "全部"
    },
    {
     "label": "允许私有网络访问",
     "subhub": "不写",
     "maps_to": "external-controller-cors.allow-private-network",
     "accessory": "switch",
     "on": true
    }
   ]
  },
  {
   "header": "重启后保留",
   "footer": "内核重启后不用重新选节点，连接也不会因虚拟 IP 改变而断开。",
   "rows": [
    {
     "label": "记住节点选择",
     "subhub": "写入",
     "maps_to": "intent clash_profile_store_selected",
     "accessory": "switch",
     "on": true
    },
    {
     "label": "保存虚拟 IP 映射",
     "subhub": "写入",
     "maps_to": "intent clash_profile_store_fake_ip",
     "accessory": "switch",
     "on": true
    }
   ]
  },
  {
   "header": "规则数据库下载地址",
   "footer": "一般不用改；访问 GitHub 困难时换成镜像。",
   "rows": [
    {
     "label": "GeoIP",
     "subhub": "不写",
     "maps_to": "geox-url.geoip",
     "accessory": "chevron",
     "detail": "默认"
    },
    {
     "label": "MMDB",
     "subhub": "不写",
     "maps_to": "geox-url.mmdb",
     "accessory": "chevron",
     "detail": "默认"
    },
    {
     "label": "ASN",
     "subhub": "不写",
     "maps_to": "geox-url.asn",
     "accessory": "chevron",
     "detail": "默认"
    },
    {
     "label": "GeoSite",
     "subhub": "不写",
     "maps_to": "geox-url.geosite",
     "accessory": "chevron",
     "detail": "默认"
    }
   ]
  },
  {
   "header": null,
   "footer": null,
   "rows": [
    {
     "label": "9 项在 iPhone 上不起作用",
     "subhub": "不适用（动作/导航）",
     "maps_to": null,
     "accessory": "chevron"
    }
   ]
  }
 ],
 "floating": [
  {
   "label": "搜索",
   "control": "searchfield",
   "maps_to": null,
   "layer": "app",
   "subhub": "na",
   "subhub_zh": "不适用（动作/导航）",
   "note": "底部悬浮玻璃搜索框，按行名筛选本页",
   "geom": {
    "x": [
     27.3,
     374.7
    ],
    "y": [
     797.3,
     846.7
    ],
    "icon_x": 42,
    "text_left": 66
   }
  }
 ]
};
