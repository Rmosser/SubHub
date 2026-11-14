window.REPLICA={
 "app": "clash-mi",
 "screen": "core-settings",
 "theme": "clashmi",
 "reference": "../screens/clash-mi/core-settings_1.png",
 "nav": {
  "flat": true,
  "left": "flatback",
  "left_box": [
   18.7,
   86
  ],
  "title": "核心设置",
  "right": "doc",
  "right_box": [
   368.7,
   86
  ],
  "center_y": 96.7
 },
 "status": {
  "time": "09:50",
  "battery": "80",
  "crumb": "App Store"
 },
 "content_top": 141.3,
 "row_h": 46.94,
 "group_gap": 7.160000000000002,
 "scroll_bottom": 840.7,
 "groups": [
  {
   "rows": [
    {
     "label": "重置",
     "subhub": "不适用（动作/导航）",
     "maps_to": null,
     "info": false,
     "accessory": "chevron"
    }
   ]
  },
  {
   "rows": [
    {
     "label": "外部控制",
     "subhub": "只在手机本机",
     "maps_to": "intent clash_external_controller → external-controller",
     "info": true,
     "field": "127.0.0.1:9090",
     "placeholder": false
    },
    {
     "label": "Secret",
     "subhub": "只在手机本机",
     "maps_to": "intent clash_secret → secret",
     "info": true,
     "field": "<redacted>",
     "placeholder": false
    },
    {
     "label": "混合代理端口",
     "subhub": "只在手机本机",
     "maps_to": "intent clash_mixed_port → mixed-port",
     "info": true,
     "field": "7890",
     "placeholder": false
    },
    {
     "label": "日志等级",
     "subhub": "只在手机本机",
     "maps_to": "intent clash_log_level → log-level",
     "info": true,
     "detail": "error",
     "accessory": "caret",
     "small": true
    },
    {
     "label": "Pprof Address",
     "subhub": "不写",
     "maps_to": "（调试用，非 mihomo 配置键）",
     "info": false,
     "field": "127.0.0.1:4578",
     "placeholder": true,
     "field_x": [
      201.3,
      358.7
     ]
    },
    {
     "label": "Pprof",
     "subhub": "不写",
     "maps_to": null,
     "info": false,
     "accessory": "chevron"
    }
   ]
  },
  {
   "rows": [
    {
     "label": "Unified Delay",
     "subhub": "只在手机本机",
     "maps_to": "unified-delay",
     "info": true,
     "detail": "不覆写",
     "accessory": "caret",
     "small": true
    },
    {
     "label": "IPv6",
     "subhub": "只在手机本机",
     "maps_to": "intent clash_ipv6 → ipv6",
     "info": true,
     "detail": "禁用",
     "accessory": "caret",
     "small": true
    },
    {
     "label": "TUN",
     "subhub": "只在手机本机",
     "maps_to": "tun",
     "info": true,
     "accessory": "chevron"
    },
    {
     "label": "Geo RuleSet",
     "subhub": "只在手机本机",
     "maps_to": "geox-url / geo-update-interval",
     "info": true,
     "accessory": "chevron"
    }
   ]
  },
  {
   "rows": [
    {
     "label": "分流模板",
     "subhub": "不写",
     "maps_to": null,
     "info": false,
     "accessory": "chevron"
    }
   ]
  },
  {
   "rows": [
    {
     "label": "覆写",
     "subhub": "只在手机本机",
     "maps_to": null,
     "info": true,
     "accessory": "chevron",
     "detail": "内置-覆写",
     "small": true
    }
   ]
  },
  {
   "rows": [
    {
     "label": "TCP并发握手",
     "subhub": "只在手机本机",
     "maps_to": "intent clash_tcp_concurrent → tcp-concurrent",
     "info": true,
     "detail": "不覆写",
     "accessory": "caret",
     "small": true
    },
    {
     "label": "TCP保活时间间隔",
     "subhub": "只在手机本机",
     "maps_to": "keep-alive-interval",
     "info": true,
     "field": "30 s",
     "placeholder": false
    },
    {
     "label": "TLS全局指纹",
     "subhub": "只在手机本机",
     "maps_to": "global-client-fingerprint",
     "info": true,
     "detail": "chrome",
     "accessory": "caret",
     "small": true
    }
   ]
  },
  {
   "rows": [
    {
     "label": "局域网设备接入",
     "subhub": "只在手机本机",
     "maps_to": "allow-lan / bind-address / authentication",
     "info": false,
     "accessory": "chevron"
    }
   ]
  },
  {
   "rows": [
    {
     "label": "DNS",
     "subhub": "只在手机本机",
     "maps_to": "dns",
     "info": true,
     "accessory": "chevron"
    },
    {
     "label": "NTP",
     "subhub": "不写",
     "maps_to": "ntp",
     "info": true,
     "accessory": "chevron"
    },
    {
     "label": "TLS",
     "subhub": "不写",
     "maps_to": "tls",
     "info": true,
     "accessory": "chevron"
    },
    {
     "label": "嗅探",
     "subhub": "只在手机本机",
     "maps_to": "sniffer",
     "info": true,
     "accessory": "chevron"
    }
   ]
  }
 ],
 "redactions": [
  [
   194.66666666666666,
   249.33333333333334,
   394.6666666666667,
   281.3333333333333
  ]
 ],
 "group_margin_pt": 25.3
};
